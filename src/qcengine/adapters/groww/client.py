# `src/qcengine/adapters/groww/client.py` — Pseudocode Spec (Phase 1)

## Purpose

Encapsulate all direct interaction with `growwapi` and expose a stable, minimal client surface to the Groww adapter modules (`marketdata.py`, later `execution.py`).

**Hard boundary:** only files under `adapters/groww/` import `growwapi`.

---

## Imports (conceptual)

* `from growwapi import GrowwAPI` (or correct SDK entrypoint)
* `from datetime import datetime`
* `from typing import Any`
* `from qcengine.adapters.base import InstrumentRef`
* `from qcengine.domain.marketdata import Timeframe`
* `from qcengine.adapters.base import AuthError, RateLimited, Unavailable, InvalidResponse`

Optional utilities:

* `from qcengine.utils.retry import retry_with_backoff` (or implement a local minimal retry helper)
* `from qcengine.utils.logging import get_logger`

---

## Config (minimal)

### `@dataclass(frozen=True) class GrowwClientConfig`

Fields (Phase 1):

* `auth_token: str`  (provided externally via env/config)
* optional:

  * `timeout_s: float = 10.0`
  * `max_retries: int = 3`
  * `retry_backoff_base_s: float = 0.5`

**Invariant:** `auth_token` non-empty.

---

## Class: `GrowwClient`

### Constructor

`def __init__(self, config: GrowwClientConfig):`

* Store config.
* Instantiate SDK client:

  * `self._api = GrowwAPI(config.auth_token)` (or equivalent)
* Prepare logger.

**Do not** do network calls in `__init__`.

---

## Method: `ping() -> None`

Purpose: verify token is valid and API reachable (lightweight).

**Implementation approach**

* Call a cheap endpoint (whichever is simplest in SDK):

  * e.g., `get_user_profile()` or similar.
* If success: return `None`.
* Map failures to normalized exceptions:

  * auth/token invalid → `AuthError(provider="groww", ...)`
  * network timeout/connection → `Unavailable(...)`
  * rate limit → `RateLimited(...)`
  * unexpected response shape → `InvalidResponse(...)`

**No retries** unless you want a single retry on network errors.

---

## Method: `get_historical_candles_raw(...) -> Any`

Signature (Phase 1):
`def get_historical_candles_raw(self, instrument: InstrumentRef, timeframe: Timeframe, start_utc: datetime, end_utc: datetime) -> Any:`

**Behavior contract**

* This returns the **raw** payload from Groww SDK, unnormalized.
* It does not return `Candle` objects; that conversion happens in `marketdata.py`.

**Input requirements**

* `start_utc` and `end_utc` must be timezone-aware UTC datetimes.
* `instrument.provider_symbol` must be whatever Groww expects for the trading symbol parameter.
* Groww may require exchange/segment/product parameters:

  * if those are required, read them from `instrument.exchange` / `instrument.segment`
  * if instrument lacks them, raise `InvalidResponse` or a custom `AdapterError` with a clear message.

**Call shape (conceptual)**

* Convert datetimes to the string format Groww expects:

  * `"YYYY-MM-DD HH:MM:SS"` or epoch seconds (follow SDK docs).
* Convert timeframe to Groww interval minutes:

  * `interval = timeframe.to_minutes()` (but only if Groww supports that interval)
* Call SDK method:

  * `self._api.get_historical_candles(trading_symbol=instrument.provider_symbol, exchange=..., segment=..., start_time=..., end_time=..., interval_in_minutes=interval)`
* Return SDK response.

**Error mapping**

* If SDK raises an auth exception / returns 401: raise `AuthError("groww", ...)`
* If rate limited / 429: raise `RateLimited("groww", ...)`
* If network error / timeout: raise `Unavailable("groww", ...)`
* If response is missing expected keys / is empty in an invalid way: raise `InvalidResponse("groww", ...)`

**Retries**

* Retry only for:

  * `RateLimited` (with backoff)
  * `Unavailable` (with backoff)
* Do not retry `AuthError` or `InvalidResponse`.

**Logging**

* Log at info:

  * provider, symbol, timeframe, start/end, interval, result count if available.
* Log at warning on retries.

---

## Helper: `_format_dt(dt_utc: datetime) -> str`

* Ensure dt is UTC aware; otherwise raise.
* Return in Groww-required format. Keep it centralized.

## Helper: `_map_timeframe_to_interval_minutes(timeframe: Timeframe) -> int`

* If timeframe not supported (e.g., 1h not supported): raise `InvalidResponse` with message “unsupported timeframe for Groww historical”.

---

## Done criteria (Codex must satisfy)

* `GrowwClient` compiles with minimal external dependencies.
* No provider normalization here (no `Candle` creation).
* All exceptions raised are from `qcengine.adapters.base` taxonomy.
* Works with a fake/mocked SDK in unit tests (design for injectability if possible).

