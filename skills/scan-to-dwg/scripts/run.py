"""End-to-end CLI: scanned PDF/image -> DXF (and optional DWG).

Usage:
    python scripts/run.py <input.pdf> [-o OUTPUT_DIR] [--no-ocr] [--no-dwg]
                                     [--scale 100] [--dpi 300] [--mode vectorize|redraw]

Output:
    OUTPUT_DIR/<basename>.dxf          always
    OUTPUT_DIR/<basename>.dwg          only if DWG converter is available
    OUTPUT_DIR/<basename>_preview.png  PNG preview of the classified layers (vectorize mode)
    OUTPUT_DIR/<basename>_pipeline.png montage of pipeline stages (debug)

Modes:
    vectorize  (default, v1) -- Connected-component vectorization; produces
                detailed polylines per layer. May produce fragmented output on
                noisy scans.
    redraw     (v2) -- Detect axis circles + OCR dimensions + scan walls, then
                emit a clean DXF with explicit AXIS / WALL / DIM / TEXT layers
                and accurate mm coordinates. Recommended for architectural
                plans that came from a CAD source originally.
"""
from __future__ import annotations
import argparse
import logging
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

# Allow running as `python scripts/run.py` without installing the package.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scan2dwg import pdf_render, preprocess, classify, vectorize, ocr, dxf_write
from scan2dwg.dwg_convert import dxf_to_dwg
from scan2dwg.config import (
    PT_TO_MM, RENDER_DPI_DEFAULT, DEFAULT_PRINT_SCALE,
    find_tesseract, find_oda_converter,
)


_LOG = logging.getLogger("scan2dwg")


