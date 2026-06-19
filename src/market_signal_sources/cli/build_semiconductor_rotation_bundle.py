from __future__ import annotations

import argparse
from collections.abc import Sequence
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

from market_signal_sources.artifacts.quality_report import write_ohlcv_quality_report
from market_signal_sources.artifacts.signal_bundle import (
    build_semiconductor_rotation_signal_bundle,
    upsert_signal_bundle_publication_index,
    write_signal_bundle_artifacts,
)
from market_signal_sources.derived.us_equity import (
    required_semiconductor_rotation_history_lookback,
)
from market_signal_sources.providers import load_ohlcv_csv, local_csv_provider_metadata


DEFAULT_COMPATIBLE_PROFILE = "us_equity:soxl_soxx_trend_income"


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        soxl_ohlcv = load_ohlcv_csv(
            args.soxl_csv,
            date_column=args.date_column,
            close_column=args.close_column,
            high_column=args.high_column,
            low_column=args.low_column,
            volume_column=args.volume_column,
            as_of=args.as_of,
        )
        soxx_ohlcv = load_ohlcv_csv(
            args.soxx_csv,
            date_column=args.date_column,
            close_column=args.close_column,
            high_column=args.high_column,
            low_column=args.low_column,
            volume_column=args.volume_column,
            as_of=args.as_of,
        )
        soxl_metadata = local_csv_provider_metadata(
            args.soxl_csv,
            as_of=args.as_of,
            provider=args.provider,
            provider_dataset=args.provider_dataset,
            license_scope=args.license_scope,
        )
        soxx_metadata = local_csv_provider_metadata(
            args.soxx_csv,
            as_of=args.as_of,
            provider=args.provider,
            provider_dataset=args.provider_dataset,
            license_scope=args.license_scope,
        )
        raw_artifact_sha256 = _combined_raw_sha256(
            {
                "SOXL": soxl_metadata.raw_artifact_sha256,
                "SOXX": soxx_metadata.raw_artifact_sha256,
            }
        )
        min_history = args.min_history
        if min_history is None:
            min_history = required_semiconductor_rotation_history_lookback(
                trend_ma_window=args.trend_ma_window,
                dynamic_rsi_quantile_window=args.dynamic_rsi_quantile_window,
                dynamic_volatility_delever_window=(
                    args.dynamic_volatility_delever_window
                ),
                dynamic_volatility_delever_quantile_window=(
                    args.dynamic_volatility_delever_quantile_window
                ),
            )
        compatible_profiles = tuple(
            args.compatible_profile or (DEFAULT_COMPATIBLE_PROFILE,)
        )
        bundle = build_semiconductor_rotation_signal_bundle(
            soxl_ohlcv,
            soxx_ohlcv,
            as_of=args.as_of,
            provider=args.provider,
            provider_dataset=args.provider_dataset,
            raw_artifact_sha256=raw_artifact_sha256,
            source_version=args.source_version,
            code_commit=args.code_commit,
            generated_at=args.generated_at,
            provider_timestamp=soxl_metadata.provider_timestamp,
            freshness_status=args.freshness_status,
            freshness_policy=args.freshness_policy,
            license_scope=args.license_scope,
            generated_by=soxl_metadata.generated_by,
            trend_ma_window=args.trend_ma_window,
            dynamic_rsi_quantile_window=args.dynamic_rsi_quantile_window,
            dynamic_rsi_quantile=args.dynamic_rsi_quantile,
            dynamic_rsi_floor=args.dynamic_rsi_floor,
            dynamic_volatility_delever_window=args.dynamic_volatility_delever_window,
            dynamic_volatility_delever_quantile_window=(
                args.dynamic_volatility_delever_quantile_window
            ),
            dynamic_volatility_delever_quantile=(
                args.dynamic_volatility_delever_quantile
            ),
            dynamic_volatility_delever_min_periods=(
                args.dynamic_volatility_delever_min_periods
            ),
            dynamic_volatility_delever_floor=args.dynamic_volatility_delever_floor,
            dynamic_volatility_delever_cap=args.dynamic_volatility_delever_cap,
            min_history=min_history,
            compatible_profiles=compatible_profiles,
        )
        output_dir = Path(args.output_dir)
        soxl_quality_report_path = output_dir / "quality_report.SOXL.json"
        soxx_quality_report_path = output_dir / "quality_report.SOXX.json"
        quality_kwargs = {
            "date_column": args.date_column,
            "close_column": args.close_column,
            "high_column": args.high_column,
            "low_column": args.low_column,
            "volume_column": args.volume_column,
            "as_of": args.as_of,
            "min_history_rows": min_history,
            "max_allowed_gap_days": args.max_allowed_gap_days,
        }
        write_ohlcv_quality_report(
            soxl_quality_report_path,
            args.soxl_csv,
            **quality_kwargs,
        )
        write_ohlcv_quality_report(
            soxx_quality_report_path,
            args.soxx_csv,
            **quality_kwargs,
        )
        artifact_paths = write_signal_bundle_artifacts(output_dir, bundle)
        artifact_paths["quality_report_SOXL"] = soxl_quality_report_path
        artifact_paths["quality_report_SOXX"] = soxx_quality_report_path
        if args.publication_index is not None:
            artifact_paths["publication_index"] = upsert_signal_bundle_publication_index(
                args.publication_index,
                artifact_paths["manifest"],
                generated_at=args.generated_at,
            )
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    summary = {
        "bundle_id": bundle["bundle_id"],
        "as_of": bundle["as_of"],
        "symbols": list(bundle["symbols"]),
        "compatible_profiles": list(compatible_profiles),
        "output_dir": str(args.output_dir),
        "artifacts": {
            name: str(path)
            for name, path in sorted(artifact_paths.items())
        },
    }
    print(json.dumps(summary, indent=2 if args.pretty else None, sort_keys=True))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a SOXL/SOXX semiconductor-rotation market_signal_bundle.v1 "
            "artifact from daily OHLCV CSVs."
        )
    )
    parser.add_argument("--soxl-csv", required=True, type=Path)
    parser.add_argument("--soxx-csv", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--provider", default="local_csv")
    parser.add_argument(
        "--provider-dataset",
        default="us_equity_semiconductor_daily_ohlcv",
    )
    parser.add_argument("--license-scope", default="internal_runtime")
    parser.add_argument("--source-version", default="0.1.0")
    parser.add_argument(
        "--code-commit",
        default="0000000000000000000000000000000000000000",
    )
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--freshness-status", default="fresh")
    parser.add_argument("--freshness-policy", default="us_equity_daily_close_t_plus_1")
    parser.add_argument("--min-history", type=int)
    parser.add_argument("--trend-ma-window", type=int, default=140)
    parser.add_argument("--dynamic-rsi-quantile-window", type=int, default=252)
    parser.add_argument("--dynamic-rsi-quantile", type=float, default=0.90)
    parser.add_argument("--dynamic-rsi-floor", type=float, default=70.0)
    parser.add_argument("--dynamic-volatility-delever-window", type=int, default=10)
    parser.add_argument(
        "--dynamic-volatility-delever-quantile-window",
        type=int,
        default=252,
    )
    parser.add_argument("--dynamic-volatility-delever-quantile", type=float, default=0.95)
    parser.add_argument("--dynamic-volatility-delever-min-periods", type=int, default=126)
    parser.add_argument("--dynamic-volatility-delever-floor", type=float, default=0.50)
    parser.add_argument("--dynamic-volatility-delever-cap", type=float, default=0.75)
    parser.add_argument("--max-allowed-gap-days", type=int, default=5)
    parser.add_argument("--date-column", default="date")
    parser.add_argument("--close-column", default="close")
    parser.add_argument("--high-column", default="high")
    parser.add_argument("--low-column", default="low")
    parser.add_argument("--volume-column", default="volume")
    parser.add_argument(
        "--compatible-profile",
        action="append",
        help=(
            "Consumer id compatible with this bundle. Defaults to "
            "us_equity:soxl_soxx_trend_income."
        ),
    )
    parser.add_argument(
        "--publication-index",
        type=Path,
        help="Optional root index to upsert with the generated manifest path.",
    )
    parser.add_argument("--pretty", action="store_true")
    return parser


def _combined_raw_sha256(parts: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for symbol, sha256_value in sorted(parts.items()):
        digest.update(f"{symbol}:{sha256_value}\n".encode("utf-8"))
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
