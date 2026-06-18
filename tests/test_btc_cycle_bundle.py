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
from market_signal_sources.artifacts.consumer_contracts import (
    SignalConsumerContractError,
    consumer_contract_registry_payload,
    known_signal_consumers,
    validate_consumer_contract_registry_file,
    write_consumer_contract_registry,
)
from market_signal_sources.artifacts.validation import (
    SignalBundleValidationError,
    required_indicator_fields_for_consumer,
    signal_bundle_consumer_audit_summary,
    validate_research_export_manifest,
    validate_signal_bundle,
    validate_signal_bundle_for_consumer,
    validate_signal_bundle_index_for_consumer,
    validate_signal_bundle_index,
    validate_signal_bundle_manifest_for_consumer,
    validate_signal_bundle_manifest,
)
from market_signal_sources.cli.build_btc_cycle_bundle import main as build_main
from market_signal_sources.cli.export_btc_cycle_research_csv import main as export_main
from market_signal_sources.cli.list_consumer_contracts import main as list_contracts_main
from market_signal_sources.cli.validate_research_export import main as validate_research_main
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
    consumer_summary = validate_signal_bundle_index_for_consumer(
        paths["index"],
        as_of="2025-09-18",
        consumer="research:ibit_btc_ahr999_mayer_precomputed_variants",
    )
    assert manifest_summary["bundle_id"] == "crypto.btc.derived_indicators.2025-09-17"
    assert index_summary["index_schema_version"] == "market_signal_index.v1"
    assert index_summary["indicator_field_count_by_symbol"]["BTC-USD"] == 13
    assert "ahr999" in index_summary["indicator_fields_by_symbol"]["BTC-USD"]
    assert consumer_summary["consumer"] == "research:ibit_btc_ahr999_mayer_precomputed_variants"
    assert consumer_summary["required_indicator_fields_by_symbol"] == {
        "BTC-USD": ("ahr999", "ahr999_sma", "mayer_multiple")
    }


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
            "--consumer",
            "research:ibit_btc_ahr999_mayer_precomputed_variants",
            "--pretty",
        ]
    )
    assert validate_result == 0
    audit_summary = json.loads(capsys.readouterr().out)
    assert audit_summary["bundle_id"] == "crypto.btc.derived_indicators.2025-09-17"
    assert audit_summary["indicator_field_count_by_symbol"] == {"BTC-USD": 13}
    assert audit_summary["required_indicator_fields_by_symbol"] == {
        "BTC-USD": ["ahr999", "ahr999_sma", "mayer_multiple"]
    }


def test_signal_bundle_consumer_contract_rejects_missing_required_field(tmp_path) -> None:
    bundle = build_btc_cycle_signal_bundle(
        _btc_frame(),
        as_of="2025-09-17",
        raw_artifact_sha256="0" * 64,
        generated_at="2025-09-17T00:15:00Z",
    )
    del bundle["derived_indicators"]["BTC-USD"]["ahr999_sma"]

    with pytest.raises(SignalBundleValidationError, match="ahr999_sma"):
        validate_signal_bundle_for_consumer(
            bundle,
            consumer="research:ibit_btc_ahr999_mayer_precomputed_variants",
        )


def test_signal_bundle_consumer_contract_can_validate_manifest_and_bundle(tmp_path) -> None:
    bundle = build_btc_cycle_signal_bundle(
        _btc_frame(),
        as_of="2025-09-17",
        raw_artifact_sha256="0" * 64,
        generated_at="2025-09-17T00:15:00Z",
    )
    paths = write_signal_bundle_artifacts(tmp_path, bundle)

    validate_signal_bundle_for_consumer(
        bundle,
        consumer="research:ibit_btc_ahr999_mayer_precomputed_variants",
    )
    manifest_summary = validate_signal_bundle_manifest_for_consumer(
        paths["manifest"],
        consumer="research:ibit_btc_ahr999_mayer_precomputed_variants",
    )
    direct_summary = signal_bundle_consumer_audit_summary(
        bundle,
        consumer="research:ibit_btc_ahr999_mayer_precomputed_variants",
    )

    assert required_indicator_fields_for_consumer(
        "research:ibit_btc_ahr999_mayer_precomputed_variants"
    ) == {"BTC-USD": ("ahr999", "ahr999_sma", "mayer_multiple")}
    assert manifest_summary["bundle_sha256"] == _sha256(paths["signal_bundle"])
    assert direct_summary["consumer"] == "research:ibit_btc_ahr999_mayer_precomputed_variants"


