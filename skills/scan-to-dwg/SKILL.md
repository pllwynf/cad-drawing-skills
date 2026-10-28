---
title: "扫描图纸转 DWG/DXF"
summary: "将纸质扫描的建筑图纸（PDF/图片）自动重绘为分层 DXF/DWG 矢量文件"
description: |
  适用于改造类项目中业主仅能提供纸质扫描图纸的场景。
  将扫描的 PDF/图片通过图像处理 + 连通分量分析 + 矢量化管线，
  自动分离轴线、墙体、门窗、标注、文字等图层，输出可编辑的 DXF 文件。
  可选转换为 DWG（需 ODA File Converter）。
  支持 OCR 文字识别（Tesseract 或 easyocr）。
version: "0.1.0"
author: "WorkBuddy"
created: "2026-07-30"
categories:
  - architecture
  - cad
  - drawing-conversion
tags:
  - scan
  - dwg
  - dxf
  - cad
  - architectural-drawing
  - ocr
  - opencv
triggers:
  - 扫描图纸转CAD
  - 扫描图转DWG
  - PDF转DXF
  - 图纸重绘
  - 纸质图纸数字化
  - scan to dwg
  - scan to dxf
  - convert scanned drawing
---

# 扫描图纸转 DWG/DXF（scan-to-dwg）

## 用途

将业主提供的**纸质扫描图纸**（PDF 或图片格式）自动重绘为分层的 **DXF/DWG** 矢量文件，解决改造类项目中无法获取 CAD 原图的问题。

## 技术管线

skill 提供**两种管线**模式（通过 `--mode` 参数选择）：

### 模式 1: vectorize（默认，v1 矢量化）

```
PDF/图片
  │
  ├─ 1. PDF 渲染 (PyMuPDF, 300 DPI)
  ├─ 2. 预处理
  │     ├─ 红色图章掩膜去除
  │     ├─ 灰度化
  │     ├─ Hough 纠偏 (deskew)
  │     ├─ 降噪 (Gaussian + Median)
  │     └─ 自适应二值化 (THRESH_BINARY_INV)
  ├─ 3. 要素分类 (connectedComponentsWithStats)
  │     ├─ AXIS   — 轴线圆环（环形 shape 检测）
  │     ├─ COLUMN — 柱（高填充率方块）
  │     ├─ WALL   — 长线条（无文字邻近）
  │     ├─ DIM    — 长线条（有文字邻近 = 尺寸标注）
  │     ├─ OPENING— 门窗/短线条/符号
  │     └─ TEXT   — 文字字形区域
  ├─ 4. 矢量化 (findContours + approxPolyDP)
  ├─ 5. OCR 文字识别 (Tesseract / easyocr)
  ├─ 6. DXF 合成 (ezdxf, 分图层, mm 单位)
  └─ 7. DWG 转换 (ODA File Converter, 可选)
```

适用：扫描质量较好、图面元素密集、需要细粒度还原。
缺点：扫描图噪声会产生大量碎线，需要在 CAD 中清理。

### 模式 2: redraw（v2 读图重绘，推荐）

