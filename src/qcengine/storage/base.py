"""Storage interfaces for persisting and retrieving market data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from qcengine.domain.marketdata import Candle, Timeframe


@dataclass
class AppendResult:
    """Outcome of persisting candles into a store."""

    written: int
    duplicates: int = 0


class CandleStore(Protocol):
    """Protocol describing the candle storage operations."""

    def append(self, candles: list[Candle]) -> AppendResult:
        """Append candles to the store with deduplication."""

    def read(
        self,
        instrument_id: str,
        timeframe: Timeframe,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Candle]:
        """Read candles for an instrument/timeframe, optionally bounded by time."""
