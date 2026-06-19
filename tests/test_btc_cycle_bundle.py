from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pandas as pd
import pytest

from market_signal_sources.artifacts.signal_bundle import (
    build_btc_cycle_signal_bundle,
    build_derived_indicator_signal_bundle,
    upsert_signal_bundle_publication_index,
    write_signal_bundle_artifacts,
    write_signal_bundle_publication_index,
)
from market_signal_sources.artifacts.source_catalog import (
    SIGNAL_SOURCE_FAMILIES,
    compatible_profiles_for_signal_source_family,
    implemented_signal_source_families_for_domain,
    known_signal_source_families,
    runtime_consumers_for_signal_source_family,
    signal_source_domain_coverage_payload,
    signal_source_family_consumer_contract_coverage,
    signal_source_family_catalog_payload,
    signal_source_family_record,
    signal_source_runtime_consumer_coverage,
    source_profiles_for_signal_source_family,
    validate_signal_source_family_catalog,
    validate_signal_source_family_catalog_file,
    validate_signal_source_family_catalog_manifest,
    write_signal_source_family_catalog,
    write_signal_source_family_catalog_artifacts,
)
from market_signal_sources.artifacts.quality_report import (
    QualityReportValidationError,
    build_ohlcv_quality_report,
    validate_ohlcv_quality_report_file,
    write_ohlcv_quality_report,
)
from market_signal_sources.artifacts.consumer_contracts import (
    SignalConsumerContractError,
    consumer_contract_registry_payload,
    known_signal_consumers,
    validate_consumer_contract_registry_file,
    validate_consumer_contract_registry_manifest,
    write_consumer_contract_registry,
    write_consumer_contract_registry_artifacts,
)
from market_signal_sources.artifacts.consumption import (
    audit_signal_consumption,
    runtime_signal_injection_plan,
    validate_consumption_audit_file,
    validate_runtime_adapter_config,
    validate_runtime_adapter_config_set_files,
    validate_runtime_adapter_deployment_config_file,
    validate_runtime_adapter_deployment_config_set_files,
    validate_runtime_signal_injection_plan_file,
    validate_runtime_signal_injection_plan_matches_audit,
    write_consumption_audit_artifact,
    write_runtime_signal_injection_plan_artifact,
)
from market_signal_sources.artifacts.platform_handoff import (
    resolve_platform_signal_handoff_manifest_from_index,
    upsert_platform_signal_handoff_index,
    validate_platform_signal_handoff_index,
    validate_platform_signal_handoff_manifest,
    write_platform_signal_handoff_index,
    write_platform_signal_handoff_manifest,
)
from market_signal_sources.artifacts.research_handoff import (
    validate_research_signal_handoff_manifest,
    write_research_signal_handoff_manifest,
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
from market_signal_sources.cli.build_platform_handoff import main as handoff_main
from market_signal_sources.cli.build_research_handoff import (
    main as research_handoff_main,
)
from market_signal_sources.cli.audit_signal_consumption import (
    main as audit_consumption_main,
)
from market_signal_sources.cli.export_btc_cycle_research_csv import main as export_main
from market_signal_sources.cli.export_us_equity_context_research_csv import (
    main as export_us_equity_context_main,
)
from market_signal_sources.cli.export_us_equity_price_proxy_research_csv import (
    main as export_us_equity_price_proxy_main,
)
from market_signal_sources.cli.export_us_equity_public_context_research_csv import (
    main as export_us_equity_public_context_main,
)
from market_signal_sources.cli.list_consumer_contracts import main as list_contracts_main
from market_signal_sources.cli.list_signal_source_families import (
    main as list_families_main,
)
from market_signal_sources.cli.validate_quality_report import main as validate_quality_main
from market_signal_sources.cli.validate_research_export import main as validate_research_main
from market_signal_sources.cli.validate_signal_bundle import main as validate_main
from market_signal_sources.derived.crypto.btc_cycle import (
    build_btc_cycle_indicator_frame,
    compute_btc_cycle_indicators,
)
from market_signal_sources.providers import local_csv_provider_metadata


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


def _signal_bundle_index_entry(root: Path, manifest_path: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "manifest_path": manifest_path.relative_to(root).as_posix(),
        "manifest_sha256": _sha256(manifest_path),
        "bundle_id": manifest["bundle_id"],
        "as_of": manifest["as_of"],
        "canonical_input": manifest["canonical_input"],
        "compatible_profiles": manifest["compatible_profiles"],
        "freshness_status": manifest["freshness_status"],
        "bundle_schema_version": manifest["bundle_schema_version"],
    }


def test_ohlcv_quality_report_flags_local_csv_issues(tmp_path) -> None:
    input_csv = tmp_path / "btc.csv"
    pd.DataFrame(
        {
            "date": [
                "2025-01-01",
                "2025-01-01",
                "2025-01-05",
                "bad-date",
                "2025-01-06",
            ],
            "close": [100.0, 101.0, 102.0, 103.0, 0.0],
            "high": [101.0, 102.0, 103.0, 104.0, 105.0],
            "low": [99.0, 100.0, 101.0, 102.0, 103.0],
            "volume": [1.0, 1.0, 1.0, 1.0, 1.0],
        }
    ).to_csv(input_csv, index=False)

    report = build_ohlcv_quality_report(
        input_csv,
        as_of="2025-01-05",
        min_history_rows=4,
        max_allowed_gap_days=1,
    )

    assert report["schema_version"] == "market_signal_quality_report.v1"
    assert report["artifact_type"] == "local_ohlcv_quality_report"
    assert report["quality_status"] == "fail"
    assert report["raw_row_count"] == 5
    assert report["normalized_row_count"] == 2
    assert report["duplicate_date_count"] == 1
    assert report["invalid_date_count"] == 1
    assert report["non_positive_close_count"] == 1
    assert report["max_gap_days"] == 4
    assert "insufficient_history_rows" in report["failure_reasons"]
    assert "duplicate_dates_collapsed" in report["warning_reasons"]
    assert "date_gaps_above_threshold" in report["warning_reasons"]


def test_quality_report_validator_accepts_publishable_artifact(tmp_path, capsys) -> None:
    input_csv = tmp_path / "btc.csv"
    quality_report_path = tmp_path / "quality_report.json"
    _btc_frame().to_csv(input_csv, index=False)
    write_ohlcv_quality_report(
        quality_report_path,
        input_csv,
        as_of="2025-09-17",
    )

    summary = validate_ohlcv_quality_report_file(quality_report_path)

    assert summary["schema_version"] == "market_signal_quality_report.v1"
    assert summary["artifact_type"] == "local_ohlcv_quality_report"
    assert summary["quality_status"] == "pass"
    assert summary["sha256"] == _sha256(quality_report_path)
    assert summary["normalized_row_count"] == 260
    assert summary["first_date"] == "2025-01-01"
    assert summary["last_date"] == "2025-09-17"

    result = validate_quality_main([str(quality_report_path), "--pretty"])

    assert result == 0
    cli_summary = json.loads(capsys.readouterr().out)
    assert cli_summary["sha256"] == _sha256(quality_report_path)
    assert cli_summary["quality_status"] == "pass"


def test_quality_report_validator_gates_failed_artifact(tmp_path, capsys) -> None:
    input_csv = tmp_path / "btc.csv"
    quality_report_path = tmp_path / "quality_report.json"
    pd.DataFrame(
        {
            "date": ["2025-01-01", "2025-01-05"],
            "close": [100.0, 102.0],
        }
    ).to_csv(input_csv, index=False)
    write_ohlcv_quality_report(
        quality_report_path,
        input_csv,
        min_history_rows=4,
        max_allowed_gap_days=1,
    )

    with pytest.raises(QualityReportValidationError, match="status is fail"):
        validate_ohlcv_quality_report_file(quality_report_path)

    result = validate_quality_main([str(quality_report_path)])

    assert result == 2
    assert "quality report status is fail" in capsys.readouterr().err

    allow_result = validate_quality_main(
        [str(quality_report_path), "--allow-fail-status", "--pretty"]
    )

    assert allow_result == 0
    cli_summary = json.loads(capsys.readouterr().out)
    assert cli_summary["quality_status"] == "fail"
    assert cli_summary["failure_reasons"] == ["insufficient_history_rows"]


def test_quality_report_validator_rejects_sensitive_fields(tmp_path) -> None:
    input_csv = tmp_path / "btc.csv"
    quality_report_path = tmp_path / "quality_report.json"
    _btc_frame().to_csv(input_csv, index=False)
    write_ohlcv_quality_report(quality_report_path, input_csv)
    report = json.loads(quality_report_path.read_text(encoding="utf-8"))
    report["provenance"] = {"signed_url": "https://example.invalid/private.csv"}
    quality_report_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(QualityReportValidationError, match="sensitive key"):
        validate_ohlcv_quality_report_file(quality_report_path)


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
    assert 0.0 <= float(indicators["ahr999_365d_percentile"]) <= 1.0
    assert float(indicators["ahr999_30d_slope"]) < 0.0
    assert indicators["mayer_multiple_365d_percentile"] == 1.0
    assert indicators["realized_volatility_30d"] == 0.0
    assert indicators["momentum_90d"] == 0.0


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
        "ahr999_365d_percentile",
        "ahr999_30d_slope",
        "mayer_multiple_365d_percentile",
        "realized_volatility_30d",
        "momentum_90d",
        "cycle_indicator_source",
    ]
    assert len(frame) == 5
    assert frame.iloc[0]["date"] == "2025-07-19"
    assert frame.iloc[-1]["date"] == "2025-07-23"
    assert frame.iloc[-1]["mayer_multiple"] == 1.0
    assert frame.iloc[-1]["mayer_multiple_365d_percentile"] == 1.0
    assert pd.isna(frame.iloc[-1]["ahr999_30d_slope"])
    assert frame.iloc[-1]["realized_volatility_30d"] == 0.0
    assert frame.iloc[-1]["momentum_90d"] == 0.0


def test_write_signal_bundle_artifacts_with_manifest_and_index(tmp_path) -> None:
    input_csv = tmp_path / "btc.csv"
    _btc_frame().to_csv(input_csv, index=False)
    quality_report_path = tmp_path / "quality_report.json"
    write_ohlcv_quality_report(
        quality_report_path,
        input_csv,
        as_of="2025-09-17",
    )
    bundle = build_btc_cycle_signal_bundle(
        _btc_frame(),
        as_of="2025-09-17",
        raw_artifact_sha256=_sha256(input_csv),
        generated_at="2025-09-17T00:15:00Z",
    )

    paths = write_signal_bundle_artifacts(
        tmp_path,
        bundle,
        quality_report_path=quality_report_path,
    )

    signal_bundle = json.loads(paths["signal_bundle"].read_text(encoding="utf-8"))
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    index = json.loads(paths["index"].read_text(encoding="utf-8"))
    quality_report = json.loads(quality_report_path.read_text(encoding="utf-8"))
    payload = signal_bundle["derived_indicators"]["BTC-USD"]
    provider_metadata = local_csv_provider_metadata(
        input_csv,
        as_of="2025-09-17",
        provider="local_csv",
        provider_dataset="btc_usd_daily_ohlcv",
    )

    assert signal_bundle["schema_version"] == "market_signal_bundle.v1"
    assert signal_bundle["bundle_id"] == "crypto.btc.derived_indicators.2025-09-17"
    assert payload["provider_timestamp"] == "2025-09-17T00:00:00Z"
    assert provider_metadata.raw_artifact_sha256 == _sha256(input_csv)
    assert provider_metadata.provider_timestamp == payload["provider_timestamp"]
    assert signal_bundle["provenance"]["raw_artifact_sha256"] == _sha256(input_csv)
    assert signal_bundle["provenance"]["license_scope"] == "internal_runtime"
    assert manifest["schema_version"] == "market_signal_manifest.v1"
    assert manifest["bundle_sha256"] == _sha256(paths["signal_bundle"])
    assert manifest["compatible_profiles"] == signal_bundle["consumer_contract"][
        "compatible_profiles"
    ]
    assert manifest["quality_report_path"] == "quality_report.json"
    assert manifest["quality_report_sha256"] == _sha256(quality_report_path)
    assert quality_report["quality_status"] == "pass"
    assert index["schema_version"] == "market_signal_index.v1"
    assert index["bundles"][0]["manifest_sha256"] == _sha256(paths["manifest"])
    assert index["bundles"][0]["compatible_profiles"] == manifest["compatible_profiles"]

    manifest_summary = validate_signal_bundle_manifest(paths["manifest"])
    index_summary = validate_signal_bundle_index(paths["index"], as_of="2025-09-18")
    consumer_summary = validate_signal_bundle_index_for_consumer(
        paths["index"],
        as_of="2025-09-18",
        consumer="research:ibit_btc_ahr999_mayer_precomputed_variants",
    )
    assert manifest_summary["bundle_id"] == "crypto.btc.derived_indicators.2025-09-17"
    assert "research:ibit_btc_ahr999_mayer_precomputed_variants" in manifest_summary[
        "compatible_profiles"
    ]
    assert manifest_summary["quality_status"] == "pass"
    assert manifest_summary["quality_normalized_row_count"] == 260
    assert manifest_summary["quality_report_sha256"] == _sha256(quality_report_path)
    assert index_summary["index_schema_version"] == "market_signal_index.v1"
    assert index_summary["indicator_field_count_by_symbol"]["BTC-USD"] == 18
    assert "us_equity:ibit_smart_dca" in index_summary["compatible_profiles"]
    assert "ahr999" in index_summary["indicator_fields_by_symbol"]["BTC-USD"]
    assert consumer_summary["consumer"] == "research:ibit_btc_ahr999_mayer_precomputed_variants"
    assert "research:ibit_btc_ahr999_mayer_precomputed_variants" in consumer_summary[
        "compatible_profiles"
    ]
    assert consumer_summary["required_indicator_fields_by_symbol"] == {
        "BTC-USD": ("ahr999", "ahr999_sma", "mayer_multiple")
    }

    quality_report_path.write_text(
        json.dumps({**quality_report, "quality_status": "warn"}),
        encoding="utf-8",
    )
    with pytest.raises(SignalBundleValidationError, match="quality_report_sha256"):
        validate_signal_bundle_manifest(paths["manifest"])