```
PDF/图片
  │
  ├─ 1. PDF 渲染 (PyMuPDF, 200 DPI)
  ├─ 2. 自动检测主平面图区域
  │     └─ 排除右侧详图、图框等
  ├─ 3. 检测轴线交点圆 (connectedComponentsWithStats)
  │     ├─ 45-85px 圆形、近似正方形
  │     ├─ 圆度 0.65-0.95、填充率 0.50-0.80
  │     └─ 仅保留主平面图区域内的圆
  ├─ 4. 构建轴线网格
  │     ├─ 纵向轴线 = top/bottom 圆的 x 坐标聚类 → 1-N 编号
  │     └─ 横向轴线 = left/right 圆的 y 坐标聚类 → A-T 编号
  ├─ 5. OCR 读取尺寸标注 (Tesseract)
  ├─ 6. 墙体检测 (沿轴线的粗线段)
  │     ├─ 自适应二值化 + 行列投影
  │     ├─ 至少跨越 80% 最小轴间距
  │     ├─ 相邻段合并（gap < 60px）
  │     └─ 每轴只保留最长 3 段
  ├─ 7. 自适应估计墙厚（实测填充宽度中位数）
  ├─ 8. 门窗洞口检测（墙线间断分析）
  │     ├─ 间断宽度 35-230 px（445-2920mm at 1:100 200dpi）
  │     ├─ door: 600-1500mm, window: 1500-2400mm
  │     └─ 两侧墙段至少 25-40px 长（过滤尺寸标注文字）
  ├─ 9. 柱标记检测（轴线交点处的实心填充矩形）
  │     └─ 尺寸 15-50px (= 190-635mm), 填充率 > 65%
  └─ 10. ezdxf 直接生成干净 DXF
        ├─ AXIS: 轴线网格（红色虚线）
        ├─ AXIS_CIRC: 轴线圆
        ├─ AXIS_TEXT: 轴线编号
        ├─ WALL: 内墙（白色实线）
        ├─ WALL_EXT: 外墙（蓝色实线）
        ├─ COLUMN: 柱（灰色实心矩形）
        ├─ OPENING: 门窗洞口（绿色矩形，门/窗有区分）
        └─ DIM: 尺寸标注文字
```

适用：原本就是 CAD 出的图纸被扫描的（如竣工图），有清晰轴线。
优点：输出干净，无碎线，无 OpenCV 矢量化噪声；DXF 可直接打开使用。
**推荐用于本项目（业主提供的扫描图通常是原 CAD 出图）。**

## 使用方法

### 基本用法

```bash
# Python 虚拟环境路径
PY="C:/Users/<用户名>/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
SKILL_DIR="C:/Users/<用户名>/.workbuddy/skills/scan-to-dwg"

# 模式 1: 矢量化（默认）
$PY "$SKILL_DIR/scripts/run.py" "input.pdf" --scale 100 --dpi 300

# 模式 2: 读图重绘（推荐改造类项目）
$PY "$SKILL_DIR/scripts/run.py" "input.pdf" --mode redraw --scale 100 --dpi 200

# 直接调用 redraw 模块
$PY -m scan2dwg.redraw_dxf "input.pdf" -o output/ --dpi 200 --scale 100

# 跳过 OCR（仅矢量，无文字）
$PY "$SKILL_DIR/scripts/run.py" "input.pdf" --no-ocr

# 跳过 DWG 转换（仅 DXF）
$PY "$SKILL_DIR/scripts/run.py" "input.pdf" --no-dwg

# 指定输出目录
$PY "$SKILL_DIR/scripts/run.py" "input.pdf" -o "output_dir/"
```

### 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `input` | (必填) | 输入文件路径，支持 PDF/PNG/JPG/TIFF/BMP |
| `-o, --output` | 同目录下 `_scan2dwg/` | 输出目录 |
| `--scale` | 100 | 打印比例（如 1:100 填 100） |
| `--dpi` | 300 (v1) / 200 (v2) | 渲染 DPI |
| `--mode` | `vectorize` | 管线模式：`vectorize`（v1 详细）或 `redraw`（v2 干净轴线） |
| `--no-ocr` | false | 跳过 OCR 文字识别 |
| `--no-dwg` | false | 跳过 DWG 转换，仅输出 DXF |
| `-v, --verbose` | false | 显示调试日志 |

### 输出文件

| 文件 | 说明 |
|------|------|
| `<name>.dxf` | 分图层 DXF 矢量文件（始终生成） |
| `<name>.dwg` | DWG 文件（需安装 ODA File Converter） |
| `<name>_layers.png` | 各图层蒙太奇预览图（v1） |
| `<name>_redraw.json` | 元数据（v2） |
| `detection.png` | 轴线圆 + 轴线网格可视化（v2） |

## 图层定义

### v2 redraw 模式（推荐）

