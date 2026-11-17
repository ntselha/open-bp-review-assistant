"""Unit tests for 3. Home BP protocol adherence (openbp/protocol_adherence.py).

Expected values follow Shimbo et al. (2020): 2 readings >= 1 minute apart,
morning and evening; sufficient = >= 3 days and >= 12 readings; optimal =
7 days and 28 readings (thresholds from config.yaml).
"""

import pytest

from conftest import protocol_week, readings
from openbp.protocol_adherence import EMPTY_RECORD, apply_first_day_rule, assess_adherence


def test_full_week_is_optimal(cfg):
    rec = assess_adherence(protocol_week(7), cfg["adherence"])
    assert rec == {"days_measured": 7, "valid_readings": 28, "am_sittings": 7,
                   "pm_sittings": 7, "am_pm_days": 7, "paired_sittings": 14,
                   "sufficient": True, "optimal": True}


@pytest.mark.parametrize("days, sufficient", [(2, False), (3, True)])
def test_three_day_minimum(cfg, days, sufficient):
    assert assess_adherence(protocol_week(days), cfg["adherence"])["sufficient"] is sufficient


def test_morning_only_week_counts_readings_but_no_am_pm_days(cfg):
    rec = assess_adherence(protocol_week(7, pm=False), cfg["adherence"])
    assert rec["am_sittings"] == 7 and rec["pm_sittings"] == 0
    assert rec["am_pm_days"] == 0
    assert rec["valid_readings"] == 14 and rec["sufficient"] is True


def test_readings_less_than_a_minute_apart_are_not_paired(cfg):
    week = readings([("2026-11-10 07:00:00", 120, 80), ("2026-11-10 07:00:30", 121, 80)])
    assert assess_adherence(week, cfg["adherence"])["paired_sittings"] == 0


def test_noon_counts_as_evening(cfg):
    rec = assess_adherence(readings([("2026-11-10 12:00", 120, 80)]), cfg["adherence"])
    assert rec["pm_sittings"] == 1 and rec["am_sittings"] == 0


def test_empty_week(cfg):
    week = readings([]).iloc[0:0]
    assert assess_adherence(week, cfg["adherence"]) == EMPTY_RECORD


def test_first_day_rule(cfg):
    rules = dict(cfg["adherence"], drop_first_day=True)
    week, dropped = apply_first_day_rule(protocol_week(3), rules)
    assert dropped is True
    assert assess_adherence(week, rules)["days_measured"] == 2


def test_first_day_rule_off_by_default(cfg):
    week, dropped = apply_first_day_rule(protocol_week(3), cfg["adherence"])
    assert dropped is False and len(week) == 12
