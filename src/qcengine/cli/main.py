"""CLI entrypoints for QC-Engine backfills and health checks."""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from qcengine.adapters.base import InstrumentRef, MarketDataAdapter
from qcengine.adapters.groww import GrowwMarketDataAdapter
from qcengine.adapters.yfinance import YFinanceMarketDataAdapter
from qcengine.domain.marketdata import Timeframe, ensure_utc
from qcengine.ingestion.backfill import BackfillJob
from qcengine.storage.parquet_store import ParquetCandleStore

logger = logging.getLogger(__name__)


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return ensure_utc(dt)


def _parse_timeframes(values: Iterable[str]) -> list[Timeframe]:
    resolved: list[Timeframe] = []
    for value in values:
        try:
            resolved.append(Timeframe(value))
        except ValueError:
            minutes = int(value.rstrip("m"))
            resolved.append(Timeframe.from_minutes(minutes))
    return resolved


def _parse_instruments(values: Iterable[str]) -> list[InstrumentRef]:
    instruments: list[InstrumentRef] = []
    for raw in values:
        parts = raw.split(":", maxsplit=1)
        if len(parts) != 2:
            raise SystemExit("instrument spec must be instrument_id:provider_symbol")
        instrument_id, provider_symbol = parts
        instruments.append(InstrumentRef(instrument_id.strip(), provider_symbol.strip()))
    return instruments


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qcengine", description="QC-Engine CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    health = subparsers.add_parser("health", help="Run adapter health check")
    health.add_argument("--provider", required=True, choices=["yfinance", "groww"], help="Adapter provider")

    backfill = subparsers.add_parser("backfill", help="Run historical candle backfill")
    backfill.add_argument("--provider", required=True, choices=["yfinance", "groww"], help="Adapter provider")
    backfill.add_argument("--instrument", action="append", required=True, help="instrument_id:provider_symbol (repeatable)")
    backfill.add_argument("--timeframe", action="append", required=True, help="Timeframe value (e.g., 1m, 5m)")
    backfill.add_argument("--start", required=True, help="ISO8601 UTC start timestamp")
    backfill.add_argument("--end", required=True, help="ISO8601 UTC end timestamp")
    backfill.add_argument("--store", type=Path, required=True, help="Parquet store root path")

    return parser


def _load_adapter(provider: str) -> MarketDataAdapter:
    if provider == "yfinance":
        return YFinanceMarketDataAdapter()
    if provider == "groww":
        raise SystemExit("Groww adapter requires an initialized client; not available via CLI yet")
    raise SystemExit(f"unknown provider: {provider}")


def main(
    argv: list[str] | None = None,
    *,
    adapter_loader: Callable[[str], MarketDataAdapter] | None = None,
    store_factory: Callable[[Path], ParquetCandleStore] | None = None,
) -> int:
    logging.basicConfig(level=logging.INFO)
    parser = _build_parser()
    args = parser.parse_args(argv)

    loader = adapter_loader or _load_adapter
    build_store = store_factory or (lambda path: ParquetCandleStore(path))

    if args.command == "health":
        adapter = loader(args.provider)
        adapter.ping()
        logger.info("adapter health ok", extra={"provider": adapter.provider_name})
        return 0

    if args.command == "backfill":
        adapter = loader(args.provider)
        instruments = _parse_instruments(args.instrument)
        timeframes = _parse_timeframes(args.timeframe)
        start = _parse_dt(args.start)
        end = _parse_dt(args.end)
        storage = build_store(Path(args.store))

        job = BackfillJob(
            adapter=adapter,
            storage=storage,
            instruments=instruments,
            timeframes=timeframes,
            start_utc=start,
            end_utc=end,
        )
        job.run()
        logger.info(
            "backfill complete",
            extra={
                "provider": adapter.provider_name,
                "instruments": [i.instrument_id for i in instruments],
                "timeframes": [tf.value for tf in timeframes],
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
        )
        return 0

    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":  # pragma: no cover - manual execution entrypoint
    raise SystemExit(main())
