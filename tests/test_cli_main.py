"""Tests for qcengine CLI entrypoints."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from qcengine.cli import main as cli_main
from qcengine.domain.marketdata import Candle, Timeframe
from qcengine.storage.base import AppendResult, CandleStore


class _FakeAdapter:
    provider_name = "fake"

    def __init__(self) -> None:
        self.ping_called = False
        self.calls = 0

    def ping(self) -> None:
        self.ping_called = True

    def get_historical_candles(self, instrument, timeframe, start_utc, end_utc):  # noqa: ANN001
        self.calls += 1
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        available = base + timedelta(seconds=self.calls)
        return [
            Candle(
                instrument_id=instrument.instrument_id,
                timeframe=timeframe,
                bar_start_ts_utc=base,
                open=1.0,
                high=1.5,
                low=0.5,
                close=1.25,
                volume=10.0,
                source=self.provider_name,
                available_ts_utc=available,
            )
        ]


class _RecordingStore(CandleStore):
    def __init__(self) -> None:
        self.appended: list[list[Candle]] = []

    def append(self, candles: list[Candle]) -> AppendResult:
        self.appended.append(candles)
        return AppendResult(written=len(candles), duplicates=0)

    def read(self, instrument_id, timeframe, start=None, end=None):  # noqa: ANN001
        return []


def test_health_command_invokes_ping(caplog) -> None:
    caplog.set_level("INFO")
    adapter = _FakeAdapter()

    exit_code = cli_main.main(
        ["health", "--provider", "yfinance"], adapter_loader=lambda provider: adapter
    )

    assert exit_code == 0
    assert adapter.ping_called is True
    assert any(getattr(record, "provider", None) == "fake" for record in caplog.records)


def test_backfill_command_runs_job(tmp_path: Path) -> None:
    adapter = _FakeAdapter()
    store = _RecordingStore()

    exit_code = cli_main.main(
        [
            "backfill",
            "--provider",
            "yfinance",
            "--instrument",
            "ABC:ABC",
            "--timeframe",
            "1m",
            "--start",
            "2024-01-01T00:00:00+00:00",
            "--end",
            "2024-01-01T00:05:00+00:00",
            "--store",
            str(tmp_path),
        ],
        adapter_loader=lambda provider: adapter,
        store_factory=lambda path: store,
    )

    assert exit_code == 0
    assert adapter.calls == 1
    assert len(store.appended) == 1
    assert all(c.instrument_id == "ABC" for c in store.appended[0])
    assert all(c.timeframe is Timeframe.MIN_1 for c in store.appended[0])
