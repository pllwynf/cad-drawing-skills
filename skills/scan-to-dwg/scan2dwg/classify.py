"""Classify a binarised drawing into per-layer masks.

Strategy (v2): operate per connected component on the binary image.
  - Columns: small high-solidity squares.
  - Axis circles: hollow rings (low solidity, ~square bbox) — or strict
    HoughCircles as a fallback.
  - Walls: long thin axis-aligned components WITHOUT nearby text.
  - Dimensions: long thin axis-aligned components WITH text nearby.
  - Openings: short / non-long components (door arcs, window breaks).
  - Text: glyph bounding boxes used for OCR; also drawn as the TEXT layer.
"""
from __future__ import annotations
from typing import Dict, List, Tuple
import numpy as np
import cv2

from .config import (
    AXIS_CIRCLE_DPIMIN, AXIS_CIRCLE_DPIMAX,
    LAYER_WALL, LAYER_COLUMN, LAYER_AXIS, LAYER_DIM, LAYER_OPENING, LAYER_TEXT,
    RENDER_DPI_DEFAULT,
)


def _px_per_pt(dpi: int = RENDER_DPI_DEFAULT) -> float:
    return dpi / 72.0


# --- columns (filled squares) -----------------------------------------------
def _detect_columns(binary: np.ndarray, px_per_pt: float) -> np.ndarray:
    out = np.zeros_like(binary)
    n, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if w == 0 or h == 0:
            continue
        bbox_area = w * h
        solidity = area / bbox_area
        aspect = max(w, h) / min(w, h)
        area_pt2 = area / (px_per_pt ** 2)
        # Column markers: ~5-15 mm printed at 1:100, side 14-42 pt, area
        # 200-1800 pt^2. Allow some slack for variable line thickness.
        if (30 <= area_pt2 <= 2500
                and solidity >= 0.85
                and aspect <= 1.6):
            cv2.rectangle(out, (x, y), (x + w, y + h), 255, -1)
    return out


# --- axis circles: ring-shape detection only ---------------------------------
def _detect_axis_circles(binary: np.ndarray, px_per_pt: float) -> np.ndarray:
    """Return (N, 3) array of (cx, cy, r) for axis-circle markers.

    Architectural drawings show axis intersections as small hollow
    circles with a label inside. We detect them by their ring-shape
    signature (square-ish bbox, low fill ratio) which is much more
    reliable than HoughCircles in dense line-drawing content.
    """
    circles_found: List[Tuple[float, float, float]] = []
    n, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if w == 0 or h == 0:
            continue
        aspect = max(w, h) / min(w, h)
        size_pt = max(w, h) / px_per_pt
        solidity = area / (w * h)
        # Axis ring: aspect ~1, size 6-15 pt printed, solidity 0.25-0.65
        # (hollow ring -> low fill ratio).
        if (6 <= size_pt <= 15 and aspect <= 1.3 and 0.25 <= solidity <= 0.65):
            cx = x + w / 2.0
            cy = y + h / 2.0
            r = max(w, h) / 2.0
            circles_found.append((cx, cy, r))

    if not circles_found:
        return np.zeros((0, 3), dtype=np.float32)
    return np.array(circles_found, dtype=np.float32)


def _render_axis_mask(shape, circles: np.ndarray) -> np.ndarray:
    out = np.zeros(shape, dtype=np.uint8)
    for (cx, cy, r) in circles:
        cv2.circle(out, (int(cx), int(cy)), int(max(2, r * 0.55)), 255, -1)
        cv2.circle(out, (int(cx), int(cy)), int(r), 255, 1)
    return out


# --- text glyphs / regions --------------------------------------------------
def _detect_text_glyphs(binary: np.ndarray, px_per_pt: float) -> List[Tuple[int, int, int, int]]:
    """Return list of (x, y, w, h) for components that look like text glyphs."""
    n, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    regions: List[Tuple[int, int, int, int]] = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        # Tight: real architectural text glyphs are 2-12 pt tall
        # and reasonably dense (no hollow noise blobs).
        if area < 12 or w < 4 or h < 4:
            continue
        size_pt = max(w, h) / px_per_pt
        if not (2.0 <= size_pt <= 12.0):
            continue
        aspect = max(w, h) / min(w, h)
        if aspect > 4.0:
            continue
        density = area / (w * h)
        if density < 0.30:
            continue
        regions.append((x, y, w, h))
    return regions


