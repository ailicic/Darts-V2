"""
Dart and dartboard detection using OpenCV.

Detection pipeline
------------------
1. Dartboard detection  – HoughCircles on a blurred grayscale frame.
2. Reference capture    – Store a clean frame of the board (no darts).
3. Dart detection       – Diff against reference; analyse new contours.
4. Tip localisation     – Extreme point of each new contour closest to the
                          board centre (the dart tip).
5. Coordinate mapping   – Convert pixel offset to polar coords; look up
                          number and ring zone.
"""

import math
import threading

import cv2
import numpy as np

from dartboard import (
    BULLSEYE_OUTER,
    BULL_OUTER,
    TREBLE_INNER,
    TREBLE_OUTER,
    DOUBLE_INNER,
    DOUBLE_OUTER,
    NUMBERS,
    get_dart_score,
)


class DartDetector:
    """Stateful dart-detection processor for a single camera stream."""

    # Minimum area (px²) for a contour to be considered a dart
    MIN_DART_AREA = 40
    MAX_DART_AREA = 8000
    # Minimum aspect ratio height/width to class a blob as dart-shaped
    MIN_ASPECT_RATIO = 1.2
    # Pixel-difference threshold for frame-diff binarisation
    DIFF_THRESHOLD = 20
    # How many seconds must pass before the next auto-detection fires
    DETECTION_COOLDOWN = 2.5

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # Dartboard calibration
        self.board_center: tuple | None = None   # (cx, cy) in pixels
        self.board_radius: float | None = None   # outer-double radius in px
        self.calibrated: bool = False

        # Reference frame for change-detection (grayscale, blurred)
        self.reference_frame: np.ndarray | None = None

        # Seconds since epoch of the last confirmed detection
        self.last_detection_time: float = 0.0

        # Internal: last darts drawn on the overlay
        self._last_overlay_darts: list = []

    # ------------------------------------------------------------------
    # Calibration helpers
    # ------------------------------------------------------------------

    def set_calibration(self, cx: float, cy: float, radius: float) -> None:
        """Manually set board centre and outer-double radius."""
        with self._lock:
            self.board_center = (int(cx), int(cy))
            self.board_radius = float(radius)
            self.calibrated = True

    def detect_dartboard(self, frame: np.ndarray) -> bool:
        """
        Attempt automatic dartboard detection via Hough circles.
        Returns True and updates calibration if a board is found.
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (9, 9), 2)

        h, w = frame.shape[:2]
        min_dim = min(h, w)
        min_r = max(min_dim // 10, 30)
        max_r = min_dim // 2

        circles = cv2.HoughCircles(
            blurred,
            cv2.HOUGH_GRADIENT,
            dp=1.2,
            minDist=min_dim // 3,
            param1=60,
            param2=28,
            minRadius=min_r,
            maxRadius=max_r,
        )

        if circles is not None:
            circles = np.round(circles[0]).astype(int)
            # Pick the largest circle (most likely to be the board)
            cx, cy, r = max(circles, key=lambda c: c[2])
            with self._lock:
                self.board_center = (int(cx), int(cy))
                self.board_radius = float(r)
                self.calibrated = True
            return True
        return False

    # ------------------------------------------------------------------
    # Reference-frame management
    # ------------------------------------------------------------------

    def capture_reference(self, frame: np.ndarray) -> None:
        """Store *frame* as the new baseline (board state without new darts)."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        ref = cv2.GaussianBlur(gray, (5, 5), 0)
        with self._lock:
            self.reference_frame = ref

    # ------------------------------------------------------------------
    # Dart detection
    # ------------------------------------------------------------------

    def detect_darts(self, frame: np.ndarray) -> list:
        """
        Compare *frame* against the stored reference and return a list of
        dart-tip pixel coordinates [(x, y), …].
        """
        with self._lock:
            ref = self.reference_frame
            center = self.board_center
            radius = self.board_radius

        if ref is None:
            self.capture_reference(frame)
            return []

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)

        # Absolute difference and threshold
        diff = cv2.absdiff(ref, blurred)
        _, thresh = cv2.threshold(diff, self.DIFF_THRESHOLD, 255, cv2.THRESH_BINARY)

        # Clean up noise
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN,  kernel, iterations=1)

        # Restrict search area to board region (if calibrated)
        if center and radius:
            mask = np.zeros_like(thresh)
            board_search_r = int(radius * 1.1)
            cv2.circle(mask, center, board_search_r, 255, -1)
            thresh = cv2.bitwise_and(thresh, mask)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        tips = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < self.MIN_DART_AREA or area > self.MAX_DART_AREA:
                continue

            x, y, w, h = cv2.boundingRect(cnt)
            if w == 0:
                continue
            aspect = h / w

            # Darts are elongated – allow vertical (h>w) or horizontal (w>h)
            if max(aspect, 1.0 / aspect) < self.MIN_ASPECT_RATIO:
                continue

            # Find the extreme point of the contour closest to the board centre
            tip = self._find_tip(cnt, center)
            tips.append(tip)

        return tips

    @staticmethod
    def _find_tip(contour: np.ndarray, center) -> tuple:
        """
        Return the extreme point of *contour* that is closest to *center*.
        Falls back to contour centroid if no center is known.
        """
        pts = contour.reshape(-1, 2)
        if center is None:
            M = cv2.moments(contour)
            if M["m00"] != 0:
                return (int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"]))
            return tuple(pts[0])

        cx, cy = center
        distances = np.sqrt((pts[:, 0] - cx) ** 2 + (pts[:, 1] - cy) ** 2)
        closest_idx = int(np.argmin(distances))
        return (int(pts[closest_idx, 0]), int(pts[closest_idx, 1]))

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def analyse_hit(self, tip: tuple, confidence: float = 0.75) -> dict | None:
        """
        Convert pixel coordinates *tip* to a scoring result.
        Returns a dict or None if not calibrated.
        """
        with self._lock:
            center = self.board_center
            radius = self.board_radius
            calibrated = self.calibrated

        if not calibrated or center is None or radius is None:
            return None

        dx = tip[0] - center[0]
        dy = tip[1] - center[1]
        number, zone, multiplier, score = get_dart_score(dx, dy, radius)

        return {
            "number": number,
            "zone": zone,
            "multiplier": multiplier,
            "score": score,
            "confidence": confidence,
            "x": tip[0],
            "y": tip[1],
        }

    # ------------------------------------------------------------------
    # Overlay drawing
    # ------------------------------------------------------------------

    def draw_overlay(
        self,
        frame: np.ndarray,
        darts: list | None = None,
    ) -> np.ndarray:
        """
        Return a copy of *frame* with the dartboard overlay and dart
        markers drawn.  *darts* is a list of (x, y) tip positions.
        """
        overlay = frame.copy()

        with self._lock:
            center = self.board_center
            radius = self.board_radius

        if center and radius:
            cx, cy = center
            r = int(radius)

            # Segment dividers and number labels
            for i, num in enumerate(NUMBERS):
                # Divider lines (at segment edges)
                edge_angle = math.radians(i * 18 - 9)
                x1 = int(cx + r * 0.09 * math.sin(edge_angle))
                y1 = int(cy - r * 0.09 * math.cos(edge_angle))
                x2 = int(cx + r * 1.02 * math.sin(edge_angle))
                y2 = int(cy - r * 1.02 * math.cos(edge_angle))
                cv2.line(overlay, (x1, y1), (x2, y2), (180, 180, 180), 1)

                # Number label just outside the double ring
                label_angle = math.radians(i * 18)
                lx = int(cx + r * 1.12 * math.sin(label_angle))
                ly = int(cy - r * 1.12 * math.cos(label_angle))
                cv2.putText(
                    overlay,
                    str(num),
                    (lx - 8, ly + 5),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.38,
                    (255, 255, 255),
                    1,
                    cv2.LINE_AA,
                )

            # Ring circles
            ring_specs = [
                (BULLSEYE_OUTER, (0, 255, 255), 2),   # bullseye
                (BULL_OUTER,     (0, 200, 255), 1),   # bull
                (TREBLE_INNER,   (255, 200, 0), 1),   # treble inner
                (TREBLE_OUTER,   (255, 140, 0), 2),   # treble outer
                (DOUBLE_INNER,   (80, 180, 255), 1),  # double inner
                (DOUBLE_OUTER,   (0, 255, 80),  2),   # double outer / board edge
            ]
            for frac, color, thickness in ring_specs:
                ring_r = int(r * frac)
                if ring_r > 0:
                    cv2.circle(overlay, (cx, cy), ring_r, color, thickness)

        # Dart markers
        if darts:
            for tip in darts:
                cv2.circle(overlay, tip, 10, (0, 0, 255), 2)
                cv2.circle(overlay, tip,  2, (0, 0, 255), -1)
                cv2.drawMarker(
                    overlay, tip, (0, 60, 255),
                    cv2.MARKER_CROSS, 22, 2, cv2.LINE_AA,
                )

        # Blend for semi-transparency
        result = cv2.addWeighted(overlay, 0.75, frame, 0.25, 0)
        return result
