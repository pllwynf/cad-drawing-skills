"""Vectorize per-layer masks into polylines and primitive entities."""
from __future__ import annotations
from typing import Dict, List, Tuple
import numpy as np
import cv2

from .config import LAYER_WALL, LAYER_COLUMN, LAYER_AXIS, LAYER_TEXT, RENDER_DPI_DEFAULT


Polyline = List[Tuple[float, float]]


def mask_to_polylines(mask: np.ndarray, epsilon_px: float = 1.2,
                      min_area_px: int = 8) -> List[Polyline]:
    """Convert a binary mask into a list of polylines (closed or open).

    Each polyline is a list of (x, y) tuples in pixel coordinates.
    Open contours are returned with a closing segment of False == open.
    """
    contours, hierarchy = cv2.findContours(
        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    polylines: List[Polyline] = []
    for cnt in contours:
        if cv2.contourArea(cnt) < min_area_px:
            continue
        approx = cv2.approxPolyDP(cnt, epsilon_px, True)
        if len(approx) < 2:
            continue
        pts = [(float(p[0][0]), float(p[0][1])) for p in approx]
        polylines.append(pts)
    return polylines


def text_bboxes_to_entities(text_regions, dpi: int = RENDER_DPI_DEFAULT):
    """Convert OCR-region bboxes into (x_center, y_center, w, h) tuples."""
    out = []
    for (x, y, w, h) in text_regions:
        cx = x + w / 2.0
        cy = y + h / 2.0
        out.append((cx, cy, w, h))
    return out


def vectorize_all(layers: Dict[str, np.ndarray],
                  text_regions,
                  dpi: int = RENDER_DPI_DEFAULT):
    """Vectorize all layers.

    Returns: (polylines_by_layer: dict[layer -> list[Polyline]],
              axis_circles_param: list of (cx, cy, r),
              text_boxes: list of (cx, cy, w, h))
    """
    polylines: Dict[str, List[Polyline]] = {}
    for name, mask in layers.items():
        if name == LAYER_AXIS:
            # axis layer contains filled disks; we'll emit them as circles via
            # the circles list, but also keep outlines as polylines for the
            # circle outline.
            polylines[name] = []
        elif name == LAYER_TEXT:
            polylines[name] = []
        else:
            polylines[name] = mask_to_polylines(mask)

    text_boxes = text_bboxes_to_entities(text_regions, dpi)
    return polylines, text_boxes