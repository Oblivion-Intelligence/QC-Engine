from datetime import datetime, timedelta, timezone

import pytest

from qcengine.domain.marketdata import Candle, Timeframe
from qcengine.storage.parquet_store import ParquetCandleStore


def _make_candle(minute_offset: int, instrument: str = "AAPL", timeframe: Timeframe = Timeframe.MIN_1) -> Candle:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    start = base + timedelta(minutes=minute_offset)
    available = start + timedelta(seconds=5)
    return Candle(
        instrument_id=instrument,
        timeframe=timeframe,
        bar_start_ts_utc=start,
        open=100.0 + minute_offset,
        high=101.0 + minute_offset,
        low=99.0 + minute_offset,
        close=100.5 + minute_offset,
        volume=10_000 + minute_offset,
        source="test",
        available_ts_utc=available,
    )


def test_append_and_deduplicate(tmp_path):
    store = ParquetCandleStore(tmp_path)

    initial = [_make_candle(i) for i in range(3)]
    result_first = store.append(initial)

    assert result_first.written == 3
    assert result_first.duplicates == 0

    # Re-append overlapping candles with one new bar to ensure deduplication works.
    overlap = [_make_candle(0), _make_candle(3)]
    result_second = store.append(overlap)

    assert result_second.written == 1
    assert result_second.duplicates == 1

    candles = store.read("AAPL", Timeframe.MIN_1)

    assert [c.bar_start_ts_utc for c in candles] == sorted(
        [c.bar_start_ts_utc for c in candles]
    )
    assert len(candles) == 4
    assert candles[-1].bar_start_ts_utc.minute == 3


def test_append_rejects_misaligned_candles(tmp_path) -> None:
    store = ParquetCandleStore(tmp_path)
    misaligned = Candle(
        instrument_id="AAPL",
        timeframe=Timeframe.MIN_5,
        bar_start_ts_utc=datetime(2024, 1, 1, 0, 1, tzinfo=timezone.utc),
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=10_000,
        source="test",
        available_ts_utc=datetime(2024, 1, 1, 0, 1, tzinfo=timezone.utc),
    )

    with pytest.raises(ValueError, match="aligned"):
        store.append([misaligned])


def test_read_filters_and_utc(tmp_path):
    store = ParquetCandleStore(tmp_path)

    store.append([_make_candle(i) for i in range(5)])

    start = datetime(2024, 1, 1, 0, 2, tzinfo=timezone.utc)
    end = datetime(2024, 1, 1, 0, 3, tzinfo=timezone.utc)

    candles = store.read("AAPL", Timeframe.MIN_1, start=start, end=end)

    assert [c.bar_start_ts_utc.minute for c in candles] == [2]
    assert all(c.bar_start_ts_utc.tzinfo is not None for c in candles)
    assert all(c.bar_start_ts_utc.utcoffset() == timedelta(0) for c in candles)


def test_read_uses_half_open_intervals(tmp_path) -> None:
    store = ParquetCandleStore(tmp_path)
    instrument = "ABC"
    timeframe = Timeframe.MIN_1
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = [
        Candle(
            instrument_id=instrument,
            timeframe=timeframe,
            bar_start_ts_utc=start + timedelta(minutes=i),
            open=100 + i,
            high=101 + i,
            low=99 + i,
            close=100 + i,
            volume=1_000 + i,
            source="test",
            available_ts_utc=start,
        )
        for i in range(3)
    ]

    store.append(candles)

    first_window_end = start + timedelta(minutes=2)
    first_window = store.read(instrument, timeframe, start=start, end=first_window_end)
    assert [c.bar_start_ts_utc for c in first_window] == [c.bar_start_ts_utc for c in candles[:2]]

    second_window = store.read(
        instrument,
        timeframe,
        start=first_window_end,
        end=first_window_end + timedelta(minutes=1),
    )
    assert [c.bar_start_ts_utc for c in second_window] == [candles[2].bar_start_ts_utc]
