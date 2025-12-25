# QC-Engine Data Contracts (Phase 1)

## 0. Scope

This document specifies **data contracts and interface contracts** between QC-Engine modules. Phase-1 focuses on:

* Market data ingestion (historical candles)
* Canonicalization into QC-Engine domain objects
* Storage (append + dedup) and retrieval semantics
* Minimal validation consumers (plotting)

Out of scope in Phase-1 (placeholders only): live feeds, order execution, portfolio/positions, decision/state artifacts.

---

## 1. Contract Conventions

### 1.1 Time standard (global)

* All QC-Engine internal datetimes are **timezone-aware UTC**.
* Fields suffixed with `_ts_utc` MUST be UTC-aware.
* Naive datetimes are invalid at module boundaries.

### 1.2 Fail-fast posture (Phase-1)

* Malformed provider payloads, missing required fields, invalid timestamps, and invalid OHLC values must raise a normalized error immediately.
* Phase-1 does **not** skip bad rows and “continue.”

### 1.3 Ownership

Each contract section declares:

* **Producer**: module responsible for creating the artifact in canonical form
* **Consumers**: modules allowed to depend on the artifact
* **Validation**: where and how invariants are enforced

### 1.4 Identifiers and uniqueness keys

When an entity can have duplicates, the contract defines:

* a uniqueness key (tuple of fields)
* whether dedup happens at production time or storage time

---

## 2. Canonical Domain Entities (QC-Engine Owned)

### 2.1 `Timeframe`

**Purpose:** Standard representation of candle resolution.

* **Type:** Enum-like
* **Allowed values (Phase-1 baseline):**

  * `1m`, `5m`, `15m`, `1h`, `1d`
* **Required methods:**

  * `to_minutes() -> int` (e.g., `1d -> 1440`)
  * `__str__` or `.value` must provide the stable code string used in:

    * file paths / partition names
    * logs
* **Validation:**

  * Unsupported conversions must raise `ValueError`

**Producer:** user/config (selection)
**Consumers:** adapters, storage, ingestion, analytics

---

### 2.2 `InstrumentRef`

**Purpose:** Provider-aware instrument identifier used as an adapter input.

* **Fields (Phase-1):**

  * `instrument_id: str`
    QC-Engine stable internal identifier (your canonical ID)
  * `provider_symbol: str`
    Provider’s required symbol string (provider-specific)
  * `exchange: str | None`
    Required for Groww historical APIs (recommended present for Groww)
  * `segment: str | None`
    Required for Groww historical APIs (recommended present for Groww)

* **Invariants:**

  * `instrument_id` non-empty
  * `provider_symbol` non-empty
  * For Groww historical candles: `exchange` and `segment` must be non-empty

**Producer:** instrument mapping / resolver (Phase-1 can be a static mapping file)
**Consumers:** adapters only

**Important:** `provider_symbol` is **not** globally meaningful. It is meaningful only under a specific adapter/provider.

---

### 2.3 `Candle`

**Purpose:** Canonical OHLCV bar used everywhere outside provider boundaries.

**Fields (required):**

* `instrument_id: str`
* `timeframe: Timeframe`
* `bar_start_ts_utc: datetime` (UTC aware)
* `open: float`
* `high: float`
* `low: float`
* `close: float`
* `volume: float | None` (nullable)
* `source: str` (e.g., `"groww"`, `"yfinance"`)
* `available_ts_utc: datetime` (UTC aware)

**Uniqueness key:**

* `(instrument_id, timeframe, bar_start_ts_utc)`

**Invariants (must be enforced by domain validation):**

* `bar_start_ts_utc` UTC-aware
* `available_ts_utc` UTC-aware
* OHLC sanity:

  * `high >= max(open, close, low)`
  * `low <= min(open, close, high)`
* Numeric finiteness (no NaN/inf)
* `volume >= 0` if present

**Ordering contract (adapter output):**

* Candle series returned by adapters MUST be sorted ascending by `bar_start_ts_utc`.

**Producer:** adapters (normalization step)
**Consumers:** storage, ingestion, analytics, (later compute/decision)

---

## 3. Adapter Interface Contracts (QC-Engine Owned)

### 3.1 Normalized Adapter Errors

All provider failures must be mapped into QC-Engine normalized errors.

* `AdapterError(provider: str, message: str, cause: Exception|None)`
* Subclasses (Phase-1 minimum):

  * `AuthError` (authentication failure / invalid token / authorization)
  * `RateLimited` (429 / rate cap exceeded)
  * `Unavailable` (timeouts, network failures, transient provider outage)
  * `InvalidResponse` (unexpected payload shape, missing fields, schema drift)

**Rule:** Provider SDK exceptions MUST NOT leak beyond adapter boundary.

**Consumers of errors:** ingestion/backfill orchestration (retry policies), monitoring.

---

### 3.2 `MarketDataAdapter` Contract

**Purpose:** Provider-agnostic interface for historical candles.

**Attributes**

* `provider_name: str` (stable identifier, e.g., `"groww"`, `"yfinance"`)

**Method**

