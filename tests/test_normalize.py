"""Test normalization logic for raw data payloads."""

from datetime import datetime, timezone

import pandas as pd
import pytest

from qcengine.domain.marketdata import Timeframe
from qcengine.ingestion.normalize import NormalizationSpec, normalize_dataframe, normalize_rows


def test_normalize_rows_sorts_and_stamps_available(monkeypatch: pytest.MonkeyPatch) -> None:
    fixed_now = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("qcengine.ingestion.normalize.now_utc", lambda: fixed_now)

    rows = [
        {"t": 1_699_999_800, "o": 11.0, "h": 12.0, "l": 10.0, "c": 11.5, "v": 150},
        {"t": 1_699_999_500, "o": 10.0, "h": 11.0, "l": 9.5, "c": 10.5, "v": 100},
    ]

    candles = normalize_rows(
        rows,
        instrument_id="ABC",
        timeframe=Timeframe.MIN_5,
        source="test",
        spec=NormalizationSpec(timestamp="t", open="o", high="h", low="l", close="c", volume="v"),
    )

    assert [c.bar_start_ts_utc for c in candles] == sorted(c.bar_start_ts_utc for c in candles)
    assert all(c.available_ts_utc == fixed_now for c in candles)
    assert all(c.timeframe is Timeframe.MIN_5 for c in candles)


def test_normalize_rows_epoch_ms() -> None:
    rows = [[1_699_999_980_000, 10, 11, 9.5, 10.5, 100]]

    candles = normalize_rows(
        rows,
        instrument_id="ABC",
        timeframe=Timeframe.MIN_1,
        source="test",
        spec=NormalizationSpec(timestamp=0, open=1, high=2, low=3, close=4, volume=5, epoch_ms=True),
    )

    assert candles[0].bar_start_ts_utc.tzinfo is timezone.utc


def test_normalize_rows_missing_timestamp() -> None:
    with pytest.raises(ValueError):
        normalize_rows(
            [
                {"o": 1, "h": 1, "l": 1, "c": 1},
            ],
            instrument_id="ABC",
            timeframe=Timeframe.MIN_1,
            source="test",
            spec=NormalizationSpec(timestamp="t", open="o", high="h", low="l", close="c"),
        )


def test_normalize_dataframe_validates_index() -> None:
    df = pd.DataFrame(
        {"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0]},
        index=pd.Index([datetime(2024, 1, 1, 0, 0)]),
    )

    with pytest.raises(ValueError):
        normalize_dataframe(df, instrument_id="ABC", timeframe=Timeframe.MIN_1, source="test")


def test_normalize_dataframe_sorts() -> None:
    idx = pd.DatetimeIndex(
        [datetime(2024, 1, 1, 0, 1, tzinfo=timezone.utc), datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)]
    )
    df = pd.DataFrame(
        {"Open": [2.0, 1.0], "High": [2.0, 1.0], "Low": [2.0, 1.0], "Close": [2.0, 1.0]},
        index=idx,
    )

    candles = normalize_dataframe(df, instrument_id="ABC", timeframe=Timeframe.MIN_1, source="test")

    assert [c.bar_start_ts_utc for c in candles] == sorted(c.bar_start_ts_utc for c in candles)


def test_normalize_rejects_misaligned_timestamp() -> None:
    rows = [
        {"t": "2024-01-01T00:01:00+00:00", "o": 10, "h": 11, "l": 9, "c": 10},
    ]

    with pytest.raises(ValueError, match="aligned"):
        normalize_rows(
            rows,
            instrument_id="ABC",
            timeframe=Timeframe.MIN_5,
            source="test",
            spec=NormalizationSpec(timestamp="t", open="o", high="h", low="l", close="c"),
        )
