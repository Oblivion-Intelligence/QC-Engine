"""Adapter contracts and canonical adapter errors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from qcengine.domain.marketdata import Candle, Timeframe


class AdapterError(Exception):
    """Base exception for all adapter failures.

    Args:
        provider: Provider identifier (e.g., "groww", "yfinance").
        message: Human-readable error message.
        cause: Optional underlying exception from the provider SDK or HTTP stack.
    """

    def __init__(self, provider: str, message: str, cause: Exception | None = None) -> None:
        self.provider = provider
        self.message = message
        self.cause = cause
        super().__init__(f"[{provider}] {message}")


class AuthError(AdapterError):
    """Raised when authentication or tokens are invalid or expired."""


class RateLimited(AdapterError):
    """Raised when the provider rate limits the request (retry with backoff)."""


class Unavailable(AdapterError):
    """Raised when the provider is temporarily unavailable or timing out."""


class InvalidResponse(AdapterError):
    """Raised when the provider returns malformed or unexpected data."""


@dataclass(frozen=True)
class InstrumentRef:
    """Canonical instrument identity plus provider-specific symbol."""

    instrument_id: str
    provider_symbol: str
    exchange: str | None = None
    segment: str | None = None

    def __post_init__(self) -> None:
        if not self.instrument_id:
            raise ValueError("instrument_id must be non-empty")
        if not self.provider_symbol:
            raise ValueError("provider_symbol must be non-empty")


@runtime_checkable
class MarketDataAdapter(Protocol):
    """Protocol for normalized historical market data adapters."""

    provider_name: str

    def get_historical_candles(
        self,
        instrument: InstrumentRef,
        timeframe: Timeframe,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[Candle]:
        """Return canonical candles sorted ascending by ``bar_start_ts_utc``.

        Implementations must normalize provider data into :class:`~qcengine.domain.marketdata.Candle`
        with fields:
        ``instrument_id == instrument.instrument_id``, ``timeframe == timeframe``,
        ``source == self.provider_name``, and ``available_ts_utc`` set at ingestion time.

        ``start_utc`` and ``end_utc`` are timezone-aware UTC datetimes.

        Raises:
            AuthError: Authentication or token failure.
            RateLimited: The provider is throttling requests.
            Unavailable: Network, timeout, or provider outage; should be retried.
            InvalidResponse: Provider returned malformed or unexpected data.
        """

    def ping(self) -> None:
        """Optional health check; raise :class:`Unavailable` if the provider is unreachable."""


class InstrumentResolver(Protocol):
    """Optional protocol to map canonical symbols to provider instrument references."""

    def resolve(self, canonical_symbol: str) -> InstrumentRef:
        """Return a provider instrument reference or raise :class:`AdapterError` if unknown."""
