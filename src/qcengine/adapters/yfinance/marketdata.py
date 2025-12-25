## `src/qcengine/adapters/yfinance/marketdata.py` — Pseudocode Spec (Phase 1, fail-fast)

### Purpose

Implement `YFinanceMarketDataAdapter` that conforms to `MarketDataAdapter` and converts yfinance historical data into canonical `Candle` objects.

**Fail-fast policy:** any malformed response, missing columns, invalid timestamps, invalid OHLC ⇒ raise `InvalidResponse`.

---

## Imports (conceptual)

* `from datetime import datetime`
* `from typing import List`
* `import yfinance as yf`
* `import pandas as pd` (yfinance returns DataFrame; treat as such)
* `from qcengine.adapters.base import MarketDataAdapter, InstrumentRef`
* `from qcengine.adapters.base import RateLimited, Unavailable, InvalidResponse, AdapterError`
* `from qcengine.domain.marketdata import Candle, Timeframe, ensure_utc, now_utc`

(Optional logger)

---

## Class: `YFinanceMarketDataAdapter`

### Attributes

* `provider_name: str = "yfinance"`

### `__init__(self)`

* no special config required initially

### `ping(self) -> None` (optional)

* Perform a minimal call (e.g., fetch a tiny range for a known symbol) OR skip ping in Phase 1.
* If implemented: network errors ⇒ `Unavailable`.

---

## Core method: `get_historical_candles(...)`

Signature:
`def get_historical_candles(self, instrument: InstrumentRef, timeframe: Timeframe, start_utc: datetime, end_utc: datetime) -> List[Candle]:`

### Preconditions (fail-fast)

1. `instrument.instrument_id` and `instrument.provider_symbol` non-empty, else `InvalidResponse`
2. Ensure UTC inputs:

   * `start_utc = ensure_utc(start_utc)`
   * `end_utc = ensure_utc(end_utc)`
3. `start_utc < end_utc` else `ValueError` or `InvalidResponse`

### Steps

1. Convert timeframe to yfinance interval string:

   * map:

     * `MIN_1 -> "1m"`
     * `MIN_5 -> "5m"`
     * `MIN_15 -> "15m"`
     * `HOUR_1 -> "60m"` (yfinance uses "60m")
     * `DAY_1 -> "1d"`
   * if timeframe unsupported by yfinance: raise `InvalidResponse("yfinance", "...unsupported timeframe...")`

2. Prepare request times:

   * yfinance `download()` expects naive timestamps in local? It handles timezone; to avoid ambiguity:

     * convert UTC datetimes to ISO strings (UTC) or pass as `datetime` objects (ensure tz-aware)
   * If the library forces naive: explicitly convert to UTC naive and document it in code, but keep internal Candle timestamps UTC-aware.

3. Fetch data:

   * Use one of:

     * `yf.download(tickers=instrument.provider_symbol, start=..., end=..., interval=..., auto_adjust=False, progress=False, group_by="ticker")`
     * or `yf.Ticker(symbol).history(start=..., end=..., interval=..., auto_adjust=False)`
   * Choose one and stick to it (recommend `Ticker().history` for single symbol).

4. Validate DataFrame:

   * Must be non-empty else return `[]` (allowed)
   * Must contain required columns:

     * `Open`, `High`, `Low`, `Close`
     * `Volume` optional (but generally present)
   * If missing required columns: raise `InvalidResponse`

5. Normalize index timestamps:

   * DataFrame index can be tz-aware or naive; enforce:

     * convert index to UTC (`tz_convert("UTC")` if tz-aware)
     * if naive: interpret as UTC (fail-fast vs assume):

       * **Preferred fail-fast**: if naive, raise `InvalidResponse("yfinance", "naive timestamps from yfinance")`
       * If yfinance consistently gives naive, you may choose to treat as UTC; but that is a semantics decision. For now: **fail-fast**.

6. Convert each row into a Candle:
   For each timestamp `ts` and row:

   * `bar_start_ts_utc = ensure_utc(ts.to_pydatetime())`
   * parse OHLC as floats
   * parse volume:

     * if Volume column present: float(row["Volume"])
     * else None
   * create `Candle`:

     * `instrument_id = instrument.instrument_id`
     * `timeframe = timeframe`
     * `bar_start_ts_utc = bar_start_ts_utc`
     * `open/high/low/close/volume`
     * `source = "yfinance"`
     * `available_ts_utc = now_utc()` (single timestamp per call is fine)

7. Ensure candles sorted ascending by `bar_start_ts_utc`:

   * DataFrame is typically ordered; still enforce:

     * sort by timestamp and return list

8. Return list

---

## Error mapping (best-effort)

yfinance doesn’t reliably throw typed rate-limit exceptions; failures are usually generic network issues.

* Network / HTTP / timeout / connection errors ⇒ `Unavailable(provider="yfinance", ...)`
* Anything that indicates throttling (if detectable) ⇒ `RateLimited` (optional; otherwise treat as `Unavailable`)
* Schema/columns/timestamps issues ⇒ `InvalidResponse`

---

## Done criteria

* Returns list of `Candle` objects that satisfy:

  * UTC-aware timestamps
  * correct OHLC + validation
  * sorted ascending
  * `source == "yfinance"`
* Empty history returns `[]`
* Missing columns or naive timestamp handling follows fail-fast policy (raise)
