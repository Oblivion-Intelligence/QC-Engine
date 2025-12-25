"""Tests for plotting helpers built on canonical candles."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import matplotlib
import pandas as pd

from qcengine.analytics.plotting import (
    candles_to_dataframe,
    plot_candles_matplotlib,
    plot_candles_plotly,
)
from qcengine.domain.marketdata import Candle, Timeframe


matplotlib.use("Agg")  # Ensure headless rendering in CI


def _sample_candles() -> list[Candle]:
    base = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)
    return [
        Candle(
            instrument_id="AAPL",
            timeframe=Timeframe.MIN_1,
            bar_start_ts_utc=base + timedelta(minutes=i),
            open=180 + i,
            high=181 + i,
            low=179 + i,
            close=180.5 + i,
            volume=1_000 + i * 10,
            source="unit-test",
            available_ts_utc=base + timedelta(minutes=i, seconds=5),
        )
        for i in range(3)
    ]


def test_candles_to_dataframe_index_and_columns():
    candles = _sample_candles()
    df = candles_to_dataframe(candles)

    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.tz is not None
    assert df.index.tz.tzname(None) == "UTC"
    assert set(["open", "high", "low", "close", "volume"]).issubset(df.columns)


def test_plot_candles_matplotlib_returns_figure_with_title():
    candles = _sample_candles()

    fig = plot_candles_matplotlib(candles, annotate_timeframe=True)

    assert fig._suptitle is not None
    assert "AAPL" in fig._suptitle.get_text()
    assert "1m" in fig._suptitle.get_text()


def test_plot_candles_plotly_traces():
    candles = _sample_candles()

    fig = plot_candles_plotly(candles, annotate_timeframe=True)

    assert fig.layout.title.text.startswith("AAPL")
    trace_names = [trace.name for trace in fig.data]
    assert "Close" in trace_names
    assert "Volume" in trace_names
