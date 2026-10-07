"""Offline Treasury nominal/real ten-year XML to explicit QSP research v1/v2.

The caller supplies bytes and capture evidence; this module has no downloader,
clock, filesystem, registration, or execution authority. Its input evidence is
a declaration, not a license, authenticated capture, or historical PIT proof.

Official formats and missing-element semantics:
https://home.treasury.gov/treasury-daily-interest-rate-xml-feed
https://home.treasury.gov/developer-notice-xml-changes

Each evidence mapping has exactly dataset, raw_sha256 and rows. Rows is a sequence aligned to XML entry order, with observation_date,
available_at, received_at and revision_id. Missing row evidence or missing
time/revision fields remain unknown. The raw hash binds this row order; an
explicit observation_date must also match its XML entry. available_at MUST describe evidence of that row revision's
publication, never a date-derived clock, first-seen time or receipt fallback.
The caller must retain original bytes and this evidence outside the QSP v1
snapshot: v1 has no field for the raw capture hash. A raw capture hash is not a
row revision identifier; appending a future row must not revise earlier rows.
These paragraphs describe v1 evidence. V2 has a separate explicit entry point
below; it never replaces v1 publication evidence with collector first-seen time.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
import hashlib
import math
import re
from xml.etree import ElementTree as ET


_ATOM = "{http://www.w3.org/2005/Atom}"
_META = "{http://schemas.microsoft.com/ado/2007/08/dataservices/metadata}"
_DATA = "{http://schemas.microsoft.com/ado/2007/08/dataservices}"
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T00:00:00")
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][+-]?[0-9]+)?")
_EXCESS_PRECISION = re.compile(r"[.,][0-9]{7}")
_OFFSET = re.compile(r"([+-])([0-9]{2})(?::?([0-9]{2}))?(?::?([0-9]{2}))?(?:[.,]([0-9]{1,6}))?$")
_ROW_FIELDS = {"observation_date", "available_at", "received_at", "revision_id"}


class TreasuryRatesError(ValueError):
    """Malformed or ambiguous source/capture contract, without input echo."""


def _time(value):
    if not isinstance(value, str) or _EXCESS_PRECISION.search(value):
        return None
    offset = _OFFSET.search(value)
    expected_offset = None
    if offset is not None:
        hours, minutes, seconds = (int(part or 0) for part in offset.group(2, 3, 4))
        if hours > 23 or minutes > 59 or seconds > 59:
            return None
        micros = int((offset.group(5) or "").ljust(6, "0"))
        expected_offset = timedelta(hours=hours, minutes=minutes, seconds=seconds, microseconds=micros)
        if offset.group(1) == "-":
            expected_offset = -expected_offset
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # fromisoformat truncates excess fractions, normalizes overflowing offset
        # fields, and drops fractional offsets whose whole seconds are zero.
        if expected_offset is not None and parsed.utcoffset() != expected_offset:
            return None
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def _stamp(value):
    parsed = _time(value)
    return None if parsed is None else parsed.isoformat().replace("+00:00", "Z")


def _single(parent, tag):
    matches = parent.findall(tag)
    if len(matches) > 1:
        raise TreasuryRatesError("duplicate_field")
    return matches[0] if matches else None


def _observation_date(properties):
    field = _single(properties, _DATA + "NEW_DATE")
    if field is not None and (len(field) or field.attrib.get(_META + "null") not in (None, "false", "0") or field.attrib.get(_META + "type") not in (None, "Edm.DateTime")):
        raise TreasuryRatesError("observation_date_invalid")
    value = "" if field is None or field.text is None else field.text.strip()
    if not _DATE.fullmatch(value):
        raise TreasuryRatesError("observation_date_invalid")
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise TreasuryRatesError("observation_date_invalid") from exc


def _value(properties, field):
    element = _single(properties, _DATA + field)
    if element is None or len(element) or element.attrib.get(_META + "null") not in (None, "false", "0"):
        return None
    if element.attrib.get(_META + "type") not in (None, "Edm.Double", "Edm.Decimal"):
        return None
    text = (element.text or "").strip()
    if not _NUMBER.fullmatch(text):
        return None
    try:
        value = float(text)
        return value if math.isfinite(value) else None
    except (ValueError, OverflowError):
        return None


def _series(raw, evidence, dataset, field, decision):
    if not isinstance(raw, bytes):
        raise TreasuryRatesError("xml_bytes_required")
    if not isinstance(evidence, Mapping) or set(evidence) != {"dataset", "raw_sha256", "rows"}:
        raise TreasuryRatesError("capture_evidence_invalid")
    if evidence["dataset"] != dataset:
        raise TreasuryRatesError("dataset_mismatch")
    if evidence["raw_sha256"] != hashlib.sha256(raw).hexdigest():
        raise TreasuryRatesError("raw_hash_mismatch")
    row_evidence = evidence["rows"]
    if not isinstance(row_evidence, Sequence) or isinstance(row_evidence, (str, bytes, bytearray)):
        raise TreasuryRatesError("row_evidence_invalid")
    try:
        text = raw.decode("utf-8")
        if "\x00" in text or "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise TreasuryRatesError("xml_declaration_forbidden")
        root = ET.fromstring(text)
    except (UnicodeError, ET.ParseError) as exc:
        raise TreasuryRatesError("xml_invalid") from exc
    if root.tag != _ATOM + "feed":
        raise TreasuryRatesError("xml_root_invalid")
    rows = []
    previous = None
    seen = set()
    for ordinal, entry in enumerate(root.findall(_ATOM + "entry")):
        content = _single(entry, _ATOM + "content")
        properties = None if content is None else _single(content, _META + "properties")
        if properties is None:
            raise TreasuryRatesError("xml_properties_missing")
        observed = _observation_date(properties)
        # Project before reading maturity values, revision or non-selector fields.
        if observed > decision.date():
            continue
        evidence_row = row_evidence[ordinal] if ordinal < len(row_evidence) else {}
        if not isinstance(evidence_row, Mapping):
            raise TreasuryRatesError("row_evidence_invalid")
        available = _time(evidence_row.get("available_at"))
        received = _time(evidence_row.get("received_at"))
        if (available is not None and available > decision) or (received is not None and received > decision):
            continue
        if evidence_row and evidence_row.get("observation_date") != observed.isoformat():
            raise TreasuryRatesError("row_evidence_date_mismatch")
        if set(evidence_row) - _ROW_FIELDS:
            raise TreasuryRatesError("row_evidence_fields_invalid")
        if observed in seen:
            raise TreasuryRatesError("duplicate_observation")
        if previous is not None and observed < previous:
            raise TreasuryRatesError("observation_order")
        seen.add(observed)
        previous = observed
        revision = evidence_row.get("revision_id")
        if not isinstance(revision, str) or not revision or revision != revision.strip() or len(revision) > 256 or revision == "latest":
            revision = None
        rows.append({
            "observation_date": observed.isoformat(),
            "value": _value(properties, field),
            "available_at": _stamp(evidence_row.get("available_at")),
            "received_at": _stamp(evidence_row.get("received_at")),
            "revision_id": revision,
        })
    return {"source_id": "us_treasury.daily_par_yield_curves",
            "series_id": dataset + "." + field,
            "basis": "treasury_par_yield", "unit": "percent", "rows": rows}


def build_treasury_rates_research_input(
    *, nominal_xml: bytes, real_xml: bytes,
    nominal_evidence: Mapping, real_evidence: Mapping, decision_at: str,
) -> dict:
    """Build QSP rates-input.v1; data/evidence gaps remain explicit unknowns.

    This does not generate reported breakeven or run the observer. The owning
    research caller must pass the result to QSP's existing v1 observer with its
    frozen explicit window/age configuration. All historical/economic/runtime
    qualification remains external; no source registry or runtime is changed.
    """
    decision = _time(decision_at)
    if decision is None:
        raise TreasuryRatesError("decision_at_invalid")
    return {
        "schema_version": "qsl.rates-context-input.research.v1",
        "decision_at": decision.isoformat().replace("+00:00", "Z"),
        "series": {
            "nominal_10y": _series(nominal_xml, nominal_evidence, "daily_treasury_yield_curve", "BC_10YEAR", decision),
            "real_10y": _series(real_xml, real_evidence, "daily_treasury_real_yield_curve", "TC_10YEAR", decision),
        },
    }


_FORWARD_TIME = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_FORWARD_ROW_FIELDS = {"observation_date", "revision_id", "source_published_at",
                       "first_seen_at", "received_at", "capture_sha256", "row_sha256"}


def _forward_time(value):
    return _time(value) if isinstance(value, str) and _FORWARD_TIME.fullmatch(value) else None


def _forward_properties(raw):
    if not isinstance(raw, bytes):
        raise TreasuryRatesError("xml_bytes_required")
    try:
        text = raw.decode("utf-8")
        if "\x00" in text or "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise TreasuryRatesError("xml_declaration_forbidden")
        root = ET.fromstring(text)
    except (UnicodeError, ET.ParseError) as exc:
        raise TreasuryRatesError("xml_invalid") from exc
    if root.tag != _ATOM + "feed":
        raise TreasuryRatesError("xml_root_invalid")
    for entry in root.findall(_ATOM + "entry"):
        content = _single(entry, _ATOM + "content")
        properties = None if content is None else _single(content, _META + "properties")
        if properties is None:
            raise TreasuryRatesError("xml_properties_missing")
        yield properties


def _forward_series(raw, evidence, dataset, field, decision, start, end):
    if not isinstance(raw, bytes):
        raise TreasuryRatesError("xml_bytes_required")
    if not isinstance(evidence, Mapping) or set(evidence) != {"dataset", "raw_sha256", "rows", "captures"}:
        raise TreasuryRatesError("capture_evidence_invalid")
    if evidence["dataset"] != dataset:
        raise TreasuryRatesError("dataset_mismatch")
    if evidence["raw_sha256"] != hashlib.sha256(raw).hexdigest():
        raise TreasuryRatesError("raw_hash_mismatch")
    row_evidence, captures = evidence["rows"], evidence["captures"]
    if not isinstance(row_evidence, Sequence) or isinstance(row_evidence, (str, bytes, bytearray)):
        raise TreasuryRatesError("row_evidence_invalid")
    if not isinstance(captures, Mapping):
        raise TreasuryRatesError("capture_evidence_invalid")
    rows = []
    for ordinal, properties in enumerate(_forward_properties(raw)):
        observed = _observation_date(properties)
        if observed < start or observed > end or observed > decision.date():
            continue
        ev = row_evidence[ordinal] if ordinal < len(row_evidence) else {}
        if not isinstance(ev, Mapping):
            raise TreasuryRatesError("row_evidence_invalid")
        first_seen = _forward_time(ev.get("first_seen_at"))
        if first_seen is not None and first_seen > decision:
            continue
        received = _forward_time(ev.get("received_at"))
        if received is not None and received > decision:
            continue
        # Only the visible projection can require content/capture evidence.
        if set(ev) != _FORWARD_ROW_FIELDS:
            raise TreasuryRatesError("row_evidence_fields_invalid")
        if ev["observation_date"] != observed.isoformat():
            raise TreasuryRatesError("row_evidence_date_mismatch")
        if ev["source_published_at"] is not None:
            raise TreasuryRatesError("source_publication_must_be_unknown")
        capture_hash, row_hash = ev["capture_sha256"], ev["row_sha256"]
        if not isinstance(capture_hash, str) or not _DIGEST.fullmatch(capture_hash):
            raise TreasuryRatesError("capture_identity_invalid")
        if not isinstance(row_hash, str) or not _DIGEST.fullmatch(row_hash):
            raise TreasuryRatesError("row_content_identity_invalid")
        captured = captures.get(capture_hash)
        if not isinstance(captured, bytes):
            raise TreasuryRatesError("capture_bytes_missing")
        if hashlib.sha256(captured).hexdigest() != capture_hash:
            raise TreasuryRatesError("capture_hash_mismatch")
        value = _value(properties, field)
        if not any(_observation_date(p) == observed and _value(p, field) == value
                   for p in _forward_properties(captured)):
            raise TreasuryRatesError("capture_row_mismatch")
        # Preserve order and duplicates: the observer owns visible ambiguity.
        revision = ev["revision_id"]
        if not isinstance(revision, str) or not revision or revision != revision.strip() or len(revision) > 256:
            revision = None
        rows.append({"observation_date": observed.isoformat(), "value": value,
                     "revision_id": revision, "source_published_at": None,
                     "first_seen_at": None if first_seen is None else first_seen.isoformat().replace("+00:00", "Z"),
                     "received_at": None if received is None else received.isoformat().replace("+00:00", "Z"),
                     "capture_sha256": capture_hash, "row_sha256": row_hash})
    return {"source_id": "us_treasury.daily_par_yield_curves", "series_id": dataset + "." + field,
            "basis": "treasury_par_yield", "unit": "percent", "rows": rows}


def build_treasury_rates_research_input_v2(
    *, nominal_xml: bytes, real_xml: bytes,
    nominal_evidence: Mapping, real_evidence: Mapping, collector_id: str,
    decision_at: str, window_start: str, window_end: str,
) -> dict:
    """Build explicit collector-known QSP v2 from caller-supplied retained bytes.

    Each evidence mapping has exactly dataset, raw_sha256, rows and captures.
    raw_sha256 binds this supplied XML response; captures maps declared original
    first-capture SHA-256 references to complete original XML bytes. Each row,
    aligned to XML entry order, has exactly observation_date, revision_id,
    source_published_at (explicitly None), first_seen_at, received_at,
    capture_sha256 and row_sha256. No missing field, publication clock, revision
    or first-seen time is manufactured. Present invalid times/revisions remain
    unknown. V2 times use exact seconds or 1-6 fractional digits with Z or
    +/-HH:MM offsets, matching the frozen observer v2 grammar.

    window_start/window_end MUST come from the same frozen QSP config later
    passed to build_rates_context_observation_v2. Project that window and future
    observation/arrival selectors before requiring row content/capture evidence.
    Visible duplicate rows remain in source order for the observer to reject.

    Selected capture bytes are hash-checked and must contain the declared XML
    observation date/value. row_sha256 is only a producer-declared immutable
    content reference, not a hash algorithm defined or verified here. The caller
    retains each original first capture externally; a newer response cannot
    replace that row's declared first-capture reference. This stateless adapter
    does not establish earliest capture, revision authenticity, trustworthy
    clocks, source rights, or persistence/immutability across calls. Missing
    actual retained bytes block selected rows. No storage or collector is added.
    """
    if not isinstance(collector_id, str) or not collector_id or collector_id != collector_id.strip() or len(collector_id) > 256:
        raise TreasuryRatesError("collector_id_invalid")
    decision = _forward_time(decision_at)
    if decision is None:
        raise TreasuryRatesError("decision_at_invalid")
    try:
        start, end = date.fromisoformat(window_start), date.fromisoformat(window_end)
        if start.isoformat() != window_start or end.isoformat() != window_end or start >= end:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise TreasuryRatesError("window_invalid") from exc
    return {"schema_version": "qsl.rates-context-input.research.v2",
            "availability_basis": "collector_first_seen", "collector_id": collector_id,
            "decision_at": decision.isoformat().replace("+00:00", "Z"),
            "series": {
                "nominal_10y": _forward_series(nominal_xml, nominal_evidence, "daily_treasury_yield_curve", "BC_10YEAR", decision, start, end),
                "real_10y": _forward_series(real_xml, real_evidence, "daily_treasury_real_yield_curve", "TC_10YEAR", decision, start, end),
            }}
