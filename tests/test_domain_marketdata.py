"""Tests for canonical market data domain models."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from qcengine.domain.marketdata import Candle, Timeframe, assert_aligned_to_grid, ensure_utc


def test_timeframe_minutes_and_from_minutes() -> None:
    assert Timeframe.DAY_1.to_minutes() == 1440
    assert Timeframe.from_minutes(5) is Timeframe.MIN_5

    with pytest.raises(ValueError):
        Timeframe.from_minutes(2)


def test_candle_key_and_serialization_roundtrip() -> None:
    bar_start = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    available = datetime(2024, 1, 1, 12, 5, tzinfo=timezone.utc)

    candle = Candle(
        instrument_id="ABC",
        timeframe=Timeframe.MIN_1,
        bar_start_ts_utc=bar_start,
        open=100.0,
        high=110.0,
        low=90.0,
        close=105.0,
        volume=1000.0,
        source="test",
        available_ts_utc=available,
    )

    assert candle.key() == ("ABC", "1m", bar_start)

    rebuilt = Candle.from_dict(candle.to_dict())
    assert rebuilt == candle


def test_naive_datetimes_rejected() -> None:
    bar_start = datetime(2024, 1, 1, 12, 0)
    available = datetime(2024, 1, 1, 12, 5, tzinfo=timezone.utc)

    with pytest.raises(ValueError):
        Candle(
            instrument_id="ABC",
            timeframe=Timeframe.MIN_1,
            bar_start_ts_utc=bar_start,
            open=100.0,
            high=110.0,
            low=90.0,
            close=105.0,
            volume=1000.0,
            source="test",
            available_ts_utc=available,
        )


def test_ohlc_validation_errors() -> None:
    with pytest.raises(ValueError, match="high must be"):
        Candle(
            instrument_id="ABC",
            timeframe=Timeframe.MIN_1,
            bar_start_ts_utc=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
            open=100.0,
            high=95.0,
            low=90.0,
            close=105.0,
            volume=1000.0,
            source="test",
            available_ts_utc=datetime(2024, 1, 1, 12, 5, tzinfo=timezone.utc),
        )

    with pytest.raises(ValueError, match="low must be"):
        Candle(
            instrument_id="ABC",
            timeframe=Timeframe.MIN_1,
            bar_start_ts_utc=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
            open=100.0,
            high=110.0,
            low=101.0,
            close=99.0,
            volume=1000.0,
            source="test",
            available_ts_utc=datetime(2024, 1, 1, 12, 5, tzinfo=timezone.utc),
        )


def test_volume_validation_and_finiteness() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        Candle(
            instrument_id="ABC",
            timeframe=Timeframe.MIN_1,
            bar_start_ts_utc=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
            open=100.0,
            high=110.0,
            low=90.0,
            close=105.0,
            volume=-1.0,
            source="test",
            available_ts_utc=datetime(2024, 1, 1, 12, 5, tzinfo=timezone.utc),
        )

    with pytest.raises(ValueError, match="finite"):
        Candle(
            instrument_id="ABC",
            timeframe=Timeframe.MIN_1,
            bar_start_ts_utc=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
            open=float("nan"),
            high=110.0,
            low=90.0,
            close=105.0,
            volume=0.0,
            source="test",
            available_ts_utc=datetime(2024, 1, 1, 12, 5, tzinfo=timezone.utc),
        )


def test_ensure_utc_converts_offsets() -> None:
    ist_time = datetime(2024, 1, 1, 15, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    normalized = ensure_utc(ist_time)

    assert normalized.tzinfo is timezone.utc
    assert normalized == datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)


def test_assert_aligned_to_grid_accepts_valid_boundaries() -> None:
    assert_aligned_to_grid(datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc), Timeframe.MIN_1)
    assert_aligned_to_grid(datetime(2024, 1, 1, 0, 5, tzinfo=timezone.utc), Timeframe.MIN_5)
    assert_aligned_to_grid(datetime(2024, 1, 1, 0, 15, tzinfo=timezone.utc), Timeframe.MIN_15)
    assert_aligned_to_grid(datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc), Timeframe.HOUR_1)
    assert_aligned_to_grid(datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc), Timeframe.DAY_1)


def test_assert_aligned_to_grid_rejects_misaligned_timestamp() -> None:
    with pytest.raises(ValueError, match="not aligned"):
        assert_aligned_to_grid(datetime(2024, 1, 1, 0, 2, tzinfo=timezone.utc), Timeframe.MIN_5)
    with pytest.raises(ValueError, match="not aligned"):
        assert_aligned_to_grid(datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc), Timeframe.DAY_1)
