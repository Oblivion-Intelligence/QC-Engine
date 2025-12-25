"""Lightweight Groww client wrapper with QC-Engine error mapping."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from growwapi import GrowwAPI
from growwapi.groww import exceptions as groww_exceptions

from qcengine.adapters.base import AuthError, InstrumentRef, InvalidResponse, RateLimited, Unavailable
from qcengine.domain.marketdata import Timeframe, ensure_utc

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GrowwClientConfig:
    """Configuration for :class:`GrowwClient`.

    Either ``access_token`` or ``api_key`` must be provided. If ``api_secret``
    accompanies ``api_key``, the client will generate a fresh access token via
    the Groww SDK before making requests.
    """

    api_key: str | None = None
    api_secret: str | None = None
    access_token: str | None = None
    timeout_s: float = 10.0
    max_retries: int = 3
    retry_backoff_base_s: float = 0.5

    def __post_init__(self) -> None:
        if not self.access_token and not self.api_key:
            raise ValueError("either access_token or api_key must be provided")


class GrowwClient:
    """Encapsulate Groww SDK calls and normalize error handling."""

    def __init__(self, config: GrowwClientConfig, api_factory: Callable[[str], Any] | None = None) -> None:
        self.provider_name = "groww"
        self._config = config
        self._api_factory = api_factory or GrowwAPI
        token = config.access_token or self._generate_access_token()
        self._api = self._api_factory(token)

    def ping(self) -> None:
        """Verify the token is usable by calling a lightweight endpoint."""

        try:
            self._api.get_user_profile(timeout=int(self._config.timeout_s))
        except Exception as exc:  # noqa: BLE001
            raise self._map_exception("get_user_profile", exc)

    def get_historical_candles_raw(
        self,
        instrument: InstrumentRef,
        timeframe: Timeframe,
        start_utc: datetime,
        end_utc: datetime,
    ) -> Any:
        """Fetch raw candle payload from Groww with retry semantics."""

        if not instrument.exchange or not instrument.segment:
            raise InvalidResponse(self.provider_name, "exchange and segment are required for Groww historical data")

        start = _format_dt(start_utc)
        end = _format_dt(end_utc)
        interval = _map_timeframe_to_interval(timeframe)

        attempt = 0
        operation = "get_historical_candles"

        while True:
            attempt += 1
            try:
                raw = self._api.get_historical_candles(
                    instrument.exchange,
                    instrument.segment,
                    instrument.provider_symbol,
                    start,
                    end,
                    interval,
                    timeout=int(self._config.timeout_s),
                )
                logger.info(
                    "groww historical candles fetched",
                    extra={
                        "symbol": instrument.provider_symbol,
                        "exchange": instrument.exchange,
                        "segment": instrument.segment,
                        "timeframe": timeframe.value,
                        "start": start,
                        "end": end,
                        "attempt": attempt,
                        "rows": len(raw.get("candles", [])) if isinstance(raw, dict) else None,
                    },
                )
                return raw
            except Exception as exc:  # noqa: BLE001
                mapped = self._map_exception(operation, exc)
                if isinstance(mapped, (RateLimited, Unavailable)) and attempt < self._config.max_retries:
                    sleep_for = self._config.retry_backoff_base_s * (2 ** (attempt - 1))
                    logger.warning(
                        "retrying groww historical fetch",
                        extra={
                            "operation": operation,
                            "retry": attempt,
                            "symbol": instrument.provider_symbol,
                            "timeframe": timeframe.value,
                            "max_retries": self._config.max_retries,
                            "sleep": sleep_for,
                            "error": str(mapped),
                            "error_type": type(mapped).__name__,
                        },
                    )
                    time.sleep(sleep_for)
                    continue
                raise mapped

    def _generate_access_token(self) -> str:
        api_key = self._config.api_key
        api_secret = self._config.api_secret
        if not api_key:
            raise ValueError("api_key is required when access_token is not provided")

        try:
            sdk = self._api_factory(api_key)
            return sdk.get_access_token(api_key, secret=api_secret)
        except Exception as exc:  # noqa: BLE001
            raise self._map_exception("get_access_token", exc)

    def _map_exception(self, operation: str, exc: Exception) -> Exception:
        """Translate Groww SDK exceptions into QC-Engine adapter errors."""

        message = f"{operation} failed: {self._format_exception_detail(exc)}"
        if isinstance(exc, (groww_exceptions.GrowwAPIAuthenticationException, groww_exceptions.GrowwAPIAuthorisationException)):
            return AuthError(self.provider_name, message, cause=exc)
        if isinstance(exc, groww_exceptions.GrowwAPIRateLimitException):
            return RateLimited(self.provider_name, message, cause=exc)
        if isinstance(exc, (groww_exceptions.GrowwAPITimeoutException, TimeoutError)):
            return Unavailable(self.provider_name, message, cause=exc)
        if isinstance(exc, groww_exceptions.GrowwAPIException):
            # Generic Groww error surfaced as invalid or forbidden payload
            return InvalidResponse(self.provider_name, message, cause=exc)
        return Unavailable(self.provider_name, message, cause=exc)

    @staticmethod
    def _format_exception_detail(exc: Exception) -> str:
        exc_type = type(exc).__name__
        code = getattr(exc, "code", None)
        message = getattr(exc, "message", None)
        parts = [exc_type]
        if code:
            parts.append(f"code={code}")
        if message:
            parts.append(f"message={message}")

        rendered = " ".join(parts)
        if not message:
            rendered = f"{rendered} ({str(exc)})" if str(exc) else rendered
        return rendered


def _format_dt(dt_utc: datetime) -> str:
    dt = ensure_utc(dt_utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _map_timeframe_to_interval(timeframe: Timeframe) -> str:
    mapping = {
        Timeframe.MIN_1: GrowwAPI.CANDLE_INTERVAL_MIN_1,
        Timeframe.MIN_5: GrowwAPI.CANDLE_INTERVAL_MIN_5,
        Timeframe.MIN_15: GrowwAPI.CANDLE_INTERVAL_MIN_15,
        Timeframe.HOUR_1: GrowwAPI.CANDLE_INTERVAL_HOUR_1,
        Timeframe.DAY_1: GrowwAPI.CANDLE_INTERVAL_DAY,
    }
    try:
        return mapping[timeframe]
    except KeyError as exc:  # pragma: no cover - invalid path
        raise InvalidResponse("groww", f"unsupported timeframe: {timeframe}") from exc

