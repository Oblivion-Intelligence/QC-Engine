# `src/qcengine/adapters/base.py` — Pseudocode Spec (Phase 1)

## Purpose

##Define **provider-agnostic adapter contracts** and **normalized adapter errors**.
##All ingestion code calls these interfaces; provider code implements them.

---

## Imports (conceptual)

* `from qcengine.domain.marketdata import Candle, Timeframe`
* `from dataclasses import dataclass` (or pydantic)
* `from typing import Protocol, runtime_checkable, Iterable`
* `from datetime import datetime`

---

## 1) Canonical adapter exceptions (normalized error taxonomy)

### `class AdapterError(Exception)`

* Base exception for all adapter failures.
* Has fields:

  * `provider: str` (e.g., "groww", "yfinance")
  * `message: str`
  * optional `cause: Exception | None`

### Subclasses (Phase 1 minimal set)

* `class AuthError(AdapterError)`
  Raised when auth/token invalid/expired.
* `class RateLimited(AdapterError)`
  Raised on rate limit; ingestion may retry with backoff.
* `class Unavailable(AdapterError)`
  Raised on network/service downtime/timeouts; retryable.
* `class InvalidResponse(AdapterError)`
  Raised when provider returns malformed/unexpected data; fail-fast.

**Design note:** ingestion/backfill may treat `RateLimited` and `Unavailable` as retryable; others as terminal (per run).

---

## 2) Provider instrument reference (minimal for Phase 1)

### `@dataclass(frozen=True) class InstrumentRef`

Represents a canonical instrument identity and the provider symbol needed by the adapter.

Fields:

* `instrument_id: str`
  Internal stable ID used by your engine.
* `provider_symbol: str`
  The symbol string the provider expects (Groww or yfinance).
* optional metadata fields (only if you already know you need them now):

  * `exchange: str | None`
  * `segment: str | None`

**Invariants**

* `instrument_id` non-empty
* `provider_symbol` non-empty

---

## 3) Market data adapter interface (historical candles only)

### `@runtime_checkable class MarketDataAdapter(Protocol)`

Properties / methods:

#### `provider_name: str`

* constant identifier, e.g., `"groww"` or `"yfinance"`

#### `def get_historical_candles(self, instrument: InstrumentRef, timeframe: Timeframe, start_utc: datetime, end_utc: datetime) -> list[Candle]:`

Behavior contract:

* `start_utc` and `end_utc` are timezone-aware UTC datetimes (callers should pass UTC).
* Returns **canonical** `Candle` objects:

  * `instrument_id == instrument.instrument_id`
  * `timeframe == timeframe`
  * `source == self.provider_name`
  * `available_ts_utc` set to “now_utc()” at normalization time
* Returned candles must be **sorted ascending by `bar_start_ts_utc`**
* If provider returns empty: return `[]` (do not throw)
* Errors:

  * auth failure → `AuthError`
  * rate limit → `RateLimited`
  * network/timeouts/service errors → `Unavailable`
  * unexpected schema/data → `InvalidResponse`

Optional (but useful) Phase 1 method:

#### `def ping(self) -> None`

* Raises `Unavailable` if provider is not reachable / auth invalid.
* Used by health checks (optional).

---

## 4) Optional: Instrument resolver interface (if you want it now)

If you intend to keep symbol mapping clean:

### `class InstrumentResolver(Protocol)`

* `def resolve(self, canonical_symbol: str) -> InstrumentRef`
* raises `AdapterError` on unknown mapping.

You can skip implementing this interface until you actually need it, but the adapter integration is cleaner if you define it now.

---

## Done criteria (Codex must satisfy)

* `MarketDataAdapter` protocol compiles and is importable.
* `InstrumentRef` exists and is frozen/immutable.
* All adapter errors exist and can be caught by ingestion code uniformly.
* No provider SDK imports here (this is a hard boundary).