def test_signal_source_family_catalog_tracks_btc_cycle_bundle_contract() -> None:
    bundle = build_btc_cycle_signal_bundle(
        _btc_frame(),
        as_of="2025-09-17",
        raw_artifact_sha256="0" * 64,
        generated_at="2025-09-17T00:15:00Z",
    )
    record = signal_source_family_record("crypto.btc_cycle_daily")
    us_context_record = signal_source_family_record("us_equity.nasdaq_sp500_context_daily")
    us_price_proxy_record = signal_source_family_record(
        "us_equity.nasdaq_sp500_price_proxy_daily"
    )
    us_public_context_record = signal_source_family_record(
        "us_equity.nasdaq_sp500_public_context_daily"
    )
    catalog = signal_source_family_catalog_payload()

    assert known_signal_source_families() == (
        "crypto.btc_cycle_daily",
        "us_equity.nasdaq_sp500_context_daily",
        "us_equity.nasdaq_sp500_price_proxy_daily",
        "us_equity.nasdaq_sp500_public_context_daily",
    )
    assert catalog["schema_version"] == "market_signal_source_families.v1"
    assert catalog["families"] == [
        record,
        us_context_record,
        us_price_proxy_record,
        us_public_context_record,
    ]
    assert catalog["domain_coverage"]["crypto"]["implemented_families"] == [
        "crypto.btc_cycle_daily"
    ]
    assert catalog["domain_coverage"]["us_equity"]["implemented_families"] == [
        "us_equity.nasdaq_sp500_context_daily",
        "us_equity.nasdaq_sp500_price_proxy_daily",
        "us_equity.nasdaq_sp500_public_context_daily",
    ]
    assert "us_equity.index_breadth_daily" in catalog["domain_coverage"][
        "us_equity"
    ]["planned_families"]
    assert signal_source_domain_coverage_payload()["hk_equity"][
        "implemented_families"
    ] == []
    assert implemented_signal_source_families_for_domain("crypto") == (
        "crypto.btc_cycle_daily",
    )
    assert implemented_signal_source_families_for_domain("hk_equity") == ()
    assert record["domain"] == "crypto"
    assert record["canonical_input"] == "derived_indicators"
    assert record["transform"] == bundle["provenance"]["transform"]
    assert record["freshness_policy"] == bundle["freshness"]["policy"]
    assert record["compatible_profiles"] == bundle["consumer_contract"][
        "compatible_profiles"
    ]
    assert compatible_profiles_for_signal_source_family(
        "crypto.btc_cycle_daily"
    ) == tuple(bundle["consumer_contract"]["compatible_profiles"])
    assert runtime_consumers_for_signal_source_family("crypto.btc_cycle_daily") == (
        "us_equity:ibit_smart_dca",
    )
    assert runtime_consumers_for_signal_source_family(
        "us_equity.nasdaq_sp500_context_daily"
    ) == ()
    runtime_coverage = signal_source_runtime_consumer_coverage()
    assert runtime_coverage["all_runtime_consumers_covered"] is True
    assert runtime_coverage["known_runtime_consumers"] == ("us_equity:ibit_smart_dca",)
    assert runtime_coverage["runtime_consumer_source_families"] == {
        "us_equity:ibit_smart_dca": ("crypto.btc_cycle_daily",)
    }
    coverage = signal_source_family_consumer_contract_coverage(
        "crypto.btc_cycle_daily"
    )
    assert coverage["all_required_fields_present"] is True
    assert coverage["consumer_count"] == 5
    assert coverage["required_indicator_fields_by_consumer"][
        "us_equity:ibit_smart_dca"
    ] == {"BTC-USD": ["ahr999"]}
    assert coverage["required_indicator_fields_by_consumer"][
        "research:ibit_btc_ahr999_helper_precomputed_variants"
    ] == {"BTC-USD": ["ahr999", "ahr999_365d_percentile", "ahr999_30d_slope"]}
    assert coverage["required_indicator_fields_by_consumer"][
        "research:ibit_btc_ahr999_mayer_precomputed_variants"
    ] == {"BTC-USD": ["ahr999", "ahr999_sma", "mayer_multiple"]}
    assert set(record["derived_indicator_fields"]) == set(
        bundle["derived_indicators"]["BTC-USD"]
    )
    us_coverage = signal_source_family_consumer_contract_coverage(
        "us_equity.nasdaq_sp500_context_daily"
    )
    assert us_coverage["consumer_count"] == 1
    assert us_coverage["required_indicator_fields_by_consumer"][
        "research:nasdaq_sp500_external_context_precomputed"
    ] == {
        "US-EQUITY-CONTEXT": [
            "breadth_above_sma200_pct",
            "cape_percentile",
            "vix_percentile",
        ]
    }
    assert us_context_record["source_profiles"] == [
        {
            "source_id": "fred.vixcls",
            "source_name": "Federal Reserve Economic Data VIXCLS",
            "provider_dataset": "VIXCLS",
            "produced_fields": ["vix_percentile"],
            "history_frequency": "daily",
            "point_in_time_status": "public_history_with_execution_lag",
            "max_allowed_lag_days": 10,
            "publication_lag_policy": "use at least T+1 before same-day DCA decisions",
            "research_use_policy": (
                "accepted for research when the downloaded CSV, as_of, and "
                "percentile lookback are hash-pinned"
            ),
            "source_url": "https://fred.stlouisfed.org/series/VIXCLS",
        },
        {
            "source_id": "shiller.cape_monthly",
            "source_name": "Robert Shiller online data CAPE",
            "provider_dataset": "ie_data.xls",
            "produced_fields": ["cape_percentile"],
            "history_frequency": "monthly",
            "point_in_time_status": "public_revised_history_snapshot_required",
            "max_allowed_lag_days": 120,
            "publication_lag_policy": "month-end or later; never same-day daily timing",
            "research_use_policy": (
                "accepted for low-frequency valuation research only when the raw "
                "download snapshot and revision date are preserved"
            ),
            "source_url": "https://www.econ.yale.edu/~shiller/data.htm",
        },
        {
            "source_id": "index_breadth.point_in_time_vendor",
            "source_name": "Point-in-time index breadth history",
            "provider_dataset": "spx_ndx_members_above_sma200_daily",
            "produced_fields": ["breadth_above_sma200_pct"],
            "history_frequency": "daily",
            "point_in_time_status": "requires_point_in_time_vendor_or_breadth_index",
            "publication_lag_policy": (
                "vendor timestamp must be no later than DCA evaluation lag"
            ),
            "research_use_policy": (
                "reject current-constituent backfills; use only point-in-time "
                "constituents or an auditable historical breadth index"
            ),
            "source_url": "",
        },
    ]
    assert source_profiles_for_signal_source_family(
        "us_equity.nasdaq_sp500_context_daily"
    )[2]["source_id"] == "index_breadth.point_in_time_vendor"
    public_coverage = signal_source_family_consumer_contract_coverage(
        "us_equity.nasdaq_sp500_public_context_daily"
    )
    assert public_coverage["consumer_count"] == 1
    assert public_coverage["required_indicator_fields_by_consumer"][
        "research:nasdaq_sp500_cape_vix_external_context_precomputed"
    ] == {
        "US-EQUITY-CONTEXT": [
            "cape_percentile",
            "vix_percentile",
        ]
    }
    assert source_profiles_for_signal_source_family(
        "us_equity.nasdaq_sp500_public_context_daily"
    )[1]["source_id"] == "shiller.cape_monthly"
    price_proxy_coverage = signal_source_family_consumer_contract_coverage(
        "us_equity.nasdaq_sp500_price_proxy_daily"
    )
    assert price_proxy_coverage["consumer_count"] == 1
    assert price_proxy_coverage["required_indicator_fields_by_consumer"][
        "research:nasdaq_sp500_price_proxy"
    ] == {
        "US-EQUITY-PRICE-PROXY": [
            "QQQ",
            "SPY",
        ]
    }
    assert us_price_proxy_record["runtime_consumers"] == []
    assert source_profiles_for_signal_source_family(
        "us_equity.nasdaq_sp500_price_proxy_daily"
    )[0]["source_id"] == "fred.nasdaq100"
    assert source_profiles_for_signal_source_family(
        "us_equity.nasdaq_sp500_price_proxy_daily"
    )[1]["source_id"] == "fred.sp500"
    assert set(record["compatible_profiles"]).issubset(set(known_signal_consumers()))


