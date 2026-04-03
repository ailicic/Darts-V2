"""
Dartboard geometry, scoring logic, and coordinate mapping.

Standard dartboard layout (BDO/WDF regulations):
- Numbers clockwise from top: 20,1,18,4,13,6,10,15,2,17,3,19,7,16,8,11,14,9,12,5
- Each segment spans 18 degrees (360/20)
- Ring boundaries measured from center:
    Bullseye outer: 6.35 mm
    Bull outer:    15.9  mm
    Treble inner:  99    mm
    Treble outer: 107    mm
    Double inner: 162    mm
    Double outer: 170    mm  (used as reference radius = 1.0)
"""

import math

# Standard clockwise number sequence starting at top (12 o'clock = 20)
NUMBERS = [20, 1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5]

# Ring boundaries as fractions of the outer-double radius (170 mm)
BULLSEYE_OUTER = 6.35 / 170    # ~0.0374
BULL_OUTER = 15.9 / 170        # ~0.0935
TREBLE_INNER = 99.0 / 170      # ~0.5824
TREBLE_OUTER = 107.0 / 170     # ~0.6294
DOUBLE_INNER = 162.0 / 170     # ~0.9529
DOUBLE_OUTER = 1.0


def get_segment_index(angle_deg: float) -> int:
    """Return segment index 0-19 for a clockwise angle from north (top)."""
    # Normalise to [0, 360)
    angle = angle_deg % 360
    # Number 20 is centred at 0°; shift so each bucket starts 9° before its centre
    return int((angle + 9) % 360 / 18) % 20


def get_number_from_angle(angle_deg: float) -> int:
    """Return the dartboard number (1-20) for a given clockwise angle from north."""
    return NUMBERS[get_segment_index(angle_deg)]


def get_zone(normalised_radius: float) -> tuple:
    """
    Return (zone_name, multiplier) for a normalised radius
    (0 = board centre, 1.0 = outer edge of double ring).
    """
    if normalised_radius <= BULLSEYE_OUTER:
        return "Bullseye", 1
    if normalised_radius <= BULL_OUTER:
        return "Bull", 1
    if normalised_radius <= TREBLE_INNER:
        return "Single", 1
    if normalised_radius <= TREBLE_OUTER:
        return "Treble", 3
    if normalised_radius <= DOUBLE_INNER:
        return "Single", 1
    if normalised_radius <= DOUBLE_OUTER:
        return "Double", 2
    return "Miss", 0


def calculate_score(number: int, zone: str, multiplier: int) -> int:
    """Return the score for a dart hit."""
    if zone == "Bullseye":
        return 50
    if zone == "Bull":
        return 25
    if zone == "Miss":
        return 0
    return number * multiplier


def get_dart_score(dx: float, dy: float, board_radius: float) -> tuple:
    """
    Calculate the full scoring result for a dart at pixel offset (dx, dy)
    from the board centre, where *board_radius* is the outer-double radius
    in pixels.

    Returns (number, zone, multiplier, score).
    """
    distance = math.sqrt(dx * dx + dy * dy)
    normalised = distance / board_radius if board_radius > 0 else 1.5

    # Clockwise angle from north: atan2(x, -y)
    angle = math.degrees(math.atan2(dx, -dy)) % 360

    zone, multiplier = get_zone(normalised)

    if zone in ("Bullseye", "Bull", "Miss"):
        number = 0
    else:
        number = get_number_from_angle(angle)

    score = calculate_score(number, zone, multiplier)
    return number, zone, multiplier, score


# ---------------------------------------------------------------------------
# Helpers for overlay drawing
# ---------------------------------------------------------------------------

def segment_angles() -> list:
    """
    Return a list of (start_angle_deg, end_angle_deg, number) for all
    20 segments (clockwise from north).
    """
    segments = []
    for i, n in enumerate(NUMBERS):
        centre = i * 18.0  # degrees clockwise from north
        segments.append((centre - 9, centre + 9, n))
    return segments
