from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pandas as pd
import pytest

from market_signal_sources.artifacts.signal_bundle import (
    build_btc_cycle_signal_bundle,
    write_signal_bundle_artifacts,
)
from market_signal_sources.artifacts.validation import (
    SignalBundleValidationError,
    validate_signal_bundle,
    validate_signal_bundle_index,
    validate_signal_bundle_manifest,
)
from market_signal_sources.cli.build_btc_cycle_bundle import main as build_main
from market_signal_sources.cli.export_btc_cycle_research_csv import main as export_main
from market_signal_sources.cli.validate_signal_bundle import main as validate_main
from market_signal_sources.derived.crypto.btc_cycle import (
    build_btc_cycle_indicator_frame,
    compute_btc_cycle_indicators,
)


def _btc_frame(rows: int = 260) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=rows, freq="D")
    return pd.DataFrame(
        {
            "date": dates.date,
            "open": [250_000.0 for _ in dates],
            "high": [250_000.0 for _ in dates],
            "low": [250_000.0 for _ in dates],
            "close": [250_000.0 for _ in dates],
            "volume": [10.0 for _ in dates],
        }
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_compute_btc_cycle_indicators_from_local_prices() -> None:
    indicators = compute_btc_cycle_indicators(_btc_frame(), as_of="2025-09-17")

    assert indicators["close"] == 250_000.0
    assert indicators["sma200"] == 250_000.0
    assert math.isclose(float(indicators["gma200"]), 250_000.0, rel_tol=1e-12)
    assert indicators["high252"] == 250_000.0
    assert indicators["drawdown_252d"] == 0.0
    assert indicators["sma200_gap"] == 0.0
    assert indicators["rsi14"] == 50.0
    assert indicators["mayer_multiple"] == 1.0
    assert indicators["cycle_indicator_source"] == "price_derived"
    assert math.isclose(
        float(indicators["ahr999"]),
        250_000.0 / float(indicators["ahr999_estimate_price"]),
        rel_tol=1e-12,
    )


def test_build_btc_cycle_indicator_frame_exports_daily_research_rows() -> None:
    frame = build_btc_cycle_indicator_frame(_btc_frame(205), as_of="2025-07-23")

    assert list(frame.columns) == [
        "date",
        "close",
        "sma200",
        "gma200",
        "high252",
        "drawdown_252d",
        "sma200_gap",
        "rsi14",
        "mayer_multiple",
        "ahr999",
        "ahr999_sma",
        "ahr999_estimate_price",
        "cycle_indicator_source",
    ]
    assert len(frame) == 5
    assert frame.iloc[0]["date"] == "2025-07-19"
    assert frame.iloc[-1]["date"] == "2025-07-23"
    assert frame.iloc[-1]["mayer_multiple"] == 1.0


def test_write_signal_bundle_artifacts_with_manifest_and_index(tmp_path) -> None:
    bundle = build_btc_cycle_signal_bundle(
        _btc_frame(),
        as_of="2025-09-17",
        raw_artifact_sha256="0" * 64,
        generated_at="2025-09-17T00:15:00Z",
    )

    paths = write_signal_bundle_artifacts(tmp_path, bundle)

    signal_bundle = json.loads(paths["signal_bundle"].read_text(encoding="utf-8"))
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    index = json.loads(paths["index"].read_text(encoding="utf-8"))
    payload = signal_bundle["derived_indicators"]["BTC-USD"]

    assert signal_bundle["schema_version"] == "market_signal_bundle.v1"
    assert signal_bundle["bundle_id"] == "crypto.btc.derived_indicators.2025-09-17"
    assert payload["provider_timestamp"] == "2025-09-17T00:00:00Z"
    assert manifest["schema_version"] == "market_signal_manifest.v1"
    assert manifest["bundle_sha256"] == _sha256(paths["signal_bundle"])
    assert index["schema_version"] == "market_signal_index.v1"
    assert index["bundles"][0]["manifest_sha256"] == _sha256(paths["manifest"])

    manifest_summary = validate_signal_bundle_manifest(paths["manifest"])
    index_summary = validate_signal_bundle_index(paths["index"], as_of="2025-09-18")
    assert manifest_summary["bundle_id"] == "crypto.btc.derived_indicators.2025-09-17"
    assert index_summary["index_schema_version"] == "market_signal_index.v1"
    assert index_summary["indicator_field_count_by_symbol"]["BTC-USD"] == 13
    assert "ahr999" in index_summary["indicator_fields_by_symbol"]["BTC-USD"]


def test_cli_builds_btc_cycle_bundle_from_csv(tmp_path, capsys) -> None:
    input_csv = tmp_path / "btc.csv"
    output_dir = tmp_path / "out"
    _btc_frame().to_csv(input_csv, index=False)

    result = build_main(
        [
            "--input-csv",
            str(input_csv),
            "--output-dir",
            str(output_dir),
            "--as-of",
            "2025-09-17",
            "--generated-at",
            "2025-09-17T00:15:00Z",
            "--pretty",
        ]
    )

    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["bundle_id"] == "crypto.btc.derived_indicators.2025-09-17"
    assert (output_dir / "signal_bundle.json").exists()
    assert (output_dir / "manifest.json").exists()
    assert (output_dir / "index.json").exists()
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["bundle_sha256"] == _sha256(output_dir / "signal_bundle.json")

    validate_result = validate_main(
        [
            "--index",
            str(output_dir / "index.json"),
            "--as-of",
            "2025-09-18",
            "--pretty",
        ]
    )
    assert validate_result == 0
    audit_summary = json.loads(capsys.readouterr().out)
    assert audit_summary["bundle_id"] == "crypto.btc.derived_indicators.2025-09-17"
    assert audit_summary["indicator_field_count_by_symbol"] == {"BTC-USD": 13}


def test_cli_exports_btc_cycle_research_csv(tmp_path, capsys) -> None:
    input_csv = tmp_path / "btc.csv"
    output_csv = tmp_path / "research" / "btc_cycle.csv"
    _btc_frame(205).to_csv(input_csv, index=False)

    result = export_main(
        [
            "--input-csv",
            str(input_csv),
            "--output-csv",
            str(output_csv),
            "--as-of",
            "2025-07-23",
            "--pretty",
        ]
    )

    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    exported = pd.read_csv(output_csv)
    assert summary["row_count"] == 5
    assert summary["last_date"] == "2025-07-23"
    assert "ahr999" in summary["columns"]
    assert "mayer_multiple" in exported.columns


def test_validator_rejects_sensitive_fields() -> None:
    bundle = build_btc_cycle_signal_bundle(
        _btc_frame(),
        as_of="2025-09-17",
        raw_artifact_sha256="0" * 64,
        generated_at="2025-09-17T00:15:00Z",
    )
    bundle["provenance"]["signed_url"] = "https://example.invalid/private?token=abc"

    with pytest.raises(SignalBundleValidationError, match="sensitive field"):
        validate_signal_bundle(bundle)


def test_validator_rejects_manifest_path_escape(tmp_path) -> None:
    bundle = build_btc_cycle_signal_bundle(
        _btc_frame(),
        as_of="2025-09-17",
        raw_artifact_sha256="0" * 64,
        generated_at="2025-09-17T00:15:00Z",
    )
    paths = write_signal_bundle_artifacts(tmp_path, bundle)
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    manifest["bundle_path"] = "../signal_bundle.json"
    paths["manifest"].write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(SignalBundleValidationError, match="escapes artifact directory"):
        validate_signal_bundle_manifest(paths["manifest"])


def test_validator_rejects_index_manifest_checksum_mismatch(tmp_path) -> None:
    bundle = build_btc_cycle_signal_bundle(
        _btc_frame(),
        as_of="2025-09-17",
        raw_artifact_sha256="0" * 64,
        generated_at="2025-09-17T00:15:00Z",
    )
    paths = write_signal_bundle_artifacts(tmp_path, bundle)
    index = json.loads(paths["index"].read_text(encoding="utf-8"))
    index["bundles"][0]["manifest_sha256"] = "0" * 64
    paths["index"].write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(SignalBundleValidationError, match="manifest_sha256 mismatch"):
        validate_signal_bundle_index(paths["index"])
