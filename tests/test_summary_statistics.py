"""Unit tests for 4. Summary statistics (openbp/summary_statistics.py)."""

import pandas as pd

from conftest import REPORT_DATE, readings
from openbp.summary_statistics import summary_statistics


def test_means_counts_and_dates():
    week = readings([("2026-11-14 07:00", 120, 80), ("2026-11-15 07:00", 125, 81)])
    history = pd.concat([readings([("2026-11-01 07:00", 200, 100)]), week])
    s = summary_statistics(week, history, REPORT_DATE)
    assert s["mean_systolic"] == 122.5 and s["mean_diastolic"] == 80.5  # week only
    assert s["reading_count"] == 2
    assert s["first_reading_date"] == "2026-11-01"
    assert s["last_reading_date"] == "2026-11-15"
    assert s["days_since_last_reading"] == 0


def test_rounds_to_one_decimal():
    week = readings([("2026-11-15 07:00", 120, 80), ("2026-11-15 07:02", 121, 80),
                     ("2026-11-15 07:04", 121, 81)])
    s = summary_statistics(week, week, REPORT_DATE)
    assert s["mean_systolic"] == 120.7 and s["mean_diastolic"] == 80.3


def test_no_readings_this_week_but_older_contact():
    empty = readings([]).iloc[0:0]
    old = readings([("2026-11-01 07:00", 120, 80)])
    s = summary_statistics(empty, old, REPORT_DATE)
    assert s["mean_systolic"] is None and s["reading_count"] == 0
    assert s["days_since_last_reading"] == 14


def test_never_reported():
    empty = readings([]).iloc[0:0]
    s = summary_statistics(empty, empty, REPORT_DATE)
    assert s["days_since_last_reading"] is None
    assert s["first_reading_date"] is None and s["last_reading_date"] is None