def test_signal_source_family_catalog_cli_prints_json_safe_payload(
    tmp_path,
    capsys,
) -> None:
    result = list_families_main(["--family", "crypto.btc_cycle_daily", "--pretty"])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "market_signal_source_families.v1"
    assert [family["family"] for family in payload["families"]] == [
        "crypto.btc_cycle_daily"
    ]
    assert payload["families"][0]["compatible_profiles"] == [
        "us_equity:ibit_smart_dca",
        "research:ibit_btc_ahr999_precomputed",
        "research:ibit_btc_ahr999_helper_precomputed_variants",
        "research:ibit_btc_ahr999_mayer_precomputed",
        "research:ibit_btc_ahr999_mayer_precomputed_variants",
    ]

    domain_result = list_families_main(["--domain", "us_equity", "--pretty"])
    assert domain_result == 0
    domain_payload = json.loads(capsys.readouterr().out)
    assert [family["family"] for family in domain_payload["families"]] == [
        "us_equity.nasdaq_sp500_context_daily",
        "us_equity.nasdaq_sp500_price_proxy_daily",
        "us_equity.nasdaq_sp500_public_context_daily",
    ]

    empty_domain_result = list_families_main(["--domain", "hk_equity", "--pretty"])
    assert empty_domain_result == 0
    empty_domain_payload = json.loads(capsys.readouterr().out)
    assert empty_domain_payload["families"] == []
    assert empty_domain_payload["domain_coverage"]["hk_equity"][
        "planned_families"
    ] == [
        "hk_equity.index_breadth_daily",
        "hk_equity.fx_liquidity_context",
    ]

    catalog_path = tmp_path / "signal_source_families.json"
    catalog_path.write_text(
        json.dumps(signal_source_family_catalog_payload(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    validate_result = list_families_main(
        [
            "--validate-json",
            str(catalog_path),
            "--require-all-known-families",
            "--require-runtime-consumer-coverage",
            "--pretty",
        ]
    )
    assert validate_result == 0
    validation_summary = json.loads(capsys.readouterr().out)
    assert validation_summary["family_count"] == 4
    assert validation_summary["all_known_families_present"] is True
    assert validation_summary["domain_coverage_present"] is True
    assert validation_summary["domain_count"] == 3
    assert validation_summary["domains"] == ["crypto", "hk_equity", "us_equity"]
    assert validation_summary["implemented_family_count"] == 4
    assert validation_summary["planned_family_count"] == 7
    assert validation_summary["source_profile_count"] == 8
    assert validation_summary["all_consumer_contracts_satisfied"] is True
    assert validation_summary["all_runtime_consumers_covered"] is True
    assert validation_summary["runtime_consumer_coverage"][
        "runtime_consumer_source_families"
    ] == {
        "us_equity:ibit_smart_dca": ["crypto.btc_cycle_daily"],
    }
    assert validation_summary["consumer_contract_coverage"][
        "crypto.btc_cycle_daily"
    ]["consumer_count"] == 5
    assert validation_summary["consumer_contract_coverage"][
        "us_equity.nasdaq_sp500_context_daily"
    ]["consumer_count"] == 1
    assert validation_summary["source_profile_coverage"][
        "us_equity.nasdaq_sp500_context_daily"
    ]["source_ids"] == [
        "fred.vixcls",
        "shiller.cape_monthly",
        "index_breadth.point_in_time_vendor",
    ]
    assert validation_summary["source_profile_coverage"][
        "us_equity.nasdaq_sp500_price_proxy_daily"
    ]["source_ids"] == [
        "fred.nasdaq100",
        "fred.sp500",
    ]
    assert validation_summary["source_profile_coverage"][
        "us_equity.nasdaq_sp500_public_context_daily"
    ]["source_ids"] == [
        "fred.vixcls",
        "shiller.cape_monthly",
    ]
    assert validation_summary["source_profile_coverage"][
        "us_equity.nasdaq_sp500_public_context_daily"
    ]["profiles"][0]["max_allowed_lag_days"] == 10
    assert validation_summary["source_profile_coverage"][
        "us_equity.nasdaq_sp500_public_context_daily"
    ]["profiles"][1]["max_allowed_lag_days"] == 120
    assert validation_summary["sha256"] == _sha256(catalog_path)

    legacy_payload = signal_source_family_catalog_payload()
    legacy_payload.pop("domain_coverage")
    legacy_summary = validate_signal_source_family_catalog(legacy_payload)
    assert legacy_summary["domain_coverage_present"] is False
    assert legacy_summary["domain_count"] == 0

    drifted_payload = signal_source_family_catalog_payload()
    drifted_payload["families"][0]["transform"] = "crypto.btc.wrong.v1"
    catalog_path.write_text(json.dumps(drifted_payload), encoding="utf-8")
    drift_result = list_families_main(["--validate-json", str(catalog_path)])
    assert drift_result == 2
    assert "signal source family record drift" in capsys.readouterr().err

    domain_drifted_payload = signal_source_family_catalog_payload()
    domain_drifted_payload["domain_coverage"]["crypto"]["planned_families"].append(
        "crypto.btc_cycle_daily"
    )
    catalog_path.write_text(json.dumps(domain_drifted_payload), encoding="utf-8")
    domain_drift_result = list_families_main(["--validate-json", str(catalog_path)])
    assert domain_drift_result == 2
    assert "signal source family catalog domain_coverage drift" in capsys.readouterr().err

    unknown_result = list_families_main(["--family", "unknown.family"])
    assert unknown_result == 2
    assert "unknown signal source family" in capsys.readouterr().err

    unknown_domain_result = list_families_main(["--domain", "unknown_domain"])
    assert unknown_domain_result == 2
    assert "unknown signal source domain" in capsys.readouterr().err

    mixed_selector_result = list_families_main(
        ["--family", "crypto.btc_cycle_daily", "--domain", "crypto"]
    )
    assert mixed_selector_result == 2
    assert "either --family or --domain" in capsys.readouterr().err

    invalid_runtime_requirement_result = list_families_main(
        ["--require-runtime-consumer-coverage"]
    )
    assert invalid_runtime_requirement_result == 2
    assert "--require-runtime-consumer-coverage is only valid" in capsys.readouterr().err


def test_signal_source_family_catalog_validation_rejects_contract_gap(
    monkeypatch,
) -> None:
    original = SIGNAL_SOURCE_FAMILIES["crypto.btc_cycle_daily"]
    reduced_fields = tuple(
        field
        for field in original["derived_indicator_fields"]
        if field != "ahr999_sma"
    )
    monkeypatch.setitem(
        SIGNAL_SOURCE_FAMILIES,
        "crypto.btc_cycle_daily",
        {
            **original,
            "derived_indicator_fields": reduced_fields,
        },
    )
    payload = signal_source_family_catalog_payload(
        families=("crypto.btc_cycle_daily",)
    )

    with pytest.raises(ValueError, match="missing required indicator fields"):
        validate_signal_source_family_catalog(payload)


def test_signal_source_family_catalog_validation_rejects_source_profile_gap(
    monkeypatch,
) -> None:
    original = SIGNAL_SOURCE_FAMILIES["us_equity.nasdaq_sp500_context_daily"]
    first_profile = dict(original["source_profiles"][0])
    first_profile["produced_fields"] = (
        *tuple(first_profile["produced_fields"]),
        "unknown_context_field",
    )
    monkeypatch.setitem(
        SIGNAL_SOURCE_FAMILIES,
        "us_equity.nasdaq_sp500_context_daily",
        {
            **original,
            "source_profiles": (
                first_profile,
                *tuple(original["source_profiles"][1:]),
            ),
        },
    )
    payload = signal_source_family_catalog_payload(
        families=("us_equity.nasdaq_sp500_context_daily",)
    )

    with pytest.raises(
        ValueError,
        match="produced fields are not derived_indicator_fields",
    ):
        validate_signal_source_family_catalog(payload)


def test_signal_source_family_catalog_validation_rejects_bad_source_lag_policy(
    monkeypatch,
) -> None:
    original = SIGNAL_SOURCE_FAMILIES["us_equity.nasdaq_sp500_public_context_daily"]
    first_profile = dict(original["source_profiles"][0])
    first_profile["max_allowed_lag_days"] = -1
    monkeypatch.setitem(
        SIGNAL_SOURCE_FAMILIES,
        "us_equity.nasdaq_sp500_public_context_daily",
        {
            **original,
            "source_profiles": (
                first_profile,
                *tuple(original["source_profiles"][1:]),
            ),
        },
    )
    payload = signal_source_family_catalog_payload(
        families=("us_equity.nasdaq_sp500_public_context_daily",)
    )

    with pytest.raises(ValueError, match="max_allowed_lag_days"):
        validate_signal_source_family_catalog(payload)


def test_signal_source_family_catalog_can_publish_manifest(
    tmp_path,
    capsys,
) -> None:
    output_json = tmp_path / "catalog" / "signal_source_families.json"

    summary = write_signal_source_family_catalog(output_json)

    assert summary["path"] == str(output_json)
    assert summary["schema_version"] == "market_signal_source_families.v1"
    assert summary["family_count"] == 4
    assert summary["all_consumer_contracts_satisfied"] is True
    assert summary["domain_coverage_present"] is True
    assert summary["source_profile_count"] == 8
    assert summary["sha256"] == _sha256(output_json)

    validate_summary = validate_signal_source_family_catalog_file(
        output_json,
        require_all_known_families=True,
    )
    assert validate_summary["all_known_families_present"] is True
    assert validate_summary["consumer_contract_coverage"][
        "crypto.btc_cycle_daily"
    ]["consumer_count"] == 5

    output_dir = tmp_path / "catalog-artifacts"
    manifest_summary = write_signal_source_family_catalog_artifacts(output_dir)
    catalog_path = output_dir / "signal_source_families.json"
    manifest_path = output_dir / "signal_source_families.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest_summary["manifest_path"] == str(manifest_path)
    assert manifest_summary["catalog_path"] == str(catalog_path)
    assert manifest_summary["manifest_schema_version"] == (
        "market_signal_source_family_catalog_manifest.v1"
    )
    assert manifest_summary["catalog_schema_version"] == (
        "market_signal_source_families.v1"
    )
    assert manifest_summary["catalog_sha256"] == _sha256(catalog_path)
    assert manifest_summary["all_known_families_present"] is True
    assert manifest_summary["domain_count"] == 3
    assert manifest_summary["planned_family_count"] == 7
    assert manifest_summary["source_profile_count"] == 8
    assert manifest_summary["all_consumer_contracts_satisfied"] is True
    assert manifest["catalog_path"] == "signal_source_families.json"
    assert manifest["source_profile_count"] == 8

    validation_summary = validate_signal_source_family_catalog_manifest(
        manifest_path,
        require_all_known_families=True,
    )
    assert validation_summary["manifest_sha256"] == _sha256(manifest_path)
    assert validation_summary["catalog_sha256"] == _sha256(catalog_path)

    cli_output_dir = tmp_path / "cli-catalog"
    result = list_families_main(
        [
            "--output-dir",
            str(cli_output_dir),
            "--pretty",
        ]
    )
    assert result == 0
    cli_summary = json.loads(capsys.readouterr().out)
    cli_manifest_path = cli_output_dir / "signal_source_families.manifest.json"
    assert cli_summary["manifest_path"] == str(cli_manifest_path)
    assert cli_summary["catalog_sha256"] == _sha256(
        cli_output_dir / "signal_source_families.json"
    )

    validate_result = list_families_main(
        [
            "--validate-manifest",
            str(cli_manifest_path),
            "--require-all-known-families",
            "--pretty",
        ]
    )
    assert validate_result == 0
    cli_validate_summary = json.loads(capsys.readouterr().out)
    assert cli_validate_summary["manifest_sha256"] == _sha256(cli_manifest_path)

    catalog_payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog_path.write_text(
        json.dumps(catalog_payload, sort_keys=True),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="catalog_sha256 mismatch"):
        validate_signal_source_family_catalog_manifest(manifest_path)


def test_signal_source_family_catalog_rejects_sensitive_fields(tmp_path) -> None:
    catalog_path = tmp_path / "signal_source_families.json"
    payload = signal_source_family_catalog_payload()
    payload["token"] = "should-not-publish"
    catalog_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="forbidden sensitive key"):
        validate_signal_source_family_catalog_file(catalog_path)


def test_signal_bundle_publication_index_upserts_manifest_tree(tmp_path) -> None:
    input_csv = tmp_path / "btc.csv"
    _btc_frame().to_csv(input_csv, index=False)
    publication_root = tmp_path / "signal_bundles"
    index_path = publication_root / "index.json"

    first_bundle = build_btc_cycle_signal_bundle(
        _btc_frame(),
        as_of="2025-09-17",
        raw_artifact_sha256=_sha256(input_csv),
        generated_at="2025-09-17T00:15:00Z",
    )
    second_bundle = build_btc_cycle_signal_bundle(
        _btc_frame(),
        as_of="2025-09-18",
        raw_artifact_sha256=_sha256(input_csv),
        generated_at="2025-09-18T00:15:00Z",
    )
    first_paths = write_signal_bundle_artifacts(
        publication_root / "crypto" / "btc" / "derived_indicators" / "2025-09-17",
        first_bundle,
    )
    second_paths = write_signal_bundle_artifacts(
        publication_root / "crypto" / "btc" / "derived_indicators" / "2025-09-18",
        second_bundle,
    )

    write_signal_bundle_publication_index(
        index_path,
        (first_paths["manifest"],),
        generated_at="2025-09-17T00:30:00Z",
    )
    upsert_signal_bundle_publication_index(
        index_path,
        second_paths["manifest"],
        generated_at="2025-09-18T00:30:00Z",
    )

    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index["generated_at"] == "2025-09-18T00:30:00Z"
    assert [entry["as_of"] for entry in index["bundles"]] == [
        "2025-09-17",
        "2025-09-18",
    ]
    assert index["bundles"][0]["manifest_path"] == (
        "crypto/btc/derived_indicators/2025-09-17/manifest.json"
    )
    assert index["bundles"][1]["manifest_sha256"] == _sha256(second_paths["manifest"])

    consumer_summary = validate_signal_bundle_index_for_consumer(
        index_path,
        as_of="2025-09-19",
        consumer="us_equity:ibit_smart_dca",
    )
    assert consumer_summary["bundle_id"] == second_bundle["bundle_id"]
    assert consumer_summary["consumer_profile_compatible"] is True


def test_consumer_index_validation_filters_incompatible_newer_bundle(tmp_path) -> None:
    input_csv = tmp_path / "btc.csv"
    _btc_frame().to_csv(input_csv, index=False)
    consumer = "research:ibit_btc_ahr999_mayer_precomputed_variants"
    compatible_bundle = build_btc_cycle_signal_bundle(
        _btc_frame(),
        as_of="2025-09-17",
        raw_artifact_sha256=_sha256(input_csv),
        generated_at="2025-09-17T00:15:00Z",
    )
    incompatible_bundle = build_btc_cycle_signal_bundle(
        _btc_frame(),
        as_of="2025-09-18",
        raw_artifact_sha256=_sha256(input_csv),
        generated_at="2025-09-18T00:15:00Z",
    )
    incompatible_bundle["consumer_contract"]["compatible_profiles"] = [
        "research:other_consumer"
    ]

    compatible_dir = tmp_path / "compatible"
    incompatible_dir = tmp_path / "incompatible"
    compatible_paths = write_signal_bundle_artifacts(compatible_dir, compatible_bundle)
    incompatible_paths = write_signal_bundle_artifacts(
        incompatible_dir,
        incompatible_bundle,
    )
    index_path = tmp_path / "index.json"
    index_path.write_text(
        json.dumps(
            {
                "schema_version": "market_signal_index.v1",
                "generated_at": "2025-09-19T00:00:00Z",
                "bundles": [
                    _signal_bundle_index_entry(tmp_path, incompatible_paths["manifest"]),
                    _signal_bundle_index_entry(tmp_path, compatible_paths["manifest"]),
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    index_summary = validate_signal_bundle_index(index_path, as_of="2025-09-19")
    consumer_summary = validate_signal_bundle_index_for_consumer(
        index_path,
        as_of="2025-09-19",
        consumer=consumer,
    )

    assert index_summary["bundle_id"] == incompatible_bundle["bundle_id"]
    assert consumer_summary["bundle_id"] == compatible_bundle["bundle_id"]
    assert consumer in consumer_summary["compatible_profiles"]
    assert consumer_summary["required_indicator_fields_by_symbol"] == {
        "BTC-USD": ("ahr999", "ahr999_sma", "mayer_multiple")
    }


def test_write_signal_bundle_artifacts_rejects_quality_report_raw_input_mismatch(
    tmp_path,
) -> None:
    input_csv = tmp_path / "btc.csv"
    _btc_frame().to_csv(input_csv, index=False)
    quality_report_path = tmp_path / "quality_report.json"
    write_ohlcv_quality_report(
        quality_report_path,
        input_csv,
        as_of="2025-09-17",
    )
    bundle = build_btc_cycle_signal_bundle(
        _btc_frame(),
        as_of="2025-09-17",
        raw_artifact_sha256="0" * 64,
        generated_at="2025-09-17T00:15:00Z",
    )

    with pytest.raises(
        SignalBundleValidationError,
        match="input_csv.sha256 mismatch",
    ):
        write_signal_bundle_artifacts(
            tmp_path,
            bundle,
            quality_report_path=quality_report_path,
        )


def test_write_signal_bundle_artifacts_self_validates_written_index(tmp_path) -> None:
    bundle = build_btc_cycle_signal_bundle(
        _btc_frame(),
        as_of="2025-09-17",
        raw_artifact_sha256="0" * 64,
        generated_at="2025-09-17T00:15:00Z",
    )
    del bundle["provenance"]["provider_dataset"]

    with pytest.raises(
        SignalBundleValidationError,
        match="provenance missing required fields: provider_dataset",
    ):
        write_signal_bundle_artifacts(tmp_path, bundle)

    paths = write_signal_bundle_artifacts(
        tmp_path / "unchecked",
        bundle,
        validate_after_write=False,
    )
    with pytest.raises(SignalBundleValidationError, match="provider_dataset"):
        validate_signal_bundle_index(paths["index"])


def test_generic_derived_indicator_bundle_can_publish_non_btc_signal(tmp_path) -> None:
    bundle = build_derived_indicator_signal_bundle(
        domain="us_equity",
        bundle_id="us_equity.index_breadth.derived_indicators.2025-09-17",
        as_of="2025-09-17",
        generated_at="2025-09-17T00:15:00Z",
        symbols=("QQQ",),
        derived_indicators={
            "QQQ": {
                "above_sma200_ratio": 0.62,
                "provider_timestamp": "2025-09-17T00:00:00Z",
            }
        },
        freshness={
            "policy": "us_equity_daily_close_t_plus_1",
            "max_age_hours": 36,
            "provider_timestamp": "2025-09-17T00:00:00Z",
            "status": "fresh",
        },
        provenance={
            "source_repo": "QuantStrategyLab/MarketSignalSources",
            "source_version": "0.1.0",
            "code_commit": "0000000000000000000000000000000000000000",
            "provider": "local_csv",
            "provider_dataset": "qqq_index_breadth_daily",
            "raw_artifact_sha256": "1" * 64,
            "transform": "us_equity.index_breadth.v1",
            "license_scope": "internal_runtime",
            "generated_by": "market_signal_sources.local_csv",
        },
        compatible_profiles=("research:us_equity_index_breadth",),
    )

    paths = write_signal_bundle_artifacts(tmp_path, bundle)
    summary = validate_signal_bundle_index(
        paths["index"],
        as_of="2025-09-18",
        bundle_id="us_equity.index_breadth.derived_indicators.2025-09-17",
    )
    written_bundle = json.loads(paths["signal_bundle"].read_text(encoding="utf-8"))

    assert written_bundle["domain"] == "us_equity"
    assert summary["bundle_id"] == (
        "us_equity.index_breadth.derived_indicators.2025-09-17"
    )
    assert summary["indicator_fields_by_symbol"] == {
        "QQQ": ("above_sma200_ratio", "provider_timestamp")
    }


def test_us_equity_context_bundle_covers_nasdaq_external_research_consumer(
    tmp_path,
) -> None:
    bundle = build_derived_indicator_signal_bundle(
        domain="us_equity",
        bundle_id="us_equity.nasdaq_sp500.context.2025-09-17",
        as_of="2025-09-17",
        generated_at="2025-09-17T00:15:00Z",
        symbols=("US-EQUITY-CONTEXT",),
        derived_indicators={
            "US-EQUITY-CONTEXT": {
                "breadth_above_sma200_pct": 0.35,
                "cape_percentile": 0.90,
                "provider_timestamp": "2025-09-17T00:00:00Z",
                "vix_percentile": 0.85,
            }
        },
        freshness={
            "policy": "us_equity_research_context_t_plus_1",
            "max_age_hours": 36,
            "provider_timestamp": "2025-09-17T00:00:00Z",
            "status": "fresh",
        },
        provenance={
            "source_repo": "QuantStrategyLab/MarketSignalSources",
            "source_version": "0.1.0",
            "code_commit": "0000000000000000000000000000000000000000",
            "provider": "local_csv",
            "provider_dataset": "nasdaq_sp500_external_context_daily",
            "raw_artifact_sha256": "2" * 64,
            "transform": "us_equity.nasdaq_sp500.context.v1",
            "license_scope": "internal_research",
            "generated_by": "market_signal_sources.local_csv",
        },
        compatible_profiles=("research:nasdaq_sp500_external_context_precomputed",),
        min_strategy_contract="derived_indicators+research_context",
    )

    paths = write_signal_bundle_artifacts(tmp_path, bundle)
    validate_signal_bundle_for_consumer(
        bundle,
        consumer="research:nasdaq_sp500_external_context_precomputed",
    )
    manifest_summary = validate_signal_bundle_manifest_for_consumer(
        paths["manifest"],
        consumer="research:nasdaq_sp500_external_context_precomputed",
    )

    assert manifest_summary["bundle_id"] == "us_equity.nasdaq_sp500.context.2025-09-17"
    assert manifest_summary["required_indicator_fields_by_symbol"] == {
        "US-EQUITY-CONTEXT": (
            "breadth_above_sma200_pct",
            "cape_percentile",
            "vix_percentile",
        )
    }


def test_cli_builds_btc_cycle_bundle_from_csv(tmp_path, capsys) -> None:
    input_csv = tmp_path / "btc.csv"
    publication_root = tmp_path / "signal_bundles"
    output_dir = publication_root / "crypto" / "btc" / "derived_indicators" / "2025-09-17"
    publication_index = publication_root / "index.json"
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
            "--publication-index",
            str(publication_index),
            "--pretty",
        ]
    )

    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["bundle_id"] == "crypto.btc.derived_indicators.2025-09-17"
    assert (output_dir / "signal_bundle.json").exists()
    assert (output_dir / "manifest.json").exists()
    assert (output_dir / "index.json").exists()
    assert (output_dir / "quality_report.json").exists()
    assert publication_index.exists()
    assert summary["artifacts"]["quality_report"] == str(output_dir / "quality_report.json")
    assert summary["artifacts"]["publication_index"] == str(publication_index)
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    signal_bundle = json.loads((output_dir / "signal_bundle.json").read_text(encoding="utf-8"))
    quality_report = json.loads((output_dir / "quality_report.json").read_text(encoding="utf-8"))
    root_index = json.loads(publication_index.read_text(encoding="utf-8"))
    assert manifest["bundle_sha256"] == _sha256(output_dir / "signal_bundle.json")
    assert manifest["quality_report_sha256"] == _sha256(output_dir / "quality_report.json")
    assert signal_bundle["provenance"]["raw_artifact_sha256"] == _sha256(input_csv)
    assert signal_bundle["freshness"]["provider_timestamp"] == "2025-09-17T00:00:00Z"
    assert root_index["bundles"][0]["manifest_path"] == (
        "crypto/btc/derived_indicators/2025-09-17/manifest.json"
    )
    assert quality_report["quality_status"] == "pass"
    assert quality_report["normalized_row_count"] == 260

    validate_result = validate_main(
        [
            "--index",
            str(publication_index),
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
    assert audit_summary["indicator_field_count_by_symbol"] == {"BTC-USD": 18}
    assert audit_summary["quality_status"] == "pass"
    assert audit_summary["quality_normalized_row_count"] == 260
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


def test_signal_bundle_consumer_contract_rejects_incompatible_profile(tmp_path) -> None:
    bundle = build_btc_cycle_signal_bundle(
        _btc_frame(),
        as_of="2025-09-17",
        raw_artifact_sha256="0" * 64,
        generated_at="2025-09-17T00:15:00Z",
    )
    bundle["consumer_contract"]["compatible_profiles"] = ["us_equity:ibit_smart_dca"]
    paths = write_signal_bundle_artifacts(tmp_path, bundle)

    with pytest.raises(SignalBundleValidationError, match="compatible_profiles"):
        validate_signal_bundle_for_consumer(
            bundle,
            consumer="research:ibit_btc_ahr999_mayer_precomputed_variants",
        )

    with pytest.raises(SignalBundleValidationError, match="compatible_profiles"):
        validate_signal_bundle_manifest_for_consumer(
            paths["manifest"],
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
    validate_signal_bundle_for_consumer(
        bundle,
        consumer="research:ibit_btc_ahr999_precomputed",
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
        "research:ibit_btc_ahr999_precomputed"
    ) == {"BTC-USD": ("ahr999",)}
    assert required_indicator_fields_for_consumer(
        "research:ibit_btc_ahr999_mayer_precomputed_variants"
    ) == {"BTC-USD": ("ahr999", "ahr999_sma", "mayer_multiple")}
    assert manifest_summary["bundle_sha256"] == _sha256(paths["signal_bundle"])
    assert direct_summary["consumer"] == "research:ibit_btc_ahr999_mayer_precomputed_variants"
    assert direct_summary["consumer_profile_compatible"] is True
    assert "research:ibit_btc_ahr999_mayer_precomputed_variants" in direct_summary[
        "compatible_profiles"
    ]


def test_consumer_contract_registry_exports_json_safe_payload(capsys) -> None:
    payload = consumer_contract_registry_payload(
        consumers=("research:ibit_btc_ahr999_mayer_precomputed_variants",)
    )

    assert known_signal_consumers() == (
        "research:ibit_btc_ahr999_helper_precomputed_variants",
        "research:ibit_btc_ahr999_mayer_precomputed",
        "research:ibit_btc_ahr999_mayer_precomputed_variants",
        "research:ibit_btc_ahr999_precomputed",
        "research:nasdaq_sp500_cape_vix_external_context_precomputed",
        "research:nasdaq_sp500_external_context_precomputed",
        "research:nasdaq_sp500_price_proxy",
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
                "BTC-USD": ["ahr999"],
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
    assert summary["all_known_consumers_present"] is False
    assert "research:ibit_btc_ahr999_mayer_precomputed" in summary[
        "missing_known_consumers"
    ]
    assert summary["sha256"] == _sha256(output_json)
    assert summary["size_bytes"] == output_json.stat().st_size
    assert summary["local_contract_registry_verified"] is True
    assert summary["canonical_registry_payload_sha256"] == summary[
        "local_registry_payload_sha256"
    ]
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
    assert validate_summary["all_known_consumers_present"] is False
    assert validate_summary["local_contract_registry_verified"] is True

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
    assert cli_validate_summary["canonical_registry_payload_sha256"] == (
        cli_validate_summary["local_registry_payload_sha256"]
    )

    require_all_result = list_contracts_main(
        [
            "--validate-json",
            str(output_json),
            "--require-all-known-consumers",
        ]
    )
    assert require_all_result == 2
    assert "missing known consumers" in capsys.readouterr().err


def test_consumer_contract_registry_can_publish_manifest(tmp_path, capsys) -> None:
    output_dir = tmp_path / "contracts"

    summary = write_consumer_contract_registry_artifacts(output_dir)
    registry_path = output_dir / "market_signal_consumers.json"
    manifest_path = output_dir / "market_signal_consumers.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert summary["manifest_path"] == str(manifest_path)
    assert summary["registry_path"] == str(registry_path)
    assert summary["manifest_schema_version"] == (
        "market_signal_consumer_contract_manifest.v1"
    )
    assert summary["registry_schema_version"] == "market_signal_consumer_contracts.v1"
    assert summary["registry_sha256"] == _sha256(registry_path)
    assert summary["manifest_sha256"] == _sha256(manifest_path)
    assert summary["all_known_consumers_present"] is True
    assert summary["local_contract_registry_verified"] is True
    assert manifest["registry_path"] == "market_signal_consumers.json"
    assert manifest["registry_sha256"] == _sha256(registry_path)

    validation_summary = validate_consumer_contract_registry_manifest(
        manifest_path,
        require_all_known_consumers=True,
    )

    assert validation_summary["registry_sha256"] == _sha256(registry_path)
    assert validation_summary["manifest_sha256"] == _sha256(manifest_path)
    assert validation_summary["consumer_count"] == 8
    assert validation_summary["local_contract_registry_verified"] is True

    cli_output_dir = tmp_path / "cli-contracts"
    result = list_contracts_main(
        [
            "--output-dir",
            str(cli_output_dir),
            "--pretty",
        ]
    )
    assert result == 0
    cli_summary = json.loads(capsys.readouterr().out)
    cli_manifest_path = cli_output_dir / "market_signal_consumers.manifest.json"
    assert cli_summary["manifest_path"] == str(cli_manifest_path)
    assert cli_summary["registry_sha256"] == _sha256(
        cli_output_dir / "market_signal_consumers.json"
    )
    assert cli_summary["local_contract_registry_verified"] is True

    validate_result = list_contracts_main(
        [
            "--validate-manifest",
            str(cli_manifest_path),
            "--require-all-known-consumers",
            "--pretty",
        ]
    )
    assert validate_result == 0
    cli_validate_summary = json.loads(capsys.readouterr().out)
    assert cli_validate_summary["manifest_sha256"] == _sha256(cli_manifest_path)
    assert cli_validate_summary["local_contract_registry_verified"] is True

    registry_payload = json.loads(registry_path.read_text(encoding="utf-8"))
    registry_path.write_text(
        json.dumps(registry_payload, sort_keys=True),
        encoding="utf-8",
    )

    with pytest.raises(SignalConsumerContractError, match="sha256 mismatch"):
        validate_consumer_contract_registry_manifest(manifest_path)


def test_consumer_contract_registry_validation_can_require_all_consumers(tmp_path) -> None:
    output_json = tmp_path / "contracts.json"
    write_consumer_contract_registry(output_json)

    summary = validate_consumer_contract_registry_file(
        output_json,
        require_all_known_consumers=True,
    )

    assert summary["all_known_consumers_present"] is True
    assert summary["missing_known_consumers"] == []
    assert summary["consumer_count"] == 8
    assert summary["local_contract_registry_verified"] is True
    assert summary["canonical_registry_payload_sha256"] == summary[
        "local_registry_payload_sha256"
    ]


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


def test_platform_signal_handoff_manifest_pins_all_platform_inputs(
    tmp_path,
    capsys,
) -> None:
    input_csv = tmp_path / "btc.csv"
    quality_report_path = tmp_path / "bundle" / "quality_report.json"
    _btc_frame().to_csv(input_csv, index=False)
    write_ohlcv_quality_report(
        quality_report_path,
        input_csv,
        as_of="2025-09-17",
    )
    bundle = build_btc_cycle_signal_bundle(
        _btc_frame(),
        as_of="2025-09-17",
        raw_artifact_sha256=_sha256(input_csv),
        generated_at="2025-09-17T00:15:00Z",
    )
    bundle_paths = write_signal_bundle_artifacts(
        tmp_path / "bundle",
        bundle,
        quality_report_path=quality_report_path,
    )
    catalog_summary = write_signal_source_family_catalog_artifacts(
        tmp_path / "source-catalog"
    )
    contract_summary = write_consumer_contract_registry_artifacts(
        tmp_path / "contracts"
    )
    handoff_path = tmp_path / "platform_handoff.json"

    summary = write_platform_signal_handoff_manifest(
        handoff_path,
        signal_bundle_manifest=bundle_paths["manifest"],
        source_family_catalog_manifest=catalog_summary["manifest_path"],
        consumer_contract_registry_manifest=contract_summary["manifest_path"],
        consumer="us_equity:ibit_smart_dca",
        require_all_known_families=True,
        require_all_known_consumers=True,
        require_runtime_consumer_coverage=True,
    )

    assert summary["schema_version"] == "market_signal_platform_handoff.v1"
    assert summary["artifact_type"] == "market_signal_platform_handoff"
    assert summary["consumer"] == "us_equity:ibit_smart_dca"
    assert summary["canonical_input"] == "derived_indicators"
    assert summary["bundle_id"] == "crypto.btc.derived_indicators.2025-09-17"
    assert summary["source_families"] == [
        "crypto.btc_cycle_daily",
        "us_equity.nasdaq_sp500_context_daily",
        "us_equity.nasdaq_sp500_price_proxy_daily",
        "us_equity.nasdaq_sp500_public_context_daily",
    ]
    assert summary["matched_source_families"] == ("crypto.btc_cycle_daily",)
    assert summary["matched_source_family_count"] == 1
    assert summary["consumer_contract_count"] == 8
    assert summary["all_known_source_families_present"] is True
    assert summary["all_known_consumers_present"] is True
    assert summary["local_contract_registry_verified"] is True
    assert summary["canonical_registry_payload_sha256"] == summary[
        "local_registry_payload_sha256"
    ]
    assert summary["all_runtime_consumers_covered"] is True
    assert summary["signal_bundle_manifest_sha256"] == _sha256(
        bundle_paths["manifest"]
    )

    validation_summary = validate_platform_signal_handoff_manifest(
        handoff_path,
        consumer="us_equity:ibit_smart_dca",
        require_all_known_families=True,
        require_all_known_consumers=True,
        require_runtime_consumer_coverage=True,
    )
    assert validation_summary["sha256"] == _sha256(handoff_path)
    assert validation_summary["all_runtime_consumers_covered"] is True
    assert validation_summary["local_contract_registry_verified"] is True

    cli_handoff_path = tmp_path / "cli_platform_handoff.json"
    result = handoff_main(
        [
            "--signal-bundle-manifest",
            str(bundle_paths["manifest"]),
            "--source-family-catalog-manifest",
            str(catalog_summary["manifest_path"]),
            "--consumer-contract-registry-manifest",
            str(contract_summary["manifest_path"]),
            "--output-manifest",
            str(cli_handoff_path),
            "--consumer",
            "us_equity:ibit_smart_dca",
            "--require-all-known-families",
            "--require-all-known-consumers",
            "--require-runtime-consumer-coverage",
            "--pretty",
        ]
    )
    assert result == 0
    cli_summary = json.loads(capsys.readouterr().out)
    assert cli_summary["path"] == str(cli_handoff_path)
    assert cli_summary["sha256"] == _sha256(cli_handoff_path)
    assert cli_summary["all_runtime_consumers_covered"] is True
    assert cli_summary["local_contract_registry_verified"] is True

    validate_result = handoff_main(
        [
            "--validate-manifest",
            str(cli_handoff_path),
            "--consumer",
            "us_equity:ibit_smart_dca",
            "--require-all-known-families",
            "--require-all-known-consumers",
            "--require-runtime-consumer-coverage",
            "--pretty",
        ]
    )
    assert validate_result == 0
    cli_validate_summary = json.loads(capsys.readouterr().out)
    assert cli_validate_summary["sha256"] == _sha256(cli_handoff_path)
    assert cli_validate_summary["all_runtime_consumers_covered"] is True
    assert cli_validate_summary["local_contract_registry_verified"] is True

    index_path = tmp_path / "platform_handoff_index.json"
    index_summary = write_platform_signal_handoff_index(
        index_path,
        [handoff_path],
        require_all_known_families=True,
        require_all_known_consumers=True,
        require_runtime_consumer_coverage=True,
    )
    assert index_summary["index_schema_version"] == (
        "market_signal_platform_handoff_index.v1"
    )
    assert index_summary["index_artifact_type"] == (
        "market_signal_platform_handoff_index"
    )
    assert index_summary["index_handoff_count"] == 1
    assert index_summary["handoff_manifest_path"] == str(handoff_path.resolve())
    assert index_summary["all_runtime_consumers_covered"] is True
    index_payload = json.loads(index_path.read_text(encoding="utf-8"))
    assert index_payload["handoffs"][0]["all_runtime_consumers_covered"] is True
    assert index_payload["handoffs"][0]["local_contract_registry_verified"] is True
    assert resolve_platform_signal_handoff_manifest_from_index(
        index_path,
        consumer="us_equity:ibit_smart_dca",
        as_of="2025-09-18",
    ) == handoff_path.resolve()

    upsert_summary = upsert_platform_signal_handoff_index(
        index_path,
        cli_handoff_path,
        require_all_known_families=True,
        require_all_known_consumers=True,
        require_runtime_consumer_coverage=True,
    )
    assert upsert_summary["index_handoff_count"] == 1
    assert upsert_summary["handoff_manifest_path"] == str(cli_handoff_path.resolve())
    assert upsert_summary["all_runtime_consumers_covered"] is True
    validation_index_summary = validate_platform_signal_handoff_index(
        index_path,
        consumer="us_equity:ibit_smart_dca",
        as_of="2025-09-18",
        require_all_known_families=True,
        require_all_known_consumers=True,
        require_runtime_consumer_coverage=True,
    )
    assert validation_index_summary["handoff_manifest_sha256"] == _sha256(
        cli_handoff_path
    )
    assert validation_index_summary["all_runtime_consumers_covered"] is True
    assert validation_index_summary["local_contract_registry_verified"] is True

    cli_index_path = tmp_path / "cli_platform_handoff_index.json"
    index_result = handoff_main(
        [
            "--output-index",
            str(cli_index_path),
            "--handoff-manifest",
            str(handoff_path),
            "--require-all-known-families",
            "--require-all-known-consumers",
            "--require-runtime-consumer-coverage",
            "--pretty",
        ]
    )
    assert index_result == 0
    cli_index_summary = json.loads(capsys.readouterr().out)
    assert cli_index_summary["index_path"] == str(cli_index_path.resolve())
    assert cli_index_summary["index_handoff_count"] == 1
    assert cli_index_summary["all_runtime_consumers_covered"] is True
    cli_index_payload = json.loads(cli_index_path.read_text(encoding="utf-8"))
    assert cli_index_payload["handoffs"][0]["all_runtime_consumers_covered"] is True

    validate_index_result = handoff_main(
        [
            "--validate-index",
            str(cli_index_path),
            "--consumer",
            "us_equity:ibit_smart_dca",
            "--as-of",
            "2025-09-18",
            "--require-all-known-families",
            "--require-all-known-consumers",
            "--require-runtime-consumer-coverage",
            "--pretty",
        ]
    )
    assert validate_index_result == 0
    cli_validate_index_summary = json.loads(capsys.readouterr().out)
    assert cli_validate_index_summary["handoff_manifest_sha256"] == _sha256(
        handoff_path
    )
    assert cli_validate_index_summary["all_runtime_consumers_covered"] is True

    consumption_summary = audit_signal_consumption(
        platform_handoff_manifest=handoff_path,
        consumer="us_equity:ibit_smart_dca",
        require_all_known_families=True,
        require_all_known_consumers=True,
        require_runtime_consumer_coverage=True,
    )
    assert consumption_summary["schema_version"] == (
        "market_signal_consumption_audit.v1"
    )
    assert consumption_summary["artifact_type"] == "market_signal_consumption_audit"
    assert consumption_summary["consumption_mode"] == "runtime_platform"
    assert consumption_summary["handoff_source"] == "platform_handoff_manifest"
    assert consumption_summary["ready_for_runtime_injection"] is True
    assert consumption_summary["ready_for_research_consumption"] is False
    assert consumption_summary["runtime_market_data_key"] == "derived_indicators"
    assert consumption_summary["runtime_payload_field"] == "derived_indicators"
    assert consumption_summary["matched_source_families"] == (
        "crypto.btc_cycle_daily",
    )
    assert consumption_summary["matched_source_family_count"] == 1
    assert consumption_summary["linked_manifest_sha256s_verified"] is True
    assert consumption_summary["consumer_contract_verified"] is True
    assert consumption_summary["local_contract_registry_verified"] is True
    assert consumption_summary["canonical_registry_payload_sha256"] == (
        consumption_summary["local_registry_payload_sha256"]
    )
    assert consumption_summary["all_runtime_consumers_covered"] is True
    audit_artifact_path = tmp_path / "consumption_audit.json"
    audit_artifact_summary = write_consumption_audit_artifact(
        audit_artifact_path,
        consumption_summary,
    )
    assert audit_artifact_summary["schema_version"] == (
        "market_signal_consumption_audit.v1"
    )
    assert audit_artifact_summary["consumption_mode"] == "runtime_platform"
    assert audit_artifact_summary["consumer"] == "us_equity:ibit_smart_dca"
    assert audit_artifact_summary["all_runtime_consumers_covered"] is True
    assert audit_artifact_summary["local_contract_registry_verified"] is True
    validated_audit_artifact = validate_consumption_audit_file(audit_artifact_path)
    assert validated_audit_artifact["sha256"] == audit_artifact_summary["sha256"]
    assert validated_audit_artifact["local_contract_registry_verified"] is True
    bad_audit = json.loads(audit_artifact_path.read_text(encoding="utf-8"))
    bad_audit["api_token"] = "redacted"
    bad_audit_path = tmp_path / "bad_consumption_audit.json"
    bad_audit_path.write_text(
        json.dumps(bad_audit, sort_keys=True),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="forbidden key"):
        validate_consumption_audit_file(bad_audit_path)
    injection_plan = runtime_signal_injection_plan(consumption_summary)
    assert injection_plan["schema_version"] == (
        "market_signal_runtime_injection_plan.v1"
    )
    assert injection_plan["artifact_type"] == "market_signal_runtime_injection_plan"
    assert injection_plan["consumer"] == "us_equity:ibit_smart_dca"
    assert injection_plan["market_data_key"] == "derived_indicators"
    assert injection_plan["payload_field"] == "derived_indicators"
    assert injection_plan["target_path"] == "market_data.derived_indicators"
    assert injection_plan["signal_bundle_manifest_sha256"] == _sha256(
        bundle_paths["manifest"]
    )
    assert injection_plan["local_contract_registry_verified"] is True
    assert injection_plan["canonical_registry_payload_sha256"] == (
        injection_plan["local_registry_payload_sha256"]
    )
    injection_plan_path = tmp_path / "runtime_injection_plan.json"
    injection_plan_artifact_summary = write_runtime_signal_injection_plan_artifact(
        injection_plan_path,
        injection_plan,
    )
    assert injection_plan_artifact_summary["schema_version"] == (
        "market_signal_runtime_injection_plan.v1"
    )
    assert injection_plan_artifact_summary["market_data_key"] == "derived_indicators"
    assert injection_plan_artifact_summary["local_contract_registry_verified"] is True
    assert validate_runtime_signal_injection_plan_file(injection_plan_path)[
        "sha256"
    ] == injection_plan_artifact_summary["sha256"]
    plan_audit_match = validate_runtime_signal_injection_plan_matches_audit(
        injection_plan_path,
        audit_artifact_path,
    )
    assert plan_audit_match["matched"] is True
    assert plan_audit_match["consumer"] == "us_equity:ibit_smart_dca"
    assert plan_audit_match["local_contract_registry_verified"] is True

    index_consumption_summary = audit_signal_consumption(
        platform_handoff_index=cli_index_path,
        consumer="us_equity:ibit_smart_dca",
        as_of="2025-09-18",
        require_all_known_families=True,
        require_all_known_consumers=True,
        require_runtime_consumer_coverage=True,
    )
    assert index_consumption_summary["handoff_source"] == "platform_handoff_index"
    assert index_consumption_summary["index_handoff_count"] == 1
    assert index_consumption_summary["lookup_as_of"] == "2025-09-18"
    assert index_consumption_summary["as_of"] == "2025-09-17"
    assert index_consumption_summary["handoff_manifest_sha256"] == _sha256(
        handoff_path
    )
    assert index_consumption_summary["local_contract_registry_verified"] is True

    audit_result = audit_consumption_main(
        [
            "--platform-handoff-index",
            str(cli_index_path),
            "--consumer",
            "us_equity:ibit_smart_dca",
            "--as-of",
            "2025-09-18",
            "--require-all-known-families",
            "--require-all-known-consumers",
            "--require-runtime-consumer-coverage",
            "--pretty",
        ]
    )
    assert audit_result == 0
    cli_consumption_summary = json.loads(capsys.readouterr().out)
    assert cli_consumption_summary["consumption_mode"] == "runtime_platform"
    assert cli_consumption_summary["runtime_injection_allowed"] is True
    assert cli_consumption_summary["consumer"] == "us_equity:ibit_smart_dca"
    assert cli_consumption_summary["lookup_as_of"] == "2025-09-18"
    assert cli_consumption_summary["as_of"] == "2025-09-17"
    assert cli_consumption_summary["all_runtime_consumers_covered"] is True
    cli_audit_artifact_path = tmp_path / "cli_consumption_audit.json"
    write_audit_result = audit_consumption_main(
        [
            "--platform-handoff-index",
            str(cli_index_path),
            "--consumer",
            "us_equity:ibit_smart_dca",
            "--as-of",
            "2025-09-18",
            "--require-all-known-families",
            "--require-all-known-consumers",
            "--require-runtime-consumer-coverage",
            "--output-json",
            str(cli_audit_artifact_path),
            "--pretty",
        ]
    )
    assert write_audit_result == 0
    cli_audit_artifact_summary = json.loads(capsys.readouterr().out)
    assert cli_audit_artifact_summary["path"] == str(cli_audit_artifact_path)
    assert cli_audit_artifact_summary["consumption_mode"] == "runtime_platform"
    assert cli_audit_artifact_summary["lookup_as_of"] == "2025-09-18"
    assert cli_audit_artifact_summary["all_runtime_consumers_covered"] is True
    validate_audit_result = audit_consumption_main(
        [
            "--validate-json",
            str(cli_audit_artifact_path),
            "--pretty",
        ]
    )
    assert validate_audit_result == 0
    cli_validate_audit_summary = json.loads(capsys.readouterr().out)
    assert cli_validate_audit_summary["sha256"] == cli_audit_artifact_summary[
        "sha256"
    ]
    assert cli_validate_audit_summary["lookup_as_of"] == "2025-09-18"
    plan_result = audit_consumption_main(
        [
            "--platform-handoff-index",
            str(cli_index_path),
            "--consumer",
            "us_equity:ibit_smart_dca",
            "--as-of",
            "2025-09-18",
            "--require-all-known-families",
            "--require-all-known-consumers",
            "--require-runtime-consumer-coverage",
            "--runtime-injection-plan",
            "--pretty",
        ]
    )
    assert plan_result == 0
    cli_injection_plan = json.loads(capsys.readouterr().out)
    assert cli_injection_plan["schema_version"] == (
        "market_signal_runtime_injection_plan.v1"
    )
    assert cli_injection_plan["market_data_key"] == "derived_indicators"
    assert cli_injection_plan["target_path"] == "market_data.derived_indicators"
    assert cli_injection_plan["consumer"] == "us_equity:ibit_smart_dca"
    assert cli_injection_plan["matched_source_families"] == [
        "crypto.btc_cycle_daily"
    ]
    cli_plan_artifact_path = tmp_path / "cli_runtime_injection_plan.json"
    write_plan_result = audit_consumption_main(
        [
            "--platform-handoff-index",
            str(cli_index_path),
            "--consumer",
            "us_equity:ibit_smart_dca",
            "--as-of",
            "2025-09-18",
            "--require-all-known-families",
            "--require-all-known-consumers",
            "--require-runtime-consumer-coverage",
            "--output-runtime-plan-json",
            str(cli_plan_artifact_path),
            "--pretty",
        ]
    )
    assert write_plan_result == 0
    cli_plan_artifact_summary = json.loads(capsys.readouterr().out)
    assert cli_plan_artifact_summary[
        "schema_version"
    ] == "market_signal_runtime_injection_plan.v1"
    validate_plan_result = audit_consumption_main(
        [
            "--validate-runtime-plan-json",
            str(cli_plan_artifact_path),
            "--pretty",
        ]
    )
    assert validate_plan_result == 0
    cli_validate_plan_summary = json.loads(capsys.readouterr().out)
    assert cli_validate_plan_summary["sha256"] == cli_plan_artifact_summary[
        "sha256"
    ]
    validate_plan_match_result = audit_consumption_main(
        [
            "--validate-runtime-plan-with-audit",
            str(cli_plan_artifact_path),
            "--audit-json",
            str(cli_audit_artifact_path),
            "--pretty",
        ]
    )
    assert validate_plan_match_result == 0
    cli_validate_plan_match = json.loads(capsys.readouterr().out)
    assert cli_validate_plan_match["schema_version"] == (
        "market_signal_runtime_plan_audit_match.v1"
    )
    assert cli_validate_plan_match["matched"] is True
    assert cli_validate_plan_match["plan_sha256"] == cli_plan_artifact_summary[
        "sha256"
    ]
    bad_plan = json.loads(cli_plan_artifact_path.read_text(encoding="utf-8"))
    bad_plan["as_of"] = "2025-09-17"
    bad_plan_path = tmp_path / "bad_runtime_injection_plan.json"
    bad_plan_path.write_text(
        json.dumps(bad_plan, sort_keys=True),
        encoding="utf-8",
    )
    bad_plan_match_result = audit_consumption_main(
        [
            "--validate-runtime-plan-with-audit",
            str(bad_plan_path),
            "--audit-json",
            str(cli_audit_artifact_path),
        ]
    )
    assert bad_plan_match_result == 2
    assert "as_of!=as_of" in capsys.readouterr().err
    runtime_adapter_config = {
        "schema_version": "market_signal_runtime_adapter_config.v1",
        "strategy": "ibit_smart_dca",
        "signal_consumer": "us_equity:ibit_smart_dca",
        "signal_handoff_index": str(cli_index_path),
        "signal_as_of": "2025-09-18",
        "accepted_freshness_statuses": ["fresh"],
        "require_all_known_families": True,
        "require_all_known_consumers": True,
        "require_runtime_consumer_coverage": True,
        "saved_consumption_audit_json": str(cli_audit_artifact_path),
        "saved_runtime_plan_json": str(cli_plan_artifact_path),
    }
    adapter_config_summary = validate_runtime_adapter_config(runtime_adapter_config)
    assert adapter_config_summary["schema_version"] == (
        "market_signal_runtime_adapter_config.v1"
    )
    assert adapter_config_summary["strategy"] == "ibit_smart_dca"
    assert adapter_config_summary["handoff_source"] == "platform_handoff_index"
    assert adapter_config_summary["require_all_known_families"] is True
    assert adapter_config_summary["require_all_known_consumers"] is True
    assert adapter_config_summary["require_runtime_consumer_coverage"] is True
    assert adapter_config_summary["runtime_plan_requires_audit_match"] is True
    runtime_adapter_config_path = tmp_path / "runtime_adapter_config.json"
    runtime_adapter_config_path.write_text(
        json.dumps(runtime_adapter_config, sort_keys=True),
        encoding="utf-8",
    )
    validate_runtime_adapter_config_result = audit_consumption_main(
        [
            "--validate-runtime-adapter-config-json",
            str(runtime_adapter_config_path),
            "--pretty",
        ]
    )
    assert validate_runtime_adapter_config_result == 0
    cli_validate_adapter_config = json.loads(capsys.readouterr().out)
    assert cli_validate_adapter_config["artifact_type"] == (
        "market_signal_runtime_adapter_config_validation"
    )
    assert cli_validate_adapter_config["sha256"] == _sha256(
        runtime_adapter_config_path
    )
    config_set_summary = validate_runtime_adapter_config_set_files(
        [runtime_adapter_config_path],
        require_all_known_runtime_consumers=True,
    )
    assert config_set_summary["schema_version"] == (
        "market_signal_runtime_adapter_config_set.v1"
    )
    assert config_set_summary["consumers"] == ("us_equity:ibit_smart_dca",)
    assert config_set_summary["all_known_runtime_consumers_present"] is True
    validate_runtime_adapter_config_set_result = audit_consumption_main(
        [
            "--validate-runtime-adapter-config-set-json",
            str(runtime_adapter_config_path),
            "--require-all-known-consumers",
            "--pretty",
        ]
    )
    assert validate_runtime_adapter_config_set_result == 0
    cli_validate_adapter_config_set = json.loads(capsys.readouterr().out)
    assert cli_validate_adapter_config_set["artifact_type"] == (
        "market_signal_runtime_adapter_config_set_validation"
    )
    assert cli_validate_adapter_config_set["all_known_runtime_consumers_present"] is True
    duplicate_runtime_adapter_config_path = (
        tmp_path / "duplicate_runtime_adapter_config.json"
    )
    duplicate_runtime_adapter_config_path.write_text(
        json.dumps(runtime_adapter_config, sort_keys=True),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate consumers"):
        validate_runtime_adapter_config_set_files(
            [runtime_adapter_config_path, duplicate_runtime_adapter_config_path]
        )
    duplicate_config_set_result = audit_consumption_main(
        [
            "--validate-runtime-adapter-config-set-json",
            str(runtime_adapter_config_path),
            str(duplicate_runtime_adapter_config_path),
        ]
    )
    assert duplicate_config_set_result == 2
    assert "duplicate consumers" in capsys.readouterr().err
    deployment_summary = validate_runtime_adapter_deployment_config_file(
        runtime_adapter_config_path
    )
    assert deployment_summary["schema_version"] == (
        "market_signal_runtime_adapter_deployment.v1"
    )
    assert deployment_summary["consumer"] == "us_equity:ibit_smart_dca"
    assert deployment_summary["handoff_path"] == str(cli_index_path)
    assert deployment_summary["audit_handoff_path"] == str(cli_index_path)
    assert deployment_summary["require_all_known_families"] is True
    assert deployment_summary["require_all_known_consumers"] is True
    assert deployment_summary["require_runtime_consumer_coverage"] is True
    assert deployment_summary["runtime_plan_matched"] is True
    validate_runtime_adapter_deployment_result = audit_consumption_main(
        [
            "--validate-runtime-adapter-deployment-json",
            str(runtime_adapter_config_path),
            "--pretty",
        ]
    )
    assert validate_runtime_adapter_deployment_result == 0
    cli_validate_adapter_deployment = json.loads(capsys.readouterr().out)
    assert cli_validate_adapter_deployment["artifact_type"] == (
        "market_signal_runtime_adapter_deployment_validation"
    )
    assert cli_validate_adapter_deployment["runtime_plan_sha256"] == (
        cli_plan_artifact_summary["sha256"]
    )
    deployment_set_summary = validate_runtime_adapter_deployment_config_set_files(
        [runtime_adapter_config_path],
        require_all_known_runtime_consumers=True,
    )
    assert deployment_set_summary["schema_version"] == (
        "market_signal_runtime_adapter_deployment_set.v1"
    )
    assert deployment_set_summary["consumers"] == ("us_equity:ibit_smart_dca",)
    assert deployment_set_summary["all_known_runtime_consumers_present"] is True
    assert deployment_set_summary["deployments"][0]["current_audit_matched"] is True
    validate_runtime_adapter_deployment_set_result = audit_consumption_main(
        [
            "--validate-runtime-adapter-deployment-set-json",
            str(runtime_adapter_config_path),
            "--require-all-known-consumers",
            "--pretty",
        ]
    )
    assert validate_runtime_adapter_deployment_set_result == 0
    cli_validate_adapter_deployment_set = json.loads(capsys.readouterr().out)
    assert cli_validate_adapter_deployment_set["artifact_type"] == (
        "market_signal_runtime_adapter_deployment_set_validation"
    )
    assert cli_validate_adapter_deployment_set[
        "all_known_runtime_consumers_present"
    ] is True
    duplicate_deployment_set_result = audit_consumption_main(
        [
            "--validate-runtime-adapter-deployment-set-json",
            str(runtime_adapter_config_path),
            str(runtime_adapter_config_path),
        ]
    )
    assert duplicate_deployment_set_result == 2
    assert "duplicate consumers" in capsys.readouterr().err
    drifted_audit = json.loads(cli_audit_artifact_path.read_text(encoding="utf-8"))
    drifted_audit["bundle_id"] = "drifted-bundle-id"
    drifted_audit_artifact_path = tmp_path / "drifted_consumption_audit.json"
    drifted_audit_artifact_path.write_text(
        json.dumps(drifted_audit, sort_keys=True),
        encoding="utf-8",
    )
    drifted_runtime_adapter_config = {
        **runtime_adapter_config,
        "saved_consumption_audit_json": str(drifted_audit_artifact_path),
    }
    drifted_runtime_adapter_config_path = (
        tmp_path / "drifted_runtime_adapter_config.json"
    )
    drifted_runtime_adapter_config_path.write_text(
        json.dumps(drifted_runtime_adapter_config, sort_keys=True),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="current audit mismatch"):
        validate_runtime_adapter_deployment_config_file(
            drifted_runtime_adapter_config_path
        )
    drifted_deployment_result = audit_consumption_main(
        [
            "--validate-runtime-adapter-deployment-json",
            str(drifted_runtime_adapter_config_path),
        ]
    )
    assert drifted_deployment_result == 2
    assert "current audit mismatch" in capsys.readouterr().err
    coverage_drifted_audit = json.loads(
        cli_audit_artifact_path.read_text(encoding="utf-8")
    )
    coverage_drifted_audit["all_runtime_consumers_covered"] = False
    coverage_drifted_audit_artifact_path = (
        tmp_path / "coverage_drifted_consumption_audit.json"
    )
    coverage_drifted_audit_artifact_path.write_text(
        json.dumps(coverage_drifted_audit, sort_keys=True),
        encoding="utf-8",
    )
    coverage_drifted_runtime_adapter_config = {
        **runtime_adapter_config,
        "saved_consumption_audit_json": str(coverage_drifted_audit_artifact_path),
    }
    coverage_drifted_runtime_adapter_config_path = (
        tmp_path / "coverage_drifted_runtime_adapter_config.json"
    )
    coverage_drifted_runtime_adapter_config_path.write_text(
        json.dumps(coverage_drifted_runtime_adapter_config, sort_keys=True),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="all_runtime_consumers_covered"):
        validate_runtime_adapter_deployment_config_file(
            coverage_drifted_runtime_adapter_config_path
        )
    coverage_drifted_deployment_result = audit_consumption_main(
        [
            "--validate-runtime-adapter-deployment-json",
            str(coverage_drifted_runtime_adapter_config_path),
        ]
    )
    assert coverage_drifted_deployment_result == 2
    assert "all_runtime_consumers_covered" in capsys.readouterr().err
    lookup_drifted_audit = json.loads(
        cli_audit_artifact_path.read_text(encoding="utf-8")
    )
    lookup_drifted_audit["lookup_as_of"] = "2025-09-19"
    lookup_drifted_audit_artifact_path = (
        tmp_path / "lookup_drifted_consumption_audit.json"
    )
    lookup_drifted_audit_artifact_path.write_text(
        json.dumps(lookup_drifted_audit, sort_keys=True),
        encoding="utf-8",
    )
    lookup_drifted_runtime_adapter_config = {
        **runtime_adapter_config,
        "saved_consumption_audit_json": str(lookup_drifted_audit_artifact_path),
    }
    lookup_drifted_runtime_adapter_config_path = (
        tmp_path / "lookup_drifted_runtime_adapter_config.json"
    )
    lookup_drifted_runtime_adapter_config_path.write_text(
        json.dumps(lookup_drifted_runtime_adapter_config, sort_keys=True),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="lookup_as_of mismatch"):
        validate_runtime_adapter_deployment_config_file(
            lookup_drifted_runtime_adapter_config_path
        )
    lookup_drifted_deployment_result = audit_consumption_main(
        [
            "--validate-runtime-adapter-deployment-json",
            str(lookup_drifted_runtime_adapter_config_path),
        ]
    )
    assert lookup_drifted_deployment_result == 2
    assert "lookup_as_of mismatch" in capsys.readouterr().err
    bad_handoff_runtime_adapter_config = {
        **runtime_adapter_config,
        "signal_handoff_index": str(tmp_path / "other_platform_handoff_index.json"),
    }
    bad_handoff_runtime_adapter_config_path = (
        tmp_path / "bad_handoff_runtime_adapter_config.json"
    )
    bad_handoff_runtime_adapter_config_path.write_text(
        json.dumps(bad_handoff_runtime_adapter_config, sort_keys=True),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="handoff path mismatch"):
        validate_runtime_adapter_deployment_config_file(
            bad_handoff_runtime_adapter_config_path
        )
    bad_handoff_deployment_result = audit_consumption_main(
        [
            "--validate-runtime-adapter-deployment-json",
            str(bad_handoff_runtime_adapter_config_path),
        ]
    )
    assert bad_handoff_deployment_result == 2
    assert "handoff path mismatch" in capsys.readouterr().err
    bad_runtime_adapter_config = {
        **runtime_adapter_config,
        "signal_consumer": "research:ibit_btc_ahr999_precomputed",
    }
    with pytest.raises(ValueError, match="research consumer"):
        validate_runtime_adapter_config(bad_runtime_adapter_config)
    bad_runtime_adapter_config = {
        **runtime_adapter_config,
        "require_runtime_consumer_coverage": "true",
    }
    with pytest.raises(ValueError, match="require_runtime_consumer_coverage"):
        validate_runtime_adapter_config(bad_runtime_adapter_config)

    with pytest.raises(ValueError, match="consumer is required"):
        audit_signal_consumption(platform_handoff_manifest=handoff_path, consumer="")

    bad_index = json.loads(cli_index_path.read_text(encoding="utf-8"))
    bad_index["handoffs"][0]["handoff_manifest_sha256"] = "0" * 64
    cli_index_path.write_text(json.dumps(bad_index), encoding="utf-8")
    with pytest.raises(ValueError, match="handoff_manifest_sha256"):
        validate_platform_signal_handoff_index(cli_index_path)

    catalog_manifest_path = Path(catalog_summary["manifest_path"])
    catalog_manifest = json.loads(catalog_manifest_path.read_text(encoding="utf-8"))
    catalog_manifest_path.write_text(
        json.dumps(catalog_manifest, sort_keys=True),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="source_family_catalog_manifest_sha256"):
        validate_platform_signal_handoff_manifest(
            handoff_path,
            consumer="us_equity:ibit_smart_dca",
            require_all_known_families=True,
            require_all_known_consumers=True,
        )


def test_platform_signal_handoff_rejects_missing_matching_source_family(
    tmp_path,
) -> None:
    input_csv = tmp_path / "btc.csv"
    quality_report_path = tmp_path / "bundle" / "quality_report.json"
    _btc_frame().to_csv(input_csv, index=False)
    write_ohlcv_quality_report(
        quality_report_path,
        input_csv,
        as_of="2025-09-17",
    )
    bundle = build_btc_cycle_signal_bundle(
        _btc_frame(),
        as_of="2025-09-17",
        raw_artifact_sha256=_sha256(input_csv),
        generated_at="2025-09-17T00:15:00Z",
    )
    bundle_paths = write_signal_bundle_artifacts(
        tmp_path / "bundle",
        bundle,
        quality_report_path=quality_report_path,
    )
    non_crypto_catalog_summary = write_signal_source_family_catalog_artifacts(
        tmp_path / "source-catalog",
        families=("us_equity.nasdaq_sp500_context_daily",),
    )
    contract_summary = write_consumer_contract_registry_artifacts(
        tmp_path / "contracts",
    )

    with pytest.raises(ValueError, match="missing family for consumer and transform"):
        write_platform_signal_handoff_manifest(
            tmp_path / "platform_handoff.json",
            signal_bundle_manifest=bundle_paths["manifest"],
            source_family_catalog_manifest=non_crypto_catalog_summary["manifest_path"],
            consumer_contract_registry_manifest=contract_summary["manifest_path"],
            consumer="us_equity:ibit_smart_dca",
        )


def test_platform_signal_handoff_rejects_research_consumer_runtime_handoff(
    tmp_path,
) -> None:
    input_csv = tmp_path / "btc.csv"
    quality_report_path = tmp_path / "bundle" / "quality_report.json"
    _btc_frame().to_csv(input_csv, index=False)
    write_ohlcv_quality_report(
        quality_report_path,
        input_csv,
        as_of="2025-09-17",
    )
    bundle = build_btc_cycle_signal_bundle(
        _btc_frame(),
        as_of="2025-09-17",
        raw_artifact_sha256=_sha256(input_csv),
        generated_at="2025-09-17T00:15:00Z",
    )
    bundle_paths = write_signal_bundle_artifacts(
        tmp_path / "bundle",
        bundle,
        quality_report_path=quality_report_path,
    )
    catalog_summary = write_signal_source_family_catalog_artifacts(
        tmp_path / "source-catalog",
    )
    contract_summary = write_consumer_contract_registry_artifacts(
        tmp_path / "contracts",
    )

    with pytest.raises(ValueError, match="missing family for consumer and transform"):
        write_platform_signal_handoff_manifest(
            tmp_path / "platform_handoff.json",
            signal_bundle_manifest=bundle_paths["manifest"],
            source_family_catalog_manifest=catalog_summary["manifest_path"],
            consumer_contract_registry_manifest=contract_summary["manifest_path"],
            consumer="research:ibit_btc_ahr999_precomputed",
        )


def test_platform_signal_handoff_rejects_registry_missing_runtime_consumer(
    tmp_path,
) -> None:
    input_csv = tmp_path / "btc.csv"
    quality_report_path = tmp_path / "bundle" / "quality_report.json"
    _btc_frame().to_csv(input_csv, index=False)
    write_ohlcv_quality_report(
        quality_report_path,
        input_csv,
        as_of="2025-09-17",
    )
    bundle = build_btc_cycle_signal_bundle(
        _btc_frame(),
        as_of="2025-09-17",
        raw_artifact_sha256=_sha256(input_csv),
        generated_at="2025-09-17T00:15:00Z",
    )
    bundle_paths = write_signal_bundle_artifacts(
        tmp_path / "bundle",
        bundle,
        quality_report_path=quality_report_path,
    )
    catalog_summary = write_signal_source_family_catalog_artifacts(
        tmp_path / "source-catalog",
    )
    contract_summary = write_consumer_contract_registry_artifacts(
        tmp_path / "contracts",
        consumers=("research:nasdaq_sp500_price_proxy",),
    )

    with pytest.raises(
        ValueError,
        match="consumer contract registry missing consumer",
    ):
        write_platform_signal_handoff_manifest(
            tmp_path / "platform_handoff.json",
            signal_bundle_manifest=bundle_paths["manifest"],
            source_family_catalog_manifest=catalog_summary["manifest_path"],
            consumer_contract_registry_manifest=contract_summary["manifest_path"],
            consumer="us_equity:ibit_smart_dca",
        )


def test_research_signal_handoff_manifest_pins_research_csv_contracts(
    tmp_path,
    capsys,
) -> None:
    fred_csv = tmp_path / "inputs" / "fred_vixcls.csv"
    shiller_csv = tmp_path / "inputs" / "shiller_cape.csv"
    output_csv = tmp_path / "research" / "us_equity_public_context.csv"
    research_manifest_path = (
        tmp_path / "research" / "us_equity_public_context.manifest.json"
    )
    quality_report_path = (
        tmp_path / "research" / "us_equity_public_context.quality.json"
    )
    fred_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "DATE": ["2025-01-02", "2025-01-03", "2025-01-06"],
            "VIXCLS": [20.0, 25.0, 30.0],
        }
    ).to_csv(fred_csv, index=False)
    pd.DataFrame(
        {
            "date": ["2024-12-31", "2025-01-06"],
            "cape": [30.0, 25.0],
        }
    ).to_csv(shiller_csv, index=False)

    export_result = export_us_equity_public_context_main(
        [
            "--fred-vixcls-csv",
            str(fred_csv),
            "--shiller-cape-csv",
            str(shiller_csv),
            "--output-csv",
            str(output_csv),
            "--manifest-path",
            str(research_manifest_path),
            "--quality-report",
            str(quality_report_path),
            "--as-of",
            "2025-01-06",
        ]
    )
    assert export_result == 0
    capsys.readouterr()

    catalog_summary = write_signal_source_family_catalog_artifacts(
        tmp_path / "source-catalog",
        families=("us_equity.nasdaq_sp500_public_context_daily",),
    )
    contract_summary = write_consumer_contract_registry_artifacts(
        tmp_path / "contracts",
        consumers=("research:nasdaq_sp500_cape_vix_external_context_precomputed",),
    )
    handoff_path = tmp_path / "research_handoff.json"

    summary = write_research_signal_handoff_manifest(
        handoff_path,
        research_export_manifest=research_manifest_path,
        source_family_catalog_manifest=catalog_summary["manifest_path"],
        consumer_contract_registry_manifest=contract_summary["manifest_path"],
        consumer="research:nasdaq_sp500_cape_vix_external_context_precomputed",
    )

    assert summary["schema_version"] == "market_signal_research_handoff.v1"
    assert summary["artifact_type"] == "market_signal_research_handoff"
    assert summary["consumer"] == (
        "research:nasdaq_sp500_cape_vix_external_context_precomputed"
    )
    assert summary["research_transform"] == "us_equity.nasdaq_sp500.context.v1"
    assert summary["research_quality_report_sha256"] == _sha256(quality_report_path)
    assert summary["source_families"] == (
        "us_equity.nasdaq_sp500_public_context_daily",
    )
    assert summary["consumer_contracts"] == (
        "research:nasdaq_sp500_cape_vix_external_context_precomputed",
    )
    assert summary["local_contract_registry_verified"] is True
    assert summary["canonical_registry_payload_sha256"] == summary[
        "local_registry_payload_sha256"
    ]
    assert summary["summary_verified"] is True

    validation_summary = validate_research_signal_handoff_manifest(
        handoff_path,
        consumer="research:nasdaq_sp500_cape_vix_external_context_precomputed",
    )
    assert validation_summary["sha256"] == _sha256(handoff_path)
    assert validation_summary["local_contract_registry_verified"] is True

    cli_handoff_path = tmp_path / "cli_research_handoff.json"
    write_result = research_handoff_main(
        [
            "--output-manifest",
            str(cli_handoff_path),
            "--research-export-manifest",
            str(research_manifest_path),
            "--source-family-catalog-manifest",
            str(catalog_summary["manifest_path"]),
            "--consumer-contract-registry-manifest",
            str(contract_summary["manifest_path"]),
            "--consumer",
            "research:nasdaq_sp500_cape_vix_external_context_precomputed",
            "--pretty",
        ]
    )
    assert write_result == 0
    cli_summary = json.loads(capsys.readouterr().out)
    assert cli_summary["path"] == str(cli_handoff_path.resolve())
    assert cli_summary["source_families"] == [
        "us_equity.nasdaq_sp500_public_context_daily"
    ]

    validate_result = research_handoff_main(
        [
            "--validate-manifest",
            str(cli_handoff_path),
            "--consumer",
            "research:nasdaq_sp500_cape_vix_external_context_precomputed",
            "--pretty",
        ]
    )
    assert validate_result == 0
    cli_validate_summary = json.loads(capsys.readouterr().out)
    assert cli_validate_summary["sha256"] == _sha256(cli_handoff_path)

    consumption_summary = audit_signal_consumption(
        research_handoff_manifest=handoff_path,
        consumer="research:nasdaq_sp500_cape_vix_external_context_precomputed",
    )
    assert consumption_summary["schema_version"] == (
        "market_signal_consumption_audit.v1"
    )
    assert consumption_summary["artifact_type"] == "market_signal_consumption_audit"
    assert consumption_summary["consumption_mode"] == "offline_research"
    assert consumption_summary["handoff_source"] == "research_handoff_manifest"
    assert consumption_summary["ready_for_research_consumption"] is True
    assert consumption_summary["ready_for_runtime_injection"] is False
    assert consumption_summary["runtime_injection_allowed"] is False
    assert consumption_summary["research_transform"] == (
        "us_equity.nasdaq_sp500.context.v1"
    )
    assert consumption_summary["linked_manifest_sha256s_verified"] is True
    assert consumption_summary["summary_verified"] is True
    research_audit_artifact_path = tmp_path / "research_consumption_audit.json"
    research_audit_artifact_summary = write_consumption_audit_artifact(
        research_audit_artifact_path,
        consumption_summary,
    )
    assert research_audit_artifact_summary["consumption_mode"] == "offline_research"
    assert research_audit_artifact_summary["ready_for_runtime_injection"] is False
    assert (
        validate_consumption_audit_file(research_audit_artifact_path)[
            "runtime_injection_allowed"
        ]
        is False
    )
    with pytest.raises(ValueError, match="not runtime-injectable"):
        runtime_signal_injection_plan(consumption_summary)

    audit_result = audit_consumption_main(
        [
            "--research-handoff-manifest",
            str(cli_handoff_path),
            "--consumer",
            "research:nasdaq_sp500_cape_vix_external_context_precomputed",
            "--pretty",
        ]
    )
    assert audit_result == 0
    cli_consumption_summary = json.loads(capsys.readouterr().out)
    assert cli_consumption_summary["consumption_mode"] == "offline_research"
    assert cli_consumption_summary["runtime_injection_allowed"] is False
    assert cli_consumption_summary["consumer"] == (
        "research:nasdaq_sp500_cape_vix_external_context_precomputed"
    )
    cli_research_audit_artifact_path = tmp_path / "cli_research_consumption_audit.json"
    write_research_audit_result = audit_consumption_main(
        [
            "--research-handoff-manifest",
            str(cli_handoff_path),
            "--consumer",
            "research:nasdaq_sp500_cape_vix_external_context_precomputed",
            "--output-json",
            str(cli_research_audit_artifact_path),
            "--pretty",
        ]
    )
    assert write_research_audit_result == 0
    cli_research_audit_artifact_summary = json.loads(capsys.readouterr().out)
    assert cli_research_audit_artifact_summary[
        "consumption_mode"
    ] == "offline_research"
    validate_research_audit_result = audit_consumption_main(
        [
            "--validate-json",
            str(cli_research_audit_artifact_path),
            "--pretty",
        ]
    )
    assert validate_research_audit_result == 0
    cli_validate_research_audit = json.loads(capsys.readouterr().out)
    assert cli_validate_research_audit["sha256"] == (
        cli_research_audit_artifact_summary["sha256"]
    )
    plan_result = audit_consumption_main(
        [
            "--research-handoff-manifest",
            str(cli_handoff_path),
            "--consumer",
            "research:nasdaq_sp500_cape_vix_external_context_precomputed",
            "--runtime-injection-plan",
        ]
    )
    assert plan_result == 2
    assert "not runtime-injectable" in capsys.readouterr().err
    write_research_plan_result = audit_consumption_main(
        [
            "--research-handoff-manifest",
            str(cli_handoff_path),
            "--consumer",
            "research:nasdaq_sp500_cape_vix_external_context_precomputed",
            "--output-runtime-plan-json",
            str(tmp_path / "bad_research_runtime_plan.json"),
        ]
    )
    assert write_research_plan_result == 2
    assert "not runtime-injectable" in capsys.readouterr().err

    wrong_consumer_result = research_handoff_main(
        [
            "--validate-manifest",
            str(cli_handoff_path),
            "--consumer",
            "research:nasdaq_sp500_external_context_precomputed",
        ]
    )
    assert wrong_consumer_result == 2
    assert "missing family for consumer" in capsys.readouterr().err

    crypto_catalog_summary = write_signal_source_family_catalog_artifacts(
        tmp_path / "crypto-source-catalog",
        families=("crypto.btc_cycle_daily",),
    )
    with pytest.raises(ValueError, match="missing family for transform"):
        write_research_signal_handoff_manifest(
            tmp_path / "bad_research_handoff.json",
            research_export_manifest=research_manifest_path,
            source_family_catalog_manifest=crypto_catalog_summary["manifest_path"],
            consumer_contract_registry_manifest=contract_summary["manifest_path"],
        )


def test_research_signal_handoff_manifest_accepts_price_proxy_contract(
    tmp_path,
    capsys,
) -> None:
    nasdaq100_csv = tmp_path / "inputs" / "fred_nasdaq100.csv"
    sp500_csv = tmp_path / "inputs" / "fred_sp500.csv"
    output_csv = tmp_path / "research" / "us_equity_price_proxy.csv"
    research_manifest_path = (
        tmp_path / "research" / "us_equity_price_proxy.manifest.json"
    )
    nasdaq100_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "DATE": ["2025-01-02", "2025-01-03", "2025-01-06"],
            "NASDAQ100": [100.0, 101.0, 102.0],
        }
    ).to_csv(nasdaq100_csv, index=False)
    pd.DataFrame(
        {
            "DATE": ["2025-01-02", "2025-01-03", "2025-01-06"],
            "SP500": [50.0, 51.0, 52.0],
        }
    ).to_csv(sp500_csv, index=False)

    export_result = export_us_equity_price_proxy_main(
        [
            "--fred-nasdaq100-csv",
            str(nasdaq100_csv),
            "--fred-sp500-csv",
            str(sp500_csv),
            "--output-csv",
            str(output_csv),
            "--manifest-path",
            str(research_manifest_path),
            "--as-of",
            "2025-01-06",
        ]
    )
    assert export_result == 0
    capsys.readouterr()

    catalog_summary = write_signal_source_family_catalog_artifacts(
        tmp_path / "source-catalog",
        families=("us_equity.nasdaq_sp500_price_proxy_daily",),
    )
    contract_summary = write_consumer_contract_registry_artifacts(
        tmp_path / "contracts",
        consumers=("research:nasdaq_sp500_price_proxy",),
    )
    handoff_path = tmp_path / "research_price_proxy_handoff.json"

    summary = write_research_signal_handoff_manifest(
        handoff_path,
        research_export_manifest=research_manifest_path,
        source_family_catalog_manifest=catalog_summary["manifest_path"],
        consumer_contract_registry_manifest=contract_summary["manifest_path"],
        consumer="research:nasdaq_sp500_price_proxy",
    )

    assert summary["research_transform"] == "us_equity.nasdaq_sp500.price_proxy.v1"
    assert summary["source_families"] == (
        "us_equity.nasdaq_sp500_price_proxy_daily",
    )
    assert summary["consumer_contracts"] == ("research:nasdaq_sp500_price_proxy",)
    assert summary["summary_verified"] is True

    validation_summary = validate_research_signal_handoff_manifest(
        handoff_path,
        consumer="research:nasdaq_sp500_price_proxy",
    )
    assert validation_summary["sha256"] == _sha256(handoff_path)


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
    assert "ahr999_365d_percentile" in summary["columns"]
    assert "mayer_multiple" in exported.columns
    assert "realized_volatility_30d" in exported.columns

    validation_summary = validate_research_export_manifest(
        manifest_path,
        expected_artifact_type="btc_cycle_research_csv",
        expected_transform="crypto.btc.ahr999.v1",
    )
    assert validation_summary["row_count"] == 5
    assert validation_summary["output_csv_sha256"] == _sha256(output_csv)
    assert validation_summary["output_csv_size_bytes"] == output_csv.stat().st_size

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

    catalog_summary = write_signal_source_family_catalog_artifacts(
        tmp_path / "btc-source-catalog"
    )
    contract_summary = write_consumer_contract_registry_artifacts(
        tmp_path / "btc-contracts"
    )
    handoff_path = tmp_path / "btc_research_handoff.json"
    handoff_summary = write_research_signal_handoff_manifest(
        handoff_path,
        research_export_manifest=manifest_path,
        source_family_catalog_manifest=catalog_summary["manifest_path"],
        consumer_contract_registry_manifest=contract_summary["manifest_path"],
        consumer="research:ibit_btc_ahr999_mayer_precomputed_variants",
        require_all_known_families=True,
        require_all_known_consumers=True,
        require_runtime_consumer_coverage=True,
    )
    assert handoff_summary["all_runtime_consumers_covered"] is True
    assert handoff_summary["source_families"] == ("crypto.btc_cycle_daily",)
    handoff_payload = json.loads(handoff_path.read_text(encoding="utf-8"))
    assert handoff_payload["all_runtime_consumers_covered"] is True

    validation_handoff_summary = validate_research_signal_handoff_manifest(
        handoff_path,
        consumer="research:ibit_btc_ahr999_mayer_precomputed_variants",
        require_all_known_families=True,
        require_all_known_consumers=True,
        require_runtime_consumer_coverage=True,
    )
    assert validation_handoff_summary["sha256"] == _sha256(handoff_path)
    assert validation_handoff_summary["all_runtime_consumers_covered"] is True

    cli_handoff_path = tmp_path / "cli_btc_research_handoff.json"
    write_handoff_result = research_handoff_main(
        [
            "--output-manifest",
            str(cli_handoff_path),
            "--research-export-manifest",
            str(manifest_path),
            "--source-family-catalog-manifest",
            str(catalog_summary["manifest_path"]),
            "--consumer-contract-registry-manifest",
            str(contract_summary["manifest_path"]),
            "--consumer",
            "research:ibit_btc_ahr999_mayer_precomputed_variants",
            "--require-all-known-families",
            "--require-all-known-consumers",
            "--require-runtime-consumer-coverage",
            "--pretty",
        ]
    )
    assert write_handoff_result == 0
    cli_handoff_summary = json.loads(capsys.readouterr().out)
    assert cli_handoff_summary["all_runtime_consumers_covered"] is True

    validate_handoff_result = research_handoff_main(
        [
            "--validate-manifest",
            str(cli_handoff_path),
            "--consumer",
            "research:ibit_btc_ahr999_mayer_precomputed_variants",
            "--require-all-known-families",
            "--require-all-known-consumers",
            "--require-runtime-consumer-coverage",
            "--pretty",
        ]
    )
    assert validate_handoff_result == 0
    cli_validate_handoff_summary = json.loads(capsys.readouterr().out)
    assert cli_validate_handoff_summary["all_runtime_consumers_covered"] is True


def test_cli_exports_us_equity_context_research_csv(tmp_path, capsys) -> None:
    dates = pd.date_range("2025-01-02", periods=5, freq="B")
    input_csv = tmp_path / "us_equity_context_raw.csv"
    output_csv = tmp_path / "research" / "us_equity_context.csv"
    manifest_path = tmp_path / "research" / "us_equity_context.manifest.json"
    quality_report_path = tmp_path / "research" / "us_equity_context.quality.json"
    pd.DataFrame(
        {
            "date": dates.date,
            "QQQ": [100.0, 101.0, 102.0, 103.0, 104.0],
            "SPY": [90.0, 91.0, 92.0, 93.0, 94.0],
            "cape_percentile": [0.70, 0.80, 0.90, 0.85, 0.88],
            "vix_percentile": [0.20, 0.40, 0.85, 0.75, 0.65],
            "breadth_above_sma200_pct": [0.60, 0.50, 0.35, 0.45, 0.40],
        }
    ).to_csv(input_csv, index=False)

    result = export_us_equity_context_main(
        [
            "--input-csv",
            str(input_csv),
            "--output-csv",
            str(output_csv),
            "--manifest-path",
            str(manifest_path),
            "--quality-report",
            str(quality_report_path),
            "--as-of",
            "2025-01-07",
            "--pretty",
        ]
    )

    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    exported = pd.read_csv(output_csv)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    quality_report = json.loads(quality_report_path.read_text(encoding="utf-8"))
    assert summary["artifact_type"] == "us_equity_context_research_csv"
    assert summary["transform"] == "us_equity.nasdaq_sp500.context.v1"
    assert summary["quality_report"] == str(quality_report_path)
    assert summary["quality_status"] == "warn"
    assert summary["row_count"] == 4
    assert summary["last_date"] == "2025-01-07"
    assert manifest["artifact_type"] == "us_equity_context_research_csv"
    assert manifest["transform"] == "us_equity.nasdaq_sp500.context.v1"
    assert manifest["input_csv"]["sha256"] == _sha256(input_csv)
    assert manifest["output_csv"]["sha256"] == _sha256(output_csv)
    assert manifest["quality_report"]["sha256"] == _sha256(quality_report_path)
    assert (
        manifest["quality_report"]["size_bytes"]
        == quality_report_path.stat().st_size
    )
    assert quality_report["schema_version"] == (
        "us_equity_context_availability_report.v1"
    )
    assert quality_report["artifact_type"] == "us_equity_context_availability_report"
    assert quality_report["quality_status"] == "warn"
    assert quality_report["filtered_after_as_of_count"] == 1
    assert quality_report["normalized_row_count"] == 4
    assert quality_report["failure_reasons"] == []
    assert quality_report["provider_timestamp_missing_column"] is True
    assert quality_report["breadth_universe_snapshot_missing_column"] is True
    assert quality_report["breadth_universe_as_of_missing_column"] is True
    assert quality_report["warning_reasons"] == [
        "rows_after_as_of_filtered",
        "missing_provider_timestamp_column",
        "missing_breadth_universe_snapshot_column",
        "missing_breadth_universe_as_of_column",
    ]
    assert list(exported.columns) == [
        "date",
        "QQQ",
        "SPY",
        "cape_percentile",
        "vix_percentile",
        "breadth_above_sma200_pct",
        "provider_timestamp",
    ]

    validation_summary = validate_research_export_manifest(
        manifest_path,
        expected_artifact_type="us_equity_context_research_csv",
        expected_transform="us_equity.nasdaq_sp500.context.v1",
    )
    assert validation_summary["row_count"] == 4
    assert validation_summary["columns"] == tuple(exported.columns)
    assert validation_summary["quality_report_sha256"] == _sha256(quality_report_path)
    assert validation_summary["quality_report_sha256_verified"] is True


def test_cli_exports_us_equity_public_context_research_csv(
    tmp_path,
    capsys,
) -> None:
    fred_csv = tmp_path / "fred_vixcls.csv"
    shiller_csv = tmp_path / "shiller_cape.csv"
    output_csv = tmp_path / "research" / "us_equity_public_context.csv"
    manifest_path = tmp_path / "research" / "us_equity_public_context.manifest.json"
    quality_report_path = (
        tmp_path / "research" / "us_equity_public_context.quality.json"
    )
    pd.DataFrame(
        {
            "DATE": [
                "2025-01-02",
                "2025-01-03",
                "2025-01-06",
                "2025-01-07",
                "2025-01-08",
            ],
            "VIXCLS": ["20", ".", "10", "30", "25"],
        }
    ).to_csv(fred_csv, index=False)
    pd.DataFrame(
        {
            "date": ["2024-12-31", "2025-01-06", "2025-02-01"],
            "cape": [30.0, 25.0, 40.0],
        }
    ).to_csv(shiller_csv, index=False)

    result = export_us_equity_public_context_main(
        [
            "--fred-vixcls-csv",
            str(fred_csv),
            "--shiller-cape-csv",
            str(shiller_csv),
            "--output-csv",
            str(output_csv),
            "--manifest-path",
            str(manifest_path),
            "--quality-report",
            str(quality_report_path),
            "--as-of",
            "2025-01-07",
            "--pretty",
        ]
    )

    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    exported = pd.read_csv(output_csv)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    quality_report = json.loads(quality_report_path.read_text(encoding="utf-8"))
    assert summary["artifact_type"] == "us_equity_context_research_csv"
    assert summary["transform"] == "us_equity.nasdaq_sp500.context.v1"
    assert summary["quality_report"] == str(quality_report_path)
    assert summary["quality_status"] == "warn"
    assert summary["row_count"] == 3
    assert list(exported.columns) == [
        "date",
        "cape_percentile",
        "vix_percentile",
        "provider_timestamp",
    ]
    assert exported["date"].tolist() == [
        "2025-01-02",
        "2025-01-06",
        "2025-01-07",
    ]
    assert exported["cape_percentile"].round(4).tolist() == [1.0, 0.5, 0.5]
    assert exported["vix_percentile"].round(4).tolist() == [1.0, 0.5, 1.0]
    assert manifest["artifact_type"] == "us_equity_context_research_csv"
    assert manifest["transform"] == "us_equity.nasdaq_sp500.context.v1"
    assert manifest["input_csv"]["sha256"] == _sha256(fred_csv)
    assert manifest["output_csv"]["sha256"] == _sha256(output_csv)
    assert manifest["quality_report"]["sha256"] == _sha256(quality_report_path)
    assert (
        manifest["quality_report"]["size_bytes"]
        == quality_report_path.stat().st_size
    )
    assert [record["source_id"] for record in manifest["input_sources"]] == [
        "fred.vixcls",
        "shiller.cape_monthly",
    ]
    assert manifest["input_sources"][1]["sha256"] == _sha256(shiller_csv)
    assert manifest["transform_parameters"]["cape_alignment"] == "asof_backward"
    assert manifest["transform_parameters"]["max_shiller_cape_lag_days"] == 120
    assert quality_report["schema_version"] == (
        "us_equity_public_context_availability_report.v1"
    )
    assert quality_report["artifact_type"] == (
        "us_equity_public_context_availability_report"
    )
    assert quality_report["quality_status"] == "warn"
    assert quality_report["public_context_row_count"] == 3
    assert quality_report["input_sources"][0]["source_id"] == "fred.vixcls"
    assert quality_report["input_sources"][0]["null_value_count"] == 1
    assert quality_report["input_sources"][0]["filtered_after_as_of_count"] == 1
    assert quality_report["input_sources"][0]["latest_observation_lag_days"] == 0
    assert quality_report["input_sources"][0]["max_allowed_lag_days"] == 10
    assert quality_report["input_sources"][1]["source_id"] == "shiller.cape_monthly"
    assert quality_report["input_sources"][1]["filtered_after_as_of_count"] == 1
    assert quality_report["input_sources"][1]["latest_observation_lag_days"] == 1
    assert quality_report["input_sources"][1]["max_allowed_lag_days"] == 120

    validation_summary = validate_research_export_manifest(
        manifest_path,
        expected_artifact_type="us_equity_context_research_csv",
        expected_transform="us_equity.nasdaq_sp500.context.v1",
    )
    assert validation_summary["row_count"] == 3
    assert validation_summary["columns"] == tuple(exported.columns)
    assert validation_summary["quality_report_sha256"] == _sha256(quality_report_path)
    assert (
        validation_summary["quality_report_size_bytes"]
        == quality_report_path.stat().st_size
    )


def test_cli_exports_us_equity_price_proxy_research_csv(
    tmp_path,
    capsys,
) -> None:
    nasdaq100_csv = tmp_path / "fred_nasdaq100.csv"
    sp500_csv = tmp_path / "fred_sp500.csv"
    output_csv = tmp_path / "research" / "us_equity_price_proxy.csv"
    manifest_path = tmp_path / "research" / "us_equity_price_proxy.manifest.json"
    pd.DataFrame(
        {
            "DATE": [
                "2025-01-02",
                "2025-01-03",
                "bad-date",
                "2025-01-07",
                "2025-01-08",
            ],
            "NASDAQ100": [100.0, 101.0, 102.0, 103.0, 104.0],
        }
    ).to_csv(nasdaq100_csv, index=False)
    pd.DataFrame(
        {
            "DATE": [
                "2025-01-02",
                "2025-01-03",
                "2025-01-06",
                "2025-01-07",
                "2025-01-08",
            ],
            "SP500": [50.0, 51.0, 52.0, 53.0, 54.0],
        }
    ).to_csv(sp500_csv, index=False)

    result = export_us_equity_price_proxy_main(
        [
            "--fred-nasdaq100-csv",
            str(nasdaq100_csv),
            "--fred-sp500-csv",
            str(sp500_csv),
            "--output-csv",
            str(output_csv),
            "--manifest-path",
            str(manifest_path),
            "--as-of",
            "2025-01-07",
            "--pretty",
        ]
    )

    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    exported = pd.read_csv(output_csv)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert summary["artifact_type"] == "us_equity_price_proxy_research_csv"
    assert summary["transform"] == "us_equity.nasdaq_sp500.price_proxy.v1"
    assert summary["row_count"] == 3
    assert summary["last_date"] == "2025-01-07"
    assert list(exported.columns) == [
        "date",
        "QQQ",
        "SPY",
        "provider_timestamp",
    ]
    assert exported["date"].tolist() == [
        "2025-01-02",
        "2025-01-03",
        "2025-01-07",
    ]
    assert exported["QQQ"].tolist() == [100.0, 101.0, 103.0]
    assert exported["SPY"].tolist() == [50.0, 51.0, 53.0]
    assert manifest["artifact_type"] == "us_equity_price_proxy_research_csv"
    assert manifest["transform"] == "us_equity.nasdaq_sp500.price_proxy.v1"
    assert manifest["input_csv"]["sha256"] == _sha256(nasdaq100_csv)
    assert manifest["output_csv"]["sha256"] == _sha256(output_csv)
    assert [record["source_id"] for record in manifest["input_sources"]] == [
        "fred.nasdaq100",
        "fred.sp500",
    ]
    assert manifest["input_sources"][1]["sha256"] == _sha256(sp500_csv)
    assert manifest["transform_parameters"]["price_alignment"] == (
        "exact_date_inner_join"
    )

    validation_summary = validate_research_export_manifest(
        manifest_path,
        expected_artifact_type="us_equity_price_proxy_research_csv",
        expected_transform="us_equity.nasdaq_sp500.price_proxy.v1",
    )
    assert validation_summary["row_count"] == 3
    assert validation_summary["columns"] == tuple(exported.columns)
    assert validation_summary["output_csv_sha256"] == _sha256(output_csv)


def test_public_context_quality_report_rejects_stale_cape_source(
    tmp_path,
    capsys,
) -> None:
    fred_csv = tmp_path / "fred_vixcls.csv"
    shiller_csv = tmp_path / "shiller_cape.csv"
    output_csv = tmp_path / "research" / "us_equity_public_context.csv"
    manifest_path = tmp_path / "research" / "us_equity_public_context.manifest.json"
    quality_report_path = (
        tmp_path / "research" / "us_equity_public_context.quality.json"
    )
    pd.DataFrame(
        {
            "DATE": ["2026-06-17", "2026-06-18", "2026-06-19"],
            "VIXCLS": [18.44, 18.10, 17.90],
        }
    ).to_csv(fred_csv, index=False)
    pd.DataFrame(
        {
            "date": ["2023-08-31", "2023-09-30"],
            "cape": [30.47, 30.81],
        }
    ).to_csv(shiller_csv, index=False)

    result = export_us_equity_public_context_main(
        [
            "--fred-vixcls-csv",
            str(fred_csv),
            "--shiller-cape-csv",
            str(shiller_csv),
            "--output-csv",
            str(output_csv),
            "--manifest-path",
            str(manifest_path),
            "--quality-report",
            str(quality_report_path),
            "--as-of",
            "2026-06-19",
        ]
    )

    assert result == 2
    assert "shiller.cape_monthly:latest_observation_stale" in capsys.readouterr().err
    quality_report = json.loads(quality_report_path.read_text(encoding="utf-8"))
    assert quality_report["quality_status"] == "fail"
    assert "shiller.cape_monthly:latest_observation_stale" in quality_report[
        "failure_reasons"
    ]
    shiller_source = quality_report["input_sources"][1]
    assert shiller_source["latest_observation_lag_days"] > 120
    assert shiller_source["max_allowed_lag_days"] == 120
    assert not output_csv.exists()


def test_research_export_validator_rejects_quality_report_drift(
    tmp_path,
    capsys,
) -> None:
    fred_csv = tmp_path / "fred_vixcls.csv"
    shiller_csv = tmp_path / "shiller_cape.csv"
    output_csv = tmp_path / "research" / "us_equity_public_context.csv"
    manifest_path = tmp_path / "research" / "us_equity_public_context.manifest.json"
    quality_report_path = (
        tmp_path / "research" / "us_equity_public_context.quality.json"
    )
    pd.DataFrame(
        {
            "DATE": ["2025-01-02", "2025-01-03", "2025-01-06"],
            "VIXCLS": ["20", "25", "30"],
        }
    ).to_csv(fred_csv, index=False)
    pd.DataFrame(
        {
            "date": ["2024-12-31", "2025-01-06"],
            "cape": [30.0, 25.0],
        }
    ).to_csv(shiller_csv, index=False)

    result = export_us_equity_public_context_main(
        [
            "--fred-vixcls-csv",
            str(fred_csv),
            "--shiller-cape-csv",
            str(shiller_csv),
            "--output-csv",
            str(output_csv),
            "--manifest-path",
            str(manifest_path),
            "--quality-report",
            str(quality_report_path),
            "--as-of",
            "2025-01-06",
        ]
    )

    assert result == 0
    capsys.readouterr()
    quality_report = json.loads(quality_report_path.read_text(encoding="utf-8"))
    quality_report["warning_reasons"] = ["tampered_after_export"]
    quality_report_path.write_text(
        json.dumps(quality_report, sort_keys=True),
        encoding="utf-8",
    )

    with pytest.raises(SignalBundleValidationError, match="quality_report.sha256"):
        validate_research_export_manifest(manifest_path)


def test_us_equity_context_quality_report_checks_point_in_time_metadata(
    tmp_path,
    capsys,
) -> None:
    dates = pd.date_range("2025-01-02", periods=4, freq="B")
    input_csv = tmp_path / "us_equity_context_raw.csv"
    strict_output_csv = tmp_path / "research" / "strict_us_equity_context.csv"
    strict_quality_report_path = (
        tmp_path / "research" / "strict_us_equity_context.quality.json"
    )
    ok_output_csv = tmp_path / "research" / "ok_us_equity_context.csv"
    ok_quality_report_path = tmp_path / "research" / "ok_us_equity_context.quality.json"
    pd.DataFrame(
        {
            "date": dates.date,
            "QQQ": [100.0, 101.0, 102.0, 103.0],
            "SPY": [90.0, 91.0, 92.0, 93.0],
            "cape_percentile": [0.70, 0.80, 0.90, 0.85],
            "vix_percentile": [0.20, 0.40, 0.85, 0.75],
            "breadth_above_sma200_pct": [0.60, 0.50, 0.35, 0.45],
            "provider_timestamp": [
                "2025-01-02T23:00:00Z",
                "2025-01-03T23:00:00Z",
                "2025-01-06T23:00:00Z",
                "2025-01-10T23:00:00Z",
            ],
            "breadth_universe_snapshot_id": ["spx-1", "spx-2", "spx-3", "spx-4"],
            "breadth_universe_as_of": [
                "2025-01-02",
                "2025-01-03",
                "2025-01-08",
                "2025-01-07",
            ],
        }
    ).to_csv(input_csv, index=False)

    strict_result = export_us_equity_context_main(
        [
            "--input-csv",
            str(input_csv),
            "--output-csv",
            str(strict_output_csv),
            "--quality-report",
            str(strict_quality_report_path),
            "--as-of",
            "2025-01-07",
            "--require-point-in-time-metadata",
        ]
    )

    assert strict_result == 2
    assert "provider_timestamp_after_as_of" in capsys.readouterr().err
    strict_quality_report = json.loads(
        strict_quality_report_path.read_text(encoding="utf-8")
    )
    assert strict_quality_report["quality_status"] == "fail"
    assert strict_quality_report["provider_timestamp_after_as_of_count"] == 1
    assert strict_quality_report[
        "breadth_universe_as_of_after_observation_count"
    ] == 1

    clean = pd.read_csv(input_csv)
    clean["provider_timestamp"] = [
        "2025-01-02T23:00:00Z",
        "2025-01-03T23:00:00Z",
        "2025-01-06T23:00:00Z",
        "2025-01-07T23:00:00Z",
    ]
    clean["breadth_universe_as_of"] = [
        "2025-01-02",
        "2025-01-03",
        "2025-01-06",
        "2025-01-07",
    ]
    clean.to_csv(input_csv, index=False)

    ok_result = export_us_equity_context_main(
        [
            "--input-csv",
            str(input_csv),
            "--output-csv",
            str(ok_output_csv),
            "--quality-report",
            str(ok_quality_report_path),
            "--as-of",
            "2025-01-07",
            "--require-point-in-time-metadata",
        ]
    )

    assert ok_result == 0
    ok_quality_report = json.loads(ok_quality_report_path.read_text(encoding="utf-8"))
    assert ok_quality_report["quality_status"] == "pass"
    assert ok_quality_report["failure_reasons"] == []
    assert ok_quality_report["warning_reasons"] == []


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


def test_research_export_validator_rejects_output_csv_shape_drift(tmp_path) -> None:
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
    manifest["columns"] = ["date", "close"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(SignalBundleValidationError, match="columns mismatch"):
        validate_research_export_manifest(manifest_path)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["columns"] = list(pd.read_csv(output_csv, nrows=0).columns)
    manifest["row_count"] = 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(SignalBundleValidationError, match="row_count mismatch"):
        validate_research_export_manifest(manifest_path)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["row_count"] = 5
    manifest["first_date"] = "1900-01-01"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(SignalBundleValidationError, match="first_date mismatch"):
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


def test_validator_rejects_invalid_compatible_profiles() -> None:
    bundle = build_btc_cycle_signal_bundle(
        _btc_frame(),
        as_of="2025-09-17",
        raw_artifact_sha256="0" * 64,
        generated_at="2025-09-17T00:15:00Z",
    )
    bundle["consumer_contract"]["compatible_profiles"] = []

    with pytest.raises(SignalBundleValidationError, match="compatible_profiles"):
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


def test_validator_rejects_manifest_compatible_profile_mismatch(tmp_path) -> None:
    bundle = build_btc_cycle_signal_bundle(
        _btc_frame(),
        as_of="2025-09-17",
        raw_artifact_sha256="0" * 64,
        generated_at="2025-09-17T00:15:00Z",
    )
    paths = write_signal_bundle_artifacts(tmp_path, bundle)
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    manifest["compatible_profiles"] = ["research:wrong_consumer"]
    paths["manifest"].write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(SignalBundleValidationError, match="compatible_profiles"):
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


def test_validator_rejects_index_compatible_profile_mismatch(tmp_path) -> None:
    bundle = build_btc_cycle_signal_bundle(
        _btc_frame(),
        as_of="2025-09-17",
        raw_artifact_sha256="0" * 64,
        generated_at="2025-09-17T00:15:00Z",
    )
    paths = write_signal_bundle_artifacts(tmp_path, bundle)
    index = json.loads(paths["index"].read_text(encoding="utf-8"))
    index["bundles"][0]["compatible_profiles"] = ["research:wrong_consumer"]
    paths["index"].write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(SignalBundleValidationError, match="compatible_profiles"):
        validate_signal_bundle_index(paths["index"])
