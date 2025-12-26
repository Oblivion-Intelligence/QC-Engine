"""Canonical time window handling for half-open UTC intervals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from qcengine.domain.marketdata import ensure_utc


@dataclass(frozen=True)
class Window:
    """A half-open UTC interval ``[start_utc, end_utc)``."""

    start_utc: datetime
    end_utc: datetime

    def __post_init__(self) -> None:  # pragma: no cover - exercised via methods
        start = ensure_utc(self.start_utc)
        end = ensure_utc(self.end_utc)

        if start >= end:
            raise ValueError("window start must be before end")

        object.__setattr__(self, "start_utc", start)
        object.__setattr__(self, "end_utc", end)

    def contains(self, timestamp: datetime) -> bool:
        """Return ``True`` if ``timestamp`` falls within the window.

        The interval is inclusive of ``start_utc`` and exclusive of ``end_utc``.
        All comparisons are performed in UTC.
        """

        ts = ensure_utc(timestamp)
        return self.start_utc <= ts < self.end_utc

    def split(self, step: timedelta) -> list[Window]:
        """Split the window into consecutive, non-overlapping chunks.

        Each resulting window starts where the previous one ended, ensuring
        stitchable ranges suitable for backfill pagination.
        """

        if step.total_seconds() <= 0:
            raise ValueError("step must be positive")

        windows: list[Window] = []
        current_start = self.start_utc
        while current_start < self.end_utc:
            next_end = min(current_start + step, self.end_utc)
            windows.append(Window(current_start, next_end))
            current_start = next_end

        return windows
