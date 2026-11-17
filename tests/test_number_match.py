"""Unit tests for 9. Number-match check (openbp/number_match.py)."""

import json

import pytest

from openbp.number_match import number_match, numbers_in, template_summary, verified_summary

SOURCE = json.dumps({"meta": {"report_date": "2026-11-15", "patients_reviewed": 12},
                     "patients": [{"patient_id": "SYN-001", "mean_systolic": 118.7},
                                  {"patient_id": "SYN-003", "mean_systolic": 144.9}]})
META = {"report_date": "2026-11-15", "window_start": "2026-11-09", "patients_reviewed": 12,
        "group_counts": {"no_recent_readings": 4, "too_few_readings": 2,
                         "above_threshold": 2, "routine": 4},
        "implausible_readings": 4, "rejected_rows": 3}


def test_numbers_normalized():
    assert numbers_in("128.0 and 128 and 2026-11-09") == {"128", "2026", "11", "9"}


def test_passes_when_every_number_is_in_source():
    assert number_match("12 patients; SYN-003 averaged 144.9 by 2026-11-15.", SOURCE) == (True, [])


@pytest.mark.parametrize("summary, invented", [
    ("Readings rose 27% this week.", ["27"]),
    ("SYN-003 averaged 145.", ["145"]),            # rounded value is still invented
    ("12 patients, 13 flagged.", ["13"]),
])
def test_catches_invented_numbers(summary, invented):
    assert number_match(summary, SOURCE) == (False, invented)


def test_text_without_numbers_passes():
    assert number_match("Several patients need outreach.", SOURCE)[0]


def generator(*replies):
    replies = list(replies)
    return lambda: (replies.pop(0), "fake model")


def test_first_attempt_passes():
    out = verified_summary(SOURCE, generator("12 patients reviewed."), "fallback")
    assert out["source"] == "llm" and len(out["attempts"]) == 1


def test_regenerates_once_after_failure():
    out = verified_summary(SOURCE, generator("99 patients.", "12 patients."), "fallback")
    assert out["source"] == "llm" and out["text"] == "12 patients."
    assert [a["status"] for a in out["attempts"]] == ["fail", "pass"]


def test_falls_back_to_template_after_two_failures():
    out = verified_summary(SOURCE, generator("99 patients.", "98 patients."), "fallback")
    assert out == {"text": "fallback", "source": "template",
                   "attempts": out["attempts"]}
    assert [a["status"] for a in out["attempts"]] == ["fail", "fail"]


def test_skipped_llm_uses_template():
    out = verified_summary(SOURCE, lambda: (None, "ANTHROPIC_API_KEY not set"), "fallback")
    assert out["source"] == "template" and out["attempts"][0]["status"] == "skipped"


def test_template_summary_passes_its_own_check():
    text = template_summary(META)
    assert "12 patients reviewed" in text
    assert number_match(text, json.dumps(META))[0]


@pytest.mark.xfail(strict=True, reason=(
    "Known limitation: the check confirms each number exists somewhere in the "
    "source, not that it belongs to the patient named next to it."))
def test_catches_number_attributed_to_wrong_patient():
    ok, _ = number_match("SYN-001 averaged 144.9 systolic.", SOURCE)  # 144.9 is SYN-003's
    assert not ok
