"""Parquet-based candle storage implementation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

from qcengine.domain.marketdata import Candle, Timeframe, assert_aligned_to_grid, ensure_utc
from qcengine.storage.base import AppendResult, CandleStore

logger = logging.getLogger(__name__)


@dataclass
class ParquetCandleStore(CandleStore):
    """Persist candles to partitioned Parquet files with deduplication."""

    root_path: Path

    def __post_init__(self) -> None:
        self.root_path = Path(self.root_path)
        self.root_path.mkdir(parents=True, exist_ok=True)

    def append(self, candles: list[Candle]) -> AppendResult:
        if not candles:
            logger.info("parquet store append called with no candles")
            return AppendResult(written=0, duplicates=0)

        for candle in candles:
            assert_aligned_to_grid(candle.bar_start_ts_utc, candle.timeframe)

        written_total = 0
        duplicates_total = 0

        for (instrument_id, timeframe), bucket in self._group_by_partition(candles):
            path = self._partition_path(instrument_id, timeframe)
            existing_df = self._read_parquet(path)
            new_df = self._candles_to_frame(bucket)

            combined_df = (
                pd.concat([existing_df, new_df]) if existing_df is not None else new_df
            ).reset_index(drop=True)

            combined_df["_arrival_order"] = combined_df.index
            combined_df["_has_volume"] = combined_df["volume"].notna()
            combined_df["_has_ohlc"] = combined_df[["open", "high", "low", "close"]].notna().all(axis=1)

            combined_df = combined_df.sort_values(
                [
                    "bar_start_ts_utc",
                    "available_ts_utc",
                    "_has_volume",
                    "_has_ohlc",
                    "_arrival_order",
                ],
                ascending=[True, False, False, False, True],
                kind="mergesort",
            )

            combined_count = len(combined_df)
            deduped_df = combined_df.drop_duplicates(
                subset=["instrument_id", "timeframe", "bar_start_ts_utc"], keep="first"
            )

            deduped_df = deduped_df.sort_values("bar_start_ts_utc").drop(
                columns=["_arrival_order", "_has_volume", "_has_ohlc"]
            )

            duplicates = combined_count - len(deduped_df)
            written = len(deduped_df) - (0 if existing_df is None else len(existing_df))

            self._write_parquet(path, deduped_df)

            written_total += written
            duplicates_total += duplicates

            logger.info(
                "parquet store append",
                extra={
                    "instrument_id": instrument_id,
                    "timeframe": timeframe.value,
                    "appended": len(bucket),
                    "written": written,
                    "duplicates": duplicates,
                    "total_after": len(deduped_df),
                    "path": str(path),
                },
            )

        return AppendResult(written=written_total, duplicates=duplicates_total)

    def read(
        self,
        instrument_id: str,
        timeframe: Timeframe,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Candle]:
        path = self._partition_path(instrument_id, timeframe)
        frame = self._read_parquet(path)
        if frame is None:
            return []

        if start:
            frame = frame[frame["bar_start_ts_utc"] >= pd.Timestamp(ensure_utc(start))]
        if end:
            frame = frame[frame["bar_start_ts_utc"] < pd.Timestamp(ensure_utc(end))]

        frame = frame.sort_values("bar_start_ts_utc")

        candles: list[Candle] = []
        for row in frame.itertuples(index=False):
            candles.append(
                Candle(
                    instrument_id=row.instrument_id,
                    timeframe=Timeframe(row.timeframe),
                    bar_start_ts_utc=row.bar_start_ts_utc.to_pydatetime(),
                    open=float(row.open),
                    high=float(row.high),
                    low=float(row.low),
                    close=float(row.close),
                    volume=None if pd.isna(row.volume) else float(row.volume),
                    source=row.source,
                    available_ts_utc=row.available_ts_utc.to_pydatetime(),
                )
            )

        return candles

    def _group_by_partition(
        self, candles: Iterable[Candle]
    ) -> Iterable[tuple[tuple[str, Timeframe], list[Candle]]]:
        buckets: dict[tuple[str, Timeframe], list[Candle]] = {}
        for candle in candles:
            key = (candle.instrument_id, candle.timeframe)
            buckets.setdefault(key, []).append(candle)
        for key, items in buckets.items():
            yield key, items

    def _partition_path(self, instrument_id: str, timeframe: Timeframe) -> Path:
        return (
            self.root_path
            / f"instrument_id={instrument_id}"
            / f"timeframe={timeframe.value}"
            / "candles.parquet"
        )

    def _candles_to_frame(self, candles: list[Candle]) -> pd.DataFrame:
        records = [
            {
                "instrument_id": c.instrument_id,
                "timeframe": c.timeframe.value,
                "bar_start_ts_utc": pd.Timestamp(c.bar_start_ts_utc),
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
                "source": c.source,
                "available_ts_utc": pd.Timestamp(c.available_ts_utc),
            }
            for c in candles
        ]
        return pd.DataFrame.from_records(records)

    def _read_parquet(self, path: Path) -> pd.DataFrame | None:
        if not path.exists():
            return None
        frame = pd.read_parquet(path)
        frame["bar_start_ts_utc"] = pd.to_datetime(frame["bar_start_ts_utc"], utc=True)
        frame["available_ts_utc"] = pd.to_datetime(frame["available_ts_utc"], utc=True)
        return frame

    def _write_parquet(self, path: Path, frame: pd.DataFrame) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
