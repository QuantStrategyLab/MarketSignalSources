from __future__ import annotations

import json

import pandas as pd

from market_signal_sources.artifacts.publication import (
    publish_platform_signal_handoff,
)
from market_signal_sources.artifacts.signal_bundle import (
    build_btc_cycle_signal_bundle,
    write_signal_bundle_artifacts,
)
from market_signal_sources.artifacts.source_catalog import (
    signal_ownership_matrix_payload,
)
from market_signal_sources.cli.list_signal_ownership_matrix import (
    main as ownership_matrix_main,
)
from market_signal_sources.cli.publish_platform_signal_handoff import (
    main as publish_handoff_main,
)


def test_signal_ownership_matrix_maps_runtime_consumers_to_source_families(capsys) -> None:
    payload = signal_ownership_matrix_payload(
        consumers=(
            "us_equity:ibit_smart_dca",
            "us_equity:nasdaq_sp500_smart_dca",
            "us_equity:soxl_soxx_trend_income",
        )
    )

    assert payload["schema_version"] == "market_signal_ownership_matrix.v1"
    assert payload["all_runtime_consumers_have_source_family"] is True
    assert payload["all_runtime_consumers_cover_required_fields"] is True
    by_consumer = {
        record["consumer"]: record
        for record in payload["consumers"]
    }
    assert by_consumer["us_equity:ibit_smart_dca"]["source_families"][0]["family"] == (
        "crypto.btc_cycle_daily"
    )
    assert by_consumer["us_equity:nasdaq_sp500_smart_dca"]["source_families"][0][
        "family"
    ] == "us_equity.technical_daily"

    result = ownership_matrix_main(
        [
            "--consumer",
            "us_equity:ibit_smart_dca",
            "--pretty",
        ]
    )
    assert result == 0
    cli_payload = json.loads(capsys.readouterr().out)
    assert cli_payload["consumers"][0]["consumer"] == "us_equity:ibit_smart_dca"
    assert cli_payload["consumers"][0]["all_required_fields_covered"] is True


def test_publish_platform_signal_handoff_builds_deployment_artifacts(tmp_path, capsys) -> None:
    publication_dir = tmp_path / "platform_handoffs" / "2025-09-17"
    bundle_manifest = _write_btc_bundle(publication_dir)
    index_path = tmp_path / "platform_handoffs" / "index.json"

    summary = publish_platform_signal_handoff(
        publication_dir,
        signal_bundle_manifest=bundle_manifest,
        consumer="us_equity:ibit_smart_dca",
        index_path=index_path,
        lookup_as_of="2025-09-18",
    )

    assert summary["schema_version"] == "market_signal_platform_publication.v1"
    assert summary["consumer"] == "us_equity:ibit_smart_dca"
    assert summary["lookup_as_of"] == "2025-09-18"
    assert summary["handoff"]["all_runtime_consumers_covered"] is True
    assert summary["audit"]["ready_for_runtime_injection"] is True
    assert summary["runtime_adapter_deployment"]["current_audit_matched"] is True
    assert index_path.exists()

    cli_publication_dir = tmp_path / "platform_handoffs" / "2025-09-18"
    cli_bundle_manifest = _write_btc_bundle(cli_publication_dir, as_of="2025-09-18")
    result = publish_handoff_main(
        [
            "--publication-dir",
            str(cli_publication_dir),
            "--signal-bundle-manifest",
            str(cli_bundle_manifest),
            "--consumer",
            "us_equity:ibit_smart_dca",
            "--index-path",
            str(index_path),
            "--lookup-as-of",
            "2025-09-19",
            "--pretty",
        ]
    )

    assert result == 0
    cli_summary = json.loads(capsys.readouterr().out)
    assert cli_summary["consumer"] == "us_equity:ibit_smart_dca"
    assert cli_summary["lookup_as_of"] == "2025-09-19"
    assert cli_summary["runtime_adapter_deployment"]["current_audit_matched"] is True
    assert cli_summary["index"]["index_handoff_count"] == 2


def _write_btc_bundle(publication_dir, *, as_of: str = "2025-09-17"):
    bundle_dir = publication_dir / "bundle"
    frame = _btc_frame(as_of=as_of)
    bundle = build_btc_cycle_signal_bundle(
        frame,
        as_of=as_of,
        raw_artifact_sha256="0" * 64,
        generated_at=f"{as_of}T00:15:00Z",
    )
    paths = write_signal_bundle_artifacts(bundle_dir, bundle)
    return paths["manifest"]


def _btc_frame(*, as_of: str) -> pd.DataFrame:
    end = pd.Timestamp(as_of)
    dates = pd.date_range(end=end, periods=220, freq="D")
    close = pd.Series(range(220), dtype="float64") + 50_000.0
    return pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "open": close - 25.0,
            "high": close + 100.0,
            "low": close - 100.0,
            "close": close,
            "volume": 1000.0,
        }
    )
