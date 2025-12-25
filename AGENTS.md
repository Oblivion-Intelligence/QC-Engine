# QC-Engine — Agent Instructions (Phase 1: Adapters + Backfill + Storage + Plot)

## Goal (this phase)
Implement:
1) Groww market data adapter (historical candles) + yfinance adapter
2) Backfill pipeline to download historical candles
3) Parquet-based candle store (append + dedup + read)
4) Simple plotting (close price + volume)

No live trading, no order placement, no websocket feeds in this phase.

---

## Non-negotiable invariants
1) **SDK boundary**
   - Only files under `src/qcengine/adapters/**` may import external provider SDKs
     (e.g., `groww`, `yfinance`).
   - Everything else must use QC-Engine domain models.

2) **Canonical candle schema**
   - All providers must normalize into `qcengine.domain.marketdata.Candle`.
   - Required fields: `instrument_id`, `timeframe`, `bar_start_ts_utc`, `open`, `high`, `low`, `close`, `volume`, `source`, `available_ts_utc`.

3) **Time discipline**
   - Store all timestamps internally in **UTC**.
   - `available_ts_utc` = the time our system ingested the candle (set during normalization/ingestion).

4) **Idempotent storage**
   - Candle uniqueness key is:
     `(instrument_id, timeframe, bar_start_ts_utc)`.
   - Parquet store `append()` must deduplicate on this key and must not create duplicates across reruns.

5) **Ordering**
   - Adapter methods must return candles sorted ascending by `bar_start_ts_utc`.

---

## Minimal engineering standards
- Provide `pytest` tests for:
  - candle ordering + schema validation
  - parquet store idempotent append/dedup
- Prefer explicit small functions over large files.
- Add structured logging where useful (counts, ranges, provider, symbol).

---

## Commands (assume these)
- Tests: `pytest -q`

If you add dependencies, update `pyproject.toml`.
