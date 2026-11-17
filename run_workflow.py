"""Open BP Review Assistant: rough-draft workflow that runs end to end.

One command, from a readings file to a staff review report:

    python run_workflow.py
    python run_workflow.py --input data/synthetic_readings.csv --roster data/synthetic_roster.csv

Each numbered section below is one node of the wire diagram
(docs/wire_diagram.png). Settings live in config.yaml, patient message
wording in message_templates.json, and the LLM prompt in prompts/.

Outputs (in output/):
    staff_review_report.html  report for staff, sorted by outreach group
    review_sheet.csv          one row per patient with approve/edit columns
    patient_results.json      everything computed for each patient
    audit_log.json            settings, versions, rejected rows, summary checks

Nothing is sent to patients. Every draft waits for staff review.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import yaml

from readability_node import ReadabilityConfig, check_readability

HERE = Path(__file__).resolve().parent
DEFAULT_INPUT = HERE / "data" / "synthetic_readings.csv"
DEFAULT_ROSTER = HERE / "data" / "synthetic_roster.csv"
DEFAULT_CONFIG = HERE / "config.yaml"
DEFAULT_TEMPLATES = HERE / "message_templates.json"
DEFAULT_OUTPUT = HERE / "output"

REQUIRED_COLUMNS = ["patient_id", "reading_datetime", "systolic", "diastolic"]

# Outreach groups, in triage order (missing-data groups come first).
GROUPS = ["no_recent_readings", "too_few_readings", "above_threshold", "routine"]
GROUP_LABELS = {
    "no_recent_readings": "1. No recent readings",
    "too_few_readings": "2. Too few readings to interpret",
    "above_threshold": "3. Above threshold",
    "routine": "4. Routine",
}


# ---------------------------------------------------------------------------
# Glue: read settings and files
# ---------------------------------------------------------------------------


def load_settings(path: Path) -> dict:
    with Path(path).open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_table(path: Path) -> pd.DataFrame:
    """Read a CSV or Excel file with every column as text."""
    path = Path(path)
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path, dtype=str)
    return pd.read_csv(path, dtype=str, keep_default_na=False)


# ---------------------------------------------------------------------------
# 1. Validate input (disposable component)
#    readings file (CSV/XLSX) -> clean readings table + rejected-rows log
# ---------------------------------------------------------------------------


def validate_input(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    missing = [c for c in REQUIRED_COLUMNS if c not in raw.columns]
    if missing:
        raise ValueError(f"readings file is missing required columns: {missing}")

    df = raw[REQUIRED_COLUMNS].copy()
    df["row_number"] = raw.index + 2  # +2: header is row 1 in a spreadsheet
    df["patient_id"] = df["patient_id"].astype(str).str.strip()
    parsed_time = pd.to_datetime(df["reading_datetime"], errors="coerce")
    sbp = pd.to_numeric(df["systolic"], errors="coerce")
    dbp = pd.to_numeric(df["diastolic"], errors="coerce")

    reason = pd.Series("", index=df.index)
    checks = [
        (df["patient_id"].isin(["", "nan", "None"]), "missing patient_id"),
        (parsed_time.isna(), "unparseable reading_datetime"),
        (sbp.isna() | dbp.isna(), "non-numeric systolic or diastolic"),
    ]
    for bad, why in checks:
        reason = reason.mask(bad & (reason == ""), why)

    key = pd.DataFrame({"p": df["patient_id"], "t": parsed_time, "s": sbp, "d": dbp})
    dup = key.duplicated(keep="first") & (reason == "")
    reason = reason.mask(dup, "duplicate row")

    rejected = [
        {"row_number": int(df.at[i, "row_number"]), "reason": reason[i],
         **{c: str(raw.at[i, c]) for c in REQUIRED_COLUMNS}}
        for i in df.index[reason != ""]
    ]
    ok = reason == ""
    clean = pd.DataFrame({
        "patient_id": df.loc[ok, "patient_id"],
        "reading_datetime": parsed_time[ok],
        "systolic": sbp[ok].astype(int),
        "diastolic": dbp[ok].astype(int),
        "row_number": df.loc[ok, "row_number"],
    }).sort_values(["patient_id", "reading_datetime"]).reset_index(drop=True)
    return clean, rejected


# ---------------------------------------------------------------------------
# 2. Flag implausible readings (disposable component)
#    readings table -> same table + flag_implausible, implausible_reason
#    Readings are flagged for staff, never deleted.
# ---------------------------------------------------------------------------


def flag_implausible(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    p = cfg["plausibility"]
    out = df.copy()
    reasons = pd.Series("", index=out.index)
    rules = [
        (~out["systolic"].between(p["systolic_min"], p["systolic_max"]),
         f"systolic outside {p['systolic_min']}-{p['systolic_max']}"),
        (~out["diastolic"].between(p["diastolic_min"], p["diastolic_max"]),
         f"diastolic outside {p['diastolic_min']}-{p['diastolic_max']}"),
        (out["systolic"] <= out["diastolic"], "systolic not above diastolic"),
    ]
    for bad, why in rules:
        reasons = reasons.mask(bad, reasons.where(reasons == "", reasons + "; ") + why)
    out["implausible_reason"] = reasons
    out["flag_implausible"] = reasons != ""
    return out


# ---------------------------------------------------------------------------
# 3. Protocol adherence (atomic protocol: Shimbo et al., 2020; Muntner et al., 2019)
#    one patient's valid readings in the review week -> adherence record (dict)
# ---------------------------------------------------------------------------


def apply_first_day_rule(week: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, bool]:
    """If configured, drop readings from the first day the patient measured."""
    if not cfg["adherence"]["drop_first_day"] or week.empty:
        return week, False
    first = week["reading_datetime"].dt.date.min()
    return week[week["reading_datetime"].dt.date != first], True


def assess_adherence(week: pd.DataFrame, cfg: dict) -> dict:
    a = cfg["adherence"]
    if week.empty:
        return {"days_measured": 0, "valid_readings": 0, "am_sittings": 0,
                "pm_sittings": 0, "am_pm_days": 0, "paired_sittings": 0,
                "sufficient": False, "optimal": False}
    w = week.assign(
        day=week["reading_datetime"].dt.date,
        period=week["reading_datetime"].dt.hour.map(
            lambda h: "AM" if h < a["morning_ends_hour"] else "PM"),
    )
    sittings = w.groupby(["day", "period"])["reading_datetime"]
    span_seconds = (sittings.max() - sittings.min()).dt.total_seconds()
    paired = int(((sittings.size() >= 2) & (span_seconds >= a["pair_min_seconds"])).sum())
    periods_per_day = w.groupby("day")["period"].nunique()
    days = int(w["day"].nunique())
    n = int(len(w))
    period_counts = w.drop_duplicates(["day", "period"])["period"].value_counts()
    return {
        "days_measured": days,
        "valid_readings": n,
        "am_sittings": int(period_counts.get("AM", 0)),
        "pm_sittings": int(period_counts.get("PM", 0)),
        "am_pm_days": int((periods_per_day == 2).sum()),
        "paired_sittings": paired,
        "sufficient": days >= a["min_days"] and n >= a["min_readings"],
        "optimal": days >= a["optimal_days"] and n >= a["optimal_readings"],
    }


# ---------------------------------------------------------------------------
# 4. Summary statistics (disposable component)
#    valid readings -> mean SBP/DBP, reading count, first/last date, days since last
# ---------------------------------------------------------------------------


def summary_statistics(week_valid: pd.DataFrame, all_rows: pd.DataFrame,
                       report_date: date) -> dict:
    last = all_rows["reading_datetime"].max() if not all_rows.empty else None
    first = all_rows["reading_datetime"].min() if not all_rows.empty else None
    return {
        "mean_systolic": round(float(week_valid["systolic"].mean()), 1) if not week_valid.empty else None,
        "mean_diastolic": round(float(week_valid["diastolic"].mean()), 1) if not week_valid.empty else None,
        "reading_count": int(len(week_valid)),
        "first_reading_date": first.date().isoformat() if first is not None else None,
        "last_reading_date": last.date().isoformat() if last is not None else None,
        "days_since_last_reading": (report_date - last.date()).days if last is not None else None,
    }


# ---------------------------------------------------------------------------
# 5. BP threshold check (atomic protocol: Whelton et al., 2017; Shimbo et al., 2020)
#    mean BP + adherence record + threshold -> BP category (str)
#    A mean at or above either threshold number counts as "above threshold",
#    matching the guideline's >=130/80 definition.
# ---------------------------------------------------------------------------


def bp_threshold_check(mean_sbp, mean_dbp, adherence: dict, cfg: dict) -> str:
    t = cfg["threshold"]
    if not adherence["sufficient"] or mean_sbp is None or mean_dbp is None:
        return "not assessable"
    if mean_sbp >= t["systolic"] or mean_dbp >= t["diastolic"]:
        return "above threshold"
    return "below threshold"


# ---------------------------------------------------------------------------
# 6. Triage grouping (disposable component, DECISION NODE)
#    adherence + BP category + days since last reading -> one outreach group
#    Missing-data rules run first, so a patient with no data can never be "routine".
# ---------------------------------------------------------------------------


def triage(adherence: dict, bp_category: str, days_since_last, cfg: dict) -> str:
    cutoff = cfg["review"]["no_reading_cutoff_days"]
    if days_since_last is None or days_since_last > cutoff:
        return "no_recent_readings"
    if not adherence["sufficient"]:
        return "too_few_readings"
    if bp_category == "above threshold":
        return "above_threshold"
    return "routine"


# ---------------------------------------------------------------------------
# 7. Draft message (disposable component; no LLM involved)
#    group + patient fields -> draft message (str) from an approved template
# ---------------------------------------------------------------------------


def draft_message(group: str, patient: dict, templates: dict, cfg: dict) -> str:
    fields = {"first_name": patient.get("first_name") or "there", **cfg["program"]}
    return templates[group].format_map(fields)


# ---------------------------------------------------------------------------
# 10. Readability check (atomic protocol: Flesch-Kincaid grade via textstat)
#     Implemented in readability_node.py and tested in
#     test_flesch_kincaid_grade_level.py; called from run() below.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 8. LLM staff summary (disposable prompt calling a versioned LLM)
#    all patient results (JSON str) -> summary text (str), or None if unavailable
# ---------------------------------------------------------------------------


def llm_staff_summary(results_json: str, cfg: dict) -> tuple[str | None, str]:
    llm = cfg["llm"]
    if not llm.get("enabled", False):
        return None, "LLM disabled in config.yaml"
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None, "ANTHROPIC_API_KEY not set"
    try:
        import anthropic  # optional; see requirements-llm.txt
    except ImportError:
        return None, "anthropic package not installed"
    prompt = (HERE / llm["prompt_file"]).read_text(encoding="utf-8")
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=llm["model"],
        max_tokens=llm["max_tokens"],
        messages=[{"role": "user", "content": prompt.replace("{results_json}", results_json)}],
    )
    text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
    return text.strip(), f"generated by {llm['model']}"


# ---------------------------------------------------------------------------
# 9. Number-match check (disposable component)
#    summary + source JSON -> pass/fail. Fail -> regenerate once -> template fallback.
# ---------------------------------------------------------------------------

_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def numbers_in(text: str) -> set[str]:
    """Every number in the text, normalized so 128.0 and 128 match."""
    return {f"{float(n):g}" for n in _NUMBER.findall(text)}


def number_match(summary: str, source_json: str) -> tuple[bool, list[str]]:
    invented = sorted(numbers_in(summary) - numbers_in(source_json), key=float)
    return (not invented), invented


def template_summary(meta: dict) -> str:
    c = meta["group_counts"]
    return (
        f"Review week {meta['window_start']} to {meta['report_date']}: "
        f"{meta['patients_reviewed']} patients reviewed. "
        f"{c['no_recent_readings']} with no recent readings, "
        f"{c['too_few_readings']} with too few readings to interpret, "
        f"{c['above_threshold']} above threshold, and {c['routine']} routine. "
        f"{meta['implausible_readings']} implausible readings were flagged and "
        f"{meta['rejected_rows']} input rows were rejected; see the audit log."
    )


def build_staff_summary(source: dict, cfg: dict) -> dict:
    source_json = json.dumps(source, indent=1, default=str)
    attempts = []
    for _ in range(2):  # first try + one regeneration
        text, note = llm_staff_summary(source_json, cfg)
        if text is None:
            attempts.append({"status": "skipped", "note": note})
            break
        ok, invented = number_match(text, source_json)
        attempts.append({"status": "pass" if ok else "fail", "note": note,
                         "invented_numbers": invented})
        if ok:
            return {"text": text, "source": "llm", "attempts": attempts}
    return {"text": template_summary(source["meta"]), "source": "template",
            "attempts": attempts}


# ---------------------------------------------------------------------------
# 11. Staff review report (disposable component; the human review point)
#     all patient results -> HTML report + review sheet CSV + JSON + audit log
# ---------------------------------------------------------------------------


def _bp(p: dict) -> str:
    s = p["stats"]
    if s["mean_systolic"] is None:
        return "-"
    return f"{s['mean_systolic']:g}/{s['mean_diastolic']:g}"


def write_report(patients: list[dict], summary: dict, rejected: list[dict],
                 meta: dict, out_dir: Path) -> None:
    e = html.escape
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
        "Synthetic data only. <b>Nothing has been sent to patients.</b> Approve or edit every "
        "draft in review_sheet.csv before use.</p>",
        f"<h2>Summary</h2><p>{e(summary['text'])}</p>",
        f"<p class='note'>Summary source: {e(summary['source'])} "
        f"({e('; '.join(a['note'] for a in summary['attempts']) or 'n/a')}).</p>",
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
            flags = []
            if p["implausible_count"]:
                flags.append(f"{p['implausible_count']} implausible: "
                             + "; ".join(sorted(set(p["implausible_reasons"]))))
            if p["translation_needed"]:
                flags.append(f"prefers language '{p['preferred_language']}'; "
                             "template is English only, arrange translation")
            if r["status"] == "flag":
                flags.append("draft above target reading grade")
            grade = "-" if r["grade"] is None else f"{r['grade']:g}"
            parts.append(
                f"<tr><td>{e(p['patient_id'])}<br>{e(p['first_name'] or '')}</td>"
                f"<td>{a['days_measured']} / {a['valid_readings']}</td>"
                f"<td>{a['am_pm_days']}</td><td>{e(_bp(p))}</td>"
                f"<td>{e(p['bp_category'])}</td>"
                f"<td>{'-' if s['days_since_last_reading'] is None else s['days_since_last_reading']}</td>"
                f"<td class='flag'>{e(' | '.join(flags))}</td>"
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
    (out_dir / "staff_review_report.html").write_text("\n".join(parts), encoding="utf-8")

    sheet = pd.DataFrame([{
        "group": GROUP_LABELS[p["group"]],
        "patient_id": p["patient_id"],
        "first_name": p["first_name"],
        "mean_bp": _bp(p),
        "days_measured": p["adherence"]["days_measured"],
        "draft_message": p["draft_message"],
        "readability_grade": p["readability"]["grade"],
        "approve (Y/N)": "",
        "edited_message": "",
        "reviewer_initials": "",
    } for p in patients])
    sheet.to_csv(out_dir / "review_sheet.csv", index=False)


# ---------------------------------------------------------------------------
# Glue: run every node in order
# ---------------------------------------------------------------------------


def run(input_path=DEFAULT_INPUT, roster_path=DEFAULT_ROSTER, config_path=DEFAULT_CONFIG,
        templates_path=DEFAULT_TEMPLATES, out_dir=DEFAULT_OUTPUT) -> dict:
    cfg = load_settings(config_path)
    templates = json.loads(Path(templates_path).read_text(encoding="utf-8"))
    missing_templates = [g for g in GROUPS if g not in templates]
    if missing_templates:
        raise ValueError(f"message_templates.json is missing groups: {missing_templates}")
    readability_cfg = ReadabilityConfig(target_grade=cfg.get("target_grade", 6.0))

    # 1-2: validate and flag
    clean, rejected = validate_input(read_table(input_path))
    readings = flag_implausible(clean, cfg)

    # Review window
    if cfg["review"]["report_date"]:
        report_date = date.fromisoformat(str(cfg["review"]["report_date"]))
    elif not readings.empty:
        report_date = readings["reading_datetime"].max().date()
    else:
        report_date = date.today()
    window_start = report_date - timedelta(days=cfg["review"]["window_days"] - 1)
    in_window = readings["reading_datetime"].dt.date.between(window_start, report_date)

    # Patient list: roster (if given) plus anyone who appears in the readings
    roster = {}
    if roster_path and Path(roster_path).exists():
        for row in read_table(roster_path).to_dict("records"):
            roster[str(row["patient_id"]).strip()] = row
    patient_ids = sorted(set(roster) | set(readings["patient_id"]))

    patients = []
    for pid in patient_ids:
        info = roster.get(pid, {})
        mine = readings[readings["patient_id"] == pid]
        upto_report = mine[mine["reading_datetime"].dt.date <= report_date]
        week_valid = mine[in_window.loc[mine.index] & ~mine["flag_implausible"]]
        week_valid, first_day_dropped = apply_first_day_rule(week_valid, cfg)

        adherence = assess_adherence(week_valid, cfg)                      # 3
        adherence["first_day_dropped"] = first_day_dropped
        stats = summary_statistics(week_valid, upto_report, report_date)   # 4
        category = bp_threshold_check(stats["mean_systolic"],              # 5
                                      stats["mean_diastolic"], adherence, cfg)
        group = triage(adherence, category, stats["days_since_last_reading"], cfg)  # 6
        patient = {"first_name": info.get("first_name", "") or ""}
        draft = draft_message(group, patient, templates, cfg)              # 7
        readability = check_readability({"text": draft, "language": "en"},  # 10
                                        readability_cfg)
        language = (info.get("preferred_language") or "en").strip()
        week_flags = mine[in_window.loc[mine.index] & mine["flag_implausible"]]
        patients.append({
            "patient_id": pid,
            "first_name": patient["first_name"],
            "preferred_language": language,
            "translation_needed": not language.lower().startswith("en"),
            "adherence": adherence,
            "stats": stats,
            "bp_category": category,
            "group": group,
            "implausible_count": int(len(week_flags)),
            "implausible_reasons": week_flags["implausible_reason"].tolist(),
            "draft_message": draft,
            "readability": {k: readability[k] for k in ("grade", "passed", "status")},
        })
    patients.sort(key=lambda p: (GROUPS.index(p["group"]), p["patient_id"]))

    meta = {
        "report_date": report_date.isoformat(),
        "window_start": window_start.isoformat(),
        "patients_reviewed": len(patients),
        "group_counts": {g: sum(p["group"] == g for p in patients) for g in GROUPS},
        "implausible_readings": sum(p["implausible_count"] for p in patients),
        "rejected_rows": len(rejected),
    }

    # 8-9: LLM summary with number-match check (template fallback)
    llm_source = {"meta": meta, "patients": [
        {k: p[k] for k in ("patient_id", "group", "bp_category", "implausible_count")}
        | {"days_measured": p["adherence"]["days_measured"],
           "mean_systolic": p["stats"]["mean_systolic"],
           "mean_diastolic": p["stats"]["mean_diastolic"],
           "days_since_last_reading": p["stats"]["days_since_last_reading"]}
        for p in patients]}
    summary = build_staff_summary(llm_source, cfg)

    # 11: outputs for staff
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_report(patients, summary, rejected, meta, out_dir)
    (out_dir / "patient_results.json").write_text(
        json.dumps({"meta": meta, "patients": patients}, indent=2, default=str),
        encoding="utf-8")
    try:
        from importlib.metadata import version
        versions = {pkg: version(pkg) for pkg in ("pandas", "textstat", "PyYAML")}
    except Exception:  # pragma: no cover
        versions = {}
    audit = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "input_file": str(input_path),
        "roster_file": str(roster_path) if roster_path else None,
        "settings": cfg,
        "package_versions": versions,
        "meta": meta,
        "staff_summary": summary,
        "rejected_rows": rejected,
    }
    (out_dir / "audit_log.json").write_text(json.dumps(audit, indent=2, default=str),
                                            encoding="utf-8")
    return {"meta": meta, "patients": patients, "summary": summary, "rejected": rejected}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Open BP Review Assistant.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="readings CSV/XLSX")
    parser.add_argument("--roster", default=str(DEFAULT_ROSTER),
                        help="patient roster CSV (optional; catches patients with no readings)")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--templates", default=str(DEFAULT_TEMPLATES))
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="output folder")
    args = parser.parse_args()

    result = run(args.input, args.roster, args.config, args.templates, args.out)
    m = result["meta"]
    print(f"Review week {m['window_start']} to {m['report_date']}: "
          f"{m['patients_reviewed']} patients")
    for g in GROUPS:
        print(f"  {GROUP_LABELS[g]:<36} {m['group_counts'][g]}")
    print(f"Implausible readings flagged: {m['implausible_readings']}; "
          f"rejected rows: {m['rejected_rows']}")
    print(f"Staff summary source: {result['summary']['source']}")
    print(f"Report written to {Path(args.out) / 'staff_review_report.html'}")


if __name__ == "__main__":
    main()
