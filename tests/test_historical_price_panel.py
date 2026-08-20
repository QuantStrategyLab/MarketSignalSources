from __future__ import annotations

import pytest

from market_signal_sources.artifacts.historical_price_panel import (
    HISTORICAL_PRICE_PANEL_SCHEMA,
    HistoricalPricePanelError,
    build_historical_price_panel,
    validate_historical_price_panel,
)


def _panel() -> dict[str, object]:
    return build_historical_price_panel(
        panel_id="russell_etf_combo.daily.v1",
        observation_start="2011-01-03",
        observation_end="2025-06-30",
        source_id="private.us_equity_eod_panel",
        raw_artifact_sha256="a" * 64,
        quality_report_sha256="b" * 64,
        license_scope="private_research",
        point_in_time_status="historical_close_with_declared_lag",
        signal_price_basis="split_adjusted_close",
        return_price_basis="total_return_adjusted_close",
        calendar_id="xnys",
        execution_lag_trading_sessions=1,
        symbols=("IWB", "QQQM", "TQQQ", "BOXX"),
    )


def test_price_panel_is_canonical_and_binds_provenance() -> None:
    panel = _panel()

    assert panel["schema_version"] == HISTORICAL_PRICE_PANEL_SCHEMA
    assert panel["symbols"] == ["BOXX", "IWB", "QQQM", "TQQQ"]
    assert panel["source"] == {
        "source_id": "private.us_equity_eod_panel",
        "raw_artifact_sha256": "a" * 64,
        "quality_report_sha256": "b" * 64,
        "license_scope": "private_research",
        "point_in_time_status": "historical_close_with_declared_lag",
    }
    assert validate_historical_price_panel(panel) == panel


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update({"snapshot_sha256": "c" * 64}), "digest mismatch"),
        (lambda value: value.update({"signal_price_basis": "unadjusted_close"}), "signal price basis"),
        (
            lambda value: value.update({"execution_lag_trading_sessions": 0}),
            "execution lag",
        ),
        (
            lambda value: value["source"].update({"point_in_time_status": "revised_history"}),
            "point-in-time status",
        ),
    ],
)
def test_ambiguous_or_tampered_price_panels_fail_closed(mutate, message: str) -> None:
    panel = _panel()
    mutate(panel)

    with pytest.raises(HistoricalPricePanelError, match=message):
        validate_historical_price_panel(panel)


def test_builder_rejects_a_reversed_observation_window() -> None:
    with pytest.raises(HistoricalPricePanelError, match="start is after"):
        build_historical_price_panel(
            panel_id="russell_etf_combo.daily.v1",
            observation_start="2025-06-30",
            observation_end="2025-06-29",
            source_id="private.us_equity_eod_panel",
            raw_artifact_sha256="a" * 64,
            quality_report_sha256="b" * 64,
            license_scope="private_research",
            point_in_time_status="point_in_time_vendor_snapshot",
            signal_price_basis="split_adjusted_close",
            return_price_basis="total_return_adjusted_close",
            calendar_id="xnys",
            execution_lag_trading_sessions=1,
            symbols=("IWB", "TQQQ"),
        )


def test_builder_rejects_duplicate_symbols() -> None:
    with pytest.raises(HistoricalPricePanelError, match="duplicate panel symbol"):
        build_historical_price_panel(
            panel_id="russell_etf_combo.daily.v1",
            observation_start="2011-01-03",
            observation_end="2025-06-30",
            source_id="private.us_equity_eod_panel",
            raw_artifact_sha256="a" * 64,
            quality_report_sha256="b" * 64,
            license_scope="private_research",
            point_in_time_status="point_in_time_vendor_snapshot",
            signal_price_basis="split_adjusted_close",
            return_price_basis="total_return_adjusted_close",
            calendar_id="xnys",
            execution_lag_trading_sessions=1,
            symbols=("IWB", "IWB"),
        )
