from __future__ import annotations

"""yfinance historical candle adapter implementation."""

from datetime import datetime, timezone
from typing import Iterable

import pandas as pd
import yfinance as yf

from qcengine.adapters.base import (
    AdapterError,
    InvalidResponse,
    MarketDataAdapter,
    InstrumentRef,
    RateLimited,
    Unavailable,
)
from qcengine.domain.marketdata import Candle, Timeframe, ensure_utc, now_utc


_INTERVAL_MAP: dict[Timeframe, str] = {
    Timeframe.MIN_1: "1m",
    Timeframe.MIN_5: "5m",
    Timeframe.MIN_15: "15m",
    Timeframe.HOUR_1: "60m",
    Timeframe.DAY_1: "1d",
}


class YFinanceMarketDataAdapter(MarketDataAdapter):
    """Adapter for fetching historical candles from yfinance."""

    provider_name: str = "yfinance"

    def ping(self) -> None:  # pragma: no cover - network reachability is environment dependent
        try:
            ticker = yf.Ticker("AAPL")
            ticker.history(period="1d", interval="1d", auto_adjust=False, prepost=False, raise_errors=True)
        except Exception as exc:  # noqa: BLE001 - we normalize to adapter errors
            raise Unavailable(self.provider_name, "yfinance ping failed", cause=exc) from exc

    def get_historical_candles(
        self,
        instrument: InstrumentRef,
        timeframe: Timeframe,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[Candle]:
        instrument_id = instrument.instrument_id.strip()
        provider_symbol = instrument.provider_symbol.strip()
        if not instrument_id or not provider_symbol:
            raise InvalidResponse(self.provider_name, "instrument_id and provider_symbol are required")

        start_utc = ensure_utc(start_utc)
        end_utc = ensure_utc(end_utc)
        if start_utc >= end_utc:
            raise InvalidResponse(self.provider_name, "start_utc must be earlier than end_utc")

        try:
            interval = _INTERVAL_MAP[timeframe]
        except KeyError as exc:
            raise InvalidResponse(self.provider_name, f"unsupported timeframe: {timeframe}") from exc

        try:
            df = self._download(provider_symbol, interval, start_utc, end_utc)
        except RateLimited:
            raise
        except Unavailable:
            raise
        except AdapterError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize to adapter taxonomy
            raise Unavailable(self.provider_name, "yfinance history request failed", cause=exc) from exc

        if df.empty:
            return []

        self._validate_columns(df)

        index = df.index
        if index.tz is None:
            raise InvalidResponse(self.provider_name, "yfinance returned naive timestamps")

        df = df.sort_index()
        available_ts = now_utc()
        candles: list[Candle] = []

        for ts, row in df.iterrows():
            ts_utc = ensure_utc(ts.to_pydatetime())
            try:
                candles.append(
                    Candle(
                        instrument_id=instrument_id,
                        timeframe=timeframe,
                        bar_start_ts_utc=ts_utc,
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        volume=None if "Volume" not in row else float(row["Volume"]),
                        source=self.provider_name,
                        available_ts_utc=available_ts,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                raise InvalidResponse(self.provider_name, "failed to normalize yfinance candle", cause=exc) from exc

        self._assert_sorted(candles)
        return candles

    def _download(
        self, provider_symbol: str, interval: str, start_utc: datetime, end_utc: datetime
    ) -> pd.DataFrame:
        try:
            df = yf.download(
                tickers=provider_symbol,
                interval=interval,
                start=start_utc.astimezone(timezone.utc).replace(tzinfo=None),
                end=end_utc.astimezone(timezone.utc).replace(tzinfo=None),
                auto_adjust=False,
                progress=False,
                group_by="ticker",
                prepost=False,
                raise_errors=True,
            )
        except Exception as exc:  # noqa: BLE001
            message = str(exc).lower()
            if "429" in message or "rate limit" in message:
                raise RateLimited(self.provider_name, "yfinance rate limited", cause=exc) from exc
            raise Unavailable(self.provider_name, "yfinance download failed", cause=exc) from exc

        if isinstance(df, pd.DataFrame) and isinstance(df.columns, pd.MultiIndex):
            # When group_by="ticker" but single ticker, columns may be multi-indexed
            df = df.xs(provider_symbol, axis=1)

        if not isinstance(df, pd.DataFrame):
            raise InvalidResponse(self.provider_name, "yfinance returned non-DataFrame response")
        return df

    def _validate_columns(self, df: pd.DataFrame) -> None:
        required = {"Open", "High", "Low", "Close"}
        missing = required.difference(df.columns)
        if missing:
            raise InvalidResponse(self.provider_name, f"missing required columns: {sorted(missing)}")

    def _assert_sorted(self, candles: Iterable[Candle]) -> None:
        previous: datetime | None = None
        for candle in candles:
            if previous and candle.bar_start_ts_utc < previous:
                raise InvalidResponse(self.provider_name, "candles must be sorted by bar_start_ts_utc")
            previous = candle.bar_start_ts_utc
