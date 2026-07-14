"""
Game-mode registry.

Usage::

    from game_modes import get_mode, list_modes

    mode = get_mode("501")
    player = mode.create_player("p1", "Alice")
"""

from .detection import DetectionMode
from .x01 import X01Mode
from .cricket import CricketMode
from .cut_throat import CutThroatMode
from .around_the_clock import AroundTheClockMode

_REGISTRY: dict = {
    "detection": DetectionMode(),
    "501": X01Mode(501),
    "301": X01Mode(301),
    "cricket": CricketMode(),
    "cut_throat": CutThroatMode(),
    "around_the_clock": AroundTheClockMode(),
}


def get_mode(mode_id: str):
    """Return the GameMode instance for *mode_id*, or raise KeyError."""
    if mode_id not in _REGISTRY:
        raise KeyError(f"Unknown game mode: {mode_id!r}. Available: {list(_REGISTRY)}")
    return _REGISTRY[mode_id]


def list_modes() -> list:
    """Return a list of dicts describing all available modes."""
    return [
        {
            "id": mode.id,
            "label": mode.label,
            "rules_summary": mode.rules_summary,
            "darts_per_turn": mode.darts_per_turn,
        }
        for mode in _REGISTRY.values()
    ]
