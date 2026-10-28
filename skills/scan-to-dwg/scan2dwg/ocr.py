"""OCR text recognition with dual-engine support: Tesseract (primary) + easyocr (fallback).

Engine selection order:
  1. Tesseract  -- fast, lightweight, needs external binary + traineddata
  2. easyocr    -- slower (PyTorch-based), pure pip install, auto-downloads models

If neither is available, all calls become no-ops and return empty results.
The pipeline still produces a DXF; the TEXT layer simply has no content.
"""
from __future__ import annotations
import logging
import warnings
from typing import List, Optional, Tuple

import numpy as np

# --- Tesseract (primary) ---
try:
    import pytesseract
    _HAS_PYTESSERACT = True
except ImportError:
    pytesseract = None  # type: ignore
    _HAS_PYTESSERACT = False

# --- easyocr (fallback) ---
# Lazy-imported: torch is heavy, so we only import easyocr when actually needed.
_HAS_EASYOCR = False
_easyocr_reader = None  # cached reader instance

from .config import find_tesseract


_LOG = logging.getLogger(__name__)
_WARNED_NO_OCR = False


# ---------------------------------------------------------------------------
# Availability checks
# ---------------------------------------------------------------------------

def _check_easyocr_available() -> bool:
    """Check if easyocr can be imported (without actually importing torch yet)."""
    try:
        import importlib
        spec = importlib.util.find_spec("easyocr")
        return spec is not None
    except Exception:
        return False


def is_available() -> bool:
    """True if at least one OCR engine is ready."""
    if _HAS_PYTESSERACT and find_tesseract() is not None:
        return True
    return _check_easyocr_available()


def get_engine_name() -> str:
    """Return the name of the engine that *will* be used, or 'none'."""
    if _HAS_PYTESSERACT and find_tesseract() is not None:
        return "tesseract"
    if _check_easyocr_available():
        return "easyocr"
    return "none"


# ---------------------------------------------------------------------------
# Tesseract backend
# ---------------------------------------------------------------------------

