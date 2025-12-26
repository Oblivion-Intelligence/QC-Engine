"""Canonical market data domain types and helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional, Tuple


class Timeframe(Enum):
    """Supported candle resolutions."""

    MIN_1 = "1m"
    MIN_5 = "5m"
    MIN_15 = "15m"
    HOUR_1 = "1h"
    DAY_1 = "1d"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    def to_minutes(self) -> int:
        """Return the timeframe length in minutes."""

        mapping = {
            Timeframe.MIN_1: 1,
            Timeframe.MIN_5: 5,
            Timeframe.MIN_15: 15,
            Timeframe.HOUR_1: 60,
            Timeframe.DAY_1: 1440,
        }
        return mapping[self]

    @classmethod
    def from_minutes(cls, minutes: int) -> "Timeframe":
        """Create a timeframe from the number of minutes.

        Raises:
            ValueError: If the provided minutes do not match a supported timeframe.
        """

        mapping = {
            1: cls.MIN_1,
            5: cls.MIN_5,
            15: cls.MIN_15,
            60: cls.HOUR_1,
            1440: cls.DAY_1,
        }
        try:
            return mapping[minutes]
        except KeyError as exc:  # pragma: no cover - error path
            raise ValueError(f"Unsupported timeframe: {minutes} minutes") from exc


def ensure_utc(dt: datetime) -> datetime:
    """Normalize a datetime to a timezone-aware UTC datetime.

    Args:
        dt: Datetime to validate.

    Returns:
        Datetime converted to UTC.

    Raises:
        ValueError: If the datetime is naive (no timezone information).
    """

    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("Datetime must be timezone-aware and set to UTC")
    return dt.astimezone(timezone.utc)


def now_utc() -> datetime:
    """Return the current timezone-aware UTC datetime."""

    return datetime.now(timezone.utc)


def assert_aligned_to_grid(ts_utc: datetime, timeframe: Timeframe) -> None:
    """Ensure a timestamp lies on the expected timeframe grid.

    Alignment rules:

    - ``MIN_1``/``MIN_5``/``MIN_15``/``HOUR_1``: the Unix timestamp modulo the
      timeframe length in seconds must be zero (with small float tolerance).
    - ``DAY_1``: the timestamp must be exactly ``00:00:00`` UTC.

    Args:
        ts_utc: Timestamp to validate (timezone-aware).
        timeframe: Candle resolution to validate against.

    Raises:
        ValueError: If the timestamp is not aligned to the timeframe grid.
    """

    ts = ensure_utc(ts_utc)

    if timeframe is Timeframe.DAY_1:
        if ts.hour or ts.minute or ts.second or ts.microsecond:
            raise ValueError(
                f"timestamp {ts.isoformat()} not aligned to timeframe grid {timeframe.value}"
            )
        return

    delta_seconds = timeframe.to_minutes() * 60
    remainder = ts.timestamp() % delta_seconds
    tolerance = 1e-6
    if remainder > tolerance and abs(delta_seconds - remainder) > tolerance:
        raise ValueError(
            f"timestamp {ts.isoformat()} not aligned to timeframe grid {timeframe.value}"
        )


@dataclass
class Candle:
    """Canonical OHLCV candle representation."""

    instrument_id: str
    timeframe: Timeframe
    bar_start_ts_utc: datetime
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float]
    source: str
    available_ts_utc: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.timeframe, Timeframe):
            try:
                self.timeframe = Timeframe(self.timeframe)
            except Exception as exc:  # pragma: no cover - invalid path
                raise ValueError(f"Invalid timeframe: {self.timeframe}") from exc

        self.bar_start_ts_utc = ensure_utc(self.bar_start_ts_utc)
        self.available_ts_utc = ensure_utc(self.available_ts_utc)

        self._validate_numbers()
        self._validate_ohlc()
        self._validate_volume()

    def _validate_numbers(self) -> None:
        for field_name, value in {
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
        }.items():
            if not math.isfinite(value):
                raise ValueError(f"{field_name} must be a finite number")

        if self.volume is not None and not math.isfinite(self.volume):
            raise ValueError("volume must be a finite number when provided")

    def _validate_ohlc(self) -> None:
        highest = max(self.open, self.close, self.low)
        if self.high < highest:
            raise ValueError("high must be >= open, close, and low")

        lowest = min(self.open, self.close, self.high)
        if self.low > lowest:
            raise ValueError("low must be <= open, close, and high")

    def _validate_volume(self) -> None:
        if self.volume is not None and self.volume < 0:
            raise ValueError("volume must be non-negative when provided")

    def key(self) -> Tuple[str, str, datetime]:
        """Return the uniqueness key for storage and deduplication."""

        return (self.instrument_id, self.timeframe.value, self.bar_start_ts_utc)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the candle to a dictionary for storage/transport."""

        return {
            "instrument_id": self.instrument_id,
            "timeframe": self.timeframe.value,
            "bar_start_ts_utc": self.bar_start_ts_utc.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "source": self.source,
            "available_ts_utc": self.available_ts_utc.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Candle":
        """Reconstruct a :class:`Candle` from :meth:`to_dict` output."""

        return cls(
            instrument_id=data["instrument_id"],
            timeframe=Timeframe(data["timeframe"]),
            bar_start_ts_utc=ensure_utc(datetime.fromisoformat(data["bar_start_ts_utc"])),
            open=float(data["open"]),
            high=float(data["high"]),
            low=float(data["low"]),
            close=float(data["close"]),
            volume=None if data.get("volume") is None else float(data["volume"]),
            source=data["source"],
            available_ts_utc=ensure_utc(datetime.fromisoformat(data["available_ts_utc"])),
        )
