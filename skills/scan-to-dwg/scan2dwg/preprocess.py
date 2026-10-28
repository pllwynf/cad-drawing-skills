"""Preprocess: mask red stamps, grayscale, light deskew, denoise, binarize."""
from __future__ import annotations
from typing import Tuple
import numpy as np
import cv2


def mask_red(bgr: np.ndarray) -> np.ndarray:
    """Replace red-dominant pixels (stamps/signatures) with white.

    Operates in-place and returns the same image.
    """
    b, g, r = cv2.split(bgr)
    red_mask = (r >= 140) & (g <= 110) & (b <= 110)
    bgr[red_mask] = 255
    return bgr


def to_grayscale(bgr: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)


def estimate_skew(binary: np.ndarray, max_angle: float = 5.0) -> float:
    """Estimate skew angle of a (mostly) line-drawing binary image in degrees.

    Uses the projection profile of Hough lines.
    Returns angle in degrees, positive = counter-clockwise.
    """
    # Downscale for speed
    h, w = binary.shape
    scale = 1.0
    if max(h, w) > 1200:
        scale = 1200.0 / max(h, w)
        small = cv2.resize(binary, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    else:
        small = binary
    edges = cv2.Canny(small, 50, 150, apertureSize=3)
    raw = cv2.HoughLinesP(edges, 1, np.pi / 360, threshold=80,
                          minLineLength=max(small.shape) // 20, maxLineGap=10)
    if raw is None or len(raw) == 0:
        return 0.0
    # OpenCV 4/5 may return either (N,1,4) or (N,4); normalise.
    lines = raw.reshape(-1, 4)
    angles = []
    for x1, y1, x2, y2 in lines:
        ang = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        # wrap to (-45, 45] so near-horizontal/vertical lines count
        if ang < -45:
            ang += 90
        elif ang > 45:
            ang -= 90
        if abs(ang) <= max_angle:
            angles.append(ang)
    if not angles:
        return 0.0
    return float(np.median(angles))


def deskew(gray: np.ndarray, angle: float) -> np.ndarray:
    if abs(angle) < 0.05:
        return gray
    h, w = gray.shape
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    # white border to avoid black wedges
    return cv2.warpAffine(gray, M, (w, h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=255)


def denoise(gray: np.ndarray, strength: int = 3) -> np.ndarray:
    """Mild Gaussian + median filter to suppress paper noise / scan wrinkles."""
    g = cv2.GaussianBlur(gray, (strength, strength), 0)
    return cv2.medianBlur(g, strength)


def binarize(gray: np.ndarray, block_size: int = 31, C: int = 8) -> np.ndarray:
    """Adaptive threshold -> binary with lines as white (255)."""
    return cv2.adaptiveThreshold(gray, 255,
                                 cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY_INV, block_size, C)


def preprocess(bgr: np.ndarray, deskew_enabled: bool = True) -> Tuple[np.ndarray, np.ndarray, float]:
    """Full preprocessing chain.

    Returns: (gray, binary, skew_angle_deg)
    """
    mask_red(bgr)
    gray = to_grayscale(bgr)
    binary_pre = binarize(gray, block_size=21, C=6)
    angle = estimate_skew(binary_pre) if deskew_enabled else 0.0
    if abs(angle) >= 0.05:
        gray = deskew(gray, angle)
    gray = denoise(gray)
    binary = binarize(gray)
    return gray, binary, angle