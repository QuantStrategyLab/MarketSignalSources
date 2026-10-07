"""SYNTHETIC_FIXTURE_ONLY: no downloaded observations."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

from market_signal_sources.providers.treasury_rates import (
    TreasuryRatesError,
    build_treasury_rates_research_input,
    build_treasury_rates_research_input_v2,
)

DATES = ("2024-01-02", "2024-01-03")
DECISION = "2024-01-05T12:00:00Z"


def xml(rows, field="BC_10YEAR"):
    entries = "".join(
        '<entry><content type="application/xml"><m:properties>'
        f'<d:NEW_DATE m:type="Edm.DateTime">{day}T00:00:00</d:NEW_DATE>'
        + ("" if value is None else f'<d:{field} m:type="Edm.Double">{value}</d:{field}>')
        + '</m:properties></content></entry>'
        for day, value in rows
    )
    return ('<feed xmlns="http://www.w3.org/2005/Atom" '
            'xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata" '
            'xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">'
            + entries + '</feed>').encode()


def evidence(raw, dataset):
    return {"dataset": dataset, "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "rows": [{"observation_date": day, "available_at": f"{day}T21:00:00Z",
                           "received_at": f"{day}T21:01:00Z",
                           "revision_id": f"SYNTHETIC_FIXTURE_ONLY:{day}:v1"}
                     for day in DATES]}


def arguments():
    nominal = xml(zip(DATES, (4.0, 4.2)))
    real = xml(zip(DATES, (1.0, 1.1)), "TC_10YEAR")
    return {"nominal_xml": nominal, "real_xml": real,
            "nominal_evidence": evidence(nominal, "daily_treasury_yield_curve"),
            "real_evidence": evidence(real, "daily_treasury_real_yield_curve"),
            "decision_at": DECISION}


def replace_nominal(args, raw):
    args["nominal_xml"] = raw
    args["nominal_evidence"]["raw_sha256"] = hashlib.sha256(raw).hexdigest()


def rows(args):
    return build_treasury_rates_research_input(**args)["series"]["nominal_10y"]["rows"]


def test_existing_qsp_shape_identities_and_no_breakeven():
    args = arguments()
    before = copy.deepcopy(args)
    result = build_treasury_rates_research_input(**args)
    assert args == before
    assert result["schema_version"] == "qsl.rates-context-input.research.v1"
    assert result["decision_at"] == DECISION
    assert set(result) == {"schema_version", "decision_at", "series"}
    assert set(result["series"]) == {"nominal_10y", "real_10y"}
    nominal, real = result["series"].values()
    assert nominal["source_id"] == real["source_id"] == "us_treasury.daily_par_yield_curves"
    assert nominal["series_id"] == "daily_treasury_yield_curve.BC_10YEAR"
    assert real["series_id"] == "daily_treasury_real_yield_curve.TC_10YEAR"
    assert nominal["basis"] == real["basis"] == "treasury_par_yield"
    assert nominal["unit"] == real["unit"] == "percent"
    assert nominal["rows"][1] == {"observation_date": DATES[1], "value": 4.2,
                                 **args["nominal_evidence"]["rows"][1]}


@pytest.mark.parametrize("value", ["-0.25", "0", "4.2"])
def test_finite_percent_values(value):
    args = arguments()
    replace_nominal(args, xml(zip(DATES, (value, value))))
    assert rows(args)[0]["value"] == float(value)


@pytest.mark.parametrize("value", [None, "NaN", "INF", "-Infinity", "true", "bad", "1e9999", "1_000", ""])
def test_invalid_or_missing_value_is_not_zero(value):
    args = arguments()
    replace_nominal(args, xml(zip(DATES, (value, 4.2))))
    assert rows(args)[0]["value"] is None


def test_xml_null_and_wrong_maturity_are_missing():
    for raw in [
        xml(zip(DATES, (4.0, 4.2))).replace(
            b'<d:BC_10YEAR m:type="Edm.Double">4.0</d:BC_10YEAR>',
            b'<d:BC_10YEAR m:null="true"/>'),
        xml(zip(DATES, (4.0, 4.2)), "BC_5YEAR"),
    ]:
        args = arguments()
        replace_nominal(args, raw)
        assert rows(args)[0]["value"] is None


@pytest.mark.parametrize("missing", ["available_at", "received_at", "revision_id"])
def test_evidence_is_never_inferred(missing):
    args = arguments()
    del args["nominal_evidence"]["rows"][0][missing]
    assert rows(args)[0][missing] is None
    if missing == "available_at":
        assert rows(args)[0]["received_at"] == f"{DATES[0]}T21:01:00Z"


def test_missing_all_row_evidence_remains_unknown():
    args = arguments()
    args["nominal_evidence"]["rows"] = []
    assert all(r["available_at"] is r["received_at"] is r["revision_id"] is None for r in rows(args))


@pytest.mark.parametrize("side", ["nominal", "real"])
def test_raw_hash_mismatch(side):
    args = arguments()
    args[f"{side}_evidence"]["raw_sha256"] = "0" * 64
    with pytest.raises(TreasuryRatesError, match="raw_hash_mismatch"):
        rows(args)


def test_dataset_role_mismatch():
    args = arguments()
    args["nominal_evidence"]["dataset"] = "daily_treasury_real_yield_curve"
    with pytest.raises(TreasuryRatesError, match="dataset_mismatch"):
        rows(args)


@pytest.mark.parametrize("raw,reason", [
    (xml([(DATES[0], 4), (DATES[0], 7), (DATES[1], 4.2)]), "duplicate_observation"),
    (xml([(DATES[1], 4.2), (DATES[0], 4)]), "observation_order"),
])
def test_visible_conflicting_revisions_and_order_are_not_repaired(raw, reason):
    args = arguments()
    replace_nominal(args, raw)
    args["nominal_evidence"]["rows"] = []
    with pytest.raises(TreasuryRatesError, match=reason):
        rows(args)


@pytest.mark.parametrize("selector", ["future_date", "available_at", "received_at"])
def test_future_or_late_append_cannot_change_past_output(selector):
    args = arguments()
    original = build_treasury_rates_research_input(**args)
    day = "2024-01-06" if selector == "future_date" else "2024-01-04"
    replace_nominal(args, xml([(DATES[0], 4), (DATES[1], 4.2), (day, "bad")]))
    ev = {"unexpected": object()}
    if selector != "future_date":
        ev[selector] = "2024-01-06T00:00:00Z"
    args["nominal_evidence"]["rows"].append(ev)
    assert build_treasury_rates_research_input(**args) == original


def test_late_required_row_is_omitted():
    args = arguments()
    args["nominal_evidence"]["rows"][1]["received_at"] = "2024-01-06T00:00:00Z"
    assert len(rows(args)) == 1


@pytest.mark.parametrize("bad", ["", "2024-01-05", "2024-01-05T12:00:00", "garbage"])
def test_decision_requires_timezone(bad):
    args = arguments()
    args["decision_at"] = bad
    with pytest.raises(TreasuryRatesError, match="decision_at_invalid"):
        rows(args)


@pytest.mark.parametrize("field", ["available_at", "received_at"])
def test_one_microsecond_future_row_is_omitted(field):
    args = arguments()
    args["nominal_evidence"]["rows"][0][field] = "2024-01-05T12:00:00.000001Z"
    assert [r["observation_date"] for r in rows(args)] == [DATES[1]]


@pytest.mark.parametrize("field", ["available_at", "received_at"])
@pytest.mark.parametrize("stamp", [
    "2024-01-03T21:00:00.0000001Z",
    "2024-01-05T12:00:00.0000001Z",
    "2024-01-03T21:00:00.0000001+05:30",
    "2024-01-03T21:00:00+00:60",
    "2024-01-03T21:00:00-00:60",
    "2024-01-03T21:00:00+05:60",
    "2024-01-03T21:00:00+24:00",
    "2024-01-03T21:00:00+05:30:60",
    "20240103T210000,0000001+0530",
    "20240103T210000+0060",
    "20240103T210000-246000",
    "2024-01-03T21:00:00+05:30:00.0000001",
    "2024-01-03T21:00:00+05:30:00,0000001",
    "2024-01-03T21:00:00+00:00:00.5",
    "2024-01-03T21:00:00-000000,5",
])
def test_illegal_precision_or_offset_is_unknown_not_normalized(field, stamp):
    args = arguments()
    args["nominal_evidence"]["rows"][0][field] = stamp
    assert rows(args)[0][field] is None


def test_excess_precision_matches_missing_time_evidence_semantics():
    args = arguments()
    args["nominal_evidence"]["rows"][0]["available_at"] = "2024-01-03T21:00:00.0000001Z"
    altered = rows(args)[0]
    del args["nominal_evidence"]["rows"][0]["available_at"]
    assert altered == rows(args)[0]


@pytest.mark.parametrize("field", ["available_at", "received_at"])
@pytest.mark.parametrize("stamp,expected", [
    ("2024-01-02T21:00:00+05:30", "2024-01-02T15:30:00Z"),
    ("2024-01-02T21:00:00-03:30", "2024-01-03T00:30:00Z"),
    ("2024-01-02T21:00:00+00:00", "2024-01-02T21:00:00Z"),
    ("2024-01-02T21:00:00.5Z", "2024-01-02T21:00:00.500000Z"),
    ("2024-01-02T21:00:00.123456+05:30", "2024-01-02T15:30:00.123456Z"),
    ("2024-01-02T21:00:00.000001Z", "2024-01-02T21:00:00.000001Z"),
    ("2024-01-02T21:00:00+05:30:00", "2024-01-02T15:30:00Z"),
    ("2024-01-02T21:00:00-03:30:01", "2024-01-03T00:30:01Z"),
    ("2024-01-02T21:00:00+05:30:00.5", "2024-01-02T15:29:59.500000Z"),
    ("20240102T210000,123456+053000", "2024-01-02T15:30:00.123456Z"),
    ("2024-01-02 21:00:00,5+05", "2024-01-02T16:00:00.500000Z"),
])
def test_valid_offsets_and_fractional_seconds_normalize(field, stamp, expected):
    args = arguments()
    args["nominal_evidence"]["rows"][0][field] = stamp
    assert rows(args)[0][field] == expected


@pytest.mark.parametrize("field", ["available_at", "received_at"])
@pytest.mark.parametrize("stamp", [
    "2024-01-05T12:00:00Z",
    "2024-01-05T12:00:00.000000Z",
    "2024-01-05T17:30:00+05:30",
    "2024-01-05T06:30:00-05:30",
])
def test_time_equal_to_decision_is_included(field, stamp):
    args = arguments()
    args["nominal_evidence"]["rows"][0][field] = stamp
    result = rows(args)
    assert [r["observation_date"] for r in result] == list(DATES)
    assert result[0][field] == "2024-01-05T12:00:00Z"


@pytest.mark.parametrize("bad", [
    "2024-01-05T12:00:00.0000001Z",
    "2024-01-05T12:00:00+00:60",
    "2024-01-05T12:00:00+05:60",
    "2024-01-05T12:00:00.1234567+05:30",
    "20240105T120000,0000001+0000",
    "20240105T120000+0060",
    "2024-01-05T12:00:00-00:00:00.5",
])
def test_decision_rejects_illegal_precision_or_offset(bad):
    args = arguments()
    args["decision_at"] = bad
    with pytest.raises(TreasuryRatesError, match="decision_at_invalid"):
        rows(args)


@pytest.mark.parametrize("stamp", [
    "2024-01-05T17:30:00+05:30",
    "2024-01-05T17:30:00+05:30:00",
    "20240105T173000,000000+053000",
])
def test_decision_at_with_legal_non_hour_offset_normalizes_v1_output(stamp):
    args = arguments()
    args["decision_at"] = stamp
    result = build_treasury_rates_research_input(**args)
    assert result["decision_at"] == DECISION


@pytest.mark.parametrize("field", ["available_at", "received_at"])
@pytest.mark.parametrize("stamp", [
    "2024-01-05T17:30:00.000001+05:30",
    "20240105T120000,000001+000000",
])
def test_future_microsecond_append_is_projected_before_invalid_payload(field, stamp):
    args = arguments()
    original = build_treasury_rates_research_input(**args)
    replace_nominal(args, xml([(DATES[0], 4), (DATES[1], 4.2), (DATES[0], "bad")]))
    args["nominal_evidence"]["rows"].append({field: stamp, "unexpected": object()})
    assert build_treasury_rates_research_input(**args) == original


@pytest.mark.parametrize("field", ["available_at", "received_at"])
@pytest.mark.parametrize("stamp", [
    "not-a-time",
    "2024-01-05T12:00:00.0000001Z",
    "2024-01-05T12:00:00+00:60",
])
def test_unparseable_selector_cannot_hide_visible_duplicate(field, stamp):
    args = arguments()
    replace_nominal(args, xml([(DATES[0], 4), (DATES[1], 4.2), (DATES[0], 7)]))
    args["nominal_evidence"]["rows"].append({"observation_date": DATES[0], field: stamp})
    with pytest.raises(TreasuryRatesError, match="duplicate_observation"):
        rows(args)


@pytest.mark.parametrize("mutation", ["dtd", "broken", "wrong_root", "duplicate_field", "bad_date"])
def test_unsafe_or_ambiguous_xml(mutation):
    args = arguments()
    raw = args["nominal_xml"]
    if mutation == "dtd":
        raw = b'<!DOCTYPE feed [<!ENTITY value "4.0">]>' + raw
    elif mutation == "broken":
        raw = raw[:-2]
    elif mutation == "wrong_root":
        raw = raw.replace(b'<feed ', b'<other ').replace(b'</feed>', b'</other>')
    elif mutation == "duplicate_field":
        raw = raw.replace(b'</m:properties>', b'<d:BC_10YEAR>7</d:BC_10YEAR></m:properties>', 1)
    else:
        raw = raw.replace(b'2024-01-02T00:00:00', b'not-a-date')
    replace_nominal(args, raw)
    with pytest.raises(TreasuryRatesError):
        rows(args)


def test_namespace_prefix_is_not_identity():
    args = arguments()
    original = build_treasury_rates_research_input(**args)
    raw = args["nominal_xml"].replace(b'xmlns:d=', b'xmlns:value=')
    raw = raw.replace(b'<d:', b'<value:').replace(b'</d:', b'</value:')
    replace_nominal(args, raw)
    assert build_treasury_rates_research_input(**args) == original


def test_module_can_be_loaded_without_optional_package_imports():
    path = Path(__file__).parents[1] / "src/market_signal_sources/providers/treasury_rates.py"
    spec = importlib.util.spec_from_file_location("isolated_treasury_rates", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.build_treasury_rates_research_input(**arguments()) == build_treasury_rates_research_input(**arguments())


def test_late_same_day_revision_does_not_hide_original_revision():
    args = arguments()
    original = build_treasury_rates_research_input(**args)
    replace_nominal(args, xml([(DATES[0], 4), (DATES[1], 4.2), (DATES[0], "bad")]))
    args["nominal_evidence"]["rows"].append({"observation_date": DATES[0],
        "available_at": "2024-01-06T00:00:00Z", "revision_id": "later-revision"})
    assert build_treasury_rates_research_input(**args) == original


def test_row_evidence_cannot_be_reassigned_to_another_observation():
    args = arguments()
    args["nominal_evidence"]["rows"][0]["observation_date"] = DATES[1]
    with pytest.raises(TreasuryRatesError, match="row_evidence_date_mismatch"):
        rows(args)


@pytest.mark.parametrize('attribute', ['m:null="true"', 'm:null="1"', 'm:null="invalid"', 'm:type="Edm.Double"'])
def test_observation_date_metadata_cannot_claim_a_null_or_nondatetime(attribute):
    args = arguments()
    raw = args['nominal_xml'].replace(b'<d:NEW_DATE m:type="Edm.DateTime">', f'<d:NEW_DATE {attribute}>'.encode(), 1)
    replace_nominal(args, raw)
    with pytest.raises(TreasuryRatesError, match='observation_date_invalid'):
        rows(args)


def test_observation_date_must_be_scalar():
    args = arguments()
    raw = args['nominal_xml'].replace(b'2024-01-02T00:00:00</d:NEW_DATE>', b'2024-01-02T00:00:00<d:extra>bad</d:extra></d:NEW_DATE>')
    replace_nominal(args, raw)
    with pytest.raises(TreasuryRatesError, match='observation_date_invalid'):
        rows(args)


@pytest.mark.parametrize('payload', [
    b'<d:BC_10YEAR>4.0<d:extra>999</d:extra></d:BC_10YEAR>',
    b'<d:BC_10YEAR m:null="1">4.0</d:BC_10YEAR>',
    b'<d:BC_10YEAR m:null="invalid">4.0</d:BC_10YEAR>',
])
def test_malformed_or_null_numeric_content_cannot_use_leading_text(payload):
    args = arguments()
    raw = args['nominal_xml'].replace(b'<d:BC_10YEAR m:type="Edm.Double">4.0</d:BC_10YEAR>', payload)
    replace_nominal(args, raw)
    assert rows(args)[0]['value'] is None


def forward_arguments():
    """SYNTHETIC_FIXTURE_ONLY: explicit collector declarations, not capture history."""
    args = arguments()
    args.update(collector_id="SYNTHETIC_FIXTURE_ONLY:collector", window_start=DATES[0], window_end=DATES[1])
    for side in ("nominal", "real"):
        ev = args[f"{side}_evidence"]
        ev["captures"] = {ev["raw_sha256"]: args[f"{side}_xml"]}
        for row in ev["rows"]:
            row["first_seen_at"] = row.pop("available_at")
            row["source_published_at"] = None
            row["capture_sha256"] = ev["raw_sha256"]
            row["row_sha256"] = hashlib.sha256(
                f"SYNTHETIC_FIXTURE_ONLY:{side}:{row['observation_date']}:v1".encode()).hexdigest()
    return args


def forward_rows(args):
    return build_treasury_rates_research_input_v2(**args)["series"]["nominal_10y"]["rows"]


def test_forward_input_shape_preserves_declarations_and_v1_is_explicit():
    args = forward_arguments()
    before = copy.deepcopy(args)
    result = build_treasury_rates_research_input_v2(**args)
    assert args == before
    assert set(result) == {"schema_version", "availability_basis", "collector_id", "decision_at", "series"}
    assert result["schema_version"] == "qsl.rates-context-input.research.v2"
    assert result["availability_basis"] == "collector_first_seen"
    assert result["collector_id"] == args["collector_id"]
    row = result["series"]["nominal_10y"]["rows"][0]
    assert row == {**args["nominal_evidence"]["rows"][0], "value": 4.0}
    assert "available_at" not in json.dumps(result)
    v1_args = arguments()
    v1_args["nominal_evidence"] = args["nominal_evidence"]
    with pytest.raises(TreasuryRatesError, match="capture_evidence_invalid"):
        build_treasury_rates_research_input(**v1_args)


@pytest.mark.parametrize("field", [
    "observation_date", "revision_id", "source_published_at", "first_seen_at",
    "received_at", "capture_sha256", "row_sha256",
])
def test_forward_visible_evidence_fields_are_required(field):
    args = forward_arguments()
    del args["nominal_evidence"]["rows"][0][field]
    with pytest.raises(TreasuryRatesError, match="row_evidence_fields_invalid"):
        forward_rows(args)


@pytest.mark.parametrize("bad", [None, "", " collector", "collector ", "x" * 257])
def test_forward_collector_identity_is_required(bad):
    args = forward_arguments()
    args["collector_id"] = bad
    with pytest.raises(TreasuryRatesError, match="collector_id_invalid"):
        forward_rows(args)


@pytest.mark.parametrize("field,bad,reason", [
    ("source_published_at", "2024-01-03T00:00:00Z", "source_publication_must_be_unknown"),
    ("observation_date", DATES[1], "row_evidence_date_mismatch"),
    ("capture_sha256", "f" * 64, "capture_bytes_missing"),
    ("row_sha256", "ABC" * 21 + "A", "row_content_identity_invalid"),
])
def test_forward_capture_declarations_are_not_inferred(field, bad, reason):
    args = forward_arguments()
    args["nominal_evidence"]["rows"][0][field] = bad
    with pytest.raises(TreasuryRatesError, match=reason):
        forward_rows(args)


@pytest.mark.parametrize("mutation,reason", [
    ("hash", "capture_hash_mismatch"),
    ("different_value", "capture_row_mismatch"),
    ("different_date", "capture_row_mismatch"),
    ("dataset", "dataset_mismatch"),
])
def test_forward_original_capture_must_bind_selected_xml_row(mutation, reason):
    args = forward_arguments()
    ev = args["nominal_evidence"]
    original = ev["raw_sha256"]
    if mutation == "hash":
        ev["captures"][original] += b" "
    elif mutation == "dataset":
        ev["dataset"] = "daily_treasury_real_yield_curve"
    else:
        raw = xml([(DATES[0], 7), (DATES[1], 4.2)]) if mutation == "different_value" else xml([(DATES[1], 4)])
        capture = hashlib.sha256(raw).hexdigest()
        ev["captures"][capture] = raw
        ev["rows"][0]["capture_sha256"] = capture
    with pytest.raises(TreasuryRatesError, match=reason):
        forward_rows(args)


@pytest.mark.parametrize("field", ["first_seen_at", "received_at"])
@pytest.mark.parametrize("stamp,expected", [
    ("2024-01-03T02:30:00.123456+05:30", "2024-01-02T21:00:00.123456Z"),
    ("2024-01-05T12:00:00Z", DECISION),
    ("2024-01-05T12:00:00.0000001Z", None),
    ("2024-01-03T21:00:00+00:60", None),
    ("20240103T210000Z", None),
    ("2024-01-03T21:00:00,5Z", None),
    ("2024-01-03T21:00:00+05:30:00", None),
])
def test_forward_time_grammar_is_explicit(field, stamp, expected):
    args = forward_arguments()
    args["nominal_evidence"]["rows"][0][field] = stamp
    assert forward_rows(args)[0][field] == expected


@pytest.mark.parametrize("selector", ["observation", "window", "first_seen_at", "received_at"])
def test_forward_hidden_append_preserves_first_capture_and_past_result(selector):
    args = forward_arguments()
    original = build_treasury_rates_research_input_v2(**args)
    day = "2024-01-06" if selector == "observation" else ("2024-01-04" if selector == "window" else DATES[0])
    replace_nominal(args, xml([(DATES[0], 4), (DATES[1], 4.2), (day, "bad")]))
    ev = {"unexpected": object()}
    if selector in ("first_seen_at", "received_at"):
        ev[selector] = "2024-01-05T17:30:00.000001+05:30"
    args["nominal_evidence"]["rows"].append(ev)
    assert build_treasury_rates_research_input_v2(**args) == original


@pytest.mark.parametrize("field", ["first_seen_at", "received_at"])
def test_forward_unparseable_selector_remains_unknown(field):
    args = forward_arguments()
    args["nominal_evidence"]["rows"][0][field] = "not-a-time"
    assert forward_rows(args)[0][field] is None


@pytest.mark.parametrize("stamp", [
    "2024-01-05T12:00:00.0000001Z", "2024-01-05T12:00:00+00:60",
    "2024-01-05T12:00:00+24:00", "20240105T120000Z",
    "2024-01-05T12:00:00,5Z", "2024-01-05T12:00:00+05:30:00",
])
def test_forward_decision_rejects_unsupported_v2_forms(stamp):
    args = forward_arguments()
    args["decision_at"] = stamp
    with pytest.raises(TreasuryRatesError, match="decision_at_invalid"):
        forward_rows(args)


@pytest.mark.parametrize("start,end", [
    ("20240102", DATES[1]), (DATES[1], DATES[0]), (DATES[0], DATES[0]), (None, DATES[1]),
])
def test_forward_projection_requires_explicit_exact_window(start, end):
    args = forward_arguments()
    args["window_start"], args["window_end"] = start, end
    with pytest.raises(TreasuryRatesError, match="window_invalid"):
        forward_rows(args)


def test_forward_unused_capture_errors_cannot_pollute_selected_rows():
    args = forward_arguments()
    original = build_treasury_rates_research_input_v2(**args)
    args["nominal_evidence"]["captures"]["invalid"] = object()
    assert build_treasury_rates_research_input_v2(**args) == original


@pytest.fixture
def qsp_forward_observer():
    """Opt-in cross-repository check against the actual frozen pure consumer."""
    path = os.environ.get("QSL_RATES_V2_OBSERVER_PATH")
    if path is None:
        pytest.skip("actual QSP v2 module path was not supplied")
    spec = importlib.util.spec_from_file_location("synthetic_qsp_forward_observer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def forward_config():
    return {"schema_version": "qsl.rates-context-config.research.v1", "window_start": DATES[0],
            "window_end": DATES[1], "max_observation_age_days": 2}


def observe_forward(args, qsp):
    config = forward_config()
    args["window_start"], args["window_end"] = config["window_start"], config["window_end"]
    return qsp.build_rates_context_observation_v2(build_treasury_rates_research_input_v2(**args), config)


def test_forward_actual_qsp_consumer_keeps_research_boundaries(qsp_forward_observer):
    result = observe_forward(forward_arguments(), qsp_forward_observer)
    assert result["series"]["nominal_10y"]["change_bp"] == 20.0
    assert result["series"]["real_10y"]["change_bp"] == 10.0
    assert result["approximate_yield_spread"]["change_bp"] == 10.0
    assert result["quality"]["status"] == "unknown"  # No independent breakeven.
    assert result["research_status"] == "UNVALIDATED_RESEARCH"
    assert result["historical_pit_verified"] is result["backtest_eligible"] is result["position_control_allowed"] is False
    assert "available_at" not in json.dumps(result)
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("mutation,reason", [
    ("latest", "REVISION_IDENTITY_INVALID"),
    ("duplicate", "ROW_ORDER_OR_REVISION_AMBIGUOUS"),
    ("hash_conflict", "ROW_IDENTITY_CONFLICT"),
    ("time_order", "RECEIPT_BEFORE_FIRST_SEEN"),
    ("precision", "FIRST_SEEN_UNKNOWN"),
    ("value", "VALUE_INVALID"),
    ("revision_conflict", "ROW_IDENTITY_CONFLICT"),
    ("reverse", "ROW_ORDER_OR_REVISION_AMBIGUOUS"),
])
def test_forward_actual_qsp_consumer_negative_cases(qsp_forward_observer, mutation, reason):
    args = forward_arguments()
    ev = args["nominal_evidence"]
    if mutation == "latest":
        ev["rows"][0]["revision_id"] = "latest"
    elif mutation == "duplicate":
        replace_nominal(args, xml([(DATES[0], 4), (DATES[0], 4), (DATES[1], 4.2)]))
        ev["rows"].insert(1, copy.deepcopy(ev["rows"][0]))
    elif mutation == "hash_conflict":
        ev["rows"][1]["row_sha256"] = ev["rows"][0]["row_sha256"]
    elif mutation == "time_order":
        ev["rows"][0]["received_at"] = "2024-01-02T20:00:00Z"
    elif mutation == "precision":
        ev["rows"][0]["first_seen_at"] = "2024-01-05T12:00:00.0000001Z"
    elif mutation == "revision_conflict":
        raw = xml([(DATES[0], 4), (DATES[0], 7), (DATES[1], 4.2)])
        replace_nominal(args, raw)
        ev["captures"][ev["raw_sha256"]] = raw
        revised = {**ev["rows"][0], "capture_sha256": ev["raw_sha256"], "row_sha256": "f" * 64}
        ev["rows"].insert(1, revised)
    elif mutation == "reverse":
        replace_nominal(args, xml([(DATES[1], 4.2), (DATES[0], 4)]))
        ev["rows"].reverse()
    else:
        raw = xml([(DATES[0], "bad"), (DATES[1], 4.2)])
        replace_nominal(args, raw)
        ev["captures"] = {ev["raw_sha256"]: raw}
        for row in ev["rows"]:
            row["capture_sha256"] = ev["raw_sha256"]
    result = observe_forward(args, qsp_forward_observer)
    nominal = result["series"]["nominal_10y"]
    assert nominal["status"] == "unknown"
    assert nominal["change_bp"] is None
    assert reason in nominal["reason_codes"]
    if mutation == "duplicate":
        assert nominal["start_observation"] is None
    assert result["series"]["real_10y"]["change_bp"] == 10.0


@pytest.mark.parametrize("selector", ["future_observation", "after_window", "before_window", "first_seen_at", "received_at"])
def test_forward_actual_consumer_hidden_rows_are_invariant(qsp_forward_observer, selector):
    args = forward_arguments()
    original = observe_forward(args, qsp_forward_observer)
    day = {"future_observation": "2024-01-06", "after_window": "2024-01-04",
           "before_window": "2024-01-01"}.get(selector, DATES[0])
    hidden = {"capture_sha256": "f" * 64, "row_sha256": object()}
    if selector in ("first_seen_at", "received_at"):
        hidden[selector] = "2024-01-05T12:00:00.000001Z"
        hidden["received_at" if selector == "first_seen_at" else "first_seen_at"] = "unsupported"
    raw_rows = [(DATES[0], 4), (DATES[1], 4.2)]
    if selector == "before_window":
        raw_rows.insert(0, (day, "bad"))
        args["nominal_evidence"]["rows"].insert(0, hidden)
    else:
        raw_rows.append((day, "bad"))
        args["nominal_evidence"]["rows"].append(hidden)
    replace_nominal(args, xml(raw_rows))
    assert observe_forward(args, qsp_forward_observer) == original


@pytest.mark.parametrize("stamp", [
    "2024-01-05T17:30:00.123456+05:30", "2024-01-05T08:30:00.123456-03:30",
])
def test_forward_actual_consumer_exact_arrival_and_offset(qsp_forward_observer, stamp):
    args = forward_arguments()
    args["decision_at"] = "2024-01-05T12:00:00.123456Z"
    for side in ("nominal", "real"):
        for row in args[f"{side}_evidence"]["rows"]:
            row["first_seen_at"] = row["received_at"] = stamp
    result = observe_forward(args, qsp_forward_observer)
    nominal = result["series"]["nominal_10y"]
    assert nominal["status"] == "declared_available"
    assert nominal["end_observation"]["known_at"] == args["decision_at"]
    assert nominal["consumer_receipt_lag_seconds"] == 0.0
    assert nominal["observation_age_days"] == 2
    earlier = copy.deepcopy(args)
    earlier["decision_at"] = DECISION
    assert observe_forward(earlier, qsp_forward_observer)["series"]["nominal_10y"]["visible_observations"] == 0


@pytest.mark.parametrize("field,bad,reason", [
    ("source_id", "different", "SOURCE_OR_BASIS_MISMATCH"),
    ("unit", "fraction", "UNIT_NOT_PERCENT"),
])
def test_forward_actual_qsp_rejects_source_or_unit_mismatch(qsp_forward_observer, field, bad, reason):
    config = forward_config()
    args = forward_arguments()
    args["window_start"], args["window_end"] = config["window_start"], config["window_end"]
    snapshot = build_treasury_rates_research_input_v2(**args)
    snapshot["series"]["real_10y"][field] = bad
    result = qsp_forward_observer.build_rates_context_observation_v2(snapshot, config)
    codes = result["approximate_yield_spread"]["reason_codes"] + result["series"]["real_10y"]["reason_codes"]
    assert reason in codes
    assert result["approximate_yield_spread"]["change_bp"] is None