def test_consumer_contract_registry_exports_json_safe_payload(capsys) -> None:
    payload = consumer_contract_registry_payload(
        consumers=("research:ibit_btc_ahr999_mayer_precomputed_variants",)
    )

    assert known_signal_consumers() == (
        "research:ibit_btc_ahr999_mayer_precomputed",
        "research:ibit_btc_ahr999_mayer_precomputed_variants",
        "us_equity:ibit_smart_dca",
    )
    assert payload == {
        "schema_version": "market_signal_consumer_contracts.v1",
        "canonical_input": "derived_indicators",
        "contracts": [
            {
                "consumer": "research:ibit_btc_ahr999_mayer_precomputed_variants",
                "canonical_input": "derived_indicators",
                "required_indicator_fields_by_symbol": {
                    "BTC-USD": ["ahr999", "ahr999_sma", "mayer_multiple"],
                },
            }
        ],
    }

    result = list_contracts_main(
        [
            "--consumer",
            "us_equity:ibit_smart_dca",
            "--pretty",
        ]
    )
    assert result == 0
    cli_payload = json.loads(capsys.readouterr().out)
    assert cli_payload["schema_version"] == "market_signal_consumer_contracts.v1"
    assert cli_payload["contracts"] == [
        {
            "consumer": "us_equity:ibit_smart_dca",
            "canonical_input": "derived_indicators",
            "required_indicator_fields_by_symbol": {
                "BTC-USD": ["ahr999", "mayer_multiple"],
            },
        }
    ]


def test_consumer_contract_registry_can_be_written_as_artifact(tmp_path, capsys) -> None:
    output_json = tmp_path / "contracts" / "market_signal_consumers.json"

    summary = write_consumer_contract_registry(
        output_json,
        consumers=("us_equity:ibit_smart_dca",),
    )
    payload = json.loads(output_json.read_text(encoding="utf-8"))

    assert summary["path"] == str(output_json)
    assert summary["schema_version"] == "market_signal_consumer_contracts.v1"
    assert summary["consumer_count"] == 1
    assert summary["sha256"] == _sha256(output_json)
    assert summary["size_bytes"] == output_json.stat().st_size
    assert payload["contracts"][0]["consumer"] == "us_equity:ibit_smart_dca"

    result = list_contracts_main(
        [
            "--consumer",
            "research:ibit_btc_ahr999_mayer_precomputed_variants",
            "--output-json",
            str(output_json),
            "--pretty",
        ]
    )

    assert result == 0
    cli_summary = json.loads(capsys.readouterr().out)
    cli_payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert cli_summary["sha256"] == _sha256(output_json)
    assert cli_payload["contracts"][0]["consumer"] == (
        "research:ibit_btc_ahr999_mayer_precomputed_variants"
    )

    validate_summary = validate_consumer_contract_registry_file(output_json)
    assert validate_summary["sha256"] == _sha256(output_json)
    assert validate_summary["consumers"] == [
        "research:ibit_btc_ahr999_mayer_precomputed_variants"
    ]

    validate_result = list_contracts_main(
        [
            "--validate-json",
            str(output_json),
            "--pretty",
        ]
    )
    assert validate_result == 0
    cli_validate_summary = json.loads(capsys.readouterr().out)
    assert cli_validate_summary["sha256"] == _sha256(output_json)
    assert cli_validate_summary["consumer_count"] == 1


def test_consumer_contract_registry_validation_rejects_drift(tmp_path) -> None:
    output_json = tmp_path / "contracts.json"
    write_consumer_contract_registry(
        output_json,
        consumers=("us_equity:ibit_smart_dca",),
    )
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    payload["contracts"][0]["required_indicator_fields_by_symbol"]["BTC-USD"].append(
        "unexpected_metric"
    )
    output_json.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SignalConsumerContractError, match="drift"):
        validate_consumer_contract_registry_file(output_json)


