"""SYNTHETIC_FIXTURE_ONLY: no downloaded observations."""
import copy
import hashlib
import importlib.util
from pathlib import Path

import pytest

from market_signal_sources.providers.treasury_rates import (
    TreasuryRatesError,
    build_treasury_rates_research_input,
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
