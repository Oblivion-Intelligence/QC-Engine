"""Ensure backfill operations are idempotent and deduplicate via storage."""

from datetime import datetime, timedelta, timezone

from qcengine.adapters.base import InstrumentRef
from qcengine.domain.marketdata import Candle, Timeframe
from qcengine.ingestion.backfill import BackfillJob
from qcengine.storage.parquet_store import ParquetCandleStore


class _DeterministicAdapter:
    provider_name = "deterministic"

    def __init__(self) -> None:
        self.calls = 0

    def ping(self) -> None:  # pragma: no cover - not used here
        return None

    def get_historical_candles(self, instrument, timeframe, start_utc, end_utc):  # noqa: ANN001
        self.calls += 1
        available = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=self.calls)
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        return [
            Candle(
                instrument_id=instrument.instrument_id,
                timeframe=timeframe,
                bar_start_ts_utc=base,
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=1_000.0,
                source=self.provider_name,
                available_ts_utc=available,
            ),
            Candle(
                instrument_id=instrument.instrument_id,
                timeframe=timeframe,
                bar_start_ts_utc=base + timedelta(minutes=timeframe.to_minutes()),
                open=101.0,
                high=102.0,
                low=100.0,
                close=101.5,
                volume=1_500.0,
                source=self.provider_name,
                available_ts_utc=available,
            ),
        ]


def test_backfill_deduplicates_across_runs(tmp_path) -> None:
    adapter = _DeterministicAdapter()
    store = ParquetCandleStore(tmp_path)
    job = BackfillJob(
        adapter=adapter,
        storage=store,
        instruments=[InstrumentRef("ABC", "ABC")],
        timeframes=[Timeframe.MIN_1],
        start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_utc=datetime(2024, 1, 1, 0, 2, tzinfo=timezone.utc),
    )

    job.run()
    job.run()

    candles = store.read("ABC", Timeframe.MIN_1)
    assert len(candles) == 2
    assert adapter.calls == 2
