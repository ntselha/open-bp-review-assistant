"""Tests for the rough-draft workflow (run_workflow.py) on synthetic data.

Covers the triage decision node, the number-match check, the input
validator and plausibility flags, and one end-to-end run that checks every
synthetic patient lands in the outreach group its pattern was built for.
The LLM step is skipped (no API key), so the template summary is tested.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import generate_synthetic_data as gen
import run_workflow as wf

HERE = Path(__file__).resolve().parent
CFG = wf.load_settings(HERE / "config.yaml")

ENOUGH = {"sufficient": True}
TOO_FEW = {"sufficient": False}


# --- 6. Triage grouping (decision node) ------------------------------------


@pytest.mark.parametrize(
    "adherence, category, days_since, expected",
    [
        (ENOUGH, "below threshold", None, "no_recent_readings"),   # never reported
        (ENOUGH, "above threshold", 12, "no_recent_readings"),     # missing beats high
        (TOO_FEW, "not assessable", 7, "too_few_readings"),        # cutoff is inclusive
        (TOO_FEW, "not assessable", 1, "too_few_readings"),
        (ENOUGH, "above threshold", 0, "above_threshold"),
        (ENOUGH, "below threshold", 0, "routine"),
    ],
    ids=["never", "stopped-but-high", "at-cutoff", "sparse", "high", "routine"],
)
def test_triage_rules(adherence, category, days_since, expected):
    assert wf.triage(adherence, category, days_since, CFG) == expected


def test_no_data_patient_is_never_routine():
    assert wf.triage({"sufficient": False}, "not assessable", None, CFG) != "routine"


# --- 5. BP threshold check --------------------------------------------------


@pytest.mark.parametrize(
    "sbp, dbp, expected",
    [(129.9, 79.9, "below threshold"), (130, 70, "above threshold"),
     (120, 80, "above threshold")],
)
def test_threshold_boundaries(sbp, dbp, expected):
    assert wf.bp_threshold_check(sbp, dbp, ENOUGH, CFG) == expected


def test_threshold_not_assessable_when_too_few():
    assert wf.bp_threshold_check(150, 95, TOO_FEW, CFG) == "not assessable"


# --- 9. Number-match check --------------------------------------------------


def test_number_match_passes_on_source_numbers():
    source = json.dumps({"mean_systolic": 128.0, "count": 3})
    assert wf.number_match("Mean was 128 across 3 patients.", source) == (True, [])


def test_number_match_catches_invented_number():
    source = json.dumps({"mean_systolic": 128.0})
    ok, invented = wf.number_match("Mean was 128, up 15% from last week.", source)
    assert not ok and invented == ["15"]


# --- 1-2. Validator and plausibility flags ----------------------------------


def test_validator_rejects_messy_rows():
    raw = pd.DataFrame({
        "patient_id": ["A", "A", "A", "A", ""],
        "reading_datetime": ["2026-11-10 07:00", "2026-11-10 07:00", "not a date",
                             "2026-11-10 19:00", "2026-11-10 19:00"],
        "systolic": ["120", "120", "120", "12O", "120"],
        "diastolic": ["80", "80", "80", "80", "80"],
    })
    clean, rejected = wf.validate_input(raw)
    assert len(clean) == 1
    assert sorted(r["reason"] for r in rejected) == [
        "duplicate row", "missing patient_id",
        "non-numeric systolic or diastolic", "unparseable reading_datetime"]


def test_validator_requires_columns():
    with pytest.raises(ValueError, match="missing required columns"):
        wf.validate_input(pd.DataFrame({"patient_id": ["A"]}))


def test_implausible_flagged_not_deleted():
    df = pd.DataFrame({"patient_id": ["A", "A", "A"],
                       "reading_datetime": pd.to_datetime(["2026-11-10"] * 3),
                       "systolic": [120, 1400, 70], "diastolic": [80, 80, 110]})
    out = wf.flag_implausible(df, CFG)
    assert len(out) == 3
    assert out["flag_implausible"].tolist() == [False, True, True]


# --- End to end on synthetic data -------------------------------------------


@pytest.fixture(scope="module")
def synthetic_run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("run")
    readings, roster = gen.generate(per_pattern=2, seed=42, end_date=date(2026, 11, 15))
    gen.write_csv(tmp / "readings.csv", readings,
                  ["patient_id", "reading_datetime", "systolic", "diastolic"])
    gen.write_csv(tmp / "roster.csv", roster,
                  ["patient_id", "first_name", "preferred_language", "synthetic_pattern"])
    mp = pytest.MonkeyPatch()
    mp.delenv("ANTHROPIC_API_KEY", raising=False)
    result = wf.run(tmp / "readings.csv", tmp / "roster.csv", out_dir=tmp / "output")
    mp.undo()
    return result, roster, tmp / "output"


def test_every_pattern_lands_in_expected_group(synthetic_run):
    result, roster, _ = synthetic_run
    groups = {p["patient_id"]: p["group"] for p in result["patients"]}
    for row in roster:
        assert groups[row["patient_id"]] == gen.EXPECTED_GROUP[row["synthetic_pattern"]], row


def test_messy_rows_rejected_and_typos_flagged(synthetic_run):
    result, _, _ = synthetic_run
    assert {r["reason"] for r in result["rejected"]} == {
        "duplicate row", "unparseable reading_datetime", "non-numeric systolic or diastolic"}
    assert result["meta"]["implausible_readings"] == 4  # 2 typos x 2 patients


def test_all_drafts_pass_readability(synthetic_run):
    result, _, _ = synthetic_run
    assert all(p["readability"]["status"] == "pass" for p in result["patients"])


def test_template_summary_used_without_key_and_passes_number_match(synthetic_run):
    result, _, _ = synthetic_run
    assert result["summary"]["source"] == "template"
    source = json.dumps({"meta": result["meta"]})
    assert wf.number_match(result["summary"]["text"], source)[0]


def test_outputs_written(synthetic_run):
    _, _, out = synthetic_run
    for name in ("staff_review_report.html", "review_sheet.csv",
                 "patient_results.json", "audit_log.json"):
        assert (out / name).stat().st_size > 0
