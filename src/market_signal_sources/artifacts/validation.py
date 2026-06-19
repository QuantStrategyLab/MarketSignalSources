from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping, Sequence
import json
from os import PathLike
from pathlib import Path
from typing import Any

from .signal_bundle import (
    CANONICAL_INPUT_DERIVED_INDICATORS,
    FRESHNESS_FRESH,
    MARKET_SIGNAL_BUNDLE_SCHEMA_VERSION,
    MARKET_SIGNAL_INDEX_SCHEMA_VERSION,
    MARKET_SIGNAL_MANIFEST_SCHEMA_VERSION,
    sha256_file,
)
from .consumer_contracts import (
    CONSUMER_REQUIRED_INDICATOR_FIELDS,
    SignalConsumerContractError,
    required_indicator_fields_for_consumer as _required_indicator_fields_for_consumer,
)
from .quality_report import QUALITY_REPORT_SCHEMA_VERSION
from .research_export import RESEARCH_EXPORT_SCHEMA_VERSION


_REQUIRED_PROVENANCE_FIELDS = frozenset(
    {
        "source_repo",
        "source_version",
        "code_commit",
        "provider",
        "provider_dataset",
        "raw_artifact_sha256",
        "transform",
        "license_scope",
        "generated_by",
    }
)
_FORBIDDEN_SENSITIVE_KEY_FRAGMENTS = frozenset(
    {
        "api_key",
        "authorization",
        "cookie",
        "credential",
        "password",
        "secret",
        "signed_url",
        "token",
    }
)
REQUIRED_INDICATOR_FIELDS_BY_CONSUMER = CONSUMER_REQUIRED_INDICATOR_FIELDS


class SignalBundleValidationError(ValueError):
    """Raised when a signal bundle artifact cannot be safely published."""


def validate_signal_bundle(
    bundle: Mapping[str, Any],
    *,
    expected_canonical_input: str = CANONICAL_INPUT_DERIVED_INDICATORS,
    accepted_freshness_statuses: Iterable[str] = (FRESHNESS_FRESH,),
) -> None:
    """Validate the producer-side market_signal_bundle.v1 contract."""

    if not isinstance(bundle, Mapping):
        raise SignalBundleValidationError("signal bundle must be a mapping")
    _validate_no_sensitive_fields(bundle)
    if bundle.get("schema_version") != MARKET_SIGNAL_BUNDLE_SCHEMA_VERSION:
        raise SignalBundleValidationError(
            f"unsupported signal bundle schema_version: {bundle.get('schema_version')!r}"
        )
    if bundle.get("bundle_type") != CANONICAL_INPUT_DERIVED_INDICATORS:
        raise SignalBundleValidationError(
            f"unsupported signal bundle_type: {bundle.get('bundle_type')!r}"
        )
    canonical_input = _canonical_input(bundle)
    if canonical_input != expected_canonical_input:
        raise SignalBundleValidationError(
            "signal bundle canonical_input mismatch: "
            f"expected {expected_canonical_input!r}, got {canonical_input!r}"
        )
    _validate_freshness(bundle, accepted_freshness_statuses=accepted_freshness_statuses)
    _validate_derived_indicators(bundle, canonical_input=canonical_input)
    _validate_provenance(bundle)


