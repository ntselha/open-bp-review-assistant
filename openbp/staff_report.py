"""11. Staff review report (disposable component; the human review point).

Input:  patients list[dict] (one result per patient, already sorted by
        group), summary dict {text, source, attempts}, rejected list[dict],
        meta dict (report_date, window_start, counts), out_dir Path
Output: writes two files to out_dir and returns their paths:
        staff_review_report.html  readable report, one table per outreach
                                  group, plus rejected input rows
        review_sheet.csv          one row per patient with blank
                                  "approve (Y/N)", "edited_message" and
                                  "reviewer_initials" columns

Nothing goes to patients from here: staff approve or edit every draft.
All text is HTML-escaped.
"""

from __future__ import annotations

import html
from pathlib import Path

import pandas as pd

from openbp.triage import GROUP_LABELS, GROUPS

REVIEW_COLUMNS = ["group", "patient_id", "first_name", "mean_bp", "days_measured",
                  "draft_message", "readability_grade", "approve (Y/N)",
                  "edited_message", "reviewer_initials"]


def mean_bp(patient: dict) -> str:
    s = patient["stats"]
    if s["mean_systolic"] is None:
        return "-"
    return f"{s['mean_systolic']:g}/{s['mean_diastolic']:g}"


def patient_flags(p: dict) -> list[str]:
    flags = []
    if p["implausible_count"]:
        flags.append(f"{p['implausible_count']} implausible: "
                     + "; ".join(sorted(set(p["implausible_reasons"]))))
    if p["translation_needed"]:
        flags.append(f"prefers language '{p['preferred_language']}'; "
                     "template is English only, arrange translation")
    if p["readability"]["status"] == "flag":
        flags.append("draft above target reading grade")
    return flags


def render_html(patients: list[dict], summary: dict, rejected: list[dict], meta: dict) -> str:
    e = html.escape
    notes = "; ".join(a["note"] for a in summary["attempts"]) or "n/a"
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<title>Open BP Review: staff report</title><style>",
        "body{font-family:system-ui,sans-serif;margin:24px;color:#1b2a3a}",
        "table{border-collapse:collapse;width:100%;margin-bottom:24px;font-size:14px}",
        "th,td{border:1px solid #c9d3de;padding:6px;vertical-align:top;text-align:left}",
        "th{background:#e8eef5}.flag{color:#a33}.note{color:#555;font-size:13px}",
        "</style></head><body>",
        "<h1>Open BP Review Assistant: weekly staff report</h1>",
        f"<p>Review week <b>{e(meta['window_start'])}</b> to <b>{e(meta['report_date'])}</b>. "
        "<b>Nothing has been sent to patients.</b> Approve or edit every draft in "
        "review_sheet.csv before use.</p>",
        f"<h2>Summary</h2><p>{e(summary['text'])}</p>",
        f"<p class='note'>Summary source: {e(summary['source'])} ({e(notes)}).</p>",
    ]
    for group in GROUPS:
        rows = [p for p in patients if p["group"] == group]
        parts.append(f"<h2>{e(GROUP_LABELS[group])} ({len(rows)})</h2>")
        if not rows:
            parts.append("<p class='note'>None this week.</p>")
            continue
        parts.append(
            "<table><tr><th>Patient</th><th>Days / readings</th><th>AM+PM days</th>"
            "<th>Mean BP</th><th>BP category</th><th>Days since last</th>"
            "<th>Flags</th><th>Draft message</th><th>Grade</th></tr>")
        for p in rows:
            a, s, r = p["adherence"], p["stats"], p["readability"]
            since = s["days_since_last_reading"]
            grade = "-" if r["grade"] is None else f"{r['grade']:g}"
            parts.append(
                f"<tr><td>{e(p['patient_id'])}<br>{e(p['first_name'])}</td>"
                f"<td>{a['days_measured']} / {a['valid_readings']}</td>"
                f"<td>{a['am_pm_days']}</td><td>{e(mean_bp(p))}</td>"
                f"<td>{e(p['bp_category'])}</td><td>{'-' if since is None else since}</td>"
                f"<td class='flag'>{e(' | '.join(patient_flags(p)))}</td>"
                f"<td>{e(p['draft_message'])}</td><td>{e(grade)} ({e(r['status'])})</td></tr>")
        parts.append("</table>")
    if rejected:
        parts.append(f"<h2>Rejected input rows ({len(rejected)})</h2><table>"
                     "<tr><th>Row</th><th>Reason</th><th>Patient</th><th>Values</th></tr>")
        for r in rejected:
            parts.append(f"<tr><td>{r['row_number']}</td><td>{e(r['reason'])}</td>"
                         f"<td>{e(r['patient_id'])}</td><td>{e(r['reading_datetime'])}, "
                         f"{e(r['systolic'])}/{e(r['diastolic'])}</td></tr>")
        parts.append("</table>")
    parts.append("</body></html>")
    return "\n".join(parts)


def review_sheet(patients: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{
        "group": GROUP_LABELS[p["group"]],
        "patient_id": p["patient_id"],
        "first_name": p["first_name"],
        "mean_bp": mean_bp(p),
        "days_measured": p["adherence"]["days_measured"],
        "draft_message": p["draft_message"],
        "readability_grade": p["readability"]["grade"],
        "approve (Y/N)": "",
        "edited_message": "",
        "reviewer_initials": "",
    } for p in patients], columns=REVIEW_COLUMNS)


def write_staff_report(patients: list[dict], summary: dict, rejected: list[dict],
                       meta: dict, out_dir: Path) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "staff_review_report.html"
    sheet = out_dir / "review_sheet.csv"
    report.write_text(render_html(patients, summary, rejected, meta), encoding="utf-8")
    review_sheet(patients).to_csv(sheet, index=False)
    return {"report": report, "review_sheet": sheet}
