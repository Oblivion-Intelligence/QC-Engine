# `src/qcengine/domain/marketdata.py` — Pseudocode Spec (Phase 1)

## Purpose

##Define the canonical market data types used across the repo. Providers (Groww/yfinance) must normalize into these objects. Storage and plotting operate only on these objects.

---

## Public API (exports)

### 1) `Timeframe` (enum-like)

* Represents candle resolution.
* Must support at least: `MIN_1`, `MIN_5`, `MIN_15`, `HOUR_1`, `DAY_1` (you can include fewer, but at minimum `MIN_1` and `DAY_1`).
* Must provide:

  * `to_minutes() -> int` (e.g., DAY_1 = 1440)
  * `__str__`/`value` that can be used in filenames (e.g., `"1m"`, `"1d"`)

**Pseudocode**

* define `class Timeframe(Enum):`

  * members map to string codes: `"1m"`, `"5m"`, `"15m"`, `"1h"`, `"1d"`
* `def to_minutes(self) -> int:`

  * map each to integer minutes
* `@classmethod def from_minutes(cls, minutes: int) -> Timeframe:`

  * raise `ValueError` if unsupported (Phase 1)

---

### 2) `Candle` (canonical OHLCV)

A single bar. Canonical across all providers.

**Fields (required)**

* `instrument_id: str`
* `timeframe: Timeframe`
* `bar_start_ts_utc: datetime`  (timezone-aware UTC)
* `open: float`
* `high: float`
* `low: float`
* `close: float`
* `volume: float | None`
* `source: str` (e.g., `"groww"`, `"yfinance"`)
* `available_ts_utc: datetime` (timezone-aware UTC; set when ingested/normalized)

**Derived/utility**

* `key() -> tuple[str, str, datetime]`

  * returns `(instrument_id, timeframe.value, bar_start_ts_utc)`
* `to_dict()` / `from_dict()` for parquet/json convenience (optional but recommended)

**Validation invariants**

* `bar_start_ts_utc` MUST be timezone-aware and in UTC.
* `available_ts_utc` MUST be timezone-aware and in UTC.
* OHLC:

  * `high >= max(open, close, low)`
  * `low <= min(open, close, high)`
* `volume`:

  * if present, must be `>= 0`
* Numeric values must be finite (no NaN/inf).

**Pseudocode**

* implement as `pydantic.BaseModel` (or dataclass + manual checks)
* add validators:

  * ensure tz-aware + UTC (reject naive datetimes)
  * ensure OHLC constraints
  * ensure numeric finiteness
* `def key(self): ...`

---

## Helper functions (module-private is fine)

### `ensure_utc(dt: datetime) -> datetime`

* If `dt` is naive: raise `ValueError` (Phase 1 strict).
* If aware but not UTC: convert to UTC.
* Return normalized UTC datetime.

### `now_utc() -> datetime`

* Return current timezone-aware UTC timestamp.

---

## Done criteria (Codex must satisfy)

* Can instantiate `Candle` with valid data.
* Invalid timezone / naive timestamps raise a clear error.
* Invalid OHLC relationships raise errors.
* `Timeframe.to_minutes()` returns correct values.
* `Candle.key()` returns stable uniqueness key as specified.

---

## Minimal tests to write later (just note here)

* Creating Candle with naive `bar_start_ts_utc` fails.
* Creating Candle with `high < open` fails.
* `Timeframe("1d").to_minutes() == 1440`.
* `Candle.key()` matches `(instrument_id, timeframe.value, bar_start_ts_utc)`.