| 图层名 | ACI 颜色 | 说明 |
|--------|----------|------|
| `AXIS` | 1 (红) | 横向 + 纵向轴线网格 |
| `AXIS_CIRC` | 1 (红) | 轴线交点圆 |
| `AXIS_TEXT` | 1 (红) | 轴线编号文字（1-N, A-T） |
| `WALL` | 7 (白) | 内墙 |
| `WALL_EXT` | 5 (蓝) | 外墙 |
| `COLUMN` | 8 (灰) | 柱 |
| `OPENING` | 3 (绿) | 门窗洞口 |
| `DIM` | 2 (黄) | 尺寸标注 |
| `TEXT` | 4 (青) | 一般文字 |

### v1 vectorize 模式

| 图层名 | ACI 颜色 | 说明 |
|--------|----------|------|
| `AXIS` | 7 (白) | 轴线圆及轴线 |
| `WALL` | 7 (白) | 墙体（粗线） |
| `COLUMN` | 8 (灰) | 柱（实心方块） |
| `OPENING` | 4 (青) | 门窗、符号 |
| `DIM` | 9 (浅灰) | 尺寸标注 |
| `TEXT` | 250 (深灰) | 文字（OCR 识别） |
| `MISC` | 8 (灰) | 未分类线条 |

## 依赖安装

### Python 依赖（已预装在隔离 venv）

```bash
pip install PyMuPDF opencv-python numpy ezdxf matplotlib pytesseract
# 可选 OCR 备选：
pip install easyocr   # 需 PyTorch，体积较大
```

### 外部工具（可选）

