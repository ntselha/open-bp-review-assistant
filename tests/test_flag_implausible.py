"""Unit tests for 2. Flag implausible (openbp/flag_implausible.py)."""

import pytest

from conftest import readings
from openbp.flag_implausible import flag_implausible


@pytest.mark.parametrize("sbp, dbp, flagged, reason_part", [
    (120, 80, False, ""),
    (1400, 80, True, "systolic outside"),       # extra zero
    (70, 110, True, "systolic not above"),      # numbers swapped
    (120, 20, True, "diastolic outside"),
    (250, 150, False, ""),                       # upper limits are allowed
    (80, 80, True, "systolic not above"),
], ids=["normal", "extra-zero", "swapped", "low-diastolic", "at-limits", "equal"])
def test_flag_rules(cfg, sbp, dbp, flagged, reason_part):
    out = flag_implausible(readings([("2026-11-10 07:00", sbp, dbp)]), cfg["plausibility"])
    assert bool(out["flag_implausible"].iloc[0]) is flagged
    assert reason_part in out["implausible_reason"].iloc[0]


def test_flags_never_delete_rows(cfg):
    df = readings([("2026-11-10 07:00", 120, 80), ("2026-11-10 07:02", 1400, 80)])
    out = flag_implausible(df, cfg["plausibility"])
    assert len(out) == 2
    assert out["flag_implausible"].tolist() == [False, True]


def test_multiple_reasons_joined(cfg):
    out = flag_implausible(readings([("2026-11-10 07:00", 30, 200)]), cfg["plausibility"])
    assert out["implausible_reason"].iloc[0].count(";") == 2


def test_input_not_modified(cfg):
    df = readings([("2026-11-10 07:00", 120, 80)])
    flag_implausible(df, cfg["plausibility"])
    assert "flag_implausible" not in df.columns


@pytest.mark.xfail(strict=True, reason=(
    "Known limitation: range rules cannot catch an in-range typo, such as 151 "
    "entered instead of 115. Staff review of unusual values is still needed."))
def test_catches_in_range_typo(cfg):
    out = flag_implausible(readings([("2026-11-10 07:00", 151, 75)]), cfg["plausibility"])
    assert out["flag_implausible"].iloc[0]
