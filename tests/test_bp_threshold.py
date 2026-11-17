"""Unit tests for 5. BP threshold check (openbp/bp_threshold.py).

Whelton et al. (2017): home BP >= 130/80 corresponds to stage 1
hypertension, so either number at or above the threshold counts.
"""

import pytest

from openbp.bp_threshold import CATEGORIES, bp_threshold_check

DEFAULT = {"systolic": 130, "diastolic": 80}


@pytest.mark.parametrize("sbp, dbp, expected", [
    (129.9, 79.9, "below threshold"),
    (130.0, 70.0, "above threshold"),   # systolic alone at threshold
    (120.0, 80.0, "above threshold"),   # diastolic alone at threshold
    (145.2, 91.7, "above threshold"),
    (118.7, 73.9, "below threshold"),
], ids=["just-below", "sbp-at", "dbp-at", "high", "controlled"])
def test_default_threshold(sbp, dbp, expected):
    assert bp_threshold_check(sbp, dbp, True, DEFAULT) == expected


@pytest.mark.parametrize("sbp, dbp", [(150, 95), (None, None), (130, None)])
def test_not_assessable_without_enough_or_any_readings(sbp, dbp):
    assert bp_threshold_check(sbp, dbp, False, DEFAULT) == "not assessable"
    if sbp is None or dbp is None:
        assert bp_threshold_check(sbp, dbp, True, DEFAULT) == "not assessable"


def test_program_can_set_its_own_threshold():
    assert bp_threshold_check(132, 78, True, {"systolic": 140, "diastolic": 90}) == "below threshold"


def test_output_is_always_a_known_category():
    for args in [(100, 60, True), (200, 120, True), (None, None, False)]:
        assert bp_threshold_check(*args, DEFAULT) in CATEGORIES
