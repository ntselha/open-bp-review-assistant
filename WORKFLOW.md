# WORKFLOW.md: instructions for regenerating the glue code

This file describes `run_workflow.py`, the glue that connects the components in `openbp/`. It is written so that a coding agent, given this file and the `openbp/` package, can regenerate `run_workflow.py` and get the same outputs. The components themselves are not regenerated from this file. Each one has its own docstring contract and unit tests in `tests/`.

**Prompt to use:** "Using WORKFLOW.md and the modules in openbp/, write run_workflow.py. Do not change anything in openbp/. Then run `python -m pytest` and `python run_workflow.py` and confirm the expected results at the end of WORKFLOW.md."

## Rules for the glue

1. The glue only reads files, calls components in the order below, passes their outputs along, and writes output files. It contains no clinical rules, thresholds, or message wording. Those live in `config.yaml`, `message_templates.json`, and the components.
2. Every setting comes from `config.yaml`. Never hard-code a number that is in the config.
3. Nothing is sent to patients. The glue only writes files for staff.
4. The workflow must run with no API key. The LLM step returns `None` when no key is set, and the template summary is used.
5. Use only the packages pinned in `requirements.txt`: Python standard library, pandas, PyYAML, textstat (through `openbp.readability_node`). `anthropic` is optional (`requirements-llm.txt`) and is imported only inside `openbp/llm_summary.py`.

## Command line

```
python run_workflow.py [--input PATH] [--roster PATH] [--config PATH] [--templates PATH] [--out DIR]
```

| Argument | Default (relative to the repository root) |
|---|---|
| `--input` | `data/synthetic_readings.csv` |
| `--roster` | `data/synthetic_roster.csv` |
| `--config` | `config.yaml` |
| `--templates` | `message_templates.json` |
| `--out` | `output/` |

Expose the same steps as a function `run(input_path, roster_path, config_path, templates_path, out_dir) -> dict` returning `{"meta", "patients", "summary", "rejected"}`, so tests can call it. `main()` parses the arguments, calls `run()`, and prints the review week, the count per group (using `GROUP_LABELS`), the implausible and rejected counts, the summary source, and the report path.

## Data assets (read with plain boilerplate)

| File | How to read it |
|---|---|
| `config.yaml` | `yaml.safe_load`. Sections: `target_grade` (top level), `program`, `review`, `adherence`, `threshold`, `plausibility`, `llm`. |
| `message_templates.json` | `json.loads`. A mapping `{group: template text}`. Call `check_templates(templates, GROUPS)` right after loading. |
| `prompts/staff_summary_prompt.txt` | Read as text. The path comes from `config["llm"]["prompt_file"]`. |
| Readings file | CSV: `pd.read_csv(path, dtype=str, keep_default_na=False)`. `.xlsx`/`.xls`: `pd.read_excel(path, dtype=str).fillna("")`. |
| Roster file (optional) | Same reader. Build a dict keyed by `patient_id` (stripped). If the path is missing or the file doesn't exist, use an empty dict. |

## Steps, in order

**Setup.** Load the config and templates. Build `ReadabilityConfig(target_grade=config.get("target_grade", 6.0))`.

**Step 1: Validate input.** `clean, rejected = validate_input(raw_readings)`.

**Step 2: Flag implausible.** `readings = flag_implausible(clean, config["plausibility"])`.

**Review window.**
- `report_date` is `config["review"]["report_date"]` if set (ISO date). Otherwise it's the date of the latest `reading_datetime` in `readings`, or today if there are no readings.
- `window_start = report_date - (window_days - 1)` days. The window includes both ends.
- Add two boolean columns:
  - `in_window`: the reading date is between `window_start` and `report_date`
  - `upto_report`: the reading date is on or before `report_date`

**Patient list.** Take the sorted union of roster IDs and `readings["patient_id"]`. A roster patient with no readings must still be processed. They will triage to `no_recent_readings`.

**For each patient, in order:**

1. Look up their roster row. `first_name` is a stripped string, or `""`. `preferred_language` is a stripped string, or `"en"`.
2. Select their readings and split them:
   - `week`: readings in the window.
   - `flagged`: `week` rows where `flag_implausible` is true.
   - `week_valid, first_day_dropped = apply_first_day_rule(week rows NOT flagged, config["adherence"])`.
3. **Step 3:** `adherence = assess_adherence(week_valid, config["adherence"])`. Then set `adherence["first_day_dropped"] = first_day_dropped`.
4. **Step 4:** `stats = summary_statistics(week_valid, all of the patient's rows with upto_report, report_date)`. Implausible readings count as contact for recency but are not averaged.
5. **Step 5:** `category = bp_threshold_check(stats["mean_systolic"], stats["mean_diastolic"], adherence["sufficient"], config["threshold"])`.
6. **Step 6:** `group = triage(adherence["sufficient"], category, stats["days_since_last_reading"], config["review"]["no_reading_cutoff_days"])`.
7. **Step 7:** `draft = draft_message(group, first_name, templates, config["program"])`.
8. **Step 10:** `readability = check_readability({"text": draft, "language": "en"}, readability_config)`. The drafts are English, so the language is always `"en"`.
9. Append a patient result dict with exactly these keys:
   - `patient_id`, `first_name`, `preferred_language`
   - `translation_needed`: true when `preferred_language` does not start with "en"
   - `adherence`, `stats`, `bp_category`, `group`
   - `implausible_count`: the number of `flagged` rows
   - `implausible_reasons`: the list of `flagged["implausible_reason"]`
   - `draft_message`
   - `readability`: only the `grade`, `passed`, and `status` keys

Sort patients by `(GROUPS.index(group), patient_id)`.

**Meta.** Build:
```
{report_date, window_start (ISO strings), patients_reviewed,
 group_counts {group: count for every group in GROUPS},
 implausible_readings (sum of implausible_count), rejected_rows (len(rejected))}
```

**Steps 8–9: LLM summary with number-match check.**
- Build `source = {"meta": meta, "patients": [...]}`. Each patient entry has only `patient_id`, `group`, `bp_category`, `implausible_count`, `days_measured`, `mean_systolic`, `mean_diastolic`, and `days_since_last_reading`. Never include names.
- Set `source_json = json.dumps(source, indent=1)`.
- Call:
  ```
  summary = verified_summary(
      source_json,
      generate=lambda: llm_staff_summary(source_json, config["llm"], prompt_text),
      fallback_text=template_summary(meta))
  ```

**Step 11: Outputs.** Call `write_staff_report(patients, summary, rejected, meta, out_dir)`. It creates `out_dir` and writes `staff_review_report.html` and `review_sheet.csv`. Then write:
- `patient_results.json`: `{"meta", "patients"}`, with indent 2.
- `audit_log.json`: `run_at` (ISO, seconds), `input_file`, `roster_file`, `settings` (the whole config), `package_versions` (pandas, numpy, textstat, PyYAML from `importlib.metadata`, or "not installed"), `meta`, `staff_summary`, `rejected_rows`. Use `default=str`.

## Expected results (how to check a regenerated glue)

Run `python generate_synthetic_data.py` (seed 42, end date 2026-11-15), then `python run_workflow.py`. It should print:

```
Review week 2026-11-09 to 2026-11-15: 12 patients
  1. No recent readings                4
  2. Too few readings to interpret     2
  3. Above threshold                   2
  4. Routine                           4
Implausible readings flagged: 4; rejected rows: 3
Staff summary source: template
```

`python -m pytest` should report all tests passing except the 2 expected failures (xfail). `tests/test_end_to_end.py` calls `run()` directly and checks every synthetic patient's group.
