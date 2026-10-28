#!/usr/bin/env python3
"""
scan-to-dwg v2: 读图 → ezdxf 直接重绘
=========================================
不依赖 accoreconsole，直接用 ezdxf 生成干净 DXF。

流程：
1. PDF/PNG → 渲染图像
2. 自动检测主平面图区域（排除详图）
3. 检测轴线圆 → 定位轴线网格
4. 检测墙线（沿轴线的粗线段）+ 自适应估计墙厚
5. 检测门窗洞口（墙线间断分析）
6. 检测柱标记（轴线交点处的填充矩形）
7. OCR 读取尺寸标注
8. ezdxf 生成 DXF（分图层、真实 mm 坐标）

输出图层：
  AXIS       - 轴线网格（红色虚线）
  AXIS_CIRC  - 轴线圆
  AXIS_TEXT  - 轴线编号
  WALL       - 内墙（白色实线）
  WALL_EXT   - 外墙（蓝色实线）
  COLUMN     - 柱（灰色填充矩形）
  OPENING    - 门窗洞口（绿色矩形）
  DIM        - 尺寸标注（黄色）
  TEXT       - 其他文字（青色）

用法：
  python redraw_dxf.py input.pdf -o output/ --dpi 200 --scale 100
"""
from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple, Optional, Dict

import cv2
import numpy as np

# ezdxf
import ezdxf
from ezdxf.enums import TextEntityAlignment

# OCR
try:
    import pytesseract
    HAS_TESS = True
except ImportError:
    HAS_TESS = False

TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class AxisInfo:
    """一条轴线的信息。"""
    pos_px: float        # 位置（像素）
    pos_mm: float        # 位置（毫米）
    label: str = ""      # 编号 (1, 2, A, B...)
    is_horizontal: bool = False  # True=横向轴线(水平线), False=纵向轴线(垂直线)


@dataclass
class WallSegment:
    """一段墙线。"""
    x1_mm: float
    y1_mm: float
    x2_mm: float
    y2_mm: float
    thickness_mm: float = 200.0  # 墙厚
    is_external: bool = False
    has_opening: bool = False    # 这段墙上是否有门窗洞口


@dataclass
class Opening:
    """门窗洞口。"""
    cx_mm: float
    cy_mm: float
    width_mm: float      # 洞口宽（沿墙方向）
    height_mm: float     # 洞口高（垂直于墙）
    kind: str = "door"   # door / window
    wall_axis: str = ""  # 所在轴线标签，如 "A", "3"


@dataclass
class Column:
    """柱标记。"""
    cx_mm: float
    cy_mm: float
    width_mm: float = 400.0  # 柱截面边长（默认 400）
    is_filled: bool = True    # 实心/空心


@dataclass
class DimText:
    """尺寸标注文字。"""
    cx_px: float
    cy_px: float
    text: str
    conf: int


@dataclass
class DrawingData:
    """从图纸中提取的全部数据。"""
    h_axes: List[AxisInfo] = field(default_factory=list)  # 横向轴线（垂直线）
    v_axes: List[AxisInfo] = field(default_factory=list)  # 纵向轴线（水平线）
    walls: List[WallSegment] = field(default_factory=list)
    openings: List[Opening] = field(default_factory=list)
    columns: List[Column] = field(default_factory=list)
    dims: List[DimText] = field(default_factory=list)
    image_w_px: int = 0
    image_h_px: int = 0
    scale_mm_per_px: float = 1.0


# ============================================================================
# 1. 图像加载
# ============================================================================

def load_image(input_path: str, dpi: int = 200) -> Tuple[np.ndarray, float, float]:
    """加载图像，返回 (img, page_w_mm, page_h_mm)。"""
    if input_path.lower().endswith(".pdf"):
        import fitz
        doc = fitz.open(input_path)
        page = doc[0]
        pix = page.get_pixmap(dpi=dpi)
        img_path = os.path.join(os.path.dirname(input_path) or ".",
                                f"_tmp_render_{dpi}dpi.png")
        pix.save(img_path)
        img = cv2.imread(img_path)
        page_w_mm = page.rect.width * 25.4 / 72
        page_h_mm = page.rect.height * 25.4 / 72
        # 清理临时文件
        try:
            os.remove(img_path)
        except:
            pass
        return img, page_w_mm, page_h_mm
    else:
        img = cv2.imread(input_path)
        if img is None:
            raise FileNotFoundError(f"Cannot read image: {input_path}")
        # 估算物理尺寸（假设 dpi）
        page_w_mm = img.shape[1] * 25.4 / dpi
        page_h_mm = img.shape[0] * 25.4 / dpi
        return img, page_w_mm, page_h_mm


# ============================================================================
# 2. 轴线圆检测
# ============================================================================

