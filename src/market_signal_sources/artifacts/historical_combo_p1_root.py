"""Seal already-acquired historical-combo inputs into one immutable local root.

The P1 metadata binding says *which* historical price panel and point-in-time
universe sources a future replay may use.  This module supplies the deliberately
small missing storage boundary: it copies those already-local byte streams into
a fresh private root, binds every byte to the metadata digests, and can later
verify that root without contacting a provider.

It does not download, parse, repair, or infer market data; validate a quality
report; choose a candidate; run P2/P3; or grant paper, shadow, live, broker, or
credential access.  Those remain separate concerns.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

from .historical_combo_p1_input import (
    HistoricalComboP1InputError,
    validate_historical_combo_p1_input,
)

HISTORICAL_COMBO_P1_ROOT_MANIFEST_SCHEMA = "qsl.us-equity-historical-combo-p1-root-manifest.v1"
ROOT_STATUS = "P1_HISTORICAL_COMBO_INPUT_PUBLISHED"
_MANIFEST_FILENAME = "manifest.json"
_INPUT_FILENAME = "input.json"
_PRICE_PANEL_FILENAME = "price-panel.raw"
_QUALITY_REPORT_FILENAME = "quality-report.raw"
_UNIVERSE_SOURCE_DIRECTORY = "universe-source"
_METADATA_BYTE_LIMIT = 1 << 20
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "research_only",
        "execution_authorized",
        "input_sha256",
        "members",
        "manifest_sha256",
    }
)
_MEMBER_FIELDS = frozenset({"path", "media_type", "size_bytes", "sha256"})


class HistoricalComboP1RootError(ValueError):
    """Raised when a local P1 root is incomplete, mutable, or inconsistent."""


def _fail(message: str) -> None:
    raise HistoricalComboP1RootError(message)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HistoricalComboP1RootError("invalid historical combo P1 root") from exc


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with os.fdopen(_open_private_regular_file(path), "rb") as handle:
            while chunk := handle.read(1 << 20):
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise HistoricalComboP1RootError("invalid historical combo P1 root") from exc
    return digest.hexdigest(), size


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        _fail(f"invalid {label}")
    return value


def _bytes(value: object, label: str) -> bytes:
    if not isinstance(value, bytes) or not value:
        _fail(f"invalid {label}")
    return value


def _validate_input(value: object) -> dict[str, object]:
    try:
        return validate_historical_combo_p1_input(value)
    except HistoricalComboP1InputError as exc:
        raise HistoricalComboP1RootError("invalid historical combo P1 input") from exc


def _expected_universe_source_digests(input_record: Mapping[str, object]) -> list[tuple[str, str]]:
    rebalances = input_record.get("rebalances")
    if not isinstance(rebalances, list):
        _fail("invalid historical combo P1 input")
    result: list[tuple[str, str]] = []
    for rebalance in rebalances:
        if not isinstance(rebalance, Mapping):
            _fail("invalid historical combo P1 input")
        decision_at = rebalance.get("decision_at")
        snapshot = rebalance.get("universe_snapshot")
        if not isinstance(decision_at, str) or not isinstance(snapshot, Mapping):
            _fail("invalid historical combo P1 input")
        source = snapshot.get("source")
        if not isinstance(source, Mapping):
            _fail("invalid historical combo P1 input")
        result.append((decision_at, _digest(source.get("raw_artifact_sha256"), "universe source digest")))
    return result


def _expected_relative_paths(input_record: Mapping[str, object]) -> tuple[str, ...]:
    universe_count = len(_expected_universe_source_digests(input_record))
    return (
        _INPUT_FILENAME,
        _MANIFEST_FILENAME,
        _PRICE_PANEL_FILENAME,
        _QUALITY_REPORT_FILENAME,
        *(f"{_UNIVERSE_SOURCE_DIRECTORY}/{index:04d}.raw" for index in range(universe_count)),
    )


def _require_new_private_output_root(output_root: str | Path) -> Path:
    destination = Path(output_root)
    if destination.exists() or destination.is_symlink():
        _fail("immutable output already exists")
    if destination.parent.is_symlink() or not destination.parent.is_dir():
        _fail("output parent is unavailable")
    return destination


def _publish_noreplace(source: Path, destination: Path) -> None:
    """Atomically publish a verified root without replacing an existing root."""
    if not sys.platform.startswith("linux"):
        _fail("required no-clobber capability unavailable")
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        _fail("required no-clobber capability unavailable")
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    parent_flags = getattr(os, "O_PATH", os.O_RDONLY) | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        parent_fd = os.open(destination.parent, parent_flags)
    except OSError as exc:
        raise HistoricalComboP1RootError("output parent is unavailable") from exc
    try:
        result = renameat2(parent_fd, source.name.encode(), parent_fd, destination.name.encode(), 1)
    finally:
        os.close(parent_fd)
    if result == 0:
        return
    if ctypes.get_errno() == errno.EEXIST:
        _fail("immutable output already exists")
    _fail("atomic no-clobber publish failed")


def _member(path: str, *, payload: bytes, media_type: str = "application/octet-stream") -> dict[str, object]:
    return {
        "path": path,
        "media_type": media_type,
        "size_bytes": len(payload),
        "sha256": _sha256_bytes(payload),
    }


def _manifest_without_digest(
    *, input_sha256: str, members: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "schema_version": HISTORICAL_COMBO_P1_ROOT_MANIFEST_SCHEMA,
        "research_only": True,
        "execution_authorized": False,
        "input_sha256": input_sha256,
        "members": members,
    }


def _build_manifest(*, input_sha256: str, members: list[dict[str, object]]) -> dict[str, object]:
    result = _manifest_without_digest(input_sha256=input_sha256, members=members)
    result["manifest_sha256"] = _sha256_bytes(_canonical(result))
    return validate_historical_combo_p1_root_manifest(result)


def _members(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or not value:
        _fail("invalid root members")
    result: list[dict[str, object]] = []
    prior_path: str | None = None
    for member in value:
        if not isinstance(member, Mapping) or set(member) != _MEMBER_FIELDS:
            _fail("invalid root member")
        path = member.get("path")
        media_type = member.get("media_type")
        size_bytes = member.get("size_bytes")
        if (
            not isinstance(path, str)
            or path.startswith("/")
            or path == ""
            or ".." in Path(path).parts
            or not isinstance(media_type, str)
            or not media_type
            or isinstance(size_bytes, bool)
            or not isinstance(size_bytes, int)
            or size_bytes <= 0
        ):
            _fail("invalid root member")
        if prior_path is not None and path <= prior_path:
            _fail("root members must be uniquely sorted")
        prior_path = path
        result.append(
            {
                "path": path,
                "media_type": media_type,
                "size_bytes": size_bytes,
                "sha256": _digest(member.get("sha256"), "root member digest"),
            }
        )
    return result


def validate_historical_combo_p1_root_manifest(value: object) -> dict[str, object]:
    """Validate a root manifest without opening raw market-data members."""
    if not isinstance(value, Mapping) or set(value) != _MANIFEST_FIELDS:
        _fail("invalid historical combo P1 root manifest")
    if (
        value.get("schema_version") != HISTORICAL_COMBO_P1_ROOT_MANIFEST_SCHEMA
        or value.get("research_only") is not True
        or value.get("execution_authorized") is not False
    ):
        _fail("invalid historical combo P1 root manifest")
    normalized: dict[str, object] = {
        "schema_version": HISTORICAL_COMBO_P1_ROOT_MANIFEST_SCHEMA,
        "research_only": True,
        "execution_authorized": False,
        "input_sha256": _digest(value.get("input_sha256"), "P1 input digest"),
        "members": _members(value.get("members")),
        "manifest_sha256": _digest(value.get("manifest_sha256"), "root manifest digest"),
    }
    if normalized["manifest_sha256"] != _sha256_bytes(
        _canonical({key: item for key, item in normalized.items() if key != "manifest_sha256"})
    ):
        _fail("root manifest digest mismatch")
    return normalized


def canonical_historical_combo_p1_root_manifest_bytes(value: object) -> bytes:
    """Return canonical bytes for a validated root manifest."""
    return _canonical(validate_historical_combo_p1_root_manifest(value))


def _input_bytes(input_record: Mapping[str, object]) -> bytes:
    return _canonical(input_record)


def _source_bytes(
    input_record: Mapping[str, object], universe_source_bytes: Mapping[str, object]
) -> list[bytes]:
    expected = _expected_universe_source_digests(input_record)
    if set(universe_source_bytes) != {decision_at for decision_at, _ in expected}:
        _fail("universe source inputs must exactly match P1 decisions")
    result: list[bytes] = []
    for decision_at, expected_digest in expected:
        payload = _bytes(universe_source_bytes[decision_at], "universe source bytes")
        if _sha256_bytes(payload) != expected_digest:
            _fail("universe source digest mismatch")
        result.append(payload)
    return result


def _price_panel_digests(input_record: Mapping[str, object]) -> tuple[str, str]:
    price_panel = input_record.get("price_panel")
    if not isinstance(price_panel, Mapping):
        _fail("invalid historical combo P1 input")
    source = price_panel.get("source")
    if not isinstance(source, Mapping):
        _fail("invalid historical combo P1 input")
    return (
        _digest(source.get("raw_artifact_sha256"), "price-panel raw digest"),
        _digest(source.get("quality_report_sha256"), "quality-report digest"),
    )


def publish_historical_combo_p1_root(
    *,
    combo_p1_input: object,
    price_panel_bytes: object,
    quality_report_bytes: object,
    universe_source_bytes: Mapping[str, object],
    output_root: str | Path,
) -> dict[str, str]:
    """Copy exact local P1 inputs into one create-only, research-only root.

    ``universe_source_bytes`` is keyed by the exact ISO-8601 ``decision_at``
    values from the P1 record.  The function accepts bytes that were acquired
    elsewhere; it never makes a network call or attempts to cure an incomplete
    data set.
    """
    destination = _require_new_private_output_root(output_root)
    input_record = _validate_input(combo_p1_input)
    panel_bytes = _bytes(price_panel_bytes, "price panel bytes")
    report_bytes = _bytes(quality_report_bytes, "quality report bytes")
    expected_panel_digest, expected_report_digest = _price_panel_digests(input_record)
    if _sha256_bytes(panel_bytes) != expected_panel_digest:
        _fail("price-panel raw digest mismatch")
    if _sha256_bytes(report_bytes) != expected_report_digest:
        _fail("quality-report digest mismatch")
    source_bytes = _source_bytes(input_record, universe_source_bytes)
    input_bytes = _input_bytes(input_record)
    input_sha256 = str(input_record["input_sha256"])
    members = [
        _member(_INPUT_FILENAME, payload=input_bytes, media_type="application/json"),
        _member(_PRICE_PANEL_FILENAME, payload=panel_bytes),
        _member(_QUALITY_REPORT_FILENAME, payload=report_bytes),
        *[
            _member(f"{_UNIVERSE_SOURCE_DIRECTORY}/{index:04d}.raw", payload=payload)
            for index, payload in enumerate(source_bytes)
        ],
    ]
    members.sort(key=lambda member: str(member["path"]))
    manifest = _build_manifest(input_sha256=input_sha256, members=members)
    manifest_bytes = canonical_historical_combo_p1_root_manifest_bytes(manifest)

    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
    try:
        temporary.chmod(0o700)
        source_directory = temporary / _UNIVERSE_SOURCE_DIRECTORY
        source_directory.mkdir(mode=0o700)
        (temporary / _INPUT_FILENAME).write_bytes(input_bytes)
        (temporary / _PRICE_PANEL_FILENAME).write_bytes(panel_bytes)
        (temporary / _QUALITY_REPORT_FILENAME).write_bytes(report_bytes)
        for index, payload in enumerate(source_bytes):
            (source_directory / f"{index:04d}.raw").write_bytes(payload)
        (temporary / _MANIFEST_FILENAME).write_bytes(manifest_bytes)
        for relative_path in _expected_relative_paths(input_record):
            if relative_path == _MANIFEST_FILENAME:
                continue
            (temporary / relative_path).chmod(0o600)
        (temporary / _MANIFEST_FILENAME).chmod(0o600)
        manifest_sha256 = verify_historical_combo_p1_root(temporary)
        _publish_noreplace(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {
        "status": ROOT_STATUS,
        "input_sha256": input_sha256,
        "manifest_sha256": manifest_sha256,
    }


def _read_metadata_file(path: Path) -> bytes:
    try:
        with os.fdopen(_open_private_regular_file(path), "rb") as handle:
            payload = handle.read(_METADATA_BYTE_LIMIT + 1)
    except OSError as exc:
        raise HistoricalComboP1RootError("invalid historical combo P1 root") from exc
    if not payload or len(payload) > _METADATA_BYTE_LIMIT:
        _fail("invalid historical combo P1 root")
    return payload


def _require_private_regular_file(path: Path) -> None:
    try:
        file_stat = path.lstat()
    except OSError as exc:
        raise HistoricalComboP1RootError("invalid historical combo P1 root") from exc
    if not stat.S_ISREG(file_stat.st_mode) or stat.S_IMODE(file_stat.st_mode) != 0o600:
        _fail("invalid historical combo P1 root")


def _open_private_regular_file(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise HistoricalComboP1RootError("invalid historical combo P1 root") from exc
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode) or stat.S_IMODE(file_stat.st_mode) != 0o600:
            _fail("invalid historical combo P1 root")
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _require_private_directory(path: Path) -> None:
    try:
        directory_stat = path.lstat()
    except OSError as exc:
        raise HistoricalComboP1RootError("invalid historical combo P1 root") from exc
    if not stat.S_ISDIR(directory_stat.st_mode) or stat.S_IMODE(directory_stat.st_mode) != 0o700:
        _fail("invalid historical combo P1 root")


def _verify_member_file(root: Path, member: Mapping[str, object]) -> None:
    relative_path = member.get("path")
    if not isinstance(relative_path, str):
        _fail("invalid historical combo P1 root")
    path = root / relative_path
    _require_private_regular_file(path)
    digest, size = _sha256_file(path)
    if digest != member.get("sha256") or size != member.get("size_bytes"):
        _fail("historical combo P1 root member mismatch")


def verify_historical_combo_p1_root(output_root: str | Path) -> str:
    """Verify one exact immutable P1 root without provider or strategy access."""
    root = Path(output_root)
    _require_private_directory(root)
    _require_private_regular_file(root / _INPUT_FILENAME)
    _require_private_regular_file(root / _MANIFEST_FILENAME)
    input_bytes = _read_metadata_file(root / _INPUT_FILENAME)
    manifest_bytes = _read_metadata_file(root / _MANIFEST_FILENAME)
    try:
        input_record = _validate_input(json.loads(input_bytes))
        if input_bytes != _input_bytes(input_record):
            _fail("invalid historical combo P1 root")
        manifest = validate_historical_combo_p1_root_manifest(json.loads(manifest_bytes))
        if manifest_bytes != canonical_historical_combo_p1_root_manifest_bytes(manifest):
            _fail("invalid historical combo P1 root")
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HistoricalComboP1RootError("invalid historical combo P1 root") from exc
    if manifest["input_sha256"] != input_record["input_sha256"]:
        _fail("P1 root input digest mismatch")

    expected_member_paths = set(_expected_relative_paths(input_record)) - {_MANIFEST_FILENAME}
    actual_paths = {entry.name for entry in root.iterdir() if entry.name != _UNIVERSE_SOURCE_DIRECTORY}
    if actual_paths != {
        _INPUT_FILENAME,
        _MANIFEST_FILENAME,
        _PRICE_PANEL_FILENAME,
        _QUALITY_REPORT_FILENAME,
    }:
        _fail("invalid historical combo P1 root")
    source_directory = root / _UNIVERSE_SOURCE_DIRECTORY
    _require_private_directory(source_directory)
    if {entry.name for entry in source_directory.iterdir()} != {
        f"{index:04d}.raw" for index, _ in enumerate(_expected_universe_source_digests(input_record))
    }:
        _fail("invalid historical combo P1 root")
    members = manifest["members"]
    if (
        not isinstance(members, list)
        or {str(member["path"]) for member in members} != expected_member_paths
    ):
        _fail("invalid historical combo P1 root")
    for member in members:
        _verify_member_file(root, member)

    panel_digest, report_digest = _price_panel_digests(input_record)
    member_digests = {str(member["path"]): str(member["sha256"]) for member in members}
    if (
        member_digests[_PRICE_PANEL_FILENAME] != panel_digest
        or member_digests[_QUALITY_REPORT_FILENAME] != report_digest
    ):
        _fail("P1 root source digest mismatch")
    for index, (_, expected_digest) in enumerate(_expected_universe_source_digests(input_record)):
        if member_digests[f"{_UNIVERSE_SOURCE_DIRECTORY}/{index:04d}.raw"] != expected_digest:
            _fail("P1 root universe source digest mismatch")
    return str(manifest["manifest_sha256"])


__all__ = [
    "HISTORICAL_COMBO_P1_ROOT_MANIFEST_SCHEMA",
    "ROOT_STATUS",
    "HistoricalComboP1RootError",
    "canonical_historical_combo_p1_root_manifest_bytes",
    "publish_historical_combo_p1_root",
    "validate_historical_combo_p1_root_manifest",
    "verify_historical_combo_p1_root",
]