| 工具 | 用途 | 安装方式 |
|------|------|----------|
| **Tesseract OCR** | 文字识别（主引擎） | [UB-Mannheim](https://github.com/UB-Mannheim/tesseract/wiki) 安装包，需 `chi_sim` 语言包 |
| **easyocr** | 文字识别（备选引擎） | `pip install easyocr` |
| **ODA File Converter** | DXF→DWG 转换 | [ODA 官网](https://www.opendesign.com/guestfiles/oda_file_converter) 免费下载 |

### OCR 引擎选择

代码自动选择可用引擎，优先级：
1. **Tesseract**（快、轻量，需外部二进制）
2. **easyocr**（慢、需 PyTorch，纯 pip 安装）
3. 无引擎时跳过 OCR，TEXT 层为空

## 坐标系与比例

- DXF 坐标单位：毫米（mm），`INSUNITS` = 4
- **比例因子（已修正）**：
  - 像素 → 实际尺寸 mm = `25.4 / dpi × print_scale`
  - 例：300 DPI、1:100 比例 → `25.4/300 × 100 = 8.467 mm/px`
- 图像 y 轴（向下）→ DXF y 轴（向上）自动翻转
- 在样图（1303×603mm PDF）上的输出去范围：
  - X: 0 ~ 130,243 mm（图纸宽 1302.4 mm ✓）
  - Y: 8.5 ~ 60,325 mm（图纸高 603.2 mm ✓）

## 已知限制

1. **柱检测**：若图中"柱"为剖面线填充而非实心方块，可能检测不到。需人工补充。
2. **OPENING 过包含**：所有非长线条的小碎片归入 OPENING 层，可能包含噪声。建议在 CAD 中清理。
3. **OCR 依赖外部工具**：未安装 Tesseract/easyocr 时 TEXT 层为空。
4. **DWG 转换依赖外部工具**：未安装 ODA File Converter 时仅输出 DXF。
5. **手绘图纸**：对非标准制图（手绘、歪斜严重）效果较差。
6. **线段精度**：approxPolyDP 容差约 1.2 像素（≈0.3mm @300DPI），满足 1mm 偏移要求。

## 模块结构

```
scan-to-dwg/
├── SKILL.md                  ← 本文件
├── scan2dwg/
│   ├── __init__.py           ← 包定义
│   ├── config.py             ← 常量、图层定义、工具发现
│   ├── pdf_render.py         ← PDF→图像渲染 (PyMuPDF)
│   ├── preprocess.py         ← 预处理（去红章/灰度/纠偏/二值化）  [v1]
│   ├── classify.py           ← 要素分类（连通分量分析）  [v1]
│   ├── vectorize.py          ← 矢量化（轮廓→多段线）  [v1]
│   ├── ocr.py                ← OCR 文字识别（Tesseract + easyocr 双引擎）
│   ├── dxf_write.py          ← DXF 合成（ezdxf）  [v1]
│   ├── dwg_convert.py        ← DXF→DWG 转换
│   ├── cad_redraw.py         ← LISP+accoreconsole 方案（实验性，因 accoreconsole 中文路径问题未启用）
│   └── redraw_dxf.py         ← v2 读图重绘：轴线圆检测+OCR+ezdxf 直接输出  [v2]
└── scripts/
    └── run.py                ← CLI 入口（支持 --mode vectorize|redraw）
```

## v2 redraw 模式实测样图（提取自实训大楼建施图1.pdf）

### v3 最新版（带门窗/柱/墙厚检测）

- 输入：PDF 单页 A1 加长（1303×603mm），1:100，蓝底白线扫描
- 渲染：200 DPI → 10256×4750 px
- 检测：
  - 主平面图区域自动识别：x=410-7179 px（左侧 70%）
  - 46 个轴线圆（top 11 + left 9 + interior + bottom + right）
  - 9 条横向轴线 (A-I)，10 条纵向轴线 (1-10)
  - 总尺寸：宽 55.95m × 高 36.28m
- **自适应墙厚：114 mm**（自动从图像测量，避免固定 200mm 的误差）
- **57 段墙线**（每轴最长 3 段）
- **21 个门窗洞口**（17 门 + 4 窗，按宽度自动分类）
- **0 个柱**（本张样图无显式柱标记）
- **258 个 OCR 识别文字**（含 6000/4500/9000 等尺寸数字）
- 输出 DXF：约 1100+ 个实体（轴线 19 + 轴线圆 90 + 轴线编号 38 + 墙 57 + 门窗 ~84 + 尺寸 258）

### v2 初版（仅轴线/墙/OCR）

- 57 段墙线 + 258 个 OCR 文字 + 输出 462 个 DXF 实体

## 关键参数（v3 调优后）

| 参数 | 值 | 说明 |
|------|-----|------|
| 检测 DPI | 200 | v2 redraw 默认 |
| 墙段最小长度 | 80% 最小轴间距 | 过滤短噪线 |
| 墙段合并间隔 | 60 px | 合并间距小于此值的相邻段 |
| 每轴保留墙段数 | 3 | 取最长 3 段 |
| 洞口最小间断 | 35 px | ≈ 445mm（门最小宽度） |
| 洞口最大间断 | 230 px | ≈ 2920mm（窗最大宽度） |
| 洞口两侧最小墙长 | 25-40 px | 过滤尺寸标注文字误判 |
| 柱检测半径 | 80 px | 轴线交点附近搜索范围 |
| 柱尺寸 | 15-50 px | ≈ 190-635mm |
| 柱填充率 | ≥ 65% | 实心判定 |
| 墙厚自适应 | 中位数 | 测量多个墙线样本取中位数 |

## 示例

在用户提供的建筑平面图样图（1:100，蓝底白线扫描，含红色竣工图章）上的运行结果：

- 输入：PDF 单页 3692×1710 pt（1303×603mm）
- 渲染：300 DPI → 15384×7125 px
- 纠偏：0.00°（原图已正）
- 管线耗时：约 88 秒（含 matplotlib 图层预览）
- 分类结果：
  - AXIS: 303 个轴线圆
  - WALL: 892 条多段线（主楼轮廓清晰）
  - DIM: 299 条多段线
  - OPENING: 7948 条多段线（偏多，含门窗+小碎片）
  - COLUMN: 0（图中无实心柱标记）
  - TEXT: 2177 个文字区域（待 OCR 引擎安装后识别）
- 输出：
  - `提取自实训大楼建施图1.dxf`（2.87 MB，9442 个实体，9 个图层）
  - `提取自实训大楼建施图1_layers.png`（图层预览蒙太奇）
  - 坐标系范围：130243 × 60325 mm（与 1:100 比例下图纸实际尺寸吻合）
