from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from market_signal_sources.artifacts.historical_combo_p1_input import (
    build_historical_combo_p1_input,
)
from market_signal_sources.artifacts.historical_combo_p1_root import (
    HISTORICAL_COMBO_P1_ROOT_MANIFEST_SCHEMA,
    ROOT_STATUS,
    HistoricalComboP1RootError,
    publish_historical_combo_p1_root,
    verify_historical_combo_p1_root,
)
from market_signal_sources.artifacts.historical_price_panel import build_historical_price_panel
from market_signal_sources.artifacts.point_in_time_universe import (
    build_point_in_time_universe_snapshot,
)
from market_signal_sources.cli.seal_historical_combo_p1_root import main as seal_main


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _payloads() -> tuple[dict[str, object], bytes, bytes, dict[str, bytes]]:
    price_panel_bytes = b"date,symbol,close\n2024-06-28,AAPL,100\n"
    quality_report_bytes = b'{"quality_status":"pass"}\n'
    first_universe_bytes = b"2024-06-28,AAPL\n2024-06-28,MSFT\n"
    second_universe_bytes = b"2025-06-27,AAPL\n2025-06-27,MSFT\n"
    price_panel = build_historical_price_panel(
        panel_id="russell_combo.daily.v1",
        observation_start="2024-01-02",
        observation_end="2025-12-31",
        source_id="private.us_equity_eod_panel",
        raw_artifact_sha256=_sha256(price_panel_bytes),
        quality_report_sha256=_sha256(quality_report_bytes),
        license_scope="private_research",
        point_in_time_status="historical_close_with_declared_lag",
        signal_price_basis="split_adjusted_close",
        return_price_basis="total_return_adjusted_close",
        calendar_id="xnys",
        execution_lag_trading_sessions=1,
        symbols=("AAPL", "MSFT", "IWB"),
    )

    def snapshot(*, effective_date: str, available_at: str, payload: bytes) -> dict[str, object]:
        return build_point_in_time_universe_snapshot(
            universe_id="russell_1000",
            effective_date=effective_date,
            available_at=available_at,
            source_id="private.russell_holdings_snapshot",
            raw_artifact_sha256=_sha256(payload),
            license_scope="private_research",
            constituents=("AAPL", "MSFT"),
        )

    input_record = build_historical_combo_p1_input(
        candidate_id="us_equity_combo_core",
        strategy_revision="d" * 40,
        config_sha256="e" * 64,
        replay_start="2024-06-28",
        replay_end="2025-06-27",
        price_panel=price_panel,
        rebalances=(
            {
                "decision_at": "2024-06-28T20:15:00Z",
                "universe_snapshot": snapshot(
                    effective_date="2024-06-28",
                    available_at="2024-06-28T20:15:00Z",
                    payload=first_universe_bytes,
                ),
            },
            {
                "decision_at": "2025-06-27T20:15:00Z",
                "universe_snapshot": snapshot(
                    effective_date="2025-06-27",
                    available_at="2025-06-27T20:15:00Z",
                    payload=second_universe_bytes,
                ),
            },
        ),
        cost_model={
            "base_turnover_cost_bps": 5.0,
            "stress_turnover_cost_bps": [10.0, 25.0],
            "execution_timing": "next_complete_trading_session_after_signal_effective_date",
        },
    )
    return (
        input_record,
        price_panel_bytes,
        quality_report_bytes,
        {
            "2024-06-28T20:15:00Z": first_universe_bytes,
            "2025-06-27T20:15:00Z": second_universe_bytes,
        },
    )