* `get_historical_candles(instrument: InstrumentRef, timeframe: Timeframe, start_utc: datetime, end_utc: datetime) -> list[Candle]`

**Inputs**

* `start_utc`, `end_utc` are UTC-aware datetimes
* `start_utc < end_utc`
* `instrument.provider_symbol` is valid for the provider
* Provider-specific required metadata must be present (e.g., Groww needs exchange/segment)

**Outputs**

* Returns canonical `Candle` objects only
* Sorted ascending by `bar_start_ts_utc`
* `Candle.instrument_id == instrument.instrument_id`
* `Candle.timeframe == timeframe`
* `Candle.source == provider_name`
* `Candle.available_ts_utc` set at normalization time

**Empty response**

* If provider returns no data: return `[]` (not an error)

---

## 4. Groww Provider Contracts (Phase-1 Critical)

This section defines the *provider-specific* contracts used inside `src/qcengine/adapters/groww/**`.

### 4.1 Authentication (Groww SDK)

Groww SDK supports access token creation via `GrowwAPI.get_access_token(...)` and then constructing `GrowwAPI(access_token)`.

**QC-Engine contract:**

* Phase-1 assumes QC-Engine is provided an **access token** via environment/config.
* Token management/refresh is outside Phase-1; QC-Engine fails with `AuthError` on invalid/expired token.

---

### 4.2 Groww instruments and symbol identity

Groww defines a **Groww symbol** used to uniquely identify an instrument across exchanges/segments (examples: `NSE-WIPRO`, `NSE-NIFTY-30Sep25-FUT`, options, etc.). The instruments dataset (CSV / SDK methods) provides `groww_symbol`, `exchange`, `segment`, and other metadata.

**QC-Engine Phase-1 position:**

* For Groww historical candles (recommended path), QC-Engine will treat:

  * `InstrumentRef.provider_symbol` = `groww_symbol`
  * `InstrumentRef.exchange` = exchange string (e.g., `NSE`)
  * `InstrumentRef.segment` = segment string (e.g., `CASH`, `FNO`)

This prevents ambiguity and aligns with Groww’s preferred historical candle API.

---

### 4.3 Groww Historical Candles (Preferred API: `get_historical_candles`)

**Groww SDK method (Phase-1 relevant):**

* `get_historical_candles(exchange, segment, groww_symbol, start_time, end_time, candle_interval)`

**Request schema contract**

* `exchange` (required): exchange identifier (e.g., `NSE`, `BSE`)
* `segment` (required): segment identifier (e.g., `CASH`, `FNO`)
* `groww_symbol` (required): Groww symbol string (e.g., `NSE-WIPRO`)
* `start_time` (required): string `YYYY-MM-DD HH:mm:ss` **or** epoch seconds
* `end_time` (required): string `YYYY-MM-DD HH:mm:ss` **or** epoch seconds
* `candle_interval` (required): interval constant/string (Groww SDK provides predefined constants)

**Response payload contract**

* Response contains a key `candles` which is an array of candle rows.
* Each candle row is:

  * `[timestamp, open, high, low, close, volume, open_interest]`
* Timestamp is provided in a string form like `YYYY-MM-DDTHH:MM:SS` (as per docs examples).
* `open_interest` is meaningful for FNO; null otherwise.

**QC-Engine normalization contract**

* `timestamp` must be interpreted into `bar_start_ts_utc` (UTC-aware).

  * **Phase-1 action item:** confirm whether the timestamp is exchange-local or UTC by running a real sample; until confirmed, QC-Engine treats it as **exchange-local time** and converts to UTC *only if the exchange timezone is explicitly defined in code/config*. If not defined, raise `InvalidResponse` (fail-fast) rather than silently assuming.
* Normalize into `Candle`:

  * ignore `open_interest` in Phase-1 (not represented in `Candle`)
  * keep volume as float or int cast to float
* Set:

  * `source = "groww"`
  * `available_ts_utc = now_utc()`
* Must return candles sorted ascending by `bar_start_ts_utc`.

**Limits contract (operational constraint)**
Groww imposes maximum request durations per candle interval. QC-Engine backfill must respect these limits by chunking requests. (Chunking logic is not part of adapter contract; it belongs to ingestion/backfill.)

---

### 4.4 Groww Historical Candles (Deprecated API: `get_historical_candle_data`)

Groww SDK also documents `get_historical_candle_data(...)` as deprecated and to be removed in future.

**QC-Engine contract:**

* Phase-1 should not depend on deprecated API except for diagnostics or transitional support.
* If implemented, it must be isolated and clearly labeled as deprecated internally.

**Deprecated response difference (not used by QC-Engine core path):**

* `candles` rows contain epoch seconds timestamps and do not include open interest in the example format.

---

### 4.5 Groww SDK exception mapping (internal)

Groww SDK provides custom exception classes under `growwapi.groww.exceptions` (authentication, authorization, rate limit, timeout, etc.).

**QC-Engine contract**

* `GrowwClient` MUST catch Groww SDK exceptions and map to QC-Engine normalized errors:

  * Authentication/authorization → `AuthError`
  * Rate limit → `RateLimited`
  * Timeout/network/transient → `Unavailable`
  * Bad request / schema mismatch / unexpected payload → `InvalidResponse` (or `AdapterError` if clearly caller fault)

