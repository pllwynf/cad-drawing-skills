"""Assemble the per-layer vector data into an ezdxf DXF document."""
from __future__ import annotations
from typing import Dict, List, Tuple
import numpy as np
import ezdxf
from ezdxf.enums import TextEntityAlignment

from .config import LAYER_DEFS, LAYER_AXIS, LAYER_TEXT


# A polyline is a list of (x, y) tuples in *image* pixel coordinates.
Polyline = List[Tuple[float, float]]
# A text entity is (cx, cy, w, h, text, conf).
TextEntity = Tuple[float, float, float, float, str, int]


def _img_to_dxf(x: float, y: float, height_px: float, scale: float) -> Tuple[float, float]:
    """Image (origin top-left, y down) -> DXF (origin bottom-left, y up), in mm."""
    return (x * scale, (height_px - y) * scale)


def create_dxf(polylines_by_layer: Dict[str, List[Polyline]],
               axis_circles: np.ndarray,
               text_entities: List[TextEntity],
               image_height_px: float,
               scale_pt_to_mm: float,
               dxf_version: str = "R2018",
               title: str = "scan-to-dwg",
               source: str = "",
               print_scale: int = 100) -> ezdxf.document.Drawing:
    """Build an ezdxf Drawing with named layers.

    scale_pt_to_mm converts PDF-point-equivalent pixel units to mm in the
    output DXF. With print scale 1:100, scale_pt_to_mm = 25.4/72 * 100.
    """
    doc = ezdxf.new(dxf_version, setup=True)
    doc.header["$INSUNITS"] = 4  # millimetres
    msp = doc.modelspace()

    # --- layers ---
    for name, defn in LAYER_DEFS.items():
        if name in doc.layers:
            layer = doc.layers.get(name)
        else:
            layer = doc.layers.add(name)
        layer.color = defn["color"]
        if defn.get("description"):
            layer.description = defn["description"]

    # --- polylines ---
    for layer_name, polylines in polylines_by_layer.items():
        if layer_name not in doc.layers:
            doc.layers.add(layer_name, color=8)
        for polyline in polylines:
            if len(polyline) < 2:
                continue
            pts = [_img_to_dxf(x, y, image_height_px, scale_pt_to_mm)
                   for (x, y) in polyline]
            try:
                msp.add_lwpolyline(pts, dxfattribs={"layer": layer_name})
            except Exception:
                # fallback: LINE-by-LINE for malformed point lists
                for i in range(len(pts) - 1):
                    msp.add_line(pts[i], pts[i + 1],
                                 dxfattribs={"layer": layer_name})

    # --- axis circles (drawn as CIRCLE entities) ---
    for (cx, cy, r) in axis_circles:
        if r <= 0:
            continue
        cx_d, cy_d = _img_to_dxf(cx, cy, image_height_px, scale_pt_to_mm)
        msp.add_circle((cx_d, cy_d), r * scale_pt_to_mm,
                       dxfattribs={"layer": LAYER_AXIS})

    # --- text entities (OCR) ---
    for (cx, cy, w, h, text, conf) in text_entities:
        if not text or h <= 0:
            continue
        height_mm = h * scale_pt_to_mm * 0.65
        if height_mm < 0.4:        # skip illegibly tiny text
            continue
        cx_d, cy_d = _img_to_dxf(cx, cy, image_height_px, scale_pt_to_mm)
        try:
            ent = msp.add_text(text, dxfattribs={
                "layer": LAYER_TEXT,
                "height": height_mm,
            })
            ent.set_placement((cx_d, cy_d), align=TextEntityAlignment.MIDDLE_CENTER)
        except Exception:
            pass

    return doc


def save_dxf(doc: ezdxf.document.Drawing, path: str) -> str:
    doc.saveas(path)
    return path