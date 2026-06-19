from __future__ import annotations

from collections.abc import Iterable, Mapping
import json
from os import PathLike
from pathlib import Path
from typing import Any

import pandas as pd

from .signal_bundle import sha256_file


RESEARCH_EXPORT_SCHEMA_VERSION = "research_export.v1"


def write_research_export_manifest(
    manifest_path: str | PathLike[str],
    *,
    output_csv_path: str | PathLike[str],
    output_frame: pd.DataFrame,
    input_csv_path: str | PathLike[str],
    artifact_type: str = "btc_cycle_research_csv",
    transform: str,
    source_version: str,
    as_of: str | None,
    min_history: int,
    input_sources: Iterable[Mapping[str, Any]] | None = None,
    transform_parameters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write a non-runtime manifest for an offline research CSV export."""

    output_path = Path(output_csv_path)
    input_path = Path(input_csv_path)
    manifest = {
        "schema_version": RESEARCH_EXPORT_SCHEMA_VERSION,
        "artifact_type": str(artifact_type),
        "transform": str(transform),
        "source_version": str(source_version),
        "as_of": None if as_of is None else pd.Timestamp(as_of).normalize().date().isoformat(),
        "min_history": int(min_history),
        "row_count": int(len(output_frame)),
        "first_date": str(output_frame.iloc[0]["date"]) if not output_frame.empty else "",
        "last_date": str(output_frame.iloc[-1]["date"]) if not output_frame.empty else "",
        "columns": [str(column) for column in output_frame.columns],
        "input_csv": {
            "path": str(input_path),
            "sha256": sha256_file(input_path),
            "size_bytes": input_path.stat().st_size,
        },
        "output_csv": {
            "path": str(output_path),
            "sha256": sha256_file(output_path),
            "size_bytes": output_path.stat().st_size,
        },
    }
    if input_sources is not None:
        manifest["input_sources"] = [
            _json_safe_mapping(record)
            for record in input_sources
        ]
    if transform_parameters is not None:
        manifest["transform_parameters"] = _json_safe_mapping(transform_parameters)
    target_path = Path(manifest_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _json_safe_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _json_safe_value(nested) for key, nested in value.items()}


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _json_safe_mapping(value)
    if isinstance(value, tuple | list):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value
