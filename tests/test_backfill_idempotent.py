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


class _InclusiveEndAdapter:
    provider_name = "inclusive-end"

    def __init__(self, candles: list[Candle]):
        self.candles = candles
        self.calls = 0

    def ping(self) -> None:  # pragma: no cover - not used here
        return None

    def get_historical_candles(self, instrument, timeframe, start_utc, end_utc):  # noqa: ANN001
        self.calls += 1
        start = start_utc.replace(tzinfo=timezone.utc)
        end = end_utc.replace(tzinfo=timezone.utc)
        return [c for c in self.candles if start <= c.bar_start_ts_utc <= end]


class _NoisyBoundaryAdapter:
    provider_name = "noisy-boundaries"

    def __init__(self, candles: list[Candle]):
        self.candles = candles

    def ping(self) -> None:  # pragma: no cover - not used here
        return None

    def get_historical_candles(self, instrument, timeframe, start_utc, end_utc):  # noqa: ANN001
        return list(self.candles)


class _StitchableDeterministicAdapter:
    """Adapter that returns inclusive ranges, duplicates, and an extra candle."""

    provider_name = "stitchable-inclusive"

    def __init__(self, base_start: datetime):
        self.base_start = base_start.replace(tzinfo=timezone.utc)
        self.calls = 0

    def ping(self) -> None:  # pragma: no cover - not used here
        return None

    def _candle(self, minute_offset: int, available_offset_seconds: int) -> Candle:
        ts = self.base_start + timedelta(minutes=minute_offset)
        available = self.base_start + timedelta(seconds=available_offset_seconds)
        return Candle(
            instrument_id="ABC",
            timeframe=Timeframe.MIN_1,
            bar_start_ts_utc=ts,
            open=100.0 + minute_offset,
            high=101.0 + minute_offset,
            low=99.0 + minute_offset,
            close=100.5 + minute_offset,
            volume=1_000.0 + minute_offset,
            source=self.provider_name,
            available_ts_utc=available,
        )

    def get_historical_candles(self, instrument, timeframe, start_utc, end_utc):  # noqa: ANN001
        self.calls += 1
        start = start_utc.replace(tzinfo=timezone.utc)
        end = end_utc.replace(tzinfo=timezone.utc)

        base_candles = [
            self._candle(0, 0),
            self._candle(0, 2),
            self._candle(1, 1),
            self._candle(2, 0),
            self._candle(2, 3),
            self._candle(3, 1),
        ]

        inclusive = [c for c in base_candles if start <= c.bar_start_ts_utc <= end]
        extra_offset = int((end - self.base_start).total_seconds() // 60) + 1
        extra_candle = self._candle(extra_offset, 5)

        result = inclusive + [extra_candle]

        for prev, curr in zip(result, result[1:]):
            assert prev.bar_start_ts_utc <= curr.bar_start_ts_utc

        return result


def test_half_open_backfill_windows_are_stitchable(tmp_path) -> None:
    instrument = InstrumentRef("ABC", "ABC")
    timeframe = Timeframe.MIN_1
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(minutes=3)
    mid = start + timedelta(minutes=1)

    candles = [
        Candle(
            instrument_id=instrument.instrument_id,
            timeframe=timeframe,
            bar_start_ts_utc=start + timedelta(minutes=i),
            open=100 + i,
            high=101 + i,
            low=99 + i,
            close=100 + i,
            volume=1_000 + i,
            source="test",
            available_ts_utc=start,
        )
        for i in range(4)
    ]

    adapter_full = _InclusiveEndAdapter(candles)
    store_full = ParquetCandleStore(tmp_path / "full")
    BackfillJob(
        adapter=adapter_full,
        storage=store_full,
        instruments=[instrument],
        timeframes=[timeframe],
        start_utc=start,
        end_utc=end,
    ).run()

    full_result = store_full.read(instrument.instrument_id, timeframe)

    adapter_split = _InclusiveEndAdapter(candles)
    store_split = ParquetCandleStore(tmp_path / "split")
    BackfillJob(
        adapter=adapter_split,
        storage=store_split,
        instruments=[instrument],
        timeframes=[timeframe],
        start_utc=start,
        end_utc=mid,
    ).run()
    BackfillJob(
        adapter=adapter_split,
        storage=store_split,
        instruments=[instrument],
        timeframes=[timeframe],
        start_utc=mid,
        end_utc=end,
    ).run()

    split_result = store_split.read(instrument.instrument_id, timeframe)

    assert [c.bar_start_ts_utc for c in full_result] == [
        c.bar_start_ts_utc for c in split_result
    ]
    assert len(full_result) == 3
    assert adapter_full.calls == 1
    assert adapter_split.calls == 2


def test_backfill_clamps_provider_noise(tmp_path) -> None:
    instrument = InstrumentRef("ABC", "ABC")
    timeframe = Timeframe.MIN_1
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(minutes=3)

    candles = [
        Candle(
            instrument_id=instrument.instrument_id,
            timeframe=timeframe,
            bar_start_ts_utc=start + timedelta(minutes=offset),
            open=100 + offset,
            high=101 + offset,
            low=99 + offset,
            close=100 + offset,
            volume=1_000 + offset,
            source="test",
            available_ts_utc=start,
        )
        for offset in (-1, 0, 1, 2, 3, 4)
    ]

    adapter = _NoisyBoundaryAdapter(candles)
    store = ParquetCandleStore(tmp_path / "clamped")

    BackfillJob(
        adapter=adapter,
        storage=store,
        instruments=[instrument],
        timeframes=[timeframe],
        start_utc=start,
        end_utc=end,
    ).run()

    stored = store.read(instrument.instrument_id, timeframe)

    assert [c.bar_start_ts_utc for c in stored] == [
        start + timedelta(minutes=i) for i in (0, 1, 2)
    ]


def test_backfill_is_stitchable_and_idempotent(tmp_path) -> None:
    instrument = InstrumentRef("ABC", "ABC")
    timeframe = Timeframe.MIN_1
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    boundary = start + timedelta(minutes=2)
    end = start + timedelta(minutes=4)

    adapter_single = _StitchableDeterministicAdapter(start)
    store_single = ParquetCandleStore(tmp_path / "single")

    BackfillJob(
        adapter=adapter_single,
        storage=store_single,
        instruments=[instrument],
        timeframes=[timeframe],
        start_utc=start,
        end_utc=end,
    ).run()

    single_run_candles = store_single.read(instrument.instrument_id, timeframe)

    adapter_split = _StitchableDeterministicAdapter(start)
    store_split = ParquetCandleStore(tmp_path / "split")

    BackfillJob(
        adapter=adapter_split,
        storage=store_split,
        instruments=[instrument],
        timeframes=[timeframe],
        start_utc=start,
        end_utc=boundary,
    ).run()
    BackfillJob(
        adapter=adapter_split,
        storage=store_split,
        instruments=[instrument],
        timeframes=[timeframe],
        start_utc=boundary,
        end_utc=end,
    ).run()

    split_run_candles = store_split.read(instrument.instrument_id, timeframe)

    assert single_run_candles == split_run_candles
    assert len(single_run_candles) == 4

    bar_starts = [c.bar_start_ts_utc for c in single_run_candles]
    assert len(set(bar_starts)) == len(bar_starts)
    assert all(bar_starts[i] < bar_starts[i + 1] for i in range(len(bar_starts) - 1))
    assert all(c.bar_start_ts_utc.minute % timeframe.to_minutes() == 0 for c in single_run_candles)
