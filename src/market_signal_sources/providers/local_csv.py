from __future__ import annotations

from dataclasses import dataclass
import hashlib
from os import PathLike
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class LocalCsvProviderMetadata:
    provider: str
    provider_dataset: str
    provider_timestamp: str
    raw_artifact_sha256: str
    license_scope: str
    generated_by: str = "market_signal_sources.local_csv"


def local_csv_provider_metadata(
    path: str | PathLike[str],
    *,
    as_of: str,
    provider: str = "local_csv",
    provider_dataset: str = "btc_usd_daily_ohlcv",
    license_scope: str = "internal_runtime",
) -> LocalCsvProviderMetadata:
    """Return auditable provider metadata for a local CSV source artifact."""

    normalized_as_of = pd.Timestamp(as_of).normalize().date().isoformat()
    return LocalCsvProviderMetadata(
        provider=_non_empty(provider, "provider"),
        provider_dataset=_non_empty(provider_dataset, "provider_dataset"),
        provider_timestamp=f"{normalized_as_of}T00:00:00Z",
        raw_artifact_sha256=_sha256_file(Path(path)),
        license_scope=_non_empty(license_scope, "license_scope"),
    )


def load_ohlcv_csv(
    path: str | PathLike[str],
    *,
    date_column: str = "date",
    close_column: str = "close",
    high_column: str | None = "high",
    low_column: str | None = "low",
    volume_column: str | None = "volume",
    as_of: str | None = None,
) -> pd.DataFrame:
    """Load a local OHLCV CSV into a normalized daily frame.

    The provider is deliberately local-only. Vendor fetching, credentials, and
    retry/rate-limit behavior belong to later provider adapters, not this MVP.
    """

    frame = pd.read_csv(Path(path))
    if date_column not in frame.columns:
        raise ValueError(f"missing date column: {date_column}")
    if close_column not in frame.columns:
        raise ValueError(f"missing close column: {close_column}")

    output = pd.DataFrame(
        {
            "date": pd.to_datetime(frame[date_column]).dt.tz_localize(None).dt.normalize(),
            "close": pd.to_numeric(frame[close_column], errors="coerce"),
        }
    )
    if high_column and high_column in frame.columns:
        output["high"] = pd.to_numeric(frame[high_column], errors="coerce")
    else:
        output["high"] = output["close"]
    if low_column and low_column in frame.columns:
        output["low"] = pd.to_numeric(frame[low_column], errors="coerce")
    else:
        output["low"] = output["close"]
    if volume_column and volume_column in frame.columns:
        output["volume"] = pd.to_numeric(frame[volume_column], errors="coerce")

    output = output.dropna(subset=["date", "close"])
    output = output.loc[output["close"] > 0.0].sort_values("date")
    output = output.drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    if as_of is not None:
        cutoff = pd.Timestamp(as_of).tz_localize(None).normalize()
        output = output.loc[output["date"] <= cutoff].reset_index(drop=True)
    if output.empty:
        raise ValueError("OHLCV CSV has no usable rows after normalization")
    return output


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _non_empty(value: object, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} must be non-empty")
    return normalized