def _save_layer_montage(layers: dict, path: str) -> None:
    """Render a montage of classified layer masks for inspection."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    names = list(layers.keys())
    n = len(names)
    cols = 3
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(5 * cols, 4 * rows))
    axes = np.atleast_1d(axes).flatten()
    for i, name in enumerate(names):
        axes[i].imshow(layers[name], cmap="gray", vmin=0, vmax=255)
        axes[i].set_title(name)
        axes[i].axis("off")
    for j in range(i + 1, len(axes)):
        axes[j].axis("off")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def process_one(image_bgr: np.ndarray, args, output_dir: str, basename: str,
                log: logging.Logger) -> dict:
    """Run the full pipeline on a single BGR image. Returns dict of output paths.

    Dispatches to v1 (vectorize) or v2 (redraw) based on args.mode.
    """
    if args.mode == "redraw":
        return _process_redraw(image_bgr, args, output_dir, basename, log)

    # ---- default v1 vectorize pipeline ----
    log.info("preprocessing ...")
    gray, binary, skew = preprocess.preprocess(image_bgr)
    log.info("  skew estimated: %.2f deg", skew)
    Hpx, Wpx = binary.shape

    log.info("classifying layers ...")
    layers, extras = classify.classify(binary, gray, dpi=args.dpi)
    log.info("  axis circles: %d", len(extras["axis_circles"]))
    log.info("  text regions: %d", len(extras["text_regions"]))

    log.info("vectorizing ...")
    polylines, text_boxes = vectorize.vectorize_all(layers, extras["text_regions"], dpi=args.dpi)
    for layer_name, pl in polylines.items():
        log.info("  %-9s: %d polylines", layer_name, len(pl))

    # OCR
    text_entities = []
    if args.no_ocr:
        log.info("OCR skipped (--no-ocr).")
    elif not ocr.is_available():
        log.warning("No OCR engine available (need Tesseract or easyocr); skipping text recognition.")
    else:
        log.info("OCR engine: %s, %d regions ...", ocr.get_engine_name(), len(text_boxes))
        text_entities = ocr.recognize_text(gray, text_boxes, lang="chi_sim+eng")
        log.info("  recognised: %d text fragments", len(text_entities))

    # Pixel -> real-world mm conversion:
    #   1 pixel = 25.4/dpi mm on paper
    #   At 1:scale, 1 paper mm = scale real-world mm
    #   => 1 pixel = 25.4/dpi * scale  real-world mm
    px_to_mm = 25.4 / args.dpi * args.scale
    log.info("assembling DXF (scale 1:%d, factor %.4f mm/px @ %d DPI) ...",
             args.scale, px_to_mm, args.dpi)

    doc = dxf_write.create_dxf(
        polylines_by_layer=polylines,
        axis_circles=extras["axis_circles"],
        text_entities=text_entities,
        image_height_px=Hpx,
        scale_pt_to_mm=px_to_mm,
        title=basename,
        print_scale=args.scale,
    )
    dxf_path = os.path.join(output_dir, basename + ".dxf")
    dxf_write.save_dxf(doc, dxf_path)
    log.info("DXF saved: %s", dxf_path)

    # Layer montage for inspection
    montage_path = os.path.join(output_dir, basename + "_layers.png")
    try:
        _save_layer_montage(layers, montage_path)
        log.info("Layer montage: %s", montage_path)
    except Exception as exc:
        log.debug("layer montage failed: %s", exc)

    # DWG conversion (best-effort)
    dwg_path = None
    if not args.no_dwg:
        try:
            dwg_path = os.path.join(output_dir, basename + ".dwg")
            dxf_to_dwg(dxf_path, dwg_path, version="R2018")
            log.info("DWG saved: %s", dwg_path)
        except Exception as exc:
            log.warning("DWG conversion skipped: %s", exc)

    return {
        "dxf": dxf_path, "dwg": dwg_path, "montage": montage_path,
        "skew_deg": skew, "text_count": len(text_entities),
    }


def _process_redraw(image_bgr: np.ndarray, args, output_dir: str,
                    basename: str, log: logging.Logger) -> dict:
    """v2 "redraw" pipeline: read drawing -> emit clean DXF."""
    from scan2dwg import redraw_dxf as _redraw
    # Save to a temp PNG with ASCII-safe name (avoid Chinese path encoding issues)
    tmp_path = os.path.join(output_dir, "_tmp_input.png")
    cv2.imwrite(tmp_path, image_bgr)
    result = _redraw.process_drawing(tmp_path, output_dir, dpi=args.dpi,
                                     print_scale=args.scale)
    # Clean up tmp
    try:
        os.remove(tmp_path)
    except Exception:
        pass
    # Rename _redraw outputs to match basename
    src_dxf = result["dxf"]
    src_json = result["meta"]
    src_vis = result["vis"]
    dst_dxf = os.path.join(output_dir, basename + ".dxf")
    dst_json = os.path.join(output_dir, basename + "_redraw.json")
    for src, dst in [(src_dxf, dst_dxf), (src_json, dst_json)]:
        if src != dst and os.path.isfile(src):
            try:
                os.replace(src, dst)
            except Exception:
                import shutil
                shutil.move(src, dst)
    return {
        "dxf": dst_dxf, "dwg": None,
        "vis": src_vis, "meta": dst_json, "summary": result["summary"],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Convert scanned drawings to DXF/DWG")
    ap.add_argument("input", help="Path to a scanned PDF (or PNG/JPG)")
    ap.add_argument("-o", "--output", default=None, help="Output directory")
    ap.add_argument("--scale", type=int, default=DEFAULT_PRINT_SCALE,
                    help="Print scale (e.g. 100 for 1:100). Default: 100")
    ap.add_argument("--dpi", type=int, default=RENDER_DPI_DEFAULT,
                    help="Render DPI. Default: 300")
    ap.add_argument("--no-ocr", action="store_true",
                    help="Skip OCR (no text recognised)")
    ap.add_argument("--no-dwg", action="store_true",
                    help="Skip DWG conversion (only DXF produced)")
    ap.add_argument("--mode", choices=["vectorize", "redraw"], default="vectorize",
                    help="Pipeline mode: vectorize (v1, detailed) or redraw (v2, clean axis-grid).")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = _LOG
    input_path = Path(args.input).resolve()
    if not input_path.exists():
        log.error("input not found: %s", input_path)
        return 2

    out_dir = args.output or str(input_path.parent / (input_path.stem + "_scan2dwg"))
    os.makedirs(out_dir, exist_ok=True)

    log.info("scan-to-dwg starting")
    log.info("  input: %s", input_path)
    log.info("  output: %s", out_dir)
    log.info("  scale: 1:%d   dpi: %d", args.scale, args.dpi)
    log.info("  OCR engine: %s", ocr.get_engine_name())
    log.info("  ODA converter: %s", find_oda_converter() or "(not found)")

    suffix = input_path.suffix.lower()
    t0 = time.time()
    if suffix == ".pdf":
        pages = pdf_render.render_pdf_pages(str(input_path), dpi=args.dpi)
        results = []
        for i, img in enumerate(pages):
            sub = f"{input_path.stem}_p{i + 1:02d}" if len(pages) > 1 else input_path.stem
            log.info("=== page %d / %d ===", i + 1, len(pages))
            results.append(process_one(img, args, out_dir, sub, log))
    elif suffix in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"):
        img = cv2.imread(str(input_path), cv2.IMREAD_COLOR)
        if img is None:
            log.error("could not read image: %s", input_path)
            return 3
        results = [process_one(img, args, out_dir, input_path.stem, log)]
    else:
        log.error("unsupported input: %s", suffix)
        return 4

    log.info("done in %.1fs", time.time() - t0)
    for i, r in enumerate(results):
        log.info("page %d: dxf=%s  dwg=%s", i + 1, r["dxf"], r.get("dwg"))
    return 0


if __name__ == "__main__":
    sys.exit(main())