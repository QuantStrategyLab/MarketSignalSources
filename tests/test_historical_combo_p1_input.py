from __future__ import annotations

import pytest

from market_signal_sources.artifacts.historical_combo_p1_input import (
    HISTORICAL_COMBO_P1_INPUT_SCHEMA,
    HistoricalComboP1InputError,
    build_historical_combo_p1_input,
    validate_historical_combo_p1_input,
)
from market_signal_sources.artifacts.historical_price_panel import build_historical_price_panel
from market_signal_sources.artifacts.point_in_time_universe import (
    build_point_in_time_universe_snapshot,
)


def _price_panel(*, symbols: tuple[str, ...] = ("AAPL", "MSFT", "IWB")) -> dict[str, object]:
    return build_historical_price_panel(
        panel_id="russell_combo.daily.v1",
        observation_start="2024-01-02",
        observation_end="2025-12-31",
        source_id="private.us_equity_eod_panel",
        raw_artifact_sha256="a" * 64,
        quality_report_sha256="b" * 64,
        license_scope="private_research",
        point_in_time_status="historical_close_with_declared_lag",
        signal_price_basis="split_adjusted_close",
        return_price_basis="total_return_adjusted_close",
        calendar_id="xnys",
        execution_lag_trading_sessions=1,
        symbols=symbols,
    )


def _snapshot(*, effective_date: str, available_at: str, symbols: tuple[str, ...]) -> dict[str, object]:
    return build_point_in_time_universe_snapshot(
        universe_id="russell_1000",
        effective_date=effective_date,
        available_at=available_at,
        source_id="example.russell_holdings_snapshot",
        raw_artifact_sha256="c" * 64,
        license_scope="private_research",
        constituents=symbols,
    )


def _input() -> dict[str, object]:
    return build_historical_combo_p1_input(
        candidate_id="us_equity_combo_core",
        strategy_revision="d" * 40,
        config_sha256="e" * 64,
        replay_start="2024-06-28",
        replay_end="2025-06-27",
        price_panel=_price_panel(),
        rebalances=(
            {
                "decision_at": "2024-06-28T20:15:00Z",
                "universe_snapshot": _snapshot(
                    effective_date="2024-06-28",
                    available_at="2024-06-28T20:15:00Z",
                    symbols=("AAPL", "MSFT"),
                ),
            },
            {
                "decision_at": "2025-06-27T20:15:00Z",
                "universe_snapshot": _snapshot(
                    effective_date="2025-06-27",
                    available_at="2025-06-27T20:15:00Z",
                    symbols=("AAPL", "MSFT"),
                ),
            },
        ),
        cost_model={
            "base_turnover_cost_bps": 5.0,
            "stress_turnover_cost_bps": [10.0, 25.0],
            "execution_timing": "next_complete_trading_session_after_signal_effective_date",
        },
    )


def test_combo_p1_binding_is_canonical_research_only_and_replayable() -> None:
    value = _input()

    assert value["schema_version"] == HISTORICAL_COMBO_P1_INPUT_SCHEMA
    assert value["research_only"] is True
    assert value["candidate"] == {
        "candidate_id": "us_equity_combo_core",
        "strategy_revision": "d" * 40,
        "config_sha256": "e" * 64,
    }
    assert validate_historical_combo_p1_input(value) == value


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update({"input_sha256": "f" * 64}), "digest mismatch"),
        (
            lambda value: value["cost_model"].update({"base_turnover_cost_bps": 0.0}),
            "base turnover cost",
        ),
        (
            lambda value: value["rebalances"][0].update({"decision_at": "2025-06-27T20:15:00Z"}),
            "strictly increasing",
        ),
    ],
)
def test_tampered_combo_p1_input_fails_closed(mutate, message: str) -> None:
    value = _input()
    mutate(value)

    with pytest.raises(HistoricalComboP1InputError, match=message):
        validate_historical_combo_p1_input(value)


def test_price_panel_must_cover_every_historical_constituent() -> None:
    with pytest.raises(HistoricalComboP1InputError, match="does not cover rebalance universe"):
        build_historical_combo_p1_input(
            candidate_id="us_equity_combo_core",
            strategy_revision="d" * 40,
            config_sha256="e" * 64,
            replay_start="2024-06-28",
            replay_end="2024-06-28",
            price_panel=_price_panel(symbols=("AAPL", "IWB")),
            rebalances=(
                {
                    "decision_at": "2024-06-28T20:15:00Z",
                    "universe_snapshot": _snapshot(
                        effective_date="2024-06-28",
                        available_at="2024-06-28T20:15:00Z",
                        symbols=("AAPL", "MSFT"),
                    ),
                },
            ),
            cost_model={
                "base_turnover_cost_bps": 5.0,
                "stress_turnover_cost_bps": [10.0, 25.0],
                "execution_timing": "next_complete_trading_session_after_signal_effective_date",
            },
        )


def test_rebalance_rejects_a_snapshot_not_known_at_its_decision_time() -> None:
    with pytest.raises(HistoricalComboP1InputError, match="invalid rebalance universe snapshot"):
        build_historical_combo_p1_input(
            candidate_id="us_equity_combo_core",
            strategy_revision="d" * 40,
            config_sha256="e" * 64,
            replay_start="2024-06-28",
            replay_end="2024-06-28",
            price_panel=_price_panel(),
            rebalances=(
                {
                    "decision_at": "2024-06-28T20:15:00Z",
                    "universe_snapshot": _snapshot(
                        effective_date="2024-06-28",
                        available_at="2024-06-28T20:15:01Z",
                        symbols=("AAPL", "MSFT"),
                    ),
                },
            ),
            cost_model={
                "base_turnover_cost_bps": 5.0,
                "stress_turnover_cost_bps": [10.0, 25.0],
                "execution_timing": "next_complete_trading_session_after_signal_effective_date",
            },
        )