def test_publisher_seals_a_verified_private_root_with_no_execution_authority(tmp_path: Path) -> None:
    input_record, price_panel_bytes, quality_report_bytes, universe_source_bytes = _payloads()
    output_root = tmp_path / "historical-combo-p1"

    result = publish_historical_combo_p1_root(
        combo_p1_input=input_record,
        price_panel_bytes=price_panel_bytes,
        quality_report_bytes=quality_report_bytes,
        universe_source_bytes=universe_source_bytes,
        output_root=output_root,
    )

    assert result["status"] == ROOT_STATUS
    assert result["input_sha256"] == input_record["input_sha256"]
    assert verify_historical_combo_p1_root(output_root) == result["manifest_sha256"]
    assert output_root.stat().st_mode & 0o777 == 0o700
    assert (output_root / "universe-source").stat().st_mode & 0o777 == 0o700
    assert {path.name for path in output_root.iterdir()} == {
        "input.json",
        "manifest.json",
        "price-panel.raw",
        "quality-report.raw",
        "universe-source",
    }
    assert {
        path.name for path in (output_root / "universe-source").iterdir()
    } == {"0000.raw", "0001.raw"}
    manifest = json.loads((output_root / "manifest.json").read_bytes())
    assert manifest["schema_version"] == HISTORICAL_COMBO_P1_ROOT_MANIFEST_SCHEMA
    assert manifest["research_only"] is True
    assert manifest["execution_authorized"] is False
    assert {member["path"] for member in manifest["members"]} == {
        "input.json",
        "price-panel.raw",
        "quality-report.raw",
        "universe-source/0000.raw",
        "universe-source/0001.raw",
    }


def test_publisher_rejects_digest_drift_without_creating_a_root(tmp_path: Path) -> None:
    input_record, price_panel_bytes, quality_report_bytes, universe_source_bytes = _payloads()
    output_root = tmp_path / "historical-combo-p1"

    with pytest.raises(HistoricalComboP1RootError, match="price-panel raw digest mismatch"):
        publish_historical_combo_p1_root(
            combo_p1_input=input_record,
            price_panel_bytes=price_panel_bytes + b"drift",
            quality_report_bytes=quality_report_bytes,
            universe_source_bytes=universe_source_bytes,
            output_root=output_root,
        )

    assert not output_root.exists()


def test_verifier_rejects_a_tampered_member_and_publisher_never_overwrites(tmp_path: Path) -> None:
    input_record, price_panel_bytes, quality_report_bytes, universe_source_bytes = _payloads()
    output_root = tmp_path / "historical-combo-p1"
    publish_historical_combo_p1_root(
        combo_p1_input=input_record,
        price_panel_bytes=price_panel_bytes,
        quality_report_bytes=quality_report_bytes,
        universe_source_bytes=universe_source_bytes,
        output_root=output_root,
    )
    (output_root / "price-panel.raw").write_bytes(b"tampered")

    with pytest.raises(HistoricalComboP1RootError, match="member mismatch"):
        verify_historical_combo_p1_root(output_root)
    with pytest.raises(HistoricalComboP1RootError, match="immutable output already exists"):
        publish_historical_combo_p1_root(
            combo_p1_input=input_record,
            price_panel_bytes=price_panel_bytes,
            quality_report_bytes=quality_report_bytes,
            universe_source_bytes=universe_source_bytes,
            output_root=output_root,
        )


def test_cli_seals_only_the_explicit_local_members(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    input_record, price_panel_bytes, quality_report_bytes, universe_source_bytes = _payloads()
    input_path = tmp_path / "input.json"
    price_path = tmp_path / "prices.csv"
    report_path = tmp_path / "quality.json"
    input_path.write_text(json.dumps(input_record), encoding="utf-8")
    price_path.write_bytes(price_panel_bytes)
    report_path.write_bytes(quality_report_bytes)
    source_args: list[str] = []
    for index, (decision_at, payload) in enumerate(sorted(universe_source_bytes.items())):
        source_path = tmp_path / f"universe-{index}.csv"
        source_path.write_bytes(payload)
        source_args.extend(["--universe-source", f"{decision_at}={source_path}"])
    output_root = tmp_path / "root"

    assert (
        seal_main(
            [
                "--input",
                str(input_path),
                "--price-panel",
                str(price_path),
                "--quality-report",
                str(report_path),
                *source_args,
                "--output-root",
                str(output_root),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == ROOT_STATUS
    assert verify_historical_combo_p1_root(output_root) == result["manifest_sha256"]
