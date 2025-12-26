from datetime import datetime, timedelta, timezone

import pytest

from qcengine.domain.marketdata import Candle, Timeframe
from qcengine.domain.time_windows import Window
from qcengine.ingestion.backfill import clamp_candles_to_window


def _make_candle(base: datetime, minutes: int) -> Candle:
    ts = base + timedelta(minutes=minutes)
    return Candle(
        instrument_id="ABC",
        timeframe=Timeframe.MIN_1,
        bar_start_ts_utc=ts,
        open=1.0,
        high=1.0,
        low=1.0,
        close=1.0,
        volume=1.0,
        source="test",
        available_ts_utc=base,
    )


def test_clamp_candles_filters_to_half_open_window() -> None:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    window = Window(base, base + timedelta(minutes=3))
    candles = [_make_candle(base, offset) for offset in (-1, 0, 1, 2, 3, 4)]

    clamped = clamp_candles_to_window(candles, window)

    assert [c.bar_start_ts_utc for c in clamped] == [
        base + timedelta(minutes=i) for i in (0, 1, 2)
    ]


def test_clamp_candles_asserts_sorted() -> None:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    window = Window(base, base + timedelta(minutes=2))
    candles = [_make_candle(base, offset) for offset in (1, 0)]

    with pytest.raises(AssertionError):
        clamp_candles_to_window(candles, window)
