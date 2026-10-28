"""Constants, defaults, environment detection for scan-to-dwg.

All tunables live here so callers can override via CLI flags without
editing code.
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Optional


# --- Geometry / units ---------------------------------------------------------
# PDF/PostScript point -> millimetre: 1 in = 25.4 mm, 1 in = 72 pt
PT_TO_MM = 25.4 / 72.0  # ≈ 0.3528

# Default drawing scale: 1 drawing unit (mm) on paper represents
# 100 mm in reality (i.e. 1:100 print scale). DXF coordinates are
# emitted in real-world mm, so the PDF->mm scale factor is PT_TO_MM * 100.
DEFAULT_PRINT_SCALE = 100


# --- Rasterization ------------------------------------------------------------
RENDER_DPI_DEFAULT = 300   # for vectorization
RENDER_DPI_PREVIEW = 150   # for quick previews


# --- Red mask (stamps / signatures) -------------------------------------------
# Pixels where red dominates are treated as non-drawing content (stamps).
RED_R_MIN = 140
RED_G_MAX = 110
RED_B_MAX = 110


# --- Layer classification -----------------------------------------------------
# Stroke width thresholds are in PDF points, calibrated at 300 DPI.
# A wall (thick) is typically >= 2.5 pt printed, openings ~1.2-2.0,
# dimension/text ~0.3-1.0 pt.
STROKE_WALL_PT = 2.2       # thick lines -> wall layer
STROKE_DIM_PT = 1.1        # medium-thin -> openings / dim
# Anything thinner is treated as text / fine detail by default.

# Detection morph-kernel sizes (in pixels at 300 DPI). These are auto
# scaled by the actual render DPI when used.
MORPH_WALL_PX = 5
MORPH_DIM_PX = 2


# --- Axis circle detection ----------------------------------------------------
AXIS_CIRCLE_DPIMIN = 60    # 60 px @ 300 DPI == 1.5 mm printed
AXIS_CIRCLE_DPIMAX = 180   # 180 px @ 300 DPI == 4.5 mm printed


# --- Column detection ---------------------------------------------------------
COLUMN_MIN_AREA_PT2 = 60.0    # min area in pt^2 for a column blob
COLUMN_MAX_AREA_PT2 = 4500.0
COLUMN_SOLIDITY_MIN = 0.85    # filled ratio inside the bounding box


# --- DXF layer naming & colors (ACI) ------------------------------------------
LAYER_AXIS    = "AXIS"
LAYER_WALL    = "WALL"
LAYER_COLUMN  = "COLUMN"
LAYER_OPENING = "OPENING"   # doors / windows / detail-index symbols
LAYER_DIM     = "DIM"
LAYER_TEXT    = "TEXT"
LAYER_MISC    = "MISC"

LAYER_DEFS = {
    LAYER_AXIS:    {"color": 7,  "description": "Axis lines & circles"},
    LAYER_WALL:    {"color": 7,  "description": "Walls (thick lines)"},
    LAYER_COLUMN:  {"color": 8,  "description": "Columns (filled squares)"},
    LAYER_OPENING: {"color": 4,  "description": "Doors, windows, symbols"},
    LAYER_DIM:     {"color": 9,  "description": "Dimension annotations"},
    LAYER_TEXT:    {"color": 250,"description": "Text labels (OCR)"},
    LAYER_MISC:    {"color": 8,  "description": "Unclassified lines"},
}


# --- Tool discovery -----------------------------------------------------------
def find_tesseract() -> Optional[str]:
    """Locate tesseract.exe on the system. Returns path or None."""
    candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    # fall back to PATH
    from shutil import which
    w = which("tesseract")
    return w


def find_oda_converter() -> Optional[str]:
    """Locate ODA File Converter (ODAFileConverter.exe)."""
    candidates = [
        r"C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe",
        r"C:\Program Files (x86)\ODA\ODAFileConverter\ODAFileConverter.exe",
        os.path.expanduser(r"~\AppData\Local\Programs\ODA\ODAFileConverter\ODAFileConverter.exe"),
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


def find_accoreconsole() -> Optional[str]:
    """Locate AutoCAD's accoreconsole.exe (for DXF->DWG via AutoCAD)."""
    base = Path(r"C:\Program Files\Autodesk")
    if not base.exists():
        return None
    for p in base.glob("*/accoreconsole.exe"):
        return str(p)
    return None