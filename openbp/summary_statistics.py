"""4. Summary statistics (disposable component).

Input:  week_valid  DataFrame of the patient's valid readings in the review
                    week (after the first-day rule)
        all_rows    DataFrame of all the patient's readings up to the report
                    date, including implausible ones (any reading counts as
                    contact for the recency check)
        report_date datetime.date
Output: dict
        mean_systolic float|None, mean_diastolic float|None (1 decimal),
        reading_count int, first_reading_date str|None,
        last_reading_date str|None (ISO dates),
        days_since_last_reading int|None (None = never reported)
"""

from __future__ import annotations

from datetime import date

import pandas as pd


def _mean(series: pd.Series):
    return round(float(series.mean()), 1) if len(series) else None


def summary_statistics(week_valid: pd.DataFrame, all_rows: pd.DataFrame,
                       report_date: date) -> dict:
    last = all_rows["reading_datetime"].max() if len(all_rows) else None
    first = all_rows["reading_datetime"].min() if len(all_rows) else None
    return {
        "mean_systolic": _mean(week_valid["systolic"]),
        "mean_diastolic": _mean(week_valid["diastolic"]),
        "reading_count": int(len(week_valid)),
        "first_reading_date": first.date().isoformat() if first is not None else None,
        "last_reading_date": last.date().isoformat() if last is not None else None,
        "days_since_last_reading": (report_date - last.date()).days if last is not None else None,
    }
