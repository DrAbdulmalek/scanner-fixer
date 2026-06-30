"""
deskew.py
Corrects small rotation angles (typically -45° to +45°) caused by
placing paper slightly crooked on the scanner glass.
Uses Hough line transform for accuracy on text documents.
"""

import cv2
import numpy as np
from typing import Tuple


def detect_skew_angle(image: np.ndarray) -> float:
    """
    Detects the skew angle of a scanned document.

    Strategy:
    1. Convert to grayscale + threshold
    2. Detect lines using HoughLinesP
    3. Filter near-horizontal lines (text baseline)
    4. Return median angle

    Args:
        image: Input image (BGR or grayscale)

    Returns:
        Detected skew angle in degrees (negative = tilted left)
    """
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()

    # Threshold to get text as white on black
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Morphological dilation to connect nearby characters into lines
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (30, 1))
    dilated = cv2.dilate(thresh, kernel, iterations=2)

    # Detect lines
    lines = cv2.HoughLinesP(
        dilated,
        rho=1,
        theta=np.pi / 180,
        threshold=100,
        minLineLength=100,
        maxLineGap=20
    )

    if lines is None:
        return 0.0

    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        if x2 - x1 == 0:
            continue
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        # Keep only near-horizontal lines (text baselines)
        if -45 < angle < 45:
            angles.append(angle)

    if not angles:
        return 0.0

    # Use median to be robust against outliers
    median_angle = float(np.median(angles))

    # Clamp to reasonable range
    return max(-45.0, min(45.0, median_angle))


def detect_skew_angle_projection(image: np.ndarray) -> float:
    """
    Alternative skew detection using horizontal projection profile.
    More reliable for documents with sparse text.

    Args:
        image: Input image

    Returns:
        Detected skew angle in degrees
    """
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()

    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    best_angle = 0.0
    best_score = -1.0

    # Search angles from -15 to +15 degrees
    for angle in np.arange(-15, 15.5, 0.5):
        rotated = _rotate_image(thresh, angle)
        # Sum pixels per row — highest variance = most aligned
        projection = np.sum(rotated, axis=1)
        score = float(np.var(projection))
        if score > best_score:
            best_score = score
            best_angle = angle

    return best_angle


def deskew(image: np.ndarray, method: str = "hough") -> Tuple[np.ndarray, float]:
    """
    Corrects the skew of a scanned document.

    Args:
        image: Input image (BGR or grayscale)
        method: "hough" (fast, good for text-rich pages) or
                "projection" (slower, better for sparse text)

    Returns:
        Tuple of (deskewed image, angle that was corrected)
    """
    if method == "projection":
        angle = detect_skew_angle_projection(image)
    else:
        angle = detect_skew_angle(image)

    # No correction needed for very small angles
    if abs(angle) < 0.3:
        return image, 0.0

    corrected = _rotate_image(image, -angle, white_background=True)
    return corrected, angle


def _rotate_image(image: np.ndarray, angle: float, white_background: bool = True) -> np.ndarray:
    """
    Rotates image around its center with optional white background fill.

    Args:
        image: Input image
        angle: Rotation angle in degrees (positive = counter-clockwise)
        white_background: Fill empty areas with white instead of black

    Returns:
        Rotated image (same size as input)
    """
    h, w = image.shape[:2]
    cx, cy = w // 2, h // 2

    matrix = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)

    if white_background:
        if len(image.shape) == 3:
            border_value = (255, 255, 255)
        else:
            border_value = 255
    else:
        border_value = 0

    rotated = cv2.warpAffine(
        image, matrix, (w, h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=border_value
    )

    return rotated
