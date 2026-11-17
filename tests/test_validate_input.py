"""Unit tests for 1. Validate input (openbp/validate_input.py)."""

import pandas as pd
import pytest

from openbp.validate_input import REQUIRED_COLUMNS, validate_input


def raw(rows):
    return pd.DataFrame(rows, columns=REQUIRED_COLUMNS, dtype=str)


def test_clean_rows_typed_and_sorted():
    clean, rejected = validate_input(raw([
        ["B", "2026-11-10 19:00:00", "130", "85"],
        ["A", "2026-11-10 07:00:00", "120", "80"],
    ]))
    assert rejected == []
    assert clean["patient_id"].tolist() == ["A", "B"]
    assert pd.api.types.is_datetime64_any_dtype(clean["reading_datetime"])
    assert clean["systolic"].tolist() == [120, 130]
    assert clean["row_number"].tolist() == [3, 2]   # spreadsheet rows kept for staff


@pytest.mark.parametrize("row, reason", [
    (["", "2026-11-10 07:00", "120", "80"], "missing patient_id"),
    (["A", "not a date", "120", "80"], "unparseable reading_datetime"),
    (["A", "2026-11-10 07:00", "12O", "80"], "non-numeric systolic or diastolic"),
    (["A", "2026-11-10 07:00", "120", ""], "non-numeric systolic or diastolic"),
], ids=["no-id", "bad-date", "letter-O", "blank-diastolic"])
def test_bad_rows_rejected_with_reason(row, reason):
    clean, rejected = validate_input(raw([row]))
    assert clean.empty
    assert rejected[0]["reason"] == reason
    assert rejected[0]["row_number"] == 2


def test_duplicate_kept_once():
    row = ["A", "2026-11-10 07:00", "120", "80"]
    clean, rejected = validate_input(raw([row, row]))
    assert len(clean) == 1
    assert [r["reason"] for r in rejected] == ["duplicate row"]


def test_mixed_date_formats_accepted():
    clean, rejected = validate_input(raw([
        ["A", "2026-11-10 07:00", "120", "80"],
        ["A", "2026-11-10 19:05:30", "121", "79"],
        ["A", "11/11/2026 7:00 AM", "119", "78"],
    ]))
    assert rejected == [] and len(clean) == 3


def test_missing_column_raises():
    with pytest.raises(ValueError, match="missing required columns"):
        validate_input(pd.DataFrame({"patient_id": ["A"]}))


def test_extra_columns_ignored():
    df = raw([["A", "2026-11-10 07:00", "120", "80"]]).assign(pulse="70")
    clean, _ = validate_input(df)
    assert "pulse" not in clean.columns
