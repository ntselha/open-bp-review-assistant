"""3. Home BP protocol adherence (atomic protocol).

Citable sources
    Shimbo D, Artinian NT, Basile JN, et al. Self-Measured Blood Pressure
    Monitoring at Home: A Joint Policy Statement From the American Heart
    Association and American Medical Association. Circulation.
    2020;142(4):e42-e63. https://doi.org/10.1161/CIR.0000000000000803
    Muntner P, Shimbo D, Carey RM, et al. Measurement of Blood Pressure in
    Humans: A Scientific Statement From the American Heart Association.
    Hypertension. 2019;73(5):e35-e66.

    Protocol: 2 readings at least 1 minute apart, morning and evening, for at
    least 3 days (12 readings), ideally 7 days (28 readings). This module
    codes the rules; the statements define them. Thresholds come from
    config.yaml so a program can match its own protocol.

Input:  one patient's valid (non-implausible) readings in the review week
        (DataFrame with reading_datetime) and the adherence settings:
        {min_days, min_readings, optimal_days, optimal_readings,
         pair_min_seconds, morning_ends_hour, drop_first_day}
Output: adherence record (dict):
        days_measured int, valid_readings int, am_sittings int,
        pm_sittings int, am_pm_days int, paired_sittings int,
        sufficient bool, optimal bool
"""

from __future__ import annotations

import pandas as pd

EMPTY_RECORD = {"days_measured": 0, "valid_readings": 0, "am_sittings": 0,
                "pm_sittings": 0, "am_pm_days": 0, "paired_sittings": 0,
                "sufficient": False, "optimal": False}


def apply_first_day_rule(week: pd.DataFrame, rules: dict) -> tuple[pd.DataFrame, bool]:
    """If drop_first_day is true, ignore readings from the patient's first day."""
    if not rules.get("drop_first_day") or week.empty:
        return week, False
    first = week["reading_datetime"].dt.date.min()
    return week[week["reading_datetime"].dt.date != first], True


def assess_adherence(week: pd.DataFrame, rules: dict) -> dict:
    if week.empty:
        return dict(EMPTY_RECORD)
    w = week.assign(
        day=week["reading_datetime"].dt.date,
        period=week["reading_datetime"].dt.hour.map(
            lambda h: "AM" if h < rules["morning_ends_hour"] else "PM"),
    )
    times = w.groupby(["day", "period"])["reading_datetime"]
    span = (times.max() - times.min()).dt.total_seconds()
    paired = int(((times.size() >= 2) & (span >= rules["pair_min_seconds"])).sum())
    sittings = w.drop_duplicates(["day", "period"])["period"].value_counts()
    days = int(w["day"].nunique())
    n = int(len(w))
    return {
        "days_measured": days,
        "valid_readings": n,
        "am_sittings": int(sittings.get("AM", 0)),
        "pm_sittings": int(sittings.get("PM", 0)),
        "am_pm_days": int((w.groupby("day")["period"].nunique() == 2).sum()),
        "paired_sittings": paired,
        "sufficient": days >= rules["min_days"] and n >= rules["min_readings"],
        "optimal": days >= rules["optimal_days"] and n >= rules["optimal_readings"],
    }
