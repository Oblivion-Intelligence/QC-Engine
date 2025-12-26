"""Adapter normalization tests for Groww and yfinance."""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from qcengine.adapters.base import InstrumentRef, InvalidResponse
from qcengine.adapters.groww import GrowwMarketDataAdapter
from qcengine.adapters.yfinance import YFinanceMarketDataAdapter
from qcengine.domain.marketdata import Timeframe


class _FakeGrowwClient:
    def __init__(self, payload: list[dict]):
        self.payload = payload

    def get_historical_candles_raw(self, instrument, timeframe, start_utc, end_utc):  # noqa: ANN001
        return self.payload


def test_groww_adapter_parses_and_sorts() -> None:
    raw = [
        {"t": 1_700_000_700, "o": 11.0, "h": 12.0, "l": 10.0, "c": 11.5, "v": 150},
        {"t": 1_700_000_100, "o": 10.0, "h": 11.0, "l": 9.5, "c": 10.5, "v": 100},
    ]
    adapter = GrowwMarketDataAdapter(client=_FakeGrowwClient(raw))
    start = datetime(2023, 11, 14, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)

    candles = adapter.get_historical_candles(
        InstrumentRef("ABC", "ABC.NS"), Timeframe.MIN_5, start, end
    )

    assert [c.bar_start_ts_utc for c in candles] == sorted(c.bar_start_ts_utc for c in candles)
    assert all(c.source == "groww" for c in candles)
    assert all(c.timeframe is Timeframe.MIN_5 for c in candles)
    assert candles[0].available_ts_utc == candles[1].available_ts_utc


def test_groww_adapter_requires_timestamp() -> None:
    adapter = GrowwMarketDataAdapter(client=_FakeGrowwClient([{"o": 1, "h": 1, "l": 1, "c": 1}]))
    start = datetime(2023, 11, 14, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)

    with pytest.raises(InvalidResponse):
        adapter.get_historical_candles(InstrumentRef("ABC", "ABC.NS"), Timeframe.MIN_5, start, end)


def test_groww_adapter_converts_bar_end_to_bar_start() -> None:
    raw = [
        {"t": 1_700_000_700, "o": 11.0, "h": 12.0, "l": 10.0, "c": 11.5, "v": 150},
        {"t": 1_700_001_000, "o": 10.0, "h": 11.0, "l": 9.5, "c": 10.5, "v": 100},
    ]
    adapter = GrowwMarketDataAdapter(client=_FakeGrowwClient(raw))

    candles = adapter.get_historical_candles(
        InstrumentRef("ABC", "ABC.NS"),
        Timeframe.MIN_5,
        datetime(2023, 11, 14, 0, 0, tzinfo=timezone.utc),
        datetime(2023, 11, 14, 1, 0, tzinfo=timezone.utc),
    )

    expected_starts = [
        datetime(2023, 11, 14, 22, 20, tzinfo=timezone.utc),
        datetime(2023, 11, 14, 22, 25, tzinfo=timezone.utc),
    ]
    assert [c.bar_start_ts_utc for c in candles] == expected_starts


def test_yfinance_normalizes_dataframe(monkeypatch: pytest.MonkeyPatch) -> None:
    from qcengine.adapters.yfinance import marketdata as yf_marketdata

    def fake_download(**kwargs):  # noqa: ANN001
        idx = pd.DatetimeIndex(
            [
                datetime(2023, 11, 14, 0, 10, tzinfo=timezone.utc),
                datetime(2023, 11, 14, 0, 5, tzinfo=timezone.utc),
            ]
        )
        return pd.DataFrame(
            {
                "Open": [11.0, 10.0],
                "High": [12.0, 11.0],
                "Low": [10.0, 9.5],
                "Close": [11.5, 10.5],
                "Volume": [150, 100],
            },
            index=idx,
        )

    monkeypatch.setattr(yf_marketdata, "yf", pytest.importorskip("yfinance"))
    monkeypatch.setattr(yf_marketdata.yf, "download", fake_download)

    adapter = YFinanceMarketDataAdapter()
    start = datetime(2023, 11, 14, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)

    candles = adapter.get_historical_candles(InstrumentRef("XYZ", "XYZ"), Timeframe.MIN_5, start, end)

    assert [c.bar_start_ts_utc for c in candles] == sorted(c.bar_start_ts_utc for c in candles)
    assert all(c.source == "yfinance" for c in candles)
    assert all(c.timeframe is Timeframe.MIN_5 for c in candles)
    assert candles[0].available_ts_utc == candles[1].available_ts_utc


def test_yfinance_rejects_misaligned_timestamps(monkeypatch: pytest.MonkeyPatch) -> None:
    from qcengine.adapters.yfinance import marketdata as yf_marketdata

    def fake_download(**kwargs):  # noqa: ANN001
        idx = pd.DatetimeIndex(
            [
                datetime(2023, 11, 14, 0, 6, tzinfo=timezone.utc),
                datetime(2023, 11, 14, 0, 1, tzinfo=timezone.utc),
            ]
        )
        return pd.DataFrame(
            {
                "Open": [11.0, 10.0],
                "High": [12.0, 11.0],
                "Low": [10.0, 9.5],
                "Close": [11.5, 10.5],
                "Volume": [150, 100],
            },
            index=idx,
        )

    monkeypatch.setattr(yf_marketdata, "yf", pytest.importorskip("yfinance"))
    monkeypatch.setattr(yf_marketdata.yf, "download", fake_download)

    adapter = YFinanceMarketDataAdapter()
    start = datetime(2023, 11, 14, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)

    with pytest.raises(InvalidResponse):
        adapter.get_historical_candles(InstrumentRef("XYZ", "XYZ"), Timeframe.MIN_5, start, end)


def test_yfinance_rejects_naive_index(monkeypatch: pytest.MonkeyPatch) -> None:
    from qcengine.adapters.yfinance import marketdata as yf_marketdata

    def fake_download(**kwargs):  # noqa: ANN001
        idx = pd.DatetimeIndex(
            [
                datetime(2023, 11, 14, 0, 5),
                datetime(2023, 11, 14, 0, 0),
            ]
        )
        return pd.DataFrame(
            {
                "Open": [11.0, 10.0],
                "High": [12.0, 11.0],
                "Low": [10.0, 9.5],
                "Close": [11.5, 10.5],
                "Volume": [150, 100],
            },
            index=idx,
        )

    monkeypatch.setattr(yf_marketdata, "yf", pytest.importorskip("yfinance"))
    monkeypatch.setattr(yf_marketdata.yf, "download", fake_download)

    adapter = YFinanceMarketDataAdapter()
    start = datetime(2023, 11, 14, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)

    with pytest.raises(InvalidResponse):
        adapter.get_historical_candles(InstrumentRef("XYZ", "XYZ"), Timeframe.MIN_5, start, end)
