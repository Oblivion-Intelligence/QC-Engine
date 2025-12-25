# QC-Engine Architecture Overview

## 1. Purpose and Operating Posture

QC-Engine is a continuously running, control-theoretic trading/control system intended to operate on a Linux VPS with high uptime. It is engineered for:

* **Correctness under uncertainty:** strict time/counterfactual discipline (“as-of” semantics).
* **Robustness:** graceful degradation under partial failures (data staleness, API downtime, compute lag).
* **Auditability and replay:** durable artifacts (observations → states → decisions → actions) enabling post-hoc verification.
* **Separation of concerns:** adapters isolate provider APIs; strategy logic cannot directly touch brokers or raw feeds.

Phase-1 scope focuses on **Sensor + Normalization + Storage + Validation plotting** (no execution).

---

## 2. System Boundary: Plant vs Controller

### Plant (external environment)

* Exchanges/market microstructure
* Broker infrastructure (Groww)
* Network conditions, rate limits, outages
* Corporate actions, symbol changes
* Account state (positions, funds, orders, fills)

### Controller (QC-Engine)

* Acquires observations (market + account)
* Normalizes and stores observations
* Produces state estimates and decisions (later)
* Plans and executes actions (later)
* Monitors and enforces interlocks

---

## 3. High-Level Control Loop

Conceptual closed loop (full system; not all stages implemented in Phase-1):

1. **Sense**: acquire raw market/account signals from providers
2. **Normalize**: convert provider payloads into canonical domain objects
3. **Store**: append-only persistence; enforce dedup keys and time discipline
4. **Estimate State**: compute constructs/features → state snapshots
5. **Decide**: control law selects target exposures/actions subject to constraints
6. **Actuate**: broker execution layer places/cancels/modifies orders
7. **Reconcile**: compare internal state vs broker truth; detect drift
8. **Monitor**: health metrics, interlocks, mode transitions (degrade/halt)

Phase-1 implements (1)–(3) and basic validation via plotting.

---

## 4. Architectural Layers (Control-Theoretic Decomposition)

### 4.1 Sensor Layer (Adapters)

**Role:** acquire external signals.
**Primary providers:** Groww (core), yfinance (supplemental/validation).
**Output:** raw provider payloads (kept within adapter boundary) and canonical observations (outside boundary).

Key rule: provider SDK imports must remain inside `src/qcengine/adapters/**`.

### 4.2 Normalization & Validation Layer

**Role:** transform raw provider responses into canonical domain objects; enforce strict invariants (UTC timestamps, OHLC validity, ordering).
**Output:** canonical `Candle` objects (Phase-1), later `Quote`, `AccountSnapshot`, etc.

Fail-fast posture: malformed payloads raise normalized adapter exceptions; no silent skipping.

### 4.3 Storage Layer (System Memory)

**Role:** persist canonical observations and artifacts to support replay and long-run operation.
**Phase-1 storage:** Parquet (append + dedup).
**Later storage:** Postgres/Timescale for 24×7 multi-service operation.

Core idea: persistence provides the “memory” of the controller and enables downstream state estimation.

### 4.4 Compute / State Estimation Layer (Later)

**Role:** compute versioned constructs/features and assemble `StateSnapshot` per asset/timeframe.
This layer enforces determinism and incremental computation constraints.

### 4.5 Decision / Coordinator Layer (Later)

**Role:** compute decisions from state + objectives + constraints.
Produces immutable `DecisionRecord` artifacts.
Interlocks can force safe actions (NO_TRADE, HALT, FLATTEN) depending on severity.

### 4.6 Planning & Execution Layer (Later)

**Role:** translate targets into executable broker instructions; manage order lifecycle.
Only executes validated decisions; includes circuit breakers and kill switch.

### 4.7 Reconciliation Layer (Later)

**Role:** validate that executed actions match broker truth; detect mismatches and trigger interlocks.

### 4.8 Monitoring & Governance Layer

**Role:** observability and operator control.
Includes health signals (staleness, lag, API status), audit logs, and mode switching.

---

## 5. Primary Data Flow (Phase-1)

### Phase-1 workflow

* **Input:** `(symbol/instrument, timeframe, start, end)`
* **Groww/yfinance adapter:** fetch historical candles
* **Normalization:** convert to canonical `Candle` list (UTC, sorted)
* **Storage:** append into Parquet store with dedup on uniqueness key
* **Validation:** plot close series + volume to sanity-check ingest

Outputs of Phase-1:

* canonical candle dataset per instrument/timeframe in storage
* repeatable “backfill → store → load → plot” path

---

## 6. Runtime Model and Service Topology (Target, later)

Target operational posture is multi-process on a single VPS, supervised by `systemd` or Docker Compose, with fault containment boundaries:

* Ingest service (market + account)
* Compute/state service
* Decision coordinator service
* Execution service (gated; can be disabled)
* Monitoring/telemetry agent

Phase-1 may run as scripts/CLI commands (not daemonized) until data correctness is verified.

---

## 7. Operating Modes (Safety Ladder)

QC-Engine is designed to support explicit modes:

* **Mode 0: Ingest-only** (store observations, no compute/decisions)
* **Mode 1: Compute-only** (state snapshots, no decisions)
* **Mode 2: Decide-only** (write decisions; NO_TRADE or simulated)
* **Mode 3: Paper execution** (simulated fills)
* **Mode 4: Live execution** (real orders; requires explicit enable)

Mode transitions are governed by health signals and interlocks (later).

---

## 8. Phase Roadmap (Architecture-Driven)

### Phase-1 (current)

* Domain models: `Candle`, `Timeframe`
* Adapter contract + error taxonomy
* Groww historical adapter + yfinance historical adapter
* Parquet store (append + dedup + load)
* Backfill command + plot validation

### Phase-2 (next)

* Portfolio truth ingestion (positions, orders, funds)
* Postgres/Timescale storage + as-of query semantics
* State estimation constructs registry (versioned)
* Health monitoring (staleness, lag)

### Phase-3

* Decision coordinator (DecisionRecord artifacts)
* Risk governor + interlocks
* Execution planning + gated live trading

---

## 9. Non-Goals (Explicit)

To prevent scope creep, QC-Engine does not attempt, in Phase-1, to define:

* full strategy logic or alpha design
* optimization routines
* low-latency execution guarantees
* cross-broker routing
* distributed orchestration (Kubernetes)

These emerge only after sensor correctness and storage semantics are validated.

---

## 10. Repository Mapping (Orientation)

Primary code lives under `src/qcengine/`:

* `domain/` — canonical data models
* `adapters/` — provider boundaries (Groww, yfinance)
* `ingestion/` — backfill and ingestion workflows
* `storage/` — persistence backends (Parquet now; DB later)
* `analytics/` — validation plots and diagnostics
* `docs/architecture/` — architectural intent, invariants, contracts