def _merge_text_regions(regions: List[Tuple[int, int, int, int]],
                        binary_shape: Tuple[int, int]) -> List[Tuple[int, int, int, int]]:
    if not regions:
        return []
    mask = np.zeros(binary_shape, dtype=np.uint8)
    for (x, y, w, h) in regions:
        cv2.rectangle(mask, (x, y), (x + w, y + h), 255, -1)
    # Dilate to bridge intra-line gaps; keep small so lines don't merge
    # across rows of text or with adjacent drawing elements.
    k = 8
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    dilated = cv2.dilate(mask, kernel, iterations=1)
    n, _, stats, _ = cv2.connectedComponentsWithStats(dilated, connectivity=8)
    merged = []
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        sub = mask[max(0, y):y + h, max(0, x):x + w]
        ys, xs = np.where(sub > 0)
        if len(xs):
            merged.append((int(xs.min() + x), int(ys.min() + y),
                           int(xs.max() - xs.min() + 1),
                           int(ys.max() - ys.min() + 1)))
        else:
            merged.append((x, y, w, h))
    return merged


# --- main classify ----------------------------------------------------------
def classify(binary: np.ndarray, gray: np.ndarray,
             dpi: int = RENDER_DPI_DEFAULT
             ) -> Tuple[Dict[str, np.ndarray], Dict[str, object]]:
    px_per_pt = _px_per_pt(dpi)
    H, W = binary.shape
    page_area = float(H * W)

    # 1. columns (filled squares)
    columns = _detect_columns(binary, px_per_pt)

    # 2. axes (rings + Hough)
    circles = _detect_axis_circles(binary, px_per_pt)
    axes = _render_axis_mask(binary.shape, circles)

    # 3. text glyphs -> line-level regions
    glyphs = _detect_text_glyphs(binary, px_per_pt)
    text_regions = _merge_text_regions(glyphs, binary.shape)
    text_mask = np.zeros_like(binary)
    for (x, y, w, h) in text_regions:
        cv2.rectangle(text_mask, (x, y), (x + w, y + h), 255, -1)

    # 4. mask out columns, axes, and text bboxes from binary to get residual
    non_special = binary.copy()
    non_special = cv2.subtract(non_special, columns)
    non_special = cv2.subtract(non_special, axes)
    # (don't subtract text_mask here -- text often sits on top of dim lines)

    # 5. classify each connected component of non_special
    n, _, stats, _ = cv2.connectedComponentsWithStats(non_special, connectivity=8)

    walls = np.zeros_like(binary)
    dims = np.zeros_like(binary)
    openings = np.zeros_like(binary)

    text_proximity = cv2.dilate(text_mask,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (35, 35)))

    LONG_ASPECT = 5.0
    MIN_LONG_AREA = 50

    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 8:
            continue
        bbox_area = w * h
        aspect = max(w, h) / min(w, h) if min(w, h) > 0 else 999
        bbox_ratio = bbox_area / page_area
        solidity = area / bbox_area if bbox_area else 0

        # Page-frame filter: large bbox that hugs the image edges and is hollow
        # (a rectangle outline). Real content has bbox ratio well below this.
        if bbox_ratio > 0.35 and solidity < 0.20:
            continue
        # Pure giant blob covering >50% area = page border / sheet background noise
        if bbox_ratio > 0.50:
            continue
        # Skip if region overlaps a text bbox (text already drawn from glyphs)
        if text_mask[y:y + h, x:x + w].any():
            continue

        # Long thin axis-aligned stroke: candidate wall OR dimension
        if aspect >= LONG_ASPECT and area >= MIN_LONG_AREA:
            pad = 6
            x1, y1 = max(0, x - pad), max(0, y - pad)
            x2, y2 = min(W, x + w + pad), min(H, y + h + pad)
            if text_proximity[y1:y2, x1:x2].any():
                cv2.rectangle(dims, (x, y), (x + w, y + h), 255, -1)
            else:
                cv2.rectangle(walls, (x, y), (x + w, y + h), 255, -1)
        else:
            cv2.rectangle(openings, (x, y), (x + w, y + h), 255, -1)

    # Drop the page frame from walls (it might still slip through)
    walls = _drop_page_frame(walls, page_area)
    dims = _drop_page_frame(dims, page_area)

    layers = {
        LAYER_WALL:    walls,
        LAYER_COLUMN:  columns,
        LAYER_AXIS:    axes,
        LAYER_DIM:     dims,
        LAYER_OPENING: openings,
        LAYER_TEXT:    text_mask,
    }
    extras = {"text_regions": text_regions, "axis_circles": circles}
    return layers, extras


def _drop_page_frame(mask: np.ndarray, page_area: float) -> np.ndarray:
    h, w = mask.shape
    out = mask.copy()
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        touches = 0
        if x <= 2: touches += 1
        if y <= 2: touches += 1
        if x + cw >= w - 2: touches += 1
        if y + ch >= h - 2: touches += 1
        area = cv2.contourArea(cnt)
        if touches >= 2 and area > 0.15 * page_area:
            cv2.drawContours(out, [cnt], -1, 0, -1)
    return out