def detect_axis_circles(img: np.ndarray,
                        bbox: Optional[Tuple[int, int, int, int]] = None
                        ) -> List[Tuple[float, float, float, str]]:
    """
    检测轴线交点圆。
    返回 [(cx, cy, radius, side)]

    bbox: (x_min, y_min, x_max, y_max) 主平面图区域，None=全图
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)
    n, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)

    h, w = img.shape[:2]
    result = []

    # 确定有效检测区域
    if bbox:
        bx_min, by_min, bx_max, by_max = bbox
    else:
        bx_min, by_min, bx_max, by_max = 0, 0, w, h

    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        cx, cy = centroids[i]

        # 在主平面图区域内（对内部判定而言，宽松）
        # 对 top/bottom/left/right 的判定：用整图位置
        # 轴线圆特征：45-85px 宽高，近似正方形
        if not (45 < bw < 85 and 45 < bh < 85 and abs(bw - bh) < 8):
            continue
        # 圆形度检测
        mask = (labels == i).astype(np.uint8) * 255
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not contours:
            continue
        perim = cv2.arcLength(contours[0], True)
        if perim < 1:
            continue
        circularity = 4 * math.pi * area / (perim * perim)
        fill = area / (bw * bh)
        if not (0.65 < circularity < 0.95 and 0.50 < fill < 0.80):
            continue

        # 位置判定（用全图坐标，因为轴线圆在图框边缘）
        if cy < h * 0.15:
            side = "top"
        elif cy > h * 0.85:
            side = "bottom"
        elif cx < w * 0.12:
            side = "left"
        elif cx > w * 0.88:
            side = "right"
        else:
            side = "interior"

        # 过滤：所有轴线圆必须位于主平面图区域内
        # top/bottom 的 x 必须在 [bx_min, bx_max] 内
        if side in ("top", "bottom") and not (bx_min < cx < bx_max):
            continue
        # left/right 的 y 必须在 [by_min, by_max] 内
        if side in ("left", "right") and not (by_min < cy < by_max):
            continue
        # interior 必须严格在主平面图中心区域内
        if side == "interior" and not (bx_min < cx < bx_max and by_min < cy < by_max):
            continue

        result.append((cx, cy, bw / 2, side))

    return result


def build_axis_grid(circles: List[Tuple[float, float, float, str]],
                    img_w: int, img_h: int,
                    scale_mm: float) -> Tuple[List[AxisInfo], List[AxisInfo]]:
    """
    从轴线圆构建轴线网格。
    横向轴线 = 水平线（y 相同的圆归为一组）
    纵向轴线 = 垂直线（x 相同的圆归为一组）

    策略：
    - 横向轴线：只用 left 边和 right 边的圆，且它们必须共享相同的 y 集合
    - 纵向轴线：只用 top 边和 bottom 边的圆，且它们必须共享相同的 x 集合

    返回 (h_axes, v_axes) - 已按位置排序并正确编号
    h_axes: 横向轴线列表（每条是一个 y 值，按 pos_mm 升序，从下往上 A→T）
    v_axes: 纵向轴线列表（每条是一个 x 值，按 pos_mm 升序，从左往右 1→N）
    """
    # 分离 left/right 圆
    left_ys = []
    right_ys = []
    for cx, cy, r, side in circles:
        if side == "left":
            left_ys.append(cy)
        elif side == "right":
            right_ys.append(cy)

    # 分离 top/bottom 圆
    top_xs = []
    bottom_xs = []
    for cx, cy, r, side in circles:
        if side == "top":
            top_xs.append(cx)
        elif side == "bottom":
            bottom_xs.append(cx)

    # 横向轴线：left ∪ right，但只保留在 left 中出现的 y（left 通常更可靠）
    # 如果 left 没有，才用 right
    if left_ys:
        h_axis_source = left_ys
    elif right_ys:
        h_axis_source = right_ys
    else:
        h_axis_source = []

    # 纵向轴线：top ∪ bottom，top 更可靠
    if top_xs:
        v_axis_source = top_xs
    elif bottom_xs:
        v_axis_source = bottom_xs
    else:
        v_axis_source = []

    # 聚类
    def cluster(values, tolerance=25):
        if not values:
            return []
        values = sorted(values)
        clusters = [[values[0]]]
        for v in values[1:]:
            if v - clusters[-1][-1] < tolerance:
                clusters[-1].append(v)
            else:
                clusters.append([v])
        return [sum(c) / len(c) for c in clusters]

    h_axis_px = cluster(h_axis_source)
    v_axis_px = cluster(v_axis_source)

    # 转 mm 坐标
    # 纵向轴线（垂直线）：x 坐标，pos_mm = x * scale_mm，从小到大
    v_axes_raw = [(x_px, x_px * scale_mm) for x_px in v_axis_px]
    # 横向轴线（水平线）：y 坐标，先翻转，pos_mm = (img_h - y_px) * scale_mm
    h_axes_raw = [(y_px, (img_h - y_px) * scale_mm) for y_px in h_axis_px]

    # 标准化（平移）
    if v_axes_raw:
        x_offset = min(p[1] for p in v_axes_raw)
        v_axes_raw = [(p[0], p[1] - x_offset) for p in v_axes_raw]
    if h_axes_raw:
        y_offset = min(p[1] for p in h_axes_raw)
        h_axes_raw = [(p[0], p[1] - y_offset) for p in h_axes_raw]

    # 按 pos_mm 升序排序（保证间距为正）
    v_axes_raw.sort(key=lambda p: p[1])
    h_axes_raw.sort(key=lambda p: p[1])

    # 过滤异常大间距（>15m 间距 = 异常，可能是两个不同建筑）
    # 通过检查间距分布自动剔除
    def filter_large_gaps(axes_raw, max_gap_mm=15000):
        if len(axes_raw) < 3:
            return axes_raw
        spacings = [axes_raw[i+1][1] - axes_raw[i][1] for i in range(len(axes_raw)-1)]
        if not spacings:
            return axes_raw
        median_spacing = sorted(spacings)[len(spacings)//2]
        # 删除间距 > median*4 的项
        filtered = [axes_raw[0]]
        for i, sp in enumerate(spacings):
            if sp <= max(median_spacing * 4, max_gap_mm):
                filtered.append(axes_raw[i+1])
            else:
                break  # 之后都是大间距，停止
        return filtered if len(filtered) >= 3 else axes_raw

    v_axes_raw = filter_large_gaps(v_axes_raw)
    h_axes_raw = filter_large_gaps(h_axes_raw)

    # 编号（按 pos_mm 升序）
    v_axes = [AxisInfo(pos_px=p[0], pos_mm=p[1],
                       label=str(i + 1), is_horizontal=False)
              for i, p in enumerate(v_axes_raw)]
    h_axes = [AxisInfo(pos_px=p[0], pos_mm=p[1],
                       label=chr(65 + i), is_horizontal=True)
              for i, p in enumerate(h_axes_raw)]

    return h_axes, v_axes


def detect_main_plan_region(img: np.ndarray) -> Tuple[int, int, int, int]:
    """
    自动检测主平面图区域（排除右侧详图区域）。

    策略：找右侧最大的连续空白列 → 详图与主图的分界。
    返回 (x_min, y_min, x_max, y_max) 像素坐标。
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = img.shape[:2]

    # 二值化（白底黑线 → 线条是黑）
    _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)

    # 找垂直方向的"内容密度"（每列有多少黑色像素）
    # 蓝色图纸：线条是深色（RGB 都低）
    # 用灰度直接计算
    _, gray_bin = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)
    col_density = np.sum(gray_bin > 0, axis=0) / h  # 0..1

    # 找右侧最大的空白列（密度 < 0.005）
    right_boundary = w
    in_blank = False
    blank_start = w
    max_blank_len = 0
    max_blank_end = w

    for x in range(w - 1, w // 2, -1):
        if col_density[x] < 0.005:  # 空白列
            if not in_blank:
                blank_start = x
                in_blank = True
        else:
            if in_blank:
                blank_len = blank_start - x
                if blank_len > max_blank_len:
                    max_blank_len = blank_len
                    max_blank_end = blank_start
                in_blank = False

    if max_blank_len > 50:
        right_boundary = max_blank_end + int(max_blank_len * 0.1)  # 加一点缓冲

    # 主平面图区域：图框内
    x_min = int(w * 0.04)
    x_max = min(w, right_boundary)
    y_min = int(h * 0.04)
    y_max = int(h * 0.92)

    # 兜底：如果右边界太靠右（>80%宽度），强制限制到 70%
    if x_max > w * 0.80:
        x_max = int(w * 0.70)

    return (x_min, y_min, x_max, y_max)


# ============================================================================
# 3. 墙线检测
# ============================================================================

def detect_walls(img: np.ndarray, h_axes: List[AxisInfo],
                 v_axes: List[AxisInfo], scale_mm: float,
                 bbox: Optional[Tuple[int, int, int, int]] = None,
                 max_gap_px: int = 60,
                 keep_top_per_axis: int = 3) -> List[WallSegment]:
    """
    检测墙线：沿轴线的粗线段。

    策略：
    - 只在主平面图区域内检测
    - 沿每条轴线做投影，找墙段
    - 墙段必须跨越至少 80% 最小轴间距
    - 相邻墙段（间距 < max_gap_px）合并
    - 每条轴线只保留最长的 N 段（去噪）
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = img.shape[:2]

    if bbox:
        bx_min, by_min, bx_max, by_max = bbox
    else:
        bx_min, by_min, bx_max, by_max = 0, 0, w, h

    # 自适应二值化
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, blockSize=51, C=10
    )
    mask = np.zeros_like(binary)
    mask[by_min:by_max, bx_min:bx_max] = 255
    binary = cv2.bitwise_and(binary, mask)

    walls = []
    wall_half_width = max(3, int(120 / scale_mm))

    # 计算相邻轴线间距
    v_spacing_px = []
    for i in range(len(v_axes) - 1):
        v_spacing_px.append(v_axes[i + 1].pos_px - v_axes[i].pos_px)
    h_spacing_px = []
    for i in range(len(h_axes) - 1):
        h_spacing_px.append(h_axes[i + 1].pos_px - h_axes[i].pos_px)
    min_v_spacing = min(v_spacing_px) if v_spacing_px else 200
    min_h_spacing = min(h_spacing_px) if h_spacing_px else 200
    min_wall_len_px = min(min_v_spacing, min_h_spacing) * 0.8
    wall_fill_threshold = 0.5

    def collect_and_process(raw_segments):
        merged = _merge_segments(raw_segments, max_gap_px, min_wall_len_px)
        # 按长度排序，只保留最长的 N 段
        merged.sort(key=lambda s: s[1] - s[0], reverse=True)
        return merged[:keep_top_per_axis]

    # --- 检测沿纵向轴线的水平墙线 ---
    for va in v_axes:
        x = int(va.pos_px)
        if x < bx_min or x > bx_max:
            continue
        x1 = max(bx_min, x - wall_half_width)
        x2 = min(bx_max, x + wall_half_width)
        col_strip = binary[:, x1:x2]
        row_sum = np.sum(col_strip > 0, axis=1)
        threshold = (x2 - x1) * wall_fill_threshold
        in_wall = False
        seg_start = 0
        raw_segments = []
        for y in range(by_min, by_max):
            if row_sum[y] > threshold:
                if not in_wall:
                    in_wall = True
                    seg_start = y
            else:
                if in_wall:
                    seg_end = y
                    seg_len = seg_end - seg_start
                    if seg_len >= min_wall_len_px:
                        raw_segments.append((seg_start, seg_end))
                    in_wall = False
        if in_wall and (by_max - seg_start) >= min_wall_len_px:
            raw_segments.append((seg_start, by_max))

        merged = collect_and_process(raw_segments)
        for seg_start, seg_end in merged:
            y_mm_start = (h - seg_end) * scale_mm
            y_mm_end = (h - seg_start) * scale_mm
            x_mm = va.pos_mm
            walls.append(WallSegment(
                x1_mm=x_mm - 100, y1_mm=y_mm_start,
                x2_mm=x_mm + 100, y2_mm=y_mm_end,
                thickness_mm=200, is_external=False
            ))

    # --- 检测沿横向轴线的垂直墙线 ---
    for ha in h_axes:
        y = int(ha.pos_px)
        if y < by_min or y > by_max:
            continue
        y1 = max(by_min, y - wall_half_width)
        y2 = min(by_max, y + wall_half_width)
        row_strip = binary[y1:y2, :]
        col_sum = np.sum(row_strip > 0, axis=0)
        threshold = (y2 - y1) * wall_fill_threshold
        in_wall = False
        seg_start = 0
        raw_segments = []
        for x in range(bx_min, bx_max):
            if col_sum[x] > threshold:
                if not in_wall:
                    in_wall = True
                    seg_start = x
            else:
                if in_wall:
                    seg_end = x
                    seg_len = seg_end - seg_start
                    if seg_len >= min_wall_len_px:
                        raw_segments.append((seg_start, seg_end))
                    in_wall = False
        if in_wall and (bx_max - seg_start) >= min_wall_len_px:
            raw_segments.append((seg_start, bx_max))

        merged = collect_and_process(raw_segments)
        for seg_start, seg_end in merged:
            x_mm_start = seg_start * scale_mm
            x_mm_end = seg_end * scale_mm
            y_mm = ha.pos_mm
            walls.append(WallSegment(
                x1_mm=x_mm_start, y1_mm=y_mm - 100,
                x2_mm=x_mm_end, y2_mm=y_mm + 100,
                thickness_mm=200, is_external=False
            ))

    return walls


def _merge_segments(segments, max_gap: int, min_len: int):
    """合并间距小于 max_gap 的相邻线段。"""
    if not segments:
        return []
    segments = sorted(segments)
    merged = [list(segments[0])]
    for start, end in segments[1:]:
        if start - merged[-1][1] <= max_gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    # 只保留合并后仍 >= min_len 的
    return [(s, e) for s, e in merged if (e - s) >= min_len]


def detect_openings(img: np.ndarray, h_axes: List[AxisInfo],
                    v_axes: List[AxisInfo], scale_mm: float,
                    bbox: Optional[Tuple[int, int, int, int]] = None,
                    min_gap_px: int = 35,
                    max_gap_px: int = 230) -> List[Opening]:
    """
    检测门窗洞口：在墙线上的间断。

    策略：
    - 沿每条轴线扫描墙线（不合并小间断）
    - 找墙段之间的 gap（gap < max_gap_px 且 > min_gap_px）
    - 洞口宽度判断：door 600-1500mm, window 1500-2400mm
    - 仅在 bbox（主平面图区域）内检测
    - 过滤掉过短的墙段（噪声/文字）以减少误检
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = img.shape[:2]

    if bbox:
        bx_min, by_min, bx_max, by_max = bbox
    else:
        bx_min, by_min, bx_max, by_max = 0, 0, w, h

    # 自适应二值化
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, blockSize=51, C=10
    )
    mask = np.zeros_like(binary)
    mask[by_min:by_max, bx_min:bx_max] = 255
    binary = cv2.bitwise_and(binary, mask)

    openings = []
    wall_half_width = max(3, int(120 / scale_mm))
    fill_threshold = 0.40  # 适中阈值

    # --- 沿纵向轴线（垂直轴）扫描水平墙线的间断 ---
    for va in v_axes:
        x = int(va.pos_px)
        if x < bx_min or x > bx_max:
            continue
        x1 = max(bx_min, x - wall_half_width)
        x2 = min(bx_max, x + wall_half_width)
        col_strip = binary[:, x1:x2]
        row_sum = np.sum(col_strip > 0, axis=1)
        threshold = (x2 - x1) * fill_threshold

        # 找墙段（dark pixel runs）- 不合并，保留所有间断
        wall_segments = []
        in_wall = False
        wall_start = 0
        for y in range(by_min, by_max):
            if row_sum[y] > threshold:
                if not in_wall:
                    wall_start = y
                    in_wall = True
            else:
                if in_wall:
                    wall_end = y
                    # 要求墙段至少 25px 长（320mm at 1:100）过滤噪声
                    if wall_end - wall_start > 25:
                        wall_segments.append((wall_start, wall_end))
                    in_wall = False
        if in_wall:
            wall_segments.append((wall_start, by_max))

        # 找间断（gap 在 min_gap_px ~ max_gap_px 之间）
        for i in range(len(wall_segments) - 1):
            s1, e1 = wall_segments[i]
            s2, e2 = wall_segments[i + 1]
            gap_size = s2 - e1
            if min_gap_px < gap_size < max_gap_px:
                # 要求两侧的墙段都至少有一定长度（避免文字误判）
                if (e1 - s1) < 40 or (e2 - s2) < 40:
                    continue
                cy = (e1 + s2) // 2
                cy_mm = (h - cy) * scale_mm
                width_mm = gap_size * scale_mm
                kind = "window" if width_mm > 1500 else "door"
                openings.append(Opening(
                    cx_mm=va.pos_mm, cy_mm=cy_mm,
                    width_mm=width_mm, height_mm=2000,
                    kind=kind, wall_axis=va.label
                ))

    # --- 沿横向轴线（水平轴）扫描垂直墙线的间断 ---
    for ha in h_axes:
        y = int(ha.pos_px)
        if y < by_min or y > by_max:
            continue
        y1 = max(by_min, y - wall_half_width)
        y2 = min(by_max, y + wall_half_width)
        row_strip = binary[y1:y2, :]
        col_sum = np.sum(row_strip > 0, axis=0)
        threshold = (y2 - y1) * fill_threshold

        wall_segments = []
        in_wall = False
        wall_start = 0
        for x in range(bx_min, bx_max):
            if col_sum[x] > threshold:
                if not in_wall:
                    wall_start = x
                    in_wall = True
            else:
                if in_wall:
                    wall_end = x
                    if wall_end - wall_start > 30:
                        wall_segments.append((wall_start, wall_end))
                    in_wall = False
        if in_wall:
            wall_segments.append((wall_start, bx_max))

        for i in range(len(wall_segments) - 1):
            s1, e1 = wall_segments[i]
            s2, e2 = wall_segments[i + 1]
            gap_size = s2 - e1
            if min_gap_px < gap_size < max_gap_px:
                if (e1 - s1) < 40 or (e2 - s2) < 40:
                    continue
                cx = (e1 + s2) // 2
                cx_mm = cx * scale_mm
                width_mm = gap_size * scale_mm
                kind = "window" if width_mm > 1500 else "door"
                openings.append(Opening(
                    cx_mm=cx_mm, cy_mm=ha.pos_mm,
                    width_mm=width_mm, height_mm=2000,
                    kind=kind, wall_axis=ha.label
                ))

    return openings


