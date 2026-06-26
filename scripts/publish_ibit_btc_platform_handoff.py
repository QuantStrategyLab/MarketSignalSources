from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

BINANCE_BTCUSDT_DAILY_URLS = (
    "https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=800",
    "https://api.binance.us/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=800",
    "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=800",
)
DEFAULT_CONSUMER = "us_equity:ibit_smart_dca"
DEFAULT_STRATEGY = "ibit_smart_dca"
DEFAULT_GCS_PREFIX = "gs://qsl-runtime-logs-shared/platform_handoffs"


def default_as_of(*, today: date | None = None) -> str:
    """Return yesterday UTC as the default signal as-of date."""
    current = today or datetime.now(UTC).date()
    return (current - timedelta(days=1)).isoformat()


def resolve_as_of(*, csv_path: Path, requested: str | None, today: date | None = None) -> str:
    """Pick the requested as-of when present in the CSV, otherwise the latest row."""
    rows = _read_csv_dates(csv_path)
    if not rows:
        raise ValueError(f"no dates found in {csv_path}")
    target = requested or default_as_of(today=today)
    if target in rows:
        return target
    return rows[-1]


def fetch_binance_btc_daily_csv(output_path: Path) -> tuple[int, str]:
    """Download BTCUSDT daily OHLCV from Binance public API into a local CSV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload, source_url = _download_binance_btcusdt_daily_klines()
    provider_name = _provider_name_for_url(source_url)

    rows: list[dict[str, object]] = []
    for entry in payload:
        timestamp_ms = int(entry[0])
        day = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).date().isoformat()
        rows.append(
            {
                "date": day,
                "open": float(entry[1]),
                "high": float(entry[2]),
                "low": float(entry[3]),
                "close": float(entry[4]),
                "volume": float(entry[5]),
            }
        )

    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["date", "open", "high", "low", "close", "volume"],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"downloaded BTCUSDT daily rows from {provider_name}")
    return len(rows), provider_name


def _download_binance_btcusdt_daily_klines() -> tuple[list[object], str]:
    errors: list[str] = []
    for url in BINANCE_BTCUSDT_DAILY_URLS:
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                payload = json.loads(response.read().decode())
        except urllib.error.URLError as exc:
            errors.append(f"{url}: {exc}")
            continue
        if not payload:
            errors.append(f"{url}: empty response")
            continue
        return payload, url
    joined = "; ".join(errors) or "no Binance endpoints configured"
    raise RuntimeError(f"failed to download Binance BTCUSDT daily klines: {joined}")


def _provider_name_for_url(url: str) -> str:
    if "binance.vision" in url:
        return "binance_vision_public"
    if "binance.us" in url:
        return "binance_us_public"
    return "binance_public"


def build_ibit_btc_platform_handoff(
    *,
    work_dir: Path,
    input_csv: Path,
    as_of: str,
    code_commit: str,
    source_version: str,
    provider: str = "binance_vision_public",
    consumer: str = DEFAULT_CONSUMER,
    strategy: str = DEFAULT_STRATEGY,
) -> dict[str, Path]:
    """Build BTC cycle bundle artifacts and the platform handoff index locally."""
    from market_signal_sources.cli.build_btc_cycle_bundle import main as build_bundle_main
    from market_signal_sources.cli.publish_platform_signal_handoff import (
        main as publish_handoff_main,
    )

    publication_dir = work_dir / "platform_handoffs" / as_of
    bundle_dir = publication_dir / "bundle"
    index_path = work_dir / "platform_handoffs" / "index.json"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    generated_at = f"{as_of}T00:15:00Z"

    build_exit = build_bundle_main(
        [
            "--input-csv",
            str(input_csv),
            "--output-dir",
            str(bundle_dir),
            "--as-of",
            as_of,
            "--provider",
            provider,
            "--provider-dataset",
            "btcusdt_daily_klines",
            "--source-version",
            source_version,
            "--code-commit",
            code_commit,
            "--generated-at",
            generated_at,
        ]
    )
    if build_exit != 0:
        raise RuntimeError(f"build-btc-cycle-bundle failed with exit code {build_exit}")

    publish_exit = publish_handoff_main(
        [
            "--publication-dir",
            str(publication_dir),
            "--signal-bundle-manifest",
            str(bundle_dir / "manifest.json"),
            "--consumer",
            consumer,
            "--strategy",
            strategy,
            "--index-path",
            str(index_path),
            "--lookup-as-of",
            as_of,
        ]
    )
    if publish_exit != 0:
        raise RuntimeError(
            f"publish-platform-signal-handoff failed with exit code {publish_exit}"
        )

    return {
        "publication_dir": publication_dir,
        "index_path": index_path,
        "bundle_manifest": bundle_dir / "manifest.json",
    }


def upload_platform_handoffs(*, local_root: Path, gcs_prefix: str) -> None:
    """Sync the local platform handoffs tree to GCS."""
    normalized = gcs_prefix.rstrip("/")
    command = ["gsutil", "-m", "rsync", "-r", str(local_root), normalized]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "unknown gsutil error"
        raise RuntimeError(f"gsutil rsync failed: {message}")


def _read_csv_dates(csv_path: Path) -> list[str]:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if "date" not in (reader.fieldnames or []):
            raise ValueError(f"{csv_path} is missing a date column")
        return [str(row["date"]) for row in reader if row.get("date")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch BTC daily OHLCV, build the IBIT smart DCA platform handoff, "
            "and optionally upload it to GCS."
        )
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path("data/output"),
        help="Local build root for platform handoff artifacts.",
    )
    parser.add_argument(
        "--as-of",
        help="Signal as-of date (YYYY-MM-DD). Defaults to yesterday UTC when present in the CSV.",
    )
    parser.add_argument(
        "--input-csv",
        type=Path,
        help="Optional pre-fetched BTC OHLCV CSV. When omitted, Binance public data is downloaded.",
    )
    parser.add_argument(
        "--gcs-prefix",
        default=DEFAULT_GCS_PREFIX,
        help="GCS prefix for platform handoffs.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Upload the generated platform handoffs directory to GCS.",
    )
    parser.add_argument(
        "--source-version",
        default="0.1.1",
        help="MarketSignalSources package version recorded in bundle provenance.",
    )
    parser.add_argument(
        "--code-commit",
        help="Git commit SHA recorded in bundle provenance. Defaults to GITHUB_SHA when set.",
    )
    parser.add_argument(
        "--consumer",
        default=DEFAULT_CONSUMER,
        help="Runtime consumer contract to publish.",
    )
    parser.add_argument(
        "--strategy",
        default=DEFAULT_STRATEGY,
        help="Platform strategy profile for runtime adapter config.",
    )
    args = parser.parse_args(argv)

    work_dir = args.work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    input_csv = args.input_csv or (work_dir / "inputs" / "btc_daily.csv")
    code_commit = args.code_commit or __import__("os").environ.get("GITHUB_SHA", "0" * 40)

    provider = "local_csv"
    if args.input_csv is None:
        row_count, provider = fetch_binance_btc_daily_csv(input_csv)
        print(f"downloaded {row_count} BTCUSDT daily rows to {input_csv}")
    elif not input_csv.is_file():
        print(f"error: input CSV not found: {input_csv}", file=sys.stderr)
        return 2

    as_of = resolve_as_of(csv_path=input_csv, requested=args.as_of)
    print(f"using as_of={as_of}")

    artifacts = build_ibit_btc_platform_handoff(
        work_dir=work_dir,
        input_csv=input_csv,
        as_of=as_of,
        code_commit=code_commit,
        source_version=args.source_version,
        provider=provider,
        consumer=args.consumer,
        strategy=args.strategy,
    )
    print(f"built platform handoff index at {artifacts['index_path']}")

    if args.execute:
        upload_root = work_dir / "platform_handoffs"
        upload_platform_handoffs(local_root=upload_root, gcs_prefix=args.gcs_prefix)
        print(f"uploaded {upload_root} to {args.gcs_prefix.rstrip('/')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