def _tesseract_recognize(gray: np.ndarray,
                         text_regions: List[Tuple[int, int, int, int]],
                         lang: str,
                         min_confidence: int,
                         padding: int
                         ) -> List[Tuple[float, float, float, float, str, int]]:
    results: List[Tuple[float, float, float, float, str, int]] = []
    H, W = gray.shape[:2]
    path = find_tesseract()
    if path:
        pytesseract.pytesseract.tesseract_cmd = path

    for (x, y, w, h) in text_regions:
        x1 = max(0, x - padding); y1 = max(0, y - padding)
        x2 = min(W, x + w + padding); y2 = min(H, y + h + padding)
        crop = gray[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        # upsample very small regions for better OCR
        if crop.shape[0] < 24 or crop.shape[1] < 60:
            scale = 3
            crop = np.kron(crop, np.ones((scale, scale), dtype=crop.dtype))
        try:
            data = pytesseract.image_to_data(
                crop, lang=lang,
                config="--psm 7 -c preserve_interword_spaces=1",
                output_type=pytesseract.Output.DICT,
            )
        except Exception as exc:
            _LOG.debug("tesseract OCR region (%d,%d,%d,%d) failed: %s", x, y, w, h, exc)
            continue
        for i, txt in enumerate(data["text"]):
            txt = (txt or "").strip()
            try:
                conf = int(float(data["conf"][i]))
            except (ValueError, TypeError):
                conf = -1
            if not txt or conf < min_confidence:
                continue
            tx = float(data["left"][i]) + float(data["width"][i]) / 2.0 + x1
            ty = float(data["top"][i]) + float(data["height"][i]) / 2.0 + y1
            tw = float(data["width"][i])
            th = float(data["height"][i])
            results.append((tx, ty, tw, th, txt, conf))
    return results


# ---------------------------------------------------------------------------
# easyocr backend
# ---------------------------------------------------------------------------

def _get_easyocr_reader(lang: str = "chi_sim+eng"):
    """Lazily create and cache an easyocr Reader.

    Maps the tesseract-style lang string to easyocr's language list.
    """
    global _easyocr_reader, _HAS_EASYOCR
    if _easyocr_reader is not None:
        return _easyocr_reader

    import easyocr  # noqa: E402  -- deferred import to avoid loading torch at module load

    # Map tesseract lang codes to easyocr lang codes
    lang_map = {
        "chi_sim": "ch_sim",
        "chi_tra": "ch_tra",
        "eng": "en",
    }
    langs = []
    for part in lang.split("+"):
        code = lang_map.get(part.strip(), part.strip())
        if code:
            langs.append(code)
    if not langs:
        langs = ["en"]

    _LOG.info("Initialising easyocr Reader (langs=%s) ...", langs)
    _easyocr_reader = easyocr.Reader(langs, gpu=False, verbose=False)
    _HAS_EASYOCR = True
    _LOG.info("easyocr Reader ready.")
    return _easyocr_reader


def _easyocr_recognize(gray: np.ndarray,
                       text_regions: List[Tuple[int, int, int, int]],
                       min_confidence: float,
                       padding: int
                       ) -> List[Tuple[float, float, float, float, str, int]]:
    results: List[Tuple[float, float, float, float, str, int]] = []
    H, W = gray.shape[:2]

    reader = _get_easyocr_reader()
    if reader is None:
        return results

    for (x, y, w, h) in text_regions:
        x1 = max(0, x - padding); y1 = max(0, y - padding)
        x2 = min(W, x + w + padding); y2 = min(H, y + h + padding)
        crop = gray[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        # easyocr works better with some padding / upsampling on tiny crops
        if crop.shape[0] < 20 or crop.shape[1] < 50:
            scale = 3
            crop = np.kron(crop, np.ones((scale, scale), dtype=crop.dtype))
        try:
            # easyocr.readtext returns list of (bbox, text, confidence)
            detections = reader.readtext(
                crop,
                detail=1,
                paragraph=False,
                text_threshold=0.5,
                low_text=0.4,
                link_threshold=0.4,
            )
        except Exception as exc:
            _LOG.debug("easyocr OCR region (%d,%d,%d,%d) failed: %s", x, y, w, h, exc)
            continue

        for bbox, text, conf in detections:
            text = (text or "").strip()
            if not text:
                continue
            # easyocr confidence is 0..1, convert to 0..100
            conf_pct = int(round(float(conf) * 100))
            if conf_pct < min_confidence:
                continue
            # bbox is [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] in crop coords
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            cx_crop = sum(xs) / len(xs)
            cy_crop = sum(ys) / len(ys)
            tw = max(xs) - min(xs)
            th = max(ys) - min(ys)
            # Map back to full image coordinates
            # Account for upsampling
            if crop.shape[0] > (y2 - y1):  # was upsampled
                sx = crop.shape[1] / float(x2 - x1)
                sy = crop.shape[0] / float(y2 - y1)
                cx_crop /= sx
                cy_crop /= sy
                tw /= sx
                th /= sy
            tx = cx_crop + x1
            ty = cy_crop + y1
            results.append((tx, ty, tw, th, text, conf_pct))
    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def recognize_text(gray: np.ndarray,
                   text_regions: List[Tuple[int, int, int, int]],
                   lang: str = "chi_sim+eng",
                   min_confidence: int = 30,
                   padding: int = 4) -> List[Tuple[float, float, float, float, str, int]]:
    """OCR each detected text region.

    Returns list of (cx, cy, w, h, text, conf) in image pixel space.
    Empty list if no OCR engine is available.

    Engine selection: Tesseract first, easyocr as fallback.
    """
    global _WARNED_NO_OCR

    # --- Try Tesseract first ---
    if _HAS_PYTESSERACT and find_tesseract() is not None:
        _LOG.info("OCR engine: tesseract (%d regions)", len(text_regions))
        return _tesseract_recognize(gray, text_regions, lang, min_confidence, padding)

    # --- Fall back to easyocr ---
    if _check_easyocr_available():
        try:
            _LOG.info("OCR engine: easyocr (%d regions)", len(text_regions))
            return _easyocr_recognize(gray, text_regions, float(min_confidence), padding)
        except Exception as exc:
            _LOG.warning("easyocr failed: %s", exc)
            return []

    # --- No engine available ---
    if not _WARNED_NO_OCR:
        warnings.warn(
            "No OCR engine available. Install either:\n"
            "  (a) Tesseract OCR (UB-Mannheim build + chi_sim traineddata), or\n"
            "  (b) easyocr:  pip install easyocr\n"
            "Text recognition will be skipped; the DXF TEXT layer will be empty."
        )
        _WARNED_NO_OCR = True
    return []