def detect_columns(img: np.ndarray, h_axes: List[AxisInfo],
                   v_axes: List[AxisInfo], scale_mm: float,
                   bbox: Optional[Tuple[int, int, int, int]] = None) -> List[Column]:
    """
    检测柱标记：在轴线交点附近找实心填充矩形。

    柱在平面图中的特征：
    - 实心黑色填充矩形（轴线交点处）
    - 尺寸通常 300-600mm 见方
    - 部分图纸用空心矩形 + 对角斜线

    策略：
    - 在每个轴线交点附近 80px 范围搜索
    - 检测填充率 > 70% 的连通区域
    - 尺寸 15-50px (= 190-635mm at 1:100 200dpi)
    - 长宽比 < 1.3（近似正方形）
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = img.shape[:2]

    if bbox:
        bx_min, by_min, bx_max, by_max = bbox
    else:
        bx_min, by_min, bx_max, by_max = 0, 0, w, h

    # 用低阈值二值化（柱是深色填充）
    _, binary = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY_INV)
    mask = np.zeros_like(binary)
    mask[by_min:by_max, bx_min:bx_max] = 255
    binary = cv2.bitwise_and(binary, mask)

    columns = []
    search_radius = 80  # px 搜索范围

    for va in v_axes:
        for ha in h_axes:
            x = int(va.pos_px)
            y = int(ha.pos_px)

            # 跳过在图框边缘的交点（轴线圆位置）
            if x < bx_min + search_radius or x > bx_max - search_radius:
                continue
            if y < by_min + search_radius or y > by_max - search_radius:
                continue

            # 检查这个区域是否是填充矩形
            x1 = x - search_radius
            x2 = x + search_radius
            y1 = y - search_radius
            y2 = y + search_radius

            region = binary[y1:y2, x1:x2]
            fill_ratio = np.sum(region > 0) / region.size

            # 柱的填充度 > 65%
            if fill_ratio < 0.65:
                continue

            # 进一步检查连通区域
            n, labels, stats, centroids = cv2.connectedComponentsWithStats(
                region, connectivity=8
            )
            for i in range(1, n):
                cw, ch, ca = stats[i, 2], stats[i, 3], stats[i, 4]
                # 柱尺寸：15-50px 见方
                if 15 < cw < 50 and 15 < ch < 50 and abs(cw - ch) < 12:
                    # 实心判定：连通区域面积接近外接矩形面积
                    if ca > cw * ch * 0.85:
                        rcx, rcy = centroids[i]
                        abs_cx = x1 + rcx
                        abs_cy = y1 + rcy
                        cx_mm = abs_cx * scale_mm
                        cy_mm = (h - abs_cy) * scale_mm
                        size_mm = (cw + ch) / 2 * scale_mm
                        columns.append(Column(
                            cx_mm=cx_mm, cy_mm=cy_mm,
                            width_mm=size_mm, is_filled=True
                        ))

    return columns


def estimate_wall_thickness(img: np.ndarray, h_axes: List[AxisInfo],
                            v_axes: List[AxisInfo], scale_mm: float,
                            bbox: Optional[Tuple[int, int, int, int]] = None) -> float:
    """
    自适应估计墙厚。

    策略：
    - 沿每条轴线取一段墙线
    - 测量该墙线在垂直于轴线方向上的填充宽度
    - 取所有测量值的中位数
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = img.shape[:2]

    if bbox:
        bx_min, by_min, bx_max, by_max = bbox
    else:
        bx_min, by_min, bx_max, by_max = 0, 0, w, h

    # 自适应二值化
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, blockSize=51, C=10
    )
    mask = np.zeros_like(binary)
    mask[by_min:by_max, bx_min:bx_max] = 255
    binary = cv2.bitwise_and(binary, mask)

    thickness_samples = []

    # 沿纵向轴线（垂直轴）测水平墙线厚度
    for va in v_axes[:3]:  # 取前 3 条就够了
        x = int(va.pos_px)
        if x < bx_min + 50 or x > bx_max - 50:
            continue
        # 在轴线附近 50px 范围内沿垂直方向找墙
        col_strip = binary[by_min + 100:by_max - 100, x - 50:x + 50]
        if col_strip.size == 0:
            continue
        row_density = np.sum(col_strip > 0, axis=1) / 100
        # 找高密度行（墙的位置）
        wall_rows = np.where(row_density > 0.3)[0]
        if len(wall_rows) > 0:
            # 计算墙的范围
            for y_pos in [wall_rows[0], wall_rows[len(wall_rows) // 2], wall_rows[-1]]:
                # 在该 y 处测量水平方向的墙厚
                if 0 <= y_pos < binary.shape[0]:
                    row = binary[y_pos, bx_min:bx_max]
                    in_run = False
                    for x_pos in range(len(row)):
                        if row[x_pos] > 0:
                            if not in_run:
                                run_start = x_pos
                                in_run = True
                        else:
                            if in_run:
                                run_end = x_pos
                                run_w = run_end - run_start
                                # 墙厚范围：5-40px (60-500mm at 1:100 200dpi)
                                if 5 < run_w < 40:
                                    thickness_samples.append(run_w * scale_mm)
                                in_run = False

    if not thickness_samples:
        return 200.0  # 默认 200mm

    # 取中位数（更稳健）
    thickness_samples.sort()
    median_mm = thickness_samples[len(thickness_samples) // 2]
    return max(100.0, min(500.0, median_mm))  # 限定 100-500mm 范围


# ============================================================================
# 4. OCR 尺寸标注
# ============================================================================

def ocr_dimensions(img: np.ndarray, scale_mm: float) -> List[DimText]:
    """用 Tesseract 识别尺寸标注文字。"""
    if not HAS_TESS or not os.path.isfile(TESSERACT_CMD):
        return []

    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 用 text detection 模式
    try:
        data = pytesseract.image_to_data(
            gray, lang="eng",
            config="--psm 11 -c preserve_interword_spaces=0",
            output_type=pytesseract.Output.DICT,
        )
    except Exception:
        return []

    results = []
    for i, txt in enumerate(data["text"]):
        txt = (txt or "").strip()
        if not txt:
            continue
        try:
            conf = int(float(data["conf"][i]))
        except (ValueError, TypeError):
            conf = -1
        if conf < 30:
            continue
        # 尺寸标注通常包含数字
        has_digit = any(c.isdigit() for c in txt)
        if not has_digit:
            continue
        cx = float(data["left"][i]) + float(data["width"][i]) / 2
        cy = float(data["top"][i]) + float(data["height"][i]) / 2
        results.append(DimText(cx_px=cx, cy_px=cy, text=txt, conf=conf))

    return results


# ============================================================================
# 5. ezdxf 生成 DXF
# ============================================================================

# 图层定义
DXF_LAYERS = {
    "AXIS":      {"color": 1,   "linetype": "DASHED"},    # 红色 虚线
    "AXIS_CIRC": {"color": 1,   "linetype": "CONTINUOUS"}, # 轴线圆
    "AXIS_TEXT": {"color": 1,   "linetype": "CONTINUOUS"}, # 轴线编号
    "WALL":      {"color": 7,   "linetype": "CONTINUOUS"}, # 白色
    "WALL_EXT":  {"color": 5,   "linetype": "CONTINUOUS"}, # 蓝色 外墙
    "COLUMN":    {"color": 8,   "linetype": "CONTINUOUS"}, # 灰色
    "OPENING":   {"color": 3,   "linetype": "CONTINUOUS"}, # 绿色
    "DIM":       {"color": 2,   "linetype": "CONTINUOUS"}, # 黄色
    "TEXT":      {"color": 4,   "linetype": "CONTINUOUS"}, # 青色
}


def generate_dxf(data: DrawingData, output_path: str, title: str = "scan-to-dwg") -> str:
    """用 ezdxf 生成干净 DXF 文件。"""
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4  # millimeters
    msp = doc.modelspace()

    # 设置图层
    for name, props in DXF_LAYERS.items():
        if name not in doc.layers:
            layer = doc.layers.add(name)
        else:
            layer = doc.layers.get(name)
        layer.color = props["color"]
        try:
            layer.linetype = props.get("linetype", "CONTINUOUS")
        except Exception:
            pass

    # --- 轴线网格 ---
    if data.v_axes and data.h_axes:
        x_min = min(a.pos_mm for a in data.v_axes) - 500
        x_max = max(a.pos_mm for a in data.v_axes) + 500
        y_min = min(a.pos_mm for a in data.h_axes) - 500
        y_max = max(a.pos_mm for a in data.h_axes) + 500

        # 横向轴线（水平线）
        for ha in data.h_axes:
            msp.add_line(
                (x_min, ha.pos_mm, 0),
                (x_max, ha.pos_mm, 0),
                dxfattribs={"layer": "AXIS"}
            )

        # 纵向轴线（垂直线）
        for va in data.v_axes:
            msp.add_line(
                (va.pos_mm, y_min, 0),
                (va.pos_mm, y_max, 0),
                dxfattribs={"layer": "AXIS"}
            )

        # 轴线圆 + 编号
        axis_radius = 400  # mm，轴线圆半径
        for va in data.v_axes:
            for ha in data.h_axes:
                # 圆
                msp.add_circle(
                    (va.pos_mm, ha.pos_mm, 0),
                    axis_radius,
                    dxfattribs={"layer": "AXIS_CIRC"}
                )

        # 轴线编号（在圆内）
        text_height = axis_radius * 0.8
        for va in data.v_axes:
            # 顶部
            y_top = max(a.pos_mm for a in data.h_axes) + axis_radius * 3
            ent = msp.add_text(va.label, dxfattribs={
                "layer": "AXIS_TEXT", "height": text_height
            })
            ent.set_placement((va.pos_mm, y_top), align=TextEntityAlignment.MIDDLE_CENTER)
            # 底部
            y_bot = min(a.pos_mm for a in data.h_axes) - axis_radius * 3
            ent2 = msp.add_text(va.label, dxfattribs={
                "layer": "AXIS_TEXT", "height": text_height
            })
            ent2.set_placement((va.pos_mm, y_bot), align=TextEntityAlignment.MIDDLE_CENTER)

        for ha in data.h_axes:
            # 左侧
            x_left = min(a.pos_mm for a in data.v_axes) - axis_radius * 3
            ent = msp.add_text(ha.label, dxfattribs={
                "layer": "AXIS_TEXT", "height": text_height
            })
            ent.set_placement((x_left, ha.pos_mm), align=TextEntityAlignment.MIDDLE_CENTER)
            # 右侧
            x_right = max(a.pos_mm for a in data.v_axes) + axis_radius * 3
            ent2 = msp.add_text(ha.label, dxfattribs={
                "layer": "AXIS_TEXT", "height": text_height
            })
            ent2.set_placement((x_right, ha.pos_mm), align=TextEntityAlignment.MIDDLE_CENTER)

    # --- 墙线 ---
    for wall in data.walls:
        layer = "WALL_EXT" if wall.is_external else "WALL"
        # 用 LWPOLYLINE 带宽度画线（模拟墙厚）
        if wall.thickness_mm > 0:
            msp.add_line(
                (wall.x1_mm, wall.y1_mm, 0),
                (wall.x2_mm, wall.y2_mm, 0),
                dxfattribs={"layer": layer}
            )

    # --- 门窗洞口 ---
    for op in data.openings:
        # 用开口矩形表示：两条平行线（门洞/窗洞的边界）
        layer = "OPENING"
        # 简化：画一个矩形标注位置
        w = op.width_mm / 2
        h_off = op.height_mm / 2
        if op.kind == "door":
            # 门：矩形 + 弧线（这里简化为矩形）
            rect_points = [
                (op.cx_mm - w, op.cy_mm - 50, 0),
                (op.cx_mm + w, op.cy_mm - 50, 0),
                (op.cx_mm + w, op.cy_mm + 50, 0),
                (op.cx_mm - w, op.cy_mm + 50, 0),
            ]
            for i in range(4):
                p1 = rect_points[i]
                p2 = rect_points[(i + 1) % 4]
                msp.add_line(p1, p2, dxfattribs={"layer": layer})
        else:
            # 窗：矩形（窗洞边界）+ 中间线（窗台/玻璃）
            rect_points = [
                (op.cx_mm - w, op.cy_mm - 40, 0),
                (op.cx_mm + w, op.cy_mm - 40, 0),
                (op.cx_mm + w, op.cy_mm + 40, 0),
                (op.cx_mm - w, op.cy_mm + 40, 0),
            ]
            for i in range(4):
                p1 = rect_points[i]
                p2 = rect_points[(i + 1) % 4]
                msp.add_line(p1, p2, dxfattribs={"layer": layer})
            # 中间窗台线
            msp.add_line(
                (op.cx_mm - w, op.cy_mm, 0),
                (op.cx_mm + w, op.cy_mm, 0),
                dxfattribs={"layer": layer}
            )

    # --- 柱 ---
    for col in data.columns:
        layer = "COLUMN"
        s = col.width_mm / 2
        if col.is_filled:
            # 实心柱：用实心矩形表示（SOLID 填充）
            rect_points = [
                (col.cx_mm - s, col.cy_mm - s, 0),
                (col.cx_mm + s, col.cy_mm - s, 0),
                (col.cx_mm + s, col.cy_mm + s, 0),
                (col.cx_mm - s, col.cy_mm + s, 0),
            ]
            # 用 hatch 或 trace 表示填充
            try:
                msp.add_solid(
                    rect_points,
                    dxfattribs={"layer": layer}
                )
            except Exception:
                # 兜底：用矩形边线
                for i in range(4):
                    p1 = rect_points[i]
                    p2 = rect_points[(i + 1) % 4]
                    msp.add_line(p1, p2, dxfattribs={"layer": layer})
        else:
            # 空心柱：只画矩形边线
            rect_points = [
                (col.cx_mm - s, col.cy_mm - s, 0),
                (col.cx_mm + s, col.cy_mm - s, 0),
                (col.cx_mm + s, col.cy_mm + s, 0),
                (col.cx_mm - s, col.cy_mm + s, 0),
            ]
            for i in range(4):
                p1 = rect_points[i]
                p2 = rect_points[(i + 1) % 4]
                msp.add_line(p1, p2, dxfattribs={"layer": layer})

    # --- 尺寸标注文字 ---
    for dim in data.dims:
        # 转换到 mm 坐标（翻转 y）
        x_mm = dim.cx_px * data.scale_mm_per_px
        y_mm = (data.image_h_px - dim.cy_px) * data.scale_mm_per_px
        ent = msp.add_text(dim.text, dxfattribs={
            "layer": "DIM", "height": 150
        })
        ent.set_placement((x_mm, y_mm), align=TextEntityAlignment.MIDDLE_CENTER)

    # 保存
    doc.saveas(output_path)
    return output_path


# ============================================================================
# 6. 主处理函数
# ============================================================================

def process_drawing(input_path: str, output_dir: str,
                    dpi: int = 200, print_scale: int = 100) -> dict:
    """
    主处理流程：读图 → 提取数据 → 生成 DXF。

    参数：
        input_path: PDF 或 PNG 路径
        output_dir: 输出目录
        dpi: 渲染 DPI
        print_scale: 图纸比例 (100 = 1:100)

    返回：
        dict with keys: dxf, data, success, summary
    """
    os.makedirs(output_dir, exist_ok=True)
    stem = Path(input_path).stem

    print(f"[1/6] 加载图像: {input_path} (DPI={dpi})")
    img, page_w_mm, page_h_mm = load_image(input_path, dpi)
    h_px, w_px = img.shape[:2]

    # 比例：1px = (25.4/dpi) mm (纸上) × print_scale (实际)
    scale_mm = (25.4 / dpi) * print_scale
    print(f"    图像: {w_px}x{h_px}px, 纸面: {page_w_mm:.0f}x{page_h_mm:.0f}mm")
    print(f"    比例: 1px = {scale_mm:.3f}mm (1:{print_scale})")

    # 自动检测主平面图区域
    bbox = detect_main_plan_region(img)
    print(f"    主平面图区域: x={bbox[0]}-{bbox[2]}, y={bbox[1]}-{bbox[3]}")

    print(f"[2/6] 检测轴线圆...")
    circles = detect_axis_circles(img, bbox=bbox)
    print(f"    找到 {len(circles)} 个轴线圆 (主平面图区域内)")
    for cx, cy, r, side in circles:
        print(f"      ({cx:.0f}, {cy:.0f}) r={r:.0f} side={side}")

    print(f"[3/6] 构建轴线网格...")
    h_axes, v_axes = build_axis_grid(circles, w_px, h_px, scale_mm)
    print(f"    横向轴线: {len(h_axes)} 条 → {[a.label for a in h_axes]}")
    print(f"    纵向轴线: {len(v_axes)} 条 → {[a.label for a in v_axes]}")
    if len(h_axes) > 1:
        spacings = [h_axes[i+1].pos_mm - h_axes[i].pos_mm for i in range(len(h_axes)-1)]
        print(f"    横轴间距(mm): {[f'{s:.0f}' for s in spacings]}")
    if len(v_axes) > 1:
        spacings = [v_axes[i+1].pos_mm - v_axes[i].pos_mm for i in range(len(v_axes)-1)]
        print(f"    纵轴间距(mm): {[f'{s:.0f}' for s in spacings]}")
        print(f"    总尺寸(mm): 宽={v_axes[-1].pos_mm:.0f}, 高={h_axes[-1].pos_mm:.0f}")

    print(f"[4/6] 检测墙线...")
    walls = detect_walls(img, h_axes, v_axes, scale_mm, bbox=bbox)
    print(f"    找到 {len(walls)} 段墙线")

    # 估计实际墙厚
    est_thickness = estimate_wall_thickness(img, h_axes, v_axes, scale_mm, bbox=bbox)
    print(f"    自适应墙厚: {est_thickness:.0f}mm")
    # 把估计的墙厚应用到所有墙段
    for w in walls:
        w.thickness_mm = est_thickness

    print(f"[4b/6] 检测门窗洞口...")
    openings = detect_openings(img, h_axes, v_axes, scale_mm, bbox=bbox)
    print(f"    找到 {len(openings)} 个门窗洞口")
    if openings:
        door_count = sum(1 for o in openings if o.kind == "door")
        window_count = sum(1 for o in openings if o.kind == "window")
        print(f"      门: {door_count}, 窗: {window_count}")

    print(f"[4c/6] 检测柱标记...")
    columns = detect_columns(img, h_axes, v_axes, scale_mm, bbox=bbox)
    print(f"    找到 {len(columns)} 个柱")

    print(f"[5/6] OCR 尺寸标注...")
    dims = ocr_dimensions(img, scale_mm)
    print(f"    识别到 {len(dims)} 个文字")

    # 组装数据
    data = DrawingData(
        h_axes=h_axes, v_axes=v_axes,
        walls=walls, openings=openings, columns=columns,
        dims=dims,
        image_w_px=w_px, image_h_px=h_px,
        scale_mm_per_px=scale_mm,
    )

    print(f"[6/6] 生成 DXF...")
    dxf_path = os.path.join(output_dir, f"{stem}_redraw.dxf")
    generate_dxf(data, dxf_path, title=stem)

    # 保存元数据
    meta = {
        "source": input_path,
        "dxf_output": dxf_path,
        "image_size_px": [w_px, h_px],
        "page_size_mm": [page_w_mm, page_h_mm],
        "scale": f"1:{print_scale}",
        "scale_mm_per_px": scale_mm,
        "h_axes": [{"label": a.label, "pos_mm": a.pos_mm} for a in h_axes],
        "v_axes": [{"label": a.label, "pos_mm": a.pos_mm} for a in v_axes],
        "wall_count": len(walls),
        "wall_thickness_mm": est_thickness,
        "opening_count": len(openings),
        "door_count": sum(1 for o in openings if o.kind == "door"),
        "window_count": sum(1 for o in openings if o.kind == "window"),
        "column_count": len(columns),
        "dim_count": len(dims),
    }
    meta_path = os.path.join(output_dir, f"{stem}_redraw.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"\n✅ DXF 已生成: {dxf_path}")
    print(f"✅ 元数据已保存: {meta_path}")

    # 保存检测可视化（用 ASCII 文件名避免编码问题）
    vis_path = os.path.join(output_dir, "detection.png")
    vis = img.copy()
    # 在主平面图区域框画框
    if bbox:
        cv2.rectangle(vis, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (0, 255, 255), 3)
    # 画轴线圆
    for cx, cy, r, side in circles:
        color = (0, 0, 255) if side in ("top", "bottom") else (255, 0, 0)
        cv2.circle(vis, (int(cx), int(cy)), int(r), color, 3)
        cv2.putText(vis, side[0], (int(cx)+15, int(cy)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    # 画轴线网格
    if h_axes and v_axes:
        x_min = min(a.pos_px for a in v_axes) - 100
        x_max = max(a.pos_px for a in v_axes) + 100
        y_min = min(a.pos_px for a in h_axes) - 100
        y_max = max(a.pos_px for a in h_axes) + 100
        for ha in h_axes:
            cv2.line(vis, (int(x_min), int(ha.pos_px)), (int(x_max), int(ha.pos_px)), (0, 255, 0), 1)
        for va in v_axes:
            cv2.line(vis, (int(va.pos_px), int(y_min)), (int(va.pos_px), int(y_max)), (0, 255, 0), 1)
    # 画墙体
    for wall in walls[:50]:  # 最多画 50 段
        # 转换 mm → 像素
        x1 = int(wall.x1_mm / scale_mm)
        y1 = h_px - int(wall.y1_mm / scale_mm)
        x2 = int(wall.x2_mm / scale_mm)
        y2 = h_px - int(wall.y2_mm / scale_mm)
        color = (0, 100, 255) if wall.is_external else (255, 100, 0)
        cv2.line(vis, (x1, y1), (x2, y2), color, 3)
    # 画门窗洞口（绿色方框）
    for op in openings:
        cx_px = int(op.cx_mm / scale_mm)
        cy_px = h_px - int(op.cy_mm / scale_mm)
        w_px = int(op.width_mm / 2 / scale_mm)
        if op.kind == "door":
            cv2.rectangle(vis, (cx_px - w_px, cy_px - 4),
                          (cx_px + w_px, cy_px + 4), (0, 255, 0), 2)
        else:
            cv2.rectangle(vis, (cx_px - w_px, cy_px - 4),
                          (cx_px + w_px, cy_px + 4), (0, 200, 100), 2)
    # 画柱（黄色方块）
    for col in columns:
        cx_px = int(col.cx_mm / scale_mm)
        cy_px = h_px - int(col.cy_mm / scale_mm)
        s_px = int(col.width_mm / 2 / scale_mm)
        cv2.rectangle(vis, (cx_px - s_px, cy_px - s_px),
                      (cx_px + s_px, cy_px + s_px), (0, 255, 255), 3)
    cv2.imwrite(vis_path, vis)
    print(f"✅ 检测可视化: {vis_path}")

    return {
        "dxf": dxf_path,
        "meta": meta_path,
        "vis": vis_path,
        "success": True,
        "summary": {
            "h_axes": len(h_axes),
            "v_axes": len(v_axes),
            "walls": len(walls),
            "wall_thickness_mm": round(est_thickness, 0),
            "openings": len(openings),
            "doors": sum(1 for o in openings if o.kind == "door"),
            "windows": sum(1 for o in openings if o.kind == "window"),
            "columns": len(columns),
            "dims": len(dims),
        }
    }


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="扫描图 → DXF 重绘")
    ap.add_argument("input", help="PDF 或 PNG 文件路径")
    ap.add_argument("--output", "-o", default="output", help="输出目录")
    ap.add_argument("--dpi", type=int, default=200, help="渲染 DPI")
    ap.add_argument("--scale", type=int, default=100, help="图纸比例 (100=1:100)")
    args = ap.parse_args()

    result = process_drawing(args.input, args.output, args.dpi, args.scale)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