def validate_signal_bundle_manifest(
    path: str | PathLike[str],
    *,
    expected_canonical_input: str = CANONICAL_INPUT_DERIVED_INDICATORS,
    accepted_freshness_statuses: Iterable[str] = (FRESHNESS_FRESH,),
) -> dict[str, Any]:
    """Validate a manifest-referenced signal bundle and return audit summary."""

    manifest_path = Path(path)
    manifest = _load_json_mapping(manifest_path, label="signal bundle manifest")
    _validate_manifest(manifest)
    bundle_path = _resolve_relative_artifact_path(
        manifest_path.parent.resolve(),
        manifest["bundle_path"],
        owner="signal bundle manifest",
        field="bundle_path",
    )
    expected_sha256 = str(manifest["bundle_sha256"]).strip().lower()
    actual_sha256 = sha256_file(bundle_path)
    if actual_sha256 != expected_sha256:
        raise SignalBundleValidationError(
            "signal bundle sha256 mismatch: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )
    bundle = _load_json_mapping(bundle_path, label="signal bundle")
    validate_signal_bundle(
        bundle,
        expected_canonical_input=expected_canonical_input,
        accepted_freshness_statuses=accepted_freshness_statuses,
    )
    quality_report_summary = _validate_optional_quality_report_reference(
        manifest,
        manifest_root=manifest_path.parent.resolve(),
        bundle=bundle,
    )
    _validate_manifest_bundle_consistency(manifest, bundle)
    summary = signal_bundle_audit_summary(bundle)
    summary.update(
        {
            "manifest_path": str(manifest_path.resolve()),
            "manifest_schema_version": str(manifest.get("schema_version", "")),
            "bundle_sha256": expected_sha256,
        }
    )
    summary.update(quality_report_summary)
    return summary


def validate_signal_bundle_index(
    path: str | PathLike[str],
    *,
    expected_canonical_input: str = CANONICAL_INPUT_DERIVED_INDICATORS,
    as_of: str | None = None,
    bundle_id: str | None = None,
    accepted_freshness_statuses: Iterable[str] = (FRESHNESS_FRESH,),
) -> dict[str, Any]:
    """Validate an index-selected manifest and return audit summary."""

    index_path = Path(path)
    index = _load_json_mapping(index_path, label="signal bundle index")
    _validate_index(index)
    manifest_path = _resolve_manifest_from_index(
        index_path,
        index,
        expected_canonical_input=expected_canonical_input,
        as_of=as_of,
        bundle_id=bundle_id,
        accepted_freshness_statuses=accepted_freshness_statuses,
    )
    summary = validate_signal_bundle_manifest(
        manifest_path,
        expected_canonical_input=expected_canonical_input,
        accepted_freshness_statuses=accepted_freshness_statuses,
    )
    summary.update(
        {
            "index_path": str(index_path.resolve()),
            "index_schema_version": str(index.get("schema_version", "")),
            "index_bundle_count": len(index.get("bundles", ()) or ()),
        }
    )
    return summary


def required_indicator_fields_for_consumer(
    consumer: str,
) -> dict[str, tuple[str, ...]]:
    """Return required derived indicator fields for a known downstream consumer."""

    try:
        return _required_indicator_fields_for_consumer(consumer)
    except SignalConsumerContractError as exc:
        raise SignalBundleValidationError(str(exc)) from exc


def validate_signal_bundle_indicator_fields(
    bundle: Mapping[str, Any],
    *,
    required_fields_by_symbol: Mapping[str, Iterable[str]],
    expected_canonical_input: str = CANONICAL_INPUT_DERIVED_INDICATORS,
    accepted_freshness_statuses: Iterable[str] = (FRESHNESS_FRESH,),
) -> None:
    """Validate that a bundle covers required derived indicator fields."""

    validate_signal_bundle(
        bundle,
        expected_canonical_input=expected_canonical_input,
        accepted_freshness_statuses=accepted_freshness_statuses,
    )
    indicators = bundle[expected_canonical_input]
    if not isinstance(indicators, Mapping):
        raise SignalBundleValidationError(f"{expected_canonical_input} must be a mapping")
    normalized_indicators = {
        _normalize_symbol(symbol): payload
        for symbol, payload in indicators.items()
    }
    for symbol, raw_required_fields in required_fields_by_symbol.items():
        normalized_symbol = _normalize_symbol(symbol)
        payload = normalized_indicators.get(normalized_symbol)
        if not isinstance(payload, Mapping):
            raise SignalBundleValidationError(
                f"{expected_canonical_input} missing required symbol: {symbol}"
            )
        available = {str(field).strip().lower() for field in payload}
        required_fields = tuple(
            str(field).strip()
            for field in raw_required_fields
            if str(field).strip()
        )
        missing = [
            field
            for field in required_fields
            if field.lower() not in available
        ]
        if missing:
            raise SignalBundleValidationError(
                f"{expected_canonical_input}[{symbol!r}] missing required fields: "
                + ", ".join(missing)
            )


def validate_signal_bundle_for_consumer(
    bundle: Mapping[str, Any],
    *,
    consumer: str,
    expected_canonical_input: str = CANONICAL_INPUT_DERIVED_INDICATORS,
    accepted_freshness_statuses: Iterable[str] = (FRESHNESS_FRESH,),
) -> None:
    """Validate a signal bundle against a known downstream consumer contract."""

    validate_signal_bundle_indicator_fields(
        bundle,
        required_fields_by_symbol=required_indicator_fields_for_consumer(consumer),
        expected_canonical_input=expected_canonical_input,
        accepted_freshness_statuses=accepted_freshness_statuses,
    )


def signal_bundle_consumer_audit_summary(
    bundle: Mapping[str, Any],
    *,
    consumer: str,
    expected_canonical_input: str = CANONICAL_INPUT_DERIVED_INDICATORS,
    accepted_freshness_statuses: Iterable[str] = (FRESHNESS_FRESH,),
) -> dict[str, Any]:
    """Return audit summary after validating consumer-specific field coverage."""

    validate_signal_bundle_for_consumer(
        bundle,
        consumer=consumer,
        expected_canonical_input=expected_canonical_input,
        accepted_freshness_statuses=accepted_freshness_statuses,
    )
    summary = signal_bundle_audit_summary(bundle)
    summary.update(
        {
            "consumer": str(consumer),
            "required_indicator_fields_by_symbol": required_indicator_fields_for_consumer(
                consumer
            ),
        }
    )
    return summary


def validate_signal_bundle_manifest_for_consumer(
    path: str | PathLike[str],
    *,
    consumer: str,
    expected_canonical_input: str = CANONICAL_INPUT_DERIVED_INDICATORS,
    accepted_freshness_statuses: Iterable[str] = (FRESHNESS_FRESH,),
) -> dict[str, Any]:
    """Validate a manifest-referenced bundle against a consumer contract."""

    summary = validate_signal_bundle_manifest(
        path,
        expected_canonical_input=expected_canonical_input,
        accepted_freshness_statuses=accepted_freshness_statuses,
    )
    manifest_path = Path(path)
    manifest = _load_json_mapping(manifest_path, label="signal bundle manifest")
    bundle_path = _resolve_relative_artifact_path(
        manifest_path.parent.resolve(),
        manifest["bundle_path"],
        owner="signal bundle manifest",
        field="bundle_path",
    )
    bundle = _load_json_mapping(bundle_path, label="signal bundle")
    validate_signal_bundle_for_consumer(
        bundle,
        consumer=consumer,
        expected_canonical_input=expected_canonical_input,
        accepted_freshness_statuses=accepted_freshness_statuses,
    )
    summary.update(
        {
            "consumer": str(consumer),
            "required_indicator_fields_by_symbol": required_indicator_fields_for_consumer(
                consumer
            ),
        }
    )
    return summary


def validate_signal_bundle_index_for_consumer(
    path: str | PathLike[str],
    *,
    consumer: str,
    expected_canonical_input: str = CANONICAL_INPUT_DERIVED_INDICATORS,
    as_of: str | None = None,
    bundle_id: str | None = None,
    accepted_freshness_statuses: Iterable[str] = (FRESHNESS_FRESH,),
) -> dict[str, Any]:
    """Validate an index-selected bundle against a consumer contract."""

    index_path = Path(path)
    index = _load_json_mapping(index_path, label="signal bundle index")
    _validate_index(index)
    manifest_path = _resolve_manifest_from_index(
        index_path,
        index,
        expected_canonical_input=expected_canonical_input,
        as_of=as_of,
        bundle_id=bundle_id,
        accepted_freshness_statuses=accepted_freshness_statuses,
    )
    summary = validate_signal_bundle_manifest_for_consumer(
        manifest_path,
        consumer=consumer,
        expected_canonical_input=expected_canonical_input,
        accepted_freshness_statuses=accepted_freshness_statuses,
    )
    summary.update(
        {
            "index_path": str(index_path.resolve()),
            "index_schema_version": str(index.get("schema_version", "")),
            "index_bundle_count": len(index.get("bundles", ()) or ()),
        }
    )
    return summary


def validate_research_export_manifest(
    path: str | PathLike[str],
    *,
    expected_artifact_type: str | None = None,
    expected_transform: str | None = None,
) -> dict[str, Any]:
    """Validate a research_export.v1 CSV manifest and return audit summary."""

    manifest_path = Path(path)
    manifest = _load_json_mapping(manifest_path, label="research export manifest")
    _validate_research_export_manifest_shape(
        manifest,
        expected_artifact_type=expected_artifact_type,
        expected_transform=expected_transform,
    )
    input_record = dict(manifest["input_csv"])
    output_record = dict(manifest["output_csv"])
    input_path = _resolve_manifest_file_path(manifest_path, input_record["path"], field="input_csv.path")
    output_path = _resolve_manifest_file_path(
        manifest_path,
        output_record["path"],
        field="output_csv.path",
    )
    _validate_manifest_file_record(input_record, input_path, field="input_csv")
    _validate_manifest_file_record(output_record, output_path, field="output_csv")
    _validate_research_export_output_csv_shape(manifest, output_path)

    return {
        "manifest_path": str(manifest_path.resolve()),
        "schema_version": str(manifest.get("schema_version", "")),
        "artifact_type": str(manifest.get("artifact_type", "")),
        "transform": str(manifest.get("transform", "")),
        "source_version": str(manifest.get("source_version", "")),
        "as_of": manifest.get("as_of"),
        "min_history": int(manifest.get("min_history", 0)),
        "row_count": int(manifest.get("row_count", 0)),
        "first_date": str(manifest.get("first_date", "")),
        "last_date": str(manifest.get("last_date", "")),
        "columns": tuple(str(column) for column in manifest["columns"]),
        "input_csv_path": str(input_path),
        "input_csv_sha256": str(input_record["sha256"]).strip().lower(),
        "input_csv_size_bytes": int(input_record["size_bytes"]),
        "output_csv_path": str(output_path),
        "output_csv_sha256": str(output_record["sha256"]).strip().lower(),
        "output_csv_size_bytes": int(output_record["size_bytes"]),
    }


def signal_bundle_audit_summary(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Return non-sensitive audit fields and indicator field coverage."""

    validate_signal_bundle(bundle)
    freshness = bundle.get("freshness")
    provenance = bundle.get("provenance")
    if not isinstance(freshness, Mapping) or not isinstance(provenance, Mapping):
        raise SignalBundleValidationError("signal bundle audit fields are incomplete")
    fields_by_symbol = _indicator_fields_by_symbol(bundle)
    return {
        "bundle_id": str(bundle.get("bundle_id", "")),
        "schema_version": str(bundle.get("schema_version", "")),
        "bundle_type": str(bundle.get("bundle_type", "")),
        "canonical_input": _canonical_input(bundle),
        "as_of": str(bundle.get("as_of", "")),
        "generated_at": str(bundle.get("generated_at", "")),
        "symbols": tuple(str(symbol) for symbol in bundle.get("symbols", ()) or ()),
        "indicator_fields_by_symbol": fields_by_symbol,
        "indicator_field_count_by_symbol": {
            symbol: len(fields)
            for symbol, fields in fields_by_symbol.items()
        },
        "freshness_status": str(freshness.get("status", "")),
        "freshness_policy": str(freshness.get("policy", "")),
        "provider_timestamp": str(freshness.get("provider_timestamp", "")),
        "source_repo": str(provenance.get("source_repo", "")),
        "source_version": str(provenance.get("source_version", "")),
        "code_commit": str(provenance.get("code_commit", "")),
        "provider": str(provenance.get("provider", "")),
        "provider_dataset": str(provenance.get("provider_dataset", "")),
        "transform": str(provenance.get("transform", "")),
    }


def _load_json_mapping(path: Path, *, label: str) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file_obj:
        payload = json.load(file_obj)
    if not isinstance(payload, Mapping):
        raise SignalBundleValidationError(f"{label} JSON root must be a mapping")
    return dict(payload)


def _resolve_manifest_from_index(
    index_path: Path,
    index: Mapping[str, Any],
    *,
    expected_canonical_input: str,
    as_of: str | None,
    bundle_id: str | None,
    accepted_freshness_statuses: Iterable[str],
) -> Path:
    accepted = {str(item).strip().lower() for item in accepted_freshness_statuses}
    target_as_of = str(as_of).strip() if as_of is not None else None
    candidates: list[Mapping[str, Any]] = []
    for raw_entry in index["bundles"]:
        entry = dict(raw_entry)
        entry_canonical_input = str(entry.get("canonical_input", "")).strip()
        entry_freshness = str(entry.get("freshness_status", "")).strip().lower()
        entry_bundle_id = str(entry.get("bundle_id", "")).strip()
        entry_as_of = str(entry.get("as_of", "")).strip()
        if entry_canonical_input != expected_canonical_input:
            continue
        if entry_freshness not in accepted:
            continue
        if bundle_id is not None and entry_bundle_id != str(bundle_id).strip():
            continue
        if target_as_of is not None and entry_as_of > target_as_of:
            continue
        candidates.append(entry)
    if not candidates:
        raise SignalBundleValidationError("signal bundle index has no matching manifest entry")

    selected = max(candidates, key=lambda entry: str(entry.get("as_of", "")))
    manifest_path = _resolve_relative_artifact_path(
        index_path.parent.resolve(),
        selected["manifest_path"],
        owner="signal bundle index",
        field="manifest_path",
    )
    expected_manifest_sha256 = str(selected["manifest_sha256"]).strip().lower()
    actual_manifest_sha256 = sha256_file(manifest_path)
    if actual_manifest_sha256 != expected_manifest_sha256:
        raise SignalBundleValidationError(
            "signal bundle index manifest_sha256 mismatch: "
            f"expected {expected_manifest_sha256}, got {actual_manifest_sha256}"
        )
    manifest = _load_json_mapping(manifest_path, label="signal bundle manifest")
    _validate_index_manifest_consistency(selected, manifest)
    return manifest_path


def _validate_manifest(manifest: Mapping[str, Any]) -> None:
    _validate_no_sensitive_fields(manifest, path="manifest")
    if manifest.get("schema_version") != MARKET_SIGNAL_MANIFEST_SCHEMA_VERSION:
        raise SignalBundleValidationError(
            "unsupported signal bundle manifest schema_version: "
            f"{manifest.get('schema_version')!r}"
        )
    for field in ("bundle_path", "bundle_sha256", "bundle_id", "as_of", "canonical_input"):
        if not _has_non_empty_value(manifest, field):
            raise SignalBundleValidationError(f"signal bundle manifest missing field: {field}")
    quality_path_present = _has_non_empty_value(manifest, "quality_report_path")
    quality_sha_present = _has_non_empty_value(manifest, "quality_report_sha256")
    if quality_path_present != quality_sha_present:
        raise SignalBundleValidationError(
            "signal bundle manifest quality_report_path and "
            "quality_report_sha256 must be provided together"
        )


def _validate_optional_quality_report_reference(
    manifest: Mapping[str, Any],
    *,
    manifest_root: Path,
    bundle: Mapping[str, Any],
) -> dict[str, Any]:
    if not _has_non_empty_value(manifest, "quality_report_path"):
        return {}
    quality_path = _resolve_relative_artifact_path(
        manifest_root,
        manifest["quality_report_path"],
        owner="signal bundle manifest",
        field="quality_report_path",
    )
    expected_sha256 = str(manifest["quality_report_sha256"]).strip().lower()
    actual_sha256 = sha256_file(quality_path)
    if actual_sha256 != expected_sha256:
        raise SignalBundleValidationError(
            "signal bundle quality_report_sha256 mismatch: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )
    quality_report = _load_json_mapping(quality_path, label="quality report")
    _validate_quality_report(quality_report)
    _validate_quality_report_bundle_consistency(quality_report, bundle)
    return {
        "quality_report_path": str(quality_path.resolve()),
        "quality_report_sha256": expected_sha256,
        "quality_status": str(quality_report["quality_status"]),
        "quality_failure_reasons": tuple(quality_report["failure_reasons"]),
        "quality_warning_reasons": tuple(quality_report["warning_reasons"]),
        "quality_raw_row_count": int(quality_report["raw_row_count"]),
        "quality_normalized_row_count": int(quality_report["normalized_row_count"]),
        "quality_first_date": str(quality_report["first_date"]),
        "quality_last_date": str(quality_report["last_date"]),
    }


def _validate_quality_report_bundle_consistency(
    quality_report: Mapping[str, Any],
    bundle: Mapping[str, Any],
) -> None:
    input_csv = quality_report.get("input_csv")
    provenance = bundle.get("provenance")
    if not isinstance(input_csv, Mapping):
        raise SignalBundleValidationError("quality report input_csv must be a mapping")
    if not isinstance(provenance, Mapping):
        raise SignalBundleValidationError("signal bundle provenance must be a mapping")
    quality_input_sha256 = str(input_csv.get("sha256", "")).strip().lower()
    bundle_raw_sha256 = str(provenance.get("raw_artifact_sha256", "")).strip().lower()
    if not quality_input_sha256:
        raise SignalBundleValidationError("quality report input_csv.sha256 is required")
    if quality_input_sha256 != bundle_raw_sha256:
        raise SignalBundleValidationError(
            "quality report input_csv.sha256 mismatch with "
            "signal bundle provenance.raw_artifact_sha256: "
            f"expected {bundle_raw_sha256}, got {quality_input_sha256}"
        )


def _validate_quality_report(report: Mapping[str, Any]) -> None:
    _validate_no_sensitive_fields(
        report,
        owner="quality report",
        path="quality_report",
    )
    if report.get("schema_version") != QUALITY_REPORT_SCHEMA_VERSION:
        raise SignalBundleValidationError(
            "unsupported quality report schema_version: "
            f"{report.get('schema_version')!r}"
        )
    if report.get("artifact_type") != "local_ohlcv_quality_report":
        raise SignalBundleValidationError(
            "quality report artifact_type mismatch: "
            f"{report.get('artifact_type')!r}"
        )
    for field in (
        "quality_status",
        "failure_reasons",
        "warning_reasons",
        "raw_row_count",
        "normalized_row_count",
        "first_date",
        "last_date",
    ):
        if field not in report:
            raise SignalBundleValidationError(f"quality report missing field: {field}")
    if not _has_non_empty_value(report, "quality_status"):
        raise SignalBundleValidationError("quality report missing field: quality_status")
    if report["quality_status"] not in {"pass", "warn", "fail"}:
        raise SignalBundleValidationError(
            f"unsupported quality_status: {report['quality_status']!r}"
        )
    if not _is_string_sequence(report["failure_reasons"]):
        raise SignalBundleValidationError("quality report failure_reasons must be strings")
    if not _is_string_sequence(report["warning_reasons"]):
        raise SignalBundleValidationError("quality report warning_reasons must be strings")
    for field in ("raw_row_count", "normalized_row_count"):
        value = report[field]
        if not isinstance(value, int) or value < 0:
            raise SignalBundleValidationError(
                f"quality report {field} must be a non-negative integer"
            )
    if report["quality_status"] == "fail":
        raise SignalBundleValidationError(
            "quality report status is fail: "
            + ",".join(str(reason) for reason in report["failure_reasons"])
        )


def _validate_index(index: Mapping[str, Any]) -> None:
    _validate_no_sensitive_fields(index, path="index")
    if index.get("schema_version") != MARKET_SIGNAL_INDEX_SCHEMA_VERSION:
        raise SignalBundleValidationError(
            "unsupported signal bundle index schema_version: "
            f"{index.get('schema_version')!r}"
        )
    bundles = index.get("bundles")
    if not _is_non_string_sequence(bundles) or not bundles:
        raise SignalBundleValidationError("signal bundle index bundles must be a non-empty sequence")
    for raw_entry in bundles:
        if not isinstance(raw_entry, Mapping):
            raise SignalBundleValidationError("signal bundle index entries must be mappings")
        entry = dict(raw_entry)
        for field in (
            "manifest_path",
            "manifest_sha256",
            "bundle_id",
            "as_of",
            "canonical_input",
            "freshness_status",
        ):
            if not _has_non_empty_value(entry, field):
                raise SignalBundleValidationError(
                    f"signal bundle index entry missing field: {field}"
                )


def _validate_research_export_manifest_shape(
    manifest: Mapping[str, Any],
    *,
    expected_artifact_type: str | None,
    expected_transform: str | None,
) -> None:
    _validate_no_sensitive_fields(
        manifest,
        owner="research export manifest",
        path="manifest",
    )
    if manifest.get("schema_version") != RESEARCH_EXPORT_SCHEMA_VERSION:
        raise SignalBundleValidationError(
            "unsupported research export schema_version: "
            f"{manifest.get('schema_version')!r}"
        )
    for field in (
        "artifact_type",
        "transform",
        "source_version",
        "min_history",
        "row_count",
        "first_date",
        "last_date",
        "columns",
        "input_csv",
        "output_csv",
    ):
        if not _has_non_empty_value(manifest, field):
            raise SignalBundleValidationError(f"research export manifest missing field: {field}")
    if (
        expected_artifact_type is not None
        and str(manifest["artifact_type"]).strip() != str(expected_artifact_type).strip()
    ):
        raise SignalBundleValidationError(
            "research export artifact_type mismatch: "
            f"{manifest['artifact_type']!r} != {expected_artifact_type!r}"
        )
    if (
        expected_transform is not None
        and str(manifest["transform"]).strip() != str(expected_transform).strip()
    ):
        raise SignalBundleValidationError(
            "research export transform mismatch: "
            f"{manifest['transform']!r} != {expected_transform!r}"
        )
    if not _is_string_sequence(manifest.get("columns")):
        raise SignalBundleValidationError("research export columns must be a sequence of strings")
    for field in ("min_history", "row_count"):
        value = manifest.get(field)
        if not isinstance(value, int) or value < 0:
            raise SignalBundleValidationError(
                f"research export {field} must be a non-negative integer"
            )
    for field in ("input_csv", "output_csv"):
        record = manifest.get(field)
        if not isinstance(record, Mapping):
            raise SignalBundleValidationError(f"research export {field} must be a mapping")
        for record_field in ("path", "sha256", "size_bytes"):
            if not _has_non_empty_value(record, record_field):
                raise SignalBundleValidationError(
                    f"research export {field} missing field: {record_field}"
                )
        size_bytes = record.get("size_bytes")
        if not isinstance(size_bytes, int) or size_bytes < 0:
            raise SignalBundleValidationError(
                f"research export {field}.size_bytes must be a non-negative integer"
            )


def _resolve_manifest_file_path(
    manifest_path: Path,
    value: object,
    *,
    field: str,
) -> Path:
    raw_path = Path(str(value))
    if raw_path.is_absolute():
        return raw_path
    manifest_relative = (manifest_path.parent / raw_path).resolve()
    if manifest_relative.exists():
        return manifest_relative
    cwd_relative = raw_path.resolve()
    if cwd_relative.exists():
        return cwd_relative
    raise SignalBundleValidationError(
        f"research export {field} does not exist relative to manifest or cwd: {value}"
    )


def _validate_manifest_file_record(
    record: Mapping[str, Any],
    path: Path,
    *,
    field: str,
) -> None:
    expected_sha256 = str(record["sha256"]).strip().lower()
    actual_sha256 = sha256_file(path)
    if actual_sha256 != expected_sha256:
        raise SignalBundleValidationError(
            f"research export {field}.sha256 mismatch: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )
    expected_size_bytes = int(record["size_bytes"])
    actual_size_bytes = path.stat().st_size
    if actual_size_bytes != expected_size_bytes:
        raise SignalBundleValidationError(
            f"research export {field}.size_bytes mismatch: "
            f"expected {expected_size_bytes}, got {actual_size_bytes}"
        )


def _validate_research_export_output_csv_shape(
    manifest: Mapping[str, Any],
    output_path: Path,
) -> None:
    with output_path.open(newline="", encoding="utf-8") as file_obj:
        reader = csv.reader(file_obj)
        try:
            header = tuple(next(reader))
        except StopIteration as exc:
            raise SignalBundleValidationError(
                "research export output_csv is empty"
            ) from exc

        manifest_columns = tuple(str(column) for column in manifest["columns"])
        if header != manifest_columns:
            raise SignalBundleValidationError(
                "research export output_csv columns mismatch: "
                f"expected {manifest_columns}, got {header}"
            )

        actual_row_count = 0
        actual_first_date = ""
        actual_last_date = ""
        date_index = header.index("date") if "date" in header else None
        for row in reader:
            actual_row_count += 1
            if date_index is None:
                continue
            if date_index >= len(row):
                raise SignalBundleValidationError(
                    "research export output_csv row missing date column value"
                )
            if not actual_first_date:
                actual_first_date = str(row[date_index])
            actual_last_date = str(row[date_index])

    expected_row_count = int(manifest["row_count"])
    if actual_row_count != expected_row_count:
        raise SignalBundleValidationError(
            "research export output_csv row_count mismatch: "
            f"expected {expected_row_count}, got {actual_row_count}"
        )
    if "date" not in header:
        return
    expected_first_date = str(manifest.get("first_date", ""))
    expected_last_date = str(manifest.get("last_date", ""))
    if actual_first_date != expected_first_date:
        raise SignalBundleValidationError(
            "research export output_csv first_date mismatch: "
            f"expected {expected_first_date!r}, got {actual_first_date!r}"
        )
    if actual_last_date != expected_last_date:
        raise SignalBundleValidationError(
            "research export output_csv last_date mismatch: "
            f"expected {expected_last_date!r}, got {actual_last_date!r}"
        )


def _resolve_relative_artifact_path(
    root: Path,
    value: object,
    *,
    owner: str,
    field: str,
) -> Path:
    relative_path = Path(str(value))
    if relative_path.is_absolute():
        raise SignalBundleValidationError(f"{owner} {field} must be relative")
    resolved = (root / relative_path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SignalBundleValidationError(f"{owner} {field} escapes artifact directory") from exc
    return resolved


def _validate_manifest_bundle_consistency(
    manifest: Mapping[str, Any],
    bundle: Mapping[str, Any],
) -> None:
    for field in ("bundle_id", "as_of"):
        manifest_value = str(manifest.get(field, "")).strip()
        bundle_value = str(bundle.get(field, "")).strip()
        if manifest_value != bundle_value:
            raise SignalBundleValidationError(
                f"signal bundle manifest {field} mismatch: {manifest_value!r} != {bundle_value!r}"
            )
    manifest_canonical_input = str(manifest.get("canonical_input", "")).strip()
    if manifest_canonical_input != _canonical_input(bundle):
        raise SignalBundleValidationError(
            "signal bundle manifest canonical_input mismatch: "
            f"{manifest_canonical_input!r} != {_canonical_input(bundle)!r}"
        )
    manifest_bundle_schema = str(manifest.get("bundle_schema_version", "")).strip()
    if manifest_bundle_schema and manifest_bundle_schema != str(bundle.get("schema_version", "")).strip():
        raise SignalBundleValidationError(
            "signal bundle manifest schema_version mismatch: "
            f"{manifest_bundle_schema!r} != {bundle.get('schema_version')!r}"
        )
    manifest_freshness = str(manifest.get("freshness_status", "")).strip()
    freshness = bundle.get("freshness")
    if isinstance(freshness, Mapping):
        bundle_freshness = str(freshness.get("status", "")).strip()
        if manifest_freshness and manifest_freshness != bundle_freshness:
            raise SignalBundleValidationError(
                "signal bundle manifest freshness_status mismatch: "
                f"{manifest_freshness!r} != {bundle_freshness!r}"
            )


def _validate_index_manifest_consistency(
    entry: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> None:
    for field in ("bundle_id", "as_of", "canonical_input"):
        entry_value = str(entry.get(field, "")).strip()
        manifest_value = str(manifest.get(field, "")).strip()
        if entry_value != manifest_value:
            raise SignalBundleValidationError(
                f"signal bundle index {field} mismatch: {entry_value!r} != {manifest_value!r}"
            )
    entry_freshness = str(entry.get("freshness_status", "")).strip()
    manifest_freshness = str(manifest.get("freshness_status", "")).strip()
    if manifest_freshness and entry_freshness != manifest_freshness:
        raise SignalBundleValidationError(
            "signal bundle index freshness_status mismatch: "
            f"{entry_freshness!r} != {manifest_freshness!r}"
        )


def _canonical_input(bundle: Mapping[str, Any]) -> str:
    consumer_contract = bundle.get("consumer_contract")
    if not isinstance(consumer_contract, Mapping):
        raise SignalBundleValidationError("consumer_contract must be a mapping")
    canonical_input = consumer_contract.get("canonical_input")
    if not isinstance(canonical_input, str) or not canonical_input.strip():
        raise SignalBundleValidationError(
            "consumer_contract.canonical_input must be a non-empty string"
        )
    return canonical_input.strip()


def _validate_freshness(
    bundle: Mapping[str, Any],
    *,
    accepted_freshness_statuses: Iterable[str],
) -> None:
    freshness = bundle.get("freshness")
    if not isinstance(freshness, Mapping):
        raise SignalBundleValidationError("freshness must be a mapping")
    status = freshness.get("status")
    if not isinstance(status, str) or not status.strip():
        raise SignalBundleValidationError("freshness.status must be a non-empty string")
    accepted = {str(item).strip().lower() for item in accepted_freshness_statuses}
    if status.strip().lower() not in accepted:
        raise SignalBundleValidationError(f"unacceptable freshness.status: {status!r}")
    provider_timestamp = freshness.get("provider_timestamp")
    if not isinstance(provider_timestamp, str) or not provider_timestamp.strip():
        raise SignalBundleValidationError(
            "freshness.provider_timestamp must be a non-empty string"
        )


def _validate_derived_indicators(
    bundle: Mapping[str, Any],
    *,
    canonical_input: str,
) -> None:
    indicators = bundle.get(canonical_input)
    if not isinstance(indicators, Mapping) or not indicators:
        raise SignalBundleValidationError("derived_indicators must be a non-empty mapping")
    symbols = bundle.get("symbols")
    if symbols is not None:
        if not _is_string_sequence(symbols):
            raise SignalBundleValidationError("symbols must be a sequence of strings")
        missing = [symbol for symbol in symbols if symbol not in indicators]
        if missing:
            raise SignalBundleValidationError(
                "derived_indicators missing symbols: "
                + ", ".join(str(symbol) for symbol in missing)
            )
    for symbol, payload in indicators.items():
        if not isinstance(symbol, str) or not symbol.strip():
            raise SignalBundleValidationError("derived_indicators keys must be symbols")
        if not isinstance(payload, Mapping) or not payload:
            raise SignalBundleValidationError(
                f"derived_indicators[{symbol!r}] must be a non-empty mapping"
            )


def _validate_provenance(bundle: Mapping[str, Any]) -> None:
    provenance = bundle.get("provenance")
    if not isinstance(provenance, Mapping):
        raise SignalBundleValidationError("provenance must be a mapping")
    missing = [
        field
        for field in sorted(_REQUIRED_PROVENANCE_FIELDS)
        if not _has_non_empty_value(provenance, field)
    ]
    if missing:
        raise SignalBundleValidationError(
            "provenance missing required fields: " + ", ".join(missing)
        )


def _indicator_fields_by_symbol(bundle: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    canonical_input = _canonical_input(bundle)
    indicators = bundle.get(canonical_input)
    if not isinstance(indicators, Mapping):
        raise SignalBundleValidationError("signal bundle indicators must be a mapping")
    fields_by_symbol: dict[str, tuple[str, ...]] = {}
    for symbol, payload in indicators.items():
        if not isinstance(payload, Mapping):
            raise SignalBundleValidationError(
                f"signal bundle indicators[{symbol!r}] must be a mapping"
            )
        fields_by_symbol[str(symbol)] = tuple(sorted(str(field) for field in payload))
    return fields_by_symbol


def _normalize_symbol(symbol: object) -> str:
    return str(symbol or "").strip().upper().removesuffix(".US")


def _validate_no_sensitive_fields(
    value: Any,
    *,
    owner: str = "signal bundle",
    path: str = "bundle",
) -> None:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key).strip().lower()
            if any(fragment in key for fragment in _FORBIDDEN_SENSITIVE_KEY_FRAGMENTS):
                raise SignalBundleValidationError(
                    f"sensitive field is not allowed in {owner}: {path}.{raw_key}"
                )
            _validate_no_sensitive_fields(item, owner=owner, path=f"{path}.{raw_key}")
    elif _is_non_string_sequence(value):
        for index, item in enumerate(value):
            _validate_no_sensitive_fields(item, owner=owner, path=f"{path}[{index}]")


def _has_non_empty_value(mapping: Mapping[str, Any], field: str) -> bool:
    value = mapping.get(field)
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None


def _is_non_string_sequence(value: Any) -> bool:
    return not isinstance(value, (str, bytes)) and isinstance(value, Sequence)


def _is_string_sequence(value: Any) -> bool:
    if not _is_non_string_sequence(value):
        return False
    return all(isinstance(item, str) and item.strip() for item in value)
