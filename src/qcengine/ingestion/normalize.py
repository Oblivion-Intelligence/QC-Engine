"""Helpers to normalize provider payloads into canonical :class:`Candle` objects.

The functions in this module are intentionally small and side-effect free so they
can be reused by adapters as a thin validation layer.  They enforce the
canonical candle schema (including UTC timestamps and ingestion time) and keep
ordering guarantees required by storage and downstream consumers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Mapping, Sequence

import pandas as pd

from qcengine.domain.marketdata import (
    Candle,
    Timeframe,
    assert_aligned_to_grid,
    ensure_utc,
    now_utc,
)


@dataclass
class NormalizationSpec:
    """Field mapping instructions for dictionary/list style payloads.

    Attributes:
        timestamp: Key name (or positional index) for the bar start time.
        open: Key name (or positional index) for the open price.
        high: Key name (or positional index) for the high price.
        low: Key name (or positional index) for the low price.
        close: Key name (or positional index) for the close price.
        volume: Optional key/index for the volume field.
        epoch_ms: Whether numeric timestamps are expressed in milliseconds.
    """

    timestamp: str | int
    open: str | int
    high: str | int
    low: str | int
    close: str | int
    volume: str | int | None = None
    epoch_ms: bool = False


def normalize_rows(
    rows: Iterable[Mapping | Sequence],
    instrument_id: str,
    timeframe: Timeframe,
    source: str,
    spec: NormalizationSpec,
    available_ts_utc: datetime | None = None,
) -> list[Candle]:
    """Normalize an iterable of mapping/sequence rows into :class:`Candle`.

    Args:
        rows: Raw payload rows coming from a provider response.
        instrument_id: Canonical instrument identifier.
        timeframe: Candle resolution.
        source: Provider identifier to stamp onto each candle.
        spec: Field mapping instructions describing the payload layout.
        available_ts_utc: Optional ingestion timestamp; defaults to ``now_utc``.

    Returns:
        List of validated candles sorted by ``bar_start_ts_utc``.
    """

    available_ts = ensure_utc(available_ts_utc) if available_ts_utc else now_utc()
    candles: list[Candle] = []

    for row in rows:
        bar_start = _extract_timestamp(row, spec)
        assert_aligned_to_grid(bar_start, timeframe)
        open_, high, low, close = (
            _extract_numeric(row, spec.open),
            _extract_numeric(row, spec.high),
            _extract_numeric(row, spec.low),
            _extract_numeric(row, spec.close),
        )
        volume = None
        if spec.volume is not None:
            value = _extract_value(row, spec.volume)
            volume = None if value is None else float(value)

        candles.append(
            Candle(
                instrument_id=instrument_id,
                timeframe=timeframe,
                bar_start_ts_utc=bar_start,
                open=float(open_),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=volume,
                source=source,
                available_ts_utc=available_ts,
            )
        )

    candles.sort(key=lambda c: c.bar_start_ts_utc)
    return candles


def normalize_dataframe(
    df: pd.DataFrame,
    instrument_id: str,
    timeframe: Timeframe,
    source: str,
    available_ts_utc: datetime | None = None,
) -> list[Candle]:
    """Normalize a DataFrame with a datetime index into :class:`Candle` objects."""

    if df.empty:
        return []

    index = df.index
    if not isinstance(index, pd.DatetimeIndex):
        raise ValueError("DataFrame index must be a DatetimeIndex")
    if index.tz is None:
        raise ValueError("DataFrame index must be timezone-aware")

    available_ts = ensure_utc(available_ts_utc) if available_ts_utc else now_utc()

    df = df.sort_index()
    candles: list[Candle] = []

    for ts, row in df.iterrows():
        bar_start = ensure_utc(ts.to_pydatetime())
        assert_aligned_to_grid(bar_start, timeframe)
        candles.append(
            Candle(
                instrument_id=instrument_id,
                timeframe=timeframe,
                bar_start_ts_utc=bar_start,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=None if "Volume" not in row else float(row["Volume"]),
                source=source,
                available_ts_utc=available_ts,
            )
        )

    return candles


def _extract_timestamp(row: Mapping | Sequence, spec: NormalizationSpec) -> datetime:
    try:
        ts = _extract_value(row, spec.timestamp)
    except KeyError as exc:
        raise ValueError("timestamp field missing") from exc
    if isinstance(ts, (int, float)):
        seconds = ts / 1000 if spec.epoch_ms else ts
        return ensure_utc(datetime.fromtimestamp(seconds, tz=timezone.utc))
    if isinstance(ts, datetime):
        return ensure_utc(ts)
    if isinstance(ts, str):
        return ensure_utc(datetime.fromisoformat(ts))
    raise ValueError("Unsupported timestamp type")


def _extract_numeric(row: Mapping | Sequence, key: str | int) -> float:
    try:
        value = _extract_value(row, key)
    except KeyError as exc:
        raise ValueError("numeric field missing") from exc
    return float(value)


def _extract_value(row: Mapping | Sequence, key: str | int):  # noqa: ANN001
    if isinstance(row, Mapping):
        return row[key]
    if isinstance(row, Sequence):
        return row[key]
    raise ValueError("Row must be mapping or sequence")
