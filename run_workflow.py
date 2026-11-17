"""Open BP Review Assistant: glue that runs every component in order.

    python run_workflow.py
    python run_workflow.py --input readings.csv --roster roster.csv --out output

The components live in openbp/ (one module per wire-diagram node). This file
only reads files, passes data between components, and writes outputs.
WORKFLOW.md describes it in enough detail to regenerate it.

Outputs (output/): staff_review_report.html, review_sheet.csv,
patient_results.json, audit_log.json. Nothing is sent to patients.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pandas as pd
import yaml

from openbp.bp_threshold import bp_threshold_check
from openbp.draft_message import check_templates, draft_message
from openbp.flag_implausible import flag_implausible
from openbp.llm_summary import llm_staff_summary
from openbp.number_match import template_summary, verified_summary
from openbp.protocol_adherence import apply_first_day_rule, assess_adherence
from openbp.readability_node import ReadabilityConfig, check_readability
from openbp.staff_report import write_staff_report
from openbp.summary_statistics import summary_statistics
from openbp.triage import GROUP_LABELS, GROUPS, triage
from openbp.validate_input import validate_input

HERE = Path(__file__).resolve().parent
DEFAULTS = {
    "input": HERE / "data" / "synthetic_readings.csv",
    "roster": HERE / "data" / "synthetic_roster.csv",
    "config": HERE / "config.yaml",
    "templates": HERE / "message_templates.json",
    "out": HERE / "output",
}


def read_table(path) -> pd.DataFrame:
    """Read a CSV or Excel file with every column as text."""
    path = Path(path)
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path, dtype=str).fillna("")
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def read_roster(path) -> dict:
    if not path or not Path(path).exists():
        return {}
    return {str(r["patient_id"]).strip(): r for r in read_table(path).to_dict("records")}


def package_versions() -> dict:
    out = {}
    for pkg in ("pandas", "numpy", "textstat", "PyYAML"):
        try:
            out[pkg] = version(pkg)
        except PackageNotFoundError:
            out[pkg] = "not installed"
    return out


def run(input_path=DEFAULTS["input"], roster_path=DEFAULTS["roster"],
        config_path=DEFAULTS["config"], templates_path=DEFAULTS["templates"],
        out_dir=DEFAULTS["out"]) -> dict:
    cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    templates = json.loads(Path(templates_path).read_text(encoding="utf-8"))
    check_templates(templates, GROUPS)
    readability_cfg = ReadabilityConfig(target_grade=cfg.get("target_grade", 6.0))

    # 1-2. Validate the file, then flag implausible readings (never delete them)
    clean, rejected = validate_input(read_table(input_path))
    readings = flag_implausible(clean, cfg["plausibility"])

    # Review window: report date from config, else the last reading date
    if cfg["review"].get("report_date"):
        report_date = date.fromisoformat(str(cfg["review"]["report_date"]))
    elif len(readings):
        report_date = readings["reading_datetime"].max().date()
    else:
        report_date = date.today()
    window_start = report_date - timedelta(days=cfg["review"]["window_days"] - 1)
    reading_day = readings["reading_datetime"].dt.date
    readings = readings.assign(in_window=reading_day.between(window_start, report_date),
                               upto_report=reading_day <= report_date)

    # Patients: everyone on the roster plus anyone in the readings file
    roster = read_roster(roster_path)
    patients = []
    for pid in sorted(set(roster) | set(readings["patient_id"])):
        info = roster.get(pid, {})
        first_name = str(info.get("first_name", "") or "").strip()
        language = str(info.get("preferred_language", "") or "en").strip()
        mine = readings[readings["patient_id"] == pid]
        week = mine[mine["in_window"]]
        week_valid, first_day_dropped = apply_first_day_rule(
            week[~week["flag_implausible"]], cfg["adherence"])
        flagged = week[week["flag_implausible"]]

        adherence = assess_adherence(week_valid, cfg["adherence"])                # 3
        adherence["first_day_dropped"] = first_day_dropped
        stats = summary_statistics(week_valid, mine[mine["upto_report"]], report_date)  # 4
        category = bp_threshold_check(stats["mean_systolic"], stats["mean_diastolic"],  # 5
                                      adherence["sufficient"], cfg["threshold"])
        group = triage(adherence["sufficient"], category,                         # 6
                       stats["days_since_last_reading"],
                       cfg["review"]["no_reading_cutoff_days"])
        draft = draft_message(group, first_name, templates, cfg["program"])       # 7
        readability = check_readability({"text": draft, "language": "en"},        # 10
                                        readability_cfg)
        patients.append({
            "patient_id": pid,
            "first_name": first_name,
            "preferred_language": language,
            "translation_needed": not language.lower().startswith("en"),
            "adherence": adherence,
            "stats": stats,
            "bp_category": category,
            "group": group,
            "implausible_count": int(len(flagged)),
            "implausible_reasons": flagged["implausible_reason"].tolist(),
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

    # 8-9. LLM summary, checked against its source; template fallback
    source = {"meta": meta, "patients": [{
        "patient_id": p["patient_id"], "group": p["group"],
        "bp_category": p["bp_category"], "implausible_count": p["implausible_count"],
        "days_measured": p["adherence"]["days_measured"],
        "mean_systolic": p["stats"]["mean_systolic"],
        "mean_diastolic": p["stats"]["mean_diastolic"],
        "days_since_last_reading": p["stats"]["days_since_last_reading"],
    } for p in patients]}
    source_json = json.dumps(source, indent=1)
    prompt = (HERE / cfg["llm"]["prompt_file"]).read_text(encoding="utf-8")
    summary = verified_summary(
        source_json,
        generate=lambda: llm_staff_summary(source_json, cfg["llm"], prompt),
        fallback_text=template_summary(meta))

    # 11. Outputs for staff, plus machine-readable results and an audit log
    out_dir = Path(out_dir)
    write_staff_report(patients, summary, rejected, meta, out_dir)
    (out_dir / "patient_results.json").write_text(
        json.dumps({"meta": meta, "patients": patients}, indent=2), encoding="utf-8")
    audit = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "input_file": str(input_path),
        "roster_file": str(roster_path) if roster_path else None,
        "settings": cfg,
        "package_versions": package_versions(),
        "meta": meta,
        "staff_summary": summary,
        "rejected_rows": rejected,
    }
    (out_dir / "audit_log.json").write_text(json.dumps(audit, indent=2, default=str),
                                            encoding="utf-8")
    return {"meta": meta, "patients": patients, "summary": summary, "rejected": rejected}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Open BP Review Assistant.")
    parser.add_argument("--input", default=str(DEFAULTS["input"]), help="readings CSV/XLSX")
    parser.add_argument("--roster", default=str(DEFAULTS["roster"]),
                        help="patient roster CSV (optional; catches patients with no readings)")
    parser.add_argument("--config", default=str(DEFAULTS["config"]))
    parser.add_argument("--templates", default=str(DEFAULTS["templates"]))
    parser.add_argument("--out", default=str(DEFAULTS["out"]), help="output folder")
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
