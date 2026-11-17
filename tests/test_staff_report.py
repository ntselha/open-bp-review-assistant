"""Unit tests for 11. Staff review report (openbp/staff_report.py)."""

import pandas as pd

from openbp.staff_report import REVIEW_COLUMNS, render_html, write_staff_report

META = {"report_date": "2026-11-15", "window_start": "2026-11-09"}
SUMMARY = {"text": "2 patients reviewed.", "source": "template",
           "attempts": [{"status": "skipped", "note": "ANTHROPIC_API_KEY not set"}]}


def patient(pid, group, name="Alex", language="en", implausible=0, status="pass"):
    return {
        "patient_id": pid, "first_name": name, "preferred_language": language,
        "translation_needed": language != "en", "group": group,
        "bp_category": "below threshold",
        "adherence": {"days_measured": 7, "valid_readings": 28, "am_pm_days": 7},
        "stats": {"mean_systolic": 118.7, "mean_diastolic": 73.9, "days_since_last_reading": 0},
        "implausible_count": implausible,
        "implausible_reasons": ["systolic outside 70-250"] * implausible,
        "draft_message": f"Hi {name}, this is Main Street Clinic.",
        "readability": {"grade": 2.3, "passed": status == "pass", "status": status},
    }


PATIENTS = [patient("SYN-005", "too_few_readings", "Wei"),
            patient("SYN-002", "routine", "Maria", language="es", implausible=2)]


def test_writes_report_and_review_sheet(tmp_path):
    paths = write_staff_report(PATIENTS, SUMMARY, [], META, tmp_path)
    assert paths["report"].exists()
    sheet = pd.read_csv(paths["review_sheet"], keep_default_na=False)
    assert list(sheet.columns) == REVIEW_COLUMNS
    assert sheet["approve (Y/N)"].tolist() == ["", ""]   # staff fill these in
    assert sheet["patient_id"].tolist() == ["SYN-005", "SYN-002"]


def test_every_group_has_a_section_even_when_empty():
    page = render_html(PATIENTS, SUMMARY, [], META)
    for heading in ("No recent readings (0)", "Too few readings to interpret (1)",
                    "Above threshold (0)", "Routine (1)"):
        assert heading in page


def test_flags_translation_and_implausible_readings():
    page = render_html(PATIENTS, SUMMARY, [], META)
    assert "arrange translation" in page
    assert "2 implausible" in page


def test_states_nothing_sent_and_summary_source():
    page = render_html(PATIENTS, SUMMARY, [], META)
    assert "Nothing has been sent to patients" in page
    assert "Summary source: template" in page


def test_lists_rejected_rows():
    rejected = [{"row_number": 9, "reason": "duplicate row", "patient_id": "SYN-001",
                 "reading_datetime": "2026-11-15 07:40:00", "systolic": "123", "diastolic": "75"}]
    assert "Rejected input rows (1)" in render_html(PATIENTS, SUMMARY, rejected, META)


def test_text_is_escaped():
    bad = [patient("SYN-009", "routine", name="<script>alert(1)</script>")]
    page = render_html(bad, SUMMARY, [], META)
    assert "<script>" not in page and "&lt;script&gt;" in page
