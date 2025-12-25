## `src/qcengine/adapters/groww/marketdata.py` — Pseudocode Spec (Phase 1, fail-fast)

### Purpose

Implement `GrowwMarketDataAdapter` that conforms to `MarketDataAdapter` and converts Groww historical candle payloads into canonical `Candle` objects. This module is the Groww **sensor-normalization block**.

**Fail-fast policy:** any malformed payload, unexpected shape, invalid timestamps, or OHLC issues must raise `InvalidResponse` (or `AdapterError` subclass), not “skip and continue.”

---

## Imports (conceptual)

* `from datetime import datetime`
* `from typing import List, Any`
* `from qcengine.adapters.base import MarketDataAdapter, InstrumentRef`
* `from qcengine.adapters.base import AuthError, RateLimited, Unavailable, InvalidResponse`
* `from qcengine.domain.marketdata import Candle, Timeframe, ensure_utc, now_utc`
* `from qcengine.adapters.groww.client import GrowwClient`
* logger utility (optional)

---

## Class: `GrowwMarketDataAdapter`

### Attributes

* `provider_name: str = "groww"`
* `_client: GrowwClient`

### `__init__(self, client: GrowwClient)`

* store client
* (optional) validate client not None

### `ping(self) -> None`

* delegate to `_client.ping()`
* allow exceptions to propagate (already normalized in client)

---

## Core method: `get_historical_candles(...)`

Signature:
`def get_historical_candles(self, instrument: InstrumentRef, timeframe: Timeframe, start_utc: datetime, end_utc: datetime) -> List[Candle]:`

### Preconditions (fail-fast)

1. `instrument.instrument_id` non-empty else raise `InvalidResponse(provider="groww", message="empty instrument_id")`
2. `instrument.provider_symbol` non-empty else raise `InvalidResponse(...)`
3. `start_utc` and `end_utc` are timezone-aware UTC:

   * call `ensure_utc(start_utc)` and `ensure_utc(end_utc)` (will raise if invalid)
4. `start_utc < end_utc` else raise `ValueError` or `InvalidResponse` (pick one consistently)

### Steps

1. `raw = _client.get_historical_candles_raw(instrument, timeframe, start_utc, end_utc)`
2. `candles = _parse_raw_to_candles(raw, instrument, timeframe)`
3. Validate ordering:

   * ensure `candles` sorted ascending by `bar_start_ts_utc`
   * if not sorted, either sort (allowed) **or** raise
   * For fail-fast consistency: **sort**, then assert strictly non-decreasing; if duplicates exist, allow duplicates here (dedup is storage’s job), but bar_start must be non-decreasing.
4. Return `candles`

### Error handling

* Do not catch and rewrap `AuthError`, `RateLimited`, `Unavailable`, `InvalidResponse` from client.
* If parsing fails due to KeyError/TypeError/value conversion, raise `InvalidResponse(provider="groww", message="unexpected historical candle payload shape", cause=e)`.

---

## Helper: `_parse_raw_to_candles(...) -> List[Candle]`

Signature:
`def _parse_raw_to_candles(raw: Any, instrument: InstrumentRef, timeframe: Timeframe) -> List[Candle]:`

### Behavior contract

* Accept Groww SDK response for historical candles.
* Must interpret the candle records and convert them into canonical `Candle`.
* Any ambiguity or missing fields → raise `InvalidResponse` immediately.

### Payload shape handling (fail-fast, minimal assumptions)

Because provider response formats vary, implement a strict validator:

1. Determine where candle rows are:

   * if raw is dict and contains a known key like `"candles"` or `"data"`:

     * `rows = raw["candles"]` or raw["data"] (choose based on actual SDK once confirmed)
   * else if raw is list:

     * `rows = raw`
   * else:

     * raise `InvalidResponse("groww", "historical candles response not list/dict")`

2. Assert `rows` is list-like; else raise.

3. For each row in rows:

   * Parse row into components:

     * `bar_ts` (timestamp)
     * `open`, `high`, `low`, `close`
     * `volume` (optional; if absent set None)
   * Acceptable row formats (choose one primary; support second only if trivial):

     * dict row: keys like `t/o/h/l/c/v` or `timestamp/open/high/low/close/volume`
     * list row: [ts, open, high, low, close, volume]
   * If row format doesn’t match expected variants → raise `InvalidResponse`

4. Convert timestamp:

   * If timestamp is epoch (int/float): interpret as seconds or ms (must decide; see “TODO hook” below)
   * If timestamp is string: parse into datetime
   * Convert to UTC aware datetime using `ensure_utc(...)`
   * Define `bar_start_ts_utc`:

     * If provider gives bar start → use it directly
     * If provider gives bar end → convert to start using timeframe minutes (must be explicit once confirmed)
   * If cannot determine → raise `InvalidResponse`

5. Convert numeric fields:

   * cast OHLC to float
   * validate finiteness
   * volume:

     * if present cast to float
     * else None

6. Create Candle:

   * `Candle(...)` with:

     * `instrument_id = instrument.instrument_id`
     * `timeframe = timeframe`
     * `bar_start_ts_utc = parsed_ts_utc`
     * `open/high/low/close/volume`
     * `source = "groww"`
     * `available_ts_utc = now_utc()` (one timestamp per call is fine; or per row, choose one per call for consistency)

7. Return list of Candle

---

## TODO hook (explicitly left for confirmation)

Add a single internal constant/branch for timestamp interpretation:

* `EPOCH_UNIT = "ms"` or `"s"`
* Start with one; if wrong, tests will fail once you run a real call.
* When you provide one real sample response, lock this down.

---

## Done criteria (must pass once implemented)

* Calling `get_historical_candles(...)` returns a list of `Candle` objects:

  * all UTC timestamps
  * sorted ascending
  * `source == "groww"`
  * `available_ts_utc` set and UTC
* Malformed payloads raise `InvalidResponse` (not silent skipping).
* Any row with missing OHLC or timestamp raises `InvalidResponse`.

---

## Minimal tests to write (phase 1)

Create unit tests that do not require hitting Groww:

1. Given a mocked raw payload (dict/list), `_parse_raw_to_candles` produces correct Candle list.
2. Missing timestamp field raises `InvalidResponse`.
3. Naive datetime parsed without tz raises.
4. Non-sorted input rows result in sorted output (or raise—depending on your chosen behavior; above we sort then validate).
