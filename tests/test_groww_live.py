"""Live Groww adapter checks using the bundled API credentials."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from qcengine.adapters.base import AuthError, InstrumentRef, InvalidResponse, RateLimited, Unavailable
from qcengine.adapters.groww import GrowwClient, GrowwClientConfig, GrowwMarketDataAdapter
from qcengine.domain.marketdata import Timeframe


def _load_credentials() -> tuple[str, str] | None:
    path = Path("src/qcengine/adapters/groww/api_key.md")
    if not path.exists():
        return None

    creds: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        creds[key.strip().lower()] = value.strip().strip('"')

    api_key = creds.get("api key") or creds.get("api_key")
    api_secret = creds.get("api secret") or creds.get("api_secret")
    if not api_key or not api_secret:
        return None
    return api_key, api_secret


def test_groww_live_ping_and_maybe_ingest() -> None:
    creds = _load_credentials()
    if not creds:
        pytest.skip("Groww API credentials not available")

    api_key, api_secret = creds
    client = GrowwClient(GrowwClientConfig(api_key=api_key, api_secret=api_secret))
    adapter = GrowwMarketDataAdapter(client)

    adapter.ping()

    instrument = InstrumentRef("NSE-INFY", "NSE-INFY", exchange="NSE", segment="CASH")
    start = datetime.now(timezone.utc) - timedelta(hours=1)
    end = datetime.now(timezone.utc)

    try:
        candles = adapter.get_historical_candles(instrument, Timeframe.MIN_5, start, end)
    except (AuthError, InvalidResponse, Unavailable, RateLimited) as exc:
        pytest.skip(f"Groww historical fetch unavailable: {exc}")

    assert candles, "expected live Groww API to return candles"
    assert candles[0].bar_start_ts_utc <= candles[-1].bar_start_ts_utc
