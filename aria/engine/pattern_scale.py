"""Pattern time-scale classification.

Patterns in ARIA span three scales:
- Micro (seconds-minutes): motion triggers light, door opens
- Meso (minutes-hours): morning routine, cooking session
- Macro (days-weeks): seasonal shifts, schedule changes

Used to tag detected patterns, shadow predictions, and accuracy tracking.
"""

from enum import Enum


class PatternScale(str, Enum):
    """Time-scale classification for detected patterns."""

    MICRO = "micro"
    MESO = "meso"
    MACRO = "macro"

    @property
    def description(self) -> str:
        """Human-readable description of this scale."""
        return _DESCRIPTIONS[self]

    @property
    def window_range(self) -> tuple[int, int | None]:
        """Duration range as (min_seconds, max_seconds_or_None)."""
        return _WINDOW_RANGES[self]

    @classmethod
    def from_duration_seconds(cls, duration_s: float) -> "PatternScale":
        """Classify a pattern by its time span.

        Args:
            duration_s: Pattern duration in seconds.

        Returns:
            The appropriate PatternScale.
        """
        if duration_s < 300:  # < 5 minutes
            return cls.MICRO
        elif duration_s < 14400:  # < 4 hours
            return cls.MESO
        else:
            return cls.MACRO


_DESCRIPTIONS = {
    PatternScale.MICRO: "Seconds to minutes — immediate reactions (motion triggers light)",
    PatternScale.MESO: "Minutes to hours — routines and sessions (morning routine)",
    PatternScale.MACRO: "Days to weeks — seasonal and schedule patterns",
}

_WINDOW_RANGES = {
    PatternScale.MICRO: (0, 300),
    PatternScale.MESO: (300, 14400),
    PatternScale.MACRO: (14400, None),
}