Provider exception objects may be preserved in `cause`.

---

## 5. yfinance Provider Contracts (Phase-1)

### 5.1 Symbol identity

QC-Engine uses provider-specific symbol strings for yfinance.

**Contract**

* `InstrumentRef.provider_symbol` = yfinance ticker string

  * (e.g., NSE equity commonly uses suffixes like `.NS`, but this is a provider policy outside QC-Engine’s canonical layer)
* `InstrumentRef.exchange` / `segment` are not required for yfinance.

### 5.2 Historical candles retrieval

yfinance returns historical OHLCV via `Ticker().history(...)` or `yf.download(...)` (implementation choice internal).

**Normalization contract**

* Required columns: Open, High, Low, Close
* Volume may be present; if missing, set `volume = None`
* Timestamp index must be convertible to UTC-aware datetimes:

  * If tz-aware: convert to UTC
  * If tz-naive: Phase-1 fail-fast (`InvalidResponse`) unless you explicitly set a policy to interpret naive timestamps

**Output contract**

* Return canonical `Candle` list sorted ascending by time
* `source = "yfinance"`
* `available_ts_utc = now_utc()`

---

## 6. Storage Contracts (Phase-1)

### 6.1 Candle storage interface (conceptual)

A storage backend must provide at minimum:

* `append(candles: list[Candle]) -> AppendResult`
* `load_range(instrument_id: str, timeframe: Timeframe, start_utc: datetime, end_utc: datetime) -> list[Candle]`

**Append contract**

* Must be idempotent:

  * writing the same candle set twice must not create duplicates
* Dedup key:

  * `(instrument_id, timeframe, bar_start_ts_utc)`
* On duplicates:

  * Phase-1 recommended behavior: keep the first occurrence and drop later duplicates OR keep the latest; but this must be explicit and deterministic.

**Load contract**

* Must return candles sorted ascending by `bar_start_ts_utc`
* Must return only candles within the requested range (inclusive/exclusive rules must be explicit; recommended: `[start, end)`)

### 6.2 Parquet store partitioning (Phase-1 recommended)

Partition directory structure (example):

* `data/candles/{instrument_id}/{timeframe}/part-*.parquet`

Partition invariants:

* all rows in a partition share instrument_id and timeframe
* schema matches canonical candle schema (flattened)

---

## 7. Ingestion / Backfill Contracts (Phase-1)

### 7.1 Backfill job input contract

Backfill orchestration consumes:

* list of `InstrumentRef`
* a `Timeframe`
* a time range `[start_utc, end_utc)`
* an adapter instance

### 7.2 Backfill behavior contract

* Must chunk requests to satisfy provider limits (Groww limits vary by candle interval)
* Must store results via storage `append()`
* Must log:

  * requested range
  * returned candle count
  * effective covered range
* On retryable errors (`RateLimited`, `Unavailable`):

  * apply bounded retry with exponential backoff
* On non-retryable errors (`AuthError`, `InvalidResponse`):

  * fail the job (Phase-1 posture)

---

## 8. Analytics / Plotting Consumer Contracts (Phase-1)

Plotting is a consumer of storage outputs, not adapters directly.

**Inputs**

* candles loaded from storage, already canonical and ordered

**Minimal expected plots**

* price series (close)
* volume series (if available)

**Plotting contract**

* Plotting must not mutate data
* Plotting must not implement inference/cleaning logic (that belongs upstream)

---

## 9. Test Fixtures and Contract Enforcement (Phase-1)

### 9.1 Required fixtures

To lock semantics (especially timezone and timestamp meaning), QC-Engine should maintain fixtures:

* `tests/fixtures/groww_historical_response.json`
  One captured, redacted `get_historical_candles` response
* Optional: `tests/fixtures/yfinance_history.parquet` or csv derived from a known small query

Fixtures should be small, stable, and used to validate parsing.

### 9.2 Required tests (minimum)

* Candle domain validation:

  * UTC awareness required
  * OHLC sanity enforced
* Adapter contract tests:

  * output type is canonical Candle only
  * output ordering ascending
  * fail-fast on malformed payload
* Storage tests:

  * append is idempotent w.r.t uniqueness key
  * load_range returns sorted, range-filtered outputs

---

## 10. Future Entities (Placeholders Only)

These headings exist to reserve vocabulary and enforce layering later. No Phase-1 implementation commitments.

* `Quote` (LTP, bid/ask, depth)
* `AccountSnapshot` (funds, margin, positions, holdings)
* `StateSnapshot` (engine state estimate per instrument/time)
* `DecisionRecord` (immutable decision artifact)
* `OrderEvent` / `FillEvent`
* `InterlockEvent` (risk/safety governance)

---

## 11. Phase-1 Implementation Checklist

Before moving beyond Phase-1, the following must be true:

* Adapters return canonical candles with correct time semantics
* Parquet store dedups idempotently on uniqueness key
* Backfill can re-run without data corruption
* Basic plots show plausible series (sanity validation)
* A single captured Groww fixture has pinned payload parsing assumptions

