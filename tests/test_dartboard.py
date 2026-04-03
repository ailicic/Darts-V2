"""
Unit tests for dartboard geometry and scoring logic.
Run with:  python -m pytest tests/
"""

import math
import sys
import os

# Make backend modules importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pytest
from dartboard import (
    NUMBERS,
    BULLSEYE_OUTER,
    BULL_OUTER,
    TREBLE_INNER,
    TREBLE_OUTER,
    DOUBLE_INNER,
    DOUBLE_OUTER,
    get_segment_index,
    get_number_from_angle,
    get_zone,
    calculate_score,
    get_dart_score,
    segment_angles,
)


# ---------------------------------------------------------------------------
# get_segment_index
# ---------------------------------------------------------------------------

class TestGetSegmentIndex:
    def test_top_is_index_zero(self):
        assert get_segment_index(0) == 0

    def test_full_circle_wraps(self):
        assert get_segment_index(360) == 0
        assert get_segment_index(720) == 0

    def test_each_segment_boundary(self):
        # All 20 segments, sampled at their centres (i*18°)
        for i in range(20):
            assert get_segment_index(i * 18) == i

    def test_negative_angle_normalised(self):
        # -9° should still map to segment 0 (20 spans -9° to +9°)
        assert get_segment_index(-5) == 0


# ---------------------------------------------------------------------------
# get_number_from_angle
# ---------------------------------------------------------------------------

class TestGetNumberFromAngle:
    @pytest.mark.parametrize("angle, expected", [
        (0,   20),
        (18,   1),
        (36,  18),
        (54,   4),
        (72,  13),
        (90,   6),
        (108, 10),
        (126, 15),
        (144,  2),
        (162, 17),
        (180,  3),
        (198, 19),
        (216,  7),
        (234, 16),
        (252,  8),
        (270, 11),
        (288, 14),
        (306,  9),
        (324, 12),
        (342,  5),
    ])
    def test_all_segments(self, angle, expected):
        assert get_number_from_angle(angle) == expected

    def test_wraps_at_360(self):
        assert get_number_from_angle(360) == 20


# ---------------------------------------------------------------------------
# get_zone
# ---------------------------------------------------------------------------

class TestGetZone:
    def test_bullseye(self):
        assert get_zone(0.0)           == ("Bullseye", 1)
        assert get_zone(BULLSEYE_OUTER) == ("Bullseye", 1)

    def test_bull(self):
        assert get_zone(BULLSEYE_OUTER + 0.001) == ("Bull", 1)
        assert get_zone(BULL_OUTER)             == ("Bull", 1)

    def test_single_inner(self):
        mid = (BULL_OUTER + TREBLE_INNER) / 2
        assert get_zone(mid) == ("Single", 1)

    def test_treble(self):
        mid = (TREBLE_INNER + TREBLE_OUTER) / 2
        assert get_zone(mid) == ("Treble", 3)

    def test_single_outer(self):
        mid = (TREBLE_OUTER + DOUBLE_INNER) / 2
        assert get_zone(mid) == ("Single", 1)

    def test_double(self):
        mid = (DOUBLE_INNER + DOUBLE_OUTER) / 2
        assert get_zone(mid) == ("Double", 2)

    def test_miss(self):
        assert get_zone(1.01) == ("Miss", 0)
        assert get_zone(2.0)  == ("Miss", 0)


# ---------------------------------------------------------------------------
# calculate_score
# ---------------------------------------------------------------------------

class TestCalculateScore:
    def test_bullseye(self):
        assert calculate_score(0, "Bullseye", 1) == 50

    def test_bull(self):
        assert calculate_score(0, "Bull", 1) == 25

    def test_miss(self):
        assert calculate_score(20, "Miss", 0) == 0

    def test_single(self):
        assert calculate_score(20, "Single", 1) == 20
        assert calculate_score(1,  "Single", 1) == 1

    def test_double(self):
        assert calculate_score(20, "Double", 2) == 40
        assert calculate_score(5,  "Double", 2) == 10

    def test_treble(self):
        assert calculate_score(20, "Treble", 3) == 60
        assert calculate_score(17, "Treble", 3) == 51


# ---------------------------------------------------------------------------
# get_dart_score (integration)
# ---------------------------------------------------------------------------

BOARD_R = 170  # pixels — equals the real-world outer-double radius in mm


class TestGetDartScore:
    """End-to-end coordinate → score tests using board_radius=170."""

    def _polar(self, angle_deg: float, frac: float):
        """Return (dx, dy) at fractional radius and clockwise angle from top."""
        r = frac * BOARD_R
        rad = math.radians(angle_deg)
        return r * math.sin(rad), -r * math.cos(rad)

    def test_bullseye(self):
        n, z, m, s = get_dart_score(0, 0, BOARD_R)
        assert z == "Bullseye"
        assert s == 50

    def test_bull(self):
        dx, dy = self._polar(0, 0.06)
        n, z, m, s = get_dart_score(dx, dy, BOARD_R)
        assert z == "Bull"
        assert s == 25

    def test_double_20(self):
        dx, dy = self._polar(0, 0.97)      # top, inside double ring
        n, z, m, s = get_dart_score(dx, dy, BOARD_R)
        assert n == 20
        assert z == "Double"
        assert s == 40

    def test_treble_20(self):
        dx, dy = self._polar(0, 0.61)      # top, inside treble ring
        n, z, m, s = get_dart_score(dx, dy, BOARD_R)
        assert n == 20
        assert z == "Treble"
        assert s == 60

    def test_single_20(self):
        dx, dy = self._polar(0, 0.30)      # top, inner single
        n, z, m, s = get_dart_score(dx, dy, BOARD_R)
        assert n == 20
        assert z == "Single"
        assert s == 20

    def test_treble_17(self):
        dx, dy = self._polar(162, 0.61)    # 162° = 17
        n, z, m, s = get_dart_score(dx, dy, BOARD_R)
        assert n == 17
        assert z == "Treble"
        assert s == 51

    def test_double_1(self):
        dx, dy = self._polar(18, 0.97)     # 18° = 1
        n, z, m, s = get_dart_score(dx, dy, BOARD_R)
        assert n == 1
        assert z == "Double"
        assert s == 2

    def test_miss(self):
        dx, dy = self._polar(0, 1.10)      # outside board
        n, z, m, s = get_dart_score(dx, dy, BOARD_R)
        assert z == "Miss"
        assert s == 0

    def test_all_numbers_single(self):
        """Single hit in each segment at inner-single radius."""
        for i, expected_num in enumerate(NUMBERS):
            angle = i * 18.0
            dx, dy = self._polar(angle, 0.35)
            n, z, m, s = get_dart_score(dx, dy, BOARD_R)
            assert n == expected_num, f"angle={angle}° expected {expected_num} got {n}"
            assert z == "Single"
            assert s == expected_num


# ---------------------------------------------------------------------------
# segment_angles helper
# ---------------------------------------------------------------------------

class TestSegmentAngles:
    def test_returns_20_segments(self):
        segs = segment_angles()
        assert len(segs) == 20

    def test_each_segment_spans_18_degrees(self):
        for start, end, _ in segment_angles():
            assert abs((end - start) - 18) < 1e-9

    def test_numbers_match_sequence(self):
        segs = segment_angles()
        for i, (_, _, n) in enumerate(segs):
            assert n == NUMBERS[i]