def test_cli_exports_btc_cycle_research_csv(tmp_path, capsys) -> None:
    input_csv = tmp_path / "btc.csv"
    output_csv = tmp_path / "research" / "btc_cycle.csv"
    manifest_path = tmp_path / "research" / "btc_cycle.manifest.json"
    _btc_frame(205).to_csv(input_csv, index=False)

    result = export_main(
        [
            "--input-csv",
            str(input_csv),
            "--output-csv",
            str(output_csv),
            "--manifest-path",
            str(manifest_path),
            "--as-of",
            "2025-07-23",
            "--pretty",
        ]
    )

    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    exported = pd.read_csv(output_csv)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert summary["row_count"] == 5
    assert summary["last_date"] == "2025-07-23"
    assert summary["manifest"] == str(manifest_path)
    assert summary["output_sha256"] == _sha256(output_csv)
    assert manifest["schema_version"] == "research_export.v1"
    assert manifest["artifact_type"] == "btc_cycle_research_csv"
    assert manifest["transform"] == "crypto.btc.ahr999.v1"
    assert manifest["input_csv"]["sha256"] == _sha256(input_csv)
    assert manifest["output_csv"]["sha256"] == _sha256(output_csv)
    assert manifest["min_history"] == 200
    assert "ahr999" in summary["columns"]
    assert "mayer_multiple" in exported.columns

    validation_summary = validate_research_export_manifest(
        manifest_path,
        expected_artifact_type="btc_cycle_research_csv",
        expected_transform="crypto.btc.ahr999.v1",
    )
    assert validation_summary["row_count"] == 5
    assert validation_summary["output_csv_sha256"] == _sha256(output_csv)

    validate_result = validate_research_main(
        [
            str(manifest_path),
            "--expected-transform",
            "crypto.btc.ahr999.v1",
            "--pretty",
        ]
    )
    assert validate_result == 0
    cli_summary = json.loads(capsys.readouterr().out)
    assert cli_summary["artifact_type"] == "btc_cycle_research_csv"
    assert cli_summary["columns"][-1] == "cycle_indicator_source"


def test_research_export_validator_rejects_checksum_mismatch(tmp_path) -> None:
    input_csv = tmp_path / "btc.csv"
    output_csv = tmp_path / "research" / "btc_cycle.csv"
    manifest_path = tmp_path / "research" / "btc_cycle.manifest.json"
    _btc_frame(205).to_csv(input_csv, index=False)
    assert export_main(
        [
            "--input-csv",
            str(input_csv),
            "--output-csv",
            str(output_csv),
            "--manifest-path",
            str(manifest_path),
            "--as-of",
            "2025-07-23",
        ]
    ) == 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["output_csv"]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(SignalBundleValidationError, match="output_csv.sha256 mismatch"):
        validate_research_export_manifest(manifest_path)


def test_research_export_validator_rejects_sensitive_fields(tmp_path) -> None:
    input_csv = tmp_path / "btc.csv"
    output_csv = tmp_path / "research" / "btc_cycle.csv"
    manifest_path = tmp_path / "research" / "btc_cycle.manifest.json"
    _btc_frame(205).to_csv(input_csv, index=False)
    assert export_main(
        [
            "--input-csv",
            str(input_csv),
            "--output-csv",
            str(output_csv),
            "--manifest-path",
            str(manifest_path),
            "--as-of",
            "2025-07-23",
        ]
    ) == 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["provenance"] = {"signed_url": "https://example.invalid/private.csv"}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(SignalBundleValidationError, match="sensitive field"):
        validate_research_export_manifest(manifest_path)


def test_research_export_validator_resolves_cwd_relative_paths(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    input_csv = Path("btc.csv")
    output_csv = Path("research") / "btc_cycle.csv"
    manifest_path = Path("research") / "btc_cycle.manifest.json"
    _btc_frame(205).to_csv(input_csv, index=False)
    assert export_main(
        [
            "--input-csv",
            str(input_csv),
            "--output-csv",
            str(output_csv),
            "--manifest-path",
            str(manifest_path),
            "--as-of",
            "2025-07-23",
        ]
    ) == 0

    validation_summary = validate_research_export_manifest(manifest_path)

    assert validation_summary["input_csv_path"] == str(input_csv.resolve())
    assert validation_summary["output_csv_path"] == str(output_csv.resolve())


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
