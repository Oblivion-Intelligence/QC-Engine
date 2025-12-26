"""Backfill orchestration for historical market data."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Sequence

from qcengine.adapters.base import (
    AdapterError,
    AuthError,
    InvalidResponse,
    MarketDataAdapter,
    InstrumentRef,
    RateLimited,
    Unavailable,
)
from qcengine.domain.marketdata import Candle, Timeframe, ensure_utc
from qcengine.domain.time_windows import Window
from qcengine.storage.base import AppendResult, CandleStore

logger = logging.getLogger(__name__)


def clamp_candles_to_window(candles: Sequence[Candle], window: Window) -> list[Candle]:
    """Filter candles to the half-open ``window`` while preserving order.

    Candles are kept iff ``window.start_utc <= bar_start_ts_utc < window.end_utc``.
    The returned list preserves the input order and asserts the sequence is sorted
    by ``bar_start_ts_utc``.
    """

    filtered = [c for c in candles if window.contains(c.bar_start_ts_utc)]

    for prev, curr in zip(filtered, filtered[1:]):
        assert (
            prev.bar_start_ts_utc <= curr.bar_start_ts_utc
        ), "candles must be sorted by bar_start_ts_utc"

    return filtered


@dataclass
class BackfillJob:
    adapter: MarketDataAdapter
    storage: CandleStore
    instruments: Sequence[InstrumentRef]
    timeframes: Iterable[Timeframe]
    start_utc: datetime
    end_utc: datetime
    max_retries: int = 3
    backoff_seconds: float = 1.0

    def run(self) -> None:
        """Execute the backfill over all instruments and timeframes."""

        window = Window(ensure_utc(self.start_utc), ensure_utc(self.end_utc))

        for instrument in self.instruments:
            for timeframe in self.timeframes:
                self._run_single(instrument, timeframe, window)

    def _run_single(
        self, instrument: InstrumentRef, timeframe: Timeframe, window: Window
    ) -> None:
        candles = clamp_candles_to_window(
            self._fetch_with_retry(
                instrument, timeframe, window.start_utc, window.end_utc
            ),
            window,
        )
        if not candles:
            logger.info(
                "backfill returned no candles",
                extra={
                    "instrument_id": instrument.instrument_id,
                    "timeframe": timeframe.value,
                    "start_utc": window.start_utc.isoformat(),
                    "end_utc": window.end_utc.isoformat(),
                },
            )
            return

        result = self.storage.append(candles)
        first, last = candles[0].bar_start_ts_utc, candles[-1].bar_start_ts_utc
        logger.info(
            "backfill stored candles",
            extra={
                "instrument_id": instrument.instrument_id,
                "timeframe": timeframe.value,
                "requested_start": window.start_utc.isoformat(),
                "requested_end": window.end_utc.isoformat(),
                "returned": len(candles),
                "written": result.written,
                "duplicates": result.duplicates,
                "covered_start": first.isoformat(),
                "covered_end": last.isoformat(),
            },
        )

    def _fetch_with_retry(
        self, instrument: InstrumentRef, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Candle]:
        attempt = 0
        while True:
            attempt += 1
            try:
                return self.adapter.get_historical_candles(instrument, timeframe, start, end)
            except (RateLimited, Unavailable) as exc:
                if attempt > self.max_retries:
                    logger.error("backfill retries exhausted", exc_info=exc)
                    raise
                sleep_for = self.backoff_seconds * (2 ** (attempt - 1))
                logger.warning(
                    "retryable adapter error; backing off",
                    extra={
                        "instrument_id": instrument.instrument_id,
                        "timeframe": timeframe.value,
                        "attempt": attempt,
                        "sleep": sleep_for,
                        "error": str(exc),
                    },
                )
                time.sleep(sleep_for)
            except (AuthError, InvalidResponse):
                raise
            except AdapterError:
                raise
