# QC-Engine Invariants

## 0. Scope and Intent

This document defines **non-negotiable system invariants**. These rules must hold across all implementations and refactors. When an invariant is violated, the correct response is to **fail fast**, **degrade explicitly**, or **halt**, depending on the invariant class.

**Phase-1 emphasis:** sensor/adapters, canonicalization, storage idempotency, time discipline.
**Later phases:** decision/execution safety invariants are listed now to prevent architectural drift.

---

## 1. Boundary and Dependency Invariants

### I-1: Provider SDK boundary

* Only modules under `src/qcengine/adapters/**` may import provider SDKs (e.g., `growwapi`, `yfinance`).
* Non-adapter code must depend only on QC-Engine domain models and adapter interfaces.

**Rationale:** isolates provider churn and prevents the engine from becoming provider-shaped.

### I-2: No provider-shaped objects cross adapter boundary

* Adapters may internally handle raw provider payloads.
* Adapters must output **only canonical domain objects** (e.g., `Candle`) to the rest of the system.

**Enforcement:** adapter return types; tests verifying canonical types.

---

## 2. Time, Causality, and “As-Of” Invariants

### I-3: UTC as internal time base

* All internal timestamps are timezone-aware and normalized to **UTC**.
* Naive datetimes are invalid inputs to core system boundaries (adapters, storage, compute).

**Phase-1 enforcement:** `ensure_utc()` rejects naive timestamps; tests.

### I-4: Available-time tagging (epistemic discipline)

* Every canonical observation artifact includes `available_ts_utc` which denotes **when QC-Engine first had the data**.
* `available_ts_utc` is set by the ingestion/normalization process, not inferred later.

**Rationale:** supports replay and prevents accidental lookahead.

### I-5: No-lookahead (future-facing invariant, listed now)

* Any decision at time `t_decision` must use only data with `available_ts_utc ≤ t_decision`.
* Any computation performed “as-of” a time must respect this constraint.

**Phase-1 note:** not fully enforced until “as-of queries” exist, but schema must support it now.

---

## 3. Canonical Market Data Invariants (Phase-1 Critical)

### I-6: Canonical candle schema

All candle data in the system must conform to `qcengine.domain.marketdata.Candle` with required fields:

* `instrument_id`, `timeframe`, `bar_start_ts_utc`
* `open`, `high`, `low`, `close`, `volume`
* `source`, `available_ts_utc`

### I-7: Candle time semantics

* `bar_start_ts_utc` denotes the start timestamp of the bar interval in UTC.
* For a given `(instrument_id, timeframe)`, candle timestamps must be aligned to the timeframe grid (implementation-dependent validation may be added later).

### I-8: Candle ordering guarantee (adapter contract)

* Adapter `get_historical_candles(...)` returns candles sorted ascending by `bar_start_ts_utc`.

**Rationale:** storage and downstream compute assume time-ordered series.

### I-9: OHLC sanity

For every candle:

* `high ≥ max(open, close, low)`
* `low ≤ min(open, close, high)`
* Values must be finite (no NaN/inf)
* `volume` if present must be `≥ 0`

**Enforcement:** domain model validators; fail-fast on violation.

---

## 4. Storage and Idempotency Invariants (Phase-1 Critical)

### I-10: Candle uniqueness key

Candle uniqueness is defined as:

* `(instrument_id, timeframe, bar_start_ts_utc)`

### I-11: Idempotent append

Storage must support idempotent writes:

* appending the same candle set twice must not create duplicates
* deduplication occurs on the uniqueness key

**Phase-1 enforcement:** Parquet store `append()` dedups; tests.

### I-12: Append-only posture (future-facing, listed now)

* Canonical records must never be silently overwritten.
* Corrections are represented as explicit revisions or new artifacts (mechanism may differ by backend).

**Phase-1 note:** Parquet store may implement “latest wins” in a controlled manner, but must not silently corrupt history.

---

## 5. Error and Failure-Mode Invariants

### I-13: Normalized adapter error taxonomy

Adapters and provider clients must raise normalized exceptions from `qcengine.adapters.base`:

* `AuthError`, `RateLimited`, `Unavailable`, `InvalidResponse` (and base `AdapterError`)

Provider-native exceptions must not propagate beyond adapter boundaries.

### I-14: Fail-fast on malformed data (Phase-1 posture)

* Malformed payloads, missing fields, invalid timestamps, and OHLC violations must raise `InvalidResponse`.
* No silent skipping of malformed rows in Phase-1.

---

## 6. Determinism and Reproducibility Invariants (future-facing, listed now)

### I-15: Deterministic computation under version pinning

* Given identical input artifacts and identical code version, derived outputs must be deterministic.
* Derived artifacts must carry a version identifier linking to the definition used.

### I-16: Replayability

* The system must be able to reconstruct derived states (and later decisions) from persisted artifacts.

---

## 7. Control and Execution Safety Invariants (future-facing, listed now)

### I-17: Strategy purity

* Strategy modules must not directly perform I/O with brokers or storage.
* Strategy proposals are pure functions of a provided context snapshot.

### I-18: Single authority for decision netting

* Only the coordinator/control layer may net, prioritize, and finalize actions.
* Execution consumes finalized decision artifacts only.

### I-19: Execution gating

* Live order placement must be explicitly enabled (kill-switch defaults to off).
* Execution must be traceable to an immutable `DecisionRecord`.

### I-20: Reconciliation supremacy

* Broker truth overrides internal beliefs on persistent mismatch.
* Mismatch triggers explicit interlocks (halt/degrade/flatten policies).

---

## 8. Enforcement Notes (Phase-1)

Phase-1 enforcement is through:

* domain model validators (`Candle`, `Timeframe`)
* adapter contracts (sorted candles, UTC)
* storage dedup tests
* minimal integration sanity checks (fetch → normalize → store → load)

Any pull request that violates invariants must be rejected or corrected.
