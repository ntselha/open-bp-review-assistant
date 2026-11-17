"""Unit tests for 6. Triage grouping, the decision node (openbp/triage.py).

These carry the equity logic: missing data must always lead to outreach,
never to "routine". Every combination of inputs is checked.
"""

import itertools

import pytest

from openbp.bp_threshold import CATEGORIES
from openbp.triage import GROUP_LABELS, GROUPS, triage

CUTOFF = 7


@pytest.mark.parametrize("sufficient, category, days_since, expected", [
    (True, "below threshold", None, "no_recent_readings"),    # never reported
    (True, "above threshold", 12, "no_recent_readings"),      # missing beats high
    (False, "not assessable", 8, "no_recent_readings"),       # one day past cutoff
    (False, "not assessable", 7, "too_few_readings"),         # cutoff is inclusive
    (False, "not assessable", 1, "too_few_readings"),
    (True, "above threshold", 0, "above_threshold"),
    (True, "below threshold", 0, "routine"),
], ids=["never", "stopped-but-high", "past-cutoff", "at-cutoff", "sparse", "high", "routine"])
def test_rules_in_order(sufficient, category, days_since, expected):
    assert triage(sufficient, category, days_since, CUTOFF) == expected


def test_no_combination_with_missing_data_is_routine():
    for sufficient, category, days_since in itertools.product(
            [True, False], CATEGORIES, [None, 0, 3, 7, 8, 30]):
        group = triage(sufficient, category, days_since, CUTOFF)
        assert group in GROUPS
        if days_since is None or days_since > CUTOFF or not sufficient:
            assert group != "routine", (sufficient, category, days_since)


def test_insufficient_patient_never_labelled_above_threshold():
    assert triage(False, "above threshold", 0, CUTOFF) == "too_few_readings"


def test_cutoff_comes_from_config():
    assert triage(True, "below threshold", 10, 14) == "routine"


def test_every_group_has_a_label():
    assert set(GROUP_LABELS) == set(GROUPS)
