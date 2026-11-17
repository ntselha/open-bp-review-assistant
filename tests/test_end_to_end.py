"""End-to-end test: the whole workflow on synthetic data.

Generates data, runs run_workflow.run(), and checks every synthetic patient
lands in the outreach group its pattern was built for. The LLM step is
skipped (no API key), so the template summary path is exercised.
"""

import json
from datetime import date

import pytest

import generate_synthetic_data as gen
import run_workflow as wf

FIELDS_R = ["patient_id", "reading_datetime", "systolic", "diastolic"]
FIELDS_P = ["patient_id", "first_name", "preferred_language", "synthetic_pattern"]


@pytest.fixture(scope="module")
def synthetic_run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("run")
    readings, roster = gen.generate(per_pattern=2, seed=42, end_date=date(2026, 11, 15))
    gen.write_csv(tmp / "readings.csv", readings, FIELDS_R)
    gen.write_csv(tmp / "roster.csv", roster, FIELDS_P)
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


def test_counts(synthetic_run):
    meta = synthetic_run[0]["meta"]
    assert meta["group_counts"] == {"no_recent_readings": 4, "too_few_readings": 2,
                                    "above_threshold": 2, "routine": 4}
    assert meta["implausible_readings"] == 4 and meta["rejected_rows"] == 3


def test_report_sorted_by_group(synthetic_run):
    order = [wf.GROUPS.index(p["group"]) for p in synthetic_run[0]["patients"]]
    assert order == sorted(order)


def test_all_drafts_pass_readability(synthetic_run):
    assert all(p["readability"]["status"] == "pass" for p in synthetic_run[0]["patients"])


def test_spanish_preference_flagged(synthetic_run):
    flagged = [p["patient_id"] for p in synthetic_run[0]["patients"] if p["translation_needed"]]
    assert flagged == ["SYN-002"]


def test_template_summary_used_without_key(synthetic_run):
    summary = synthetic_run[0]["summary"]
    assert summary["source"] == "template"
    assert summary["attempts"][0]["note"] == "ANTHROPIC_API_KEY not set"


def test_outputs_written(synthetic_run):
    out = synthetic_run[2]
    for name in ("staff_review_report.html", "review_sheet.csv",
                 "patient_results.json", "audit_log.json"):
        assert (out / name).stat().st_size > 0
    audit = json.loads((out / "audit_log.json").read_text(encoding="utf-8"))
    assert audit["settings"]["llm"]["model"] == "claude-haiku-5-5"
    assert len(audit["rejected_rows"]) == 3
