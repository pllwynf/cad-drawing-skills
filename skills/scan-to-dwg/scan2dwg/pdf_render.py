"""Render PDF pages to images via PyMuPDF (pure pip, no poppler needed)."""
from __future__ import annotations
import os
from pathlib import Path
from typing import List
import numpy as np

import fitz  # PyMuPDF


def render_pdf_pages(pdf_path: str, dpi: int = 300) -> List[np.ndarray]:
    """Render every page of a PDF to a BGR uint8 image at the given DPI."""
    if not Path(pdf_path).exists():
        raise FileNotFoundError(pdf_path)
    doc = fitz.open(pdf_path)
    out: List[np.ndarray] = []
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    for page in doc:
        pix = page.get_pixmap(matrix=mat, alpha=False)
        # PyMuPDF returns RGB
        rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
        bgr = rgb[:, :, ::-1].copy()  # RGB->BGR
        out.append(bgr)
    doc.close()
    return out


def render_pdf_to_pngs(pdf_path: str, out_dir: str, dpi: int = 300, prefix: str = "page") -> List[str]:
    """Render a PDF to PNG files. Returns the list of output paths."""
    os.makedirs(out_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    paths: List[str] = []
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=mat, alpha=False)
        path = os.path.join(out_dir, f"{prefix}_{i:03d}.png")
        pix.save(path)
        paths.append(path)
    doc.close()
    return paths