from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from scripts.publish_ibit_btc_platform_handoff import (
    BINANCE_BTCUSDT_DAILY_URLS,
    _provider_name_for_url,
    build_ibit_btc_platform_handoff,
    default_as_of,
    resolve_as_of,
)
from market_signal_sources.artifacts.validation import (
    SignalBundleValidationError,
    validate_signal_bundle,
)


def _write_btc_csv(path: Path, dates: list[str]) -> None:
    frame = pd.DataFrame(
        {
            "date": dates,
            "open": [100.0] * len(dates),
            "high": [101.0] * len(dates),
            "low": [99.0] * len(dates),
            "close": [100.5] * len(dates),
            "volume": [1000.0] * len(dates),
        }
    )
    frame.to_csv(path, index=False)


def test_default_as_of_uses_yesterday_utc() -> None:
    assert default_as_of(today=date(2026, 6, 27)) == "2026-06-26"


def test_resolve_as_of_prefers_requested_date_when_present(tmp_path: Path) -> None:
    csv_path = tmp_path / "btc.csv"
    _write_btc_csv(csv_path, ["2026-06-23", "2026-06-24", "2026-06-25"])

    assert resolve_as_of(csv_path=csv_path, requested="2026-06-24", today=date(2026, 6, 27)) == (
        "2026-06-24"
    )


def test_resolve_as_of_falls_back_to_latest_csv_date(tmp_path: Path) -> None:
    csv_path = tmp_path / "btc.csv"
    _write_btc_csv(csv_path, ["2026-06-23", "2026-06-24", "2026-06-25"])

    assert resolve_as_of(csv_path=csv_path, requested=None, today=date(2026, 6, 27)) == (
        "2026-06-25"
    )


def test_resolve_as_of_raises_for_empty_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "btc.csv"
    csv_path.write_text("date,open,high,low,close,volume\n", encoding="utf-8")

    with pytest.raises(ValueError, match="no dates found"):
        resolve_as_of(csv_path=csv_path, requested="2026-06-25")


def test_provider_name_for_url() -> None:
    assert _provider_name_for_url(BINANCE_BTCUSDT_DAILY_URLS[0]) == "binance_vision_public"
    assert _provider_name_for_url(BINANCE_BTCUSDT_DAILY_URLS[1]) == "binance_us_public"
    assert _provider_name_for_url(BINANCE_BTCUSDT_DAILY_URLS[2]) == "binance_public"


def test_ibit_daily_handoff_remains_fresh_through_next_us_trading_afternoon(tmp_path: Path) -> None:
    csv_path = tmp_path / "btc.csv"
    dates = pd.date_range(end="2026-09-24", periods=800, freq="D")
    _write_btc_csv(csv_path, [day.date().isoformat() for day in dates])
    artifacts = build_ibit_btc_platform_handoff(
        work_dir=tmp_path / "output",
        input_csv=csv_path,
        as_of="2026-09-24",
        code_commit="a" * 40,
        source_version="0.1.1",
    )
    bundle = json.loads(
        (artifacts["publication_dir"] / "bundle" / "signal_bundle.json").read_text(encoding="utf-8")
    )
    assert bundle["freshness"]["provider_timestamp"] == "2026-09-24T00:00:00Z"
    assert bundle["freshness"]["max_age_hours"] == 48
    validate_signal_bundle(bundle, now="2026-09-25T19:45:00Z")
    with pytest.raises(SignalBundleValidationError, match="freshness"):
        validate_signal_bundle(bundle, now="2026-09-26T00:00:01Z")
