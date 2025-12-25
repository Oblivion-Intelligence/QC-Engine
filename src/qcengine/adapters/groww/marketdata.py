"""Groww historical candle adapter implementation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from qcengine.adapters.base import InvalidResponse, MarketDataAdapter, InstrumentRef
from qcengine.domain.marketdata import Candle, Timeframe, ensure_utc, now_utc

EPOCH_UNIT = "s"


class GrowwMarketDataAdapter(MarketDataAdapter):
    """Adapter that normalizes Groww raw candles into canonical :class:`Candle`."""

    provider_name: str = "groww"

    def __init__(self, client: Any) -> None:
        if client is None:
            raise InvalidResponse(self.provider_name, "client is required")
        self._client = client

    def ping(self) -> None:
        if hasattr(self._client, "ping"):
            self._client.ping()

    def get_historical_candles(
        self,
        instrument: InstrumentRef,
        timeframe: Timeframe,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[Candle]:
        instrument_id = instrument.instrument_id.strip()
        provider_symbol = instrument.provider_symbol.strip()
        if not instrument_id:
            raise InvalidResponse(self.provider_name, "empty instrument_id")
        if not provider_symbol:
            raise InvalidResponse(self.provider_name, "empty provider_symbol")

        start_utc = ensure_utc(start_utc)
        end_utc = ensure_utc(end_utc)
        if start_utc >= end_utc:
            raise InvalidResponse(self.provider_name, "start_utc must be earlier than end_utc")

        raw = self._client.get_historical_candles_raw(instrument, timeframe, start_utc, end_utc)
        candles = _parse_raw_to_candles(raw, instrument, timeframe)
        candles.sort(key=lambda c: c.bar_start_ts_utc)
        _assert_sorted(candles)
        return candles


def _parse_raw_to_candles(raw: Any, instrument: InstrumentRef, timeframe: Timeframe) -> list[Candle]:
    rows = _extract_rows(raw)
    available_ts = now_utc()
    candles: list[Candle] = []

    for row in rows:
        try:
            bar_start = _parse_timestamp(row)
            open_, high, low, close, volume = _parse_ohlcv(row)
            candles.append(
                Candle(
                    instrument_id=instrument.instrument_id,
                    timeframe=timeframe,
                    bar_start_ts_utc=bar_start,
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                    source="groww",
                    available_ts_utc=available_ts,
                )
            )
        except InvalidResponse:
            raise
        except Exception as exc:  # noqa: BLE001
            raise InvalidResponse("groww", "unexpected historical candle payload shape", cause=exc) from exc

    return candles


def _extract_rows(raw: Any) -> Iterable[Any]:
    if isinstance(raw, dict):
        for key in ("candles", "data"):
            if key in raw:
                rows = raw[key]
                break
        else:
            rows = raw
    else:
        rows = raw

    if not isinstance(rows, Iterable):
        raise InvalidResponse("groww", "historical candles response not list/dict")
    return rows


def _parse_timestamp(row: Any) -> datetime:
    if isinstance(row, dict):
        ts = row.get("t") or row.get("timestamp") or row.get("time")
    elif isinstance(row, (list, tuple)) and len(row) >= 1:
        ts = row[0]
    else:
        raise InvalidResponse("groww", "candle row missing timestamp")

    if isinstance(ts, (int, float)):
        seconds = ts / 1000 if EPOCH_UNIT == "ms" else ts
        dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    elif isinstance(ts, str):
        dt = datetime.fromisoformat(ts)
    elif isinstance(ts, datetime):
        dt = ts
    else:
        raise InvalidResponse("groww", "unsupported timestamp type")

    return ensure_utc(dt)


def _parse_ohlcv(row: Any) -> tuple[float, float, float, float, float | None]:
    if isinstance(row, dict):
        try:
            open_ = float(row.get("o") if "o" in row else row["open"])
            high = float(row.get("h") if "h" in row else row["high"])
            low = float(row.get("l") if "l" in row else row["low"])
            close = float(row.get("c") if "c" in row else row["close"])
            volume_raw = row.get("v") if "v" in row else row.get("volume")
        except KeyError as exc:
            raise InvalidResponse("groww", "missing ohlc fields") from exc
    elif isinstance(row, (list, tuple)) and len(row) >= 5:
        open_, high, low, close = map(float, row[1:5])
        volume_raw = row[5] if len(row) > 5 else None
    else:
        raise InvalidResponse("groww", "candle row not in expected dict/list format")

    volume = None if volume_raw is None else float(volume_raw)
    return open_, high, low, close, volume


def _assert_sorted(candles: Iterable[Candle]) -> None:
    previous: datetime | None = None
    for candle in candles:
        if previous and candle.bar_start_ts_utc < previous:
            raise InvalidResponse("groww", "candles must be sorted ascending by bar_start_ts_utc")
        previous = candle.bar_start_ts_utc
