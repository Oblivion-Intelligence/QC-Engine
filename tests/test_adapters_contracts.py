"""Adapter contract enforcement and ordering tests."""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from qcengine.adapters.base import InstrumentRef, InvalidResponse
from qcengine.adapters.groww import GrowwMarketDataAdapter
from qcengine.adapters.yfinance import YFinanceMarketDataAdapter
from qcengine.domain.marketdata import Timeframe


class _FakeGrowwClient:
    def __init__(self, payload):  # noqa: ANN001
        self.payload = payload

    def get_historical_candles_raw(self, instrument, timeframe, start_utc, end_utc):  # noqa: ANN001
        return self.payload


def test_groww_rejects_invalid_time_window() -> None:
    adapter = GrowwMarketDataAdapter(client=_FakeGrowwClient([]))
    start = datetime(2023, 11, 14, 0, 10, tzinfo=timezone.utc)
    end = start - timedelta(minutes=5)

    with pytest.raises(InvalidResponse):
        adapter.get_historical_candles(InstrumentRef("ABC", "ABC.NS"), Timeframe.MIN_5, start, end)


def test_yfinance_rejects_unsupported_timeframe(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = YFinanceMarketDataAdapter()
    start = datetime(2023, 11, 14, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(minutes=5)

    monkeypatch.setattr(cli_module := pytest.importorskip("qcengine.adapters.yfinance.marketdata"), "_INTERVAL_MAP", {})

    with pytest.raises(InvalidResponse):
        adapter.get_historical_candles(InstrumentRef("ABC", "ABC"), Timeframe.MIN_1, start, end)


def test_yfinance_preserves_order_and_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    from qcengine.adapters.yfinance import marketdata as yf_marketdata

    def fake_download(**kwargs):  # noqa: ANN001
        idx = pd.DatetimeIndex(
            [
                datetime(2023, 11, 14, 0, 5, tzinfo=timezone.utc),
                datetime(2023, 11, 14, 0, 0, tzinfo=timezone.utc),
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
    assert all(c.instrument_id == "XYZ" for c in candles)
    assert all(c.timeframe is Timeframe.MIN_5 for c in candles)
