"""Unit tests for 12. Synthetic data generator (generate_synthetic_data.py, test fixture)."""

from datetime import date

import generate_synthetic_data as gen

END = date(2026, 11, 15)


def test_same_seed_same_data():
    assert gen.generate(2, 42, END) == gen.generate(2, 42, END)
    assert gen.generate(2, 42, END) != gen.generate(2, 7, END)


def test_every_pattern_present_with_expected_group():
    _, roster = gen.generate(3, 42, END)
    assert len(roster) == 3 * len(gen.PATTERNS)
    assert {r["synthetic_pattern"] for r in roster} == set(gen.PATTERNS) == set(gen.EXPECTED_GROUP)


def test_never_reported_patients_have_no_readings():
    readings, roster = gen.generate(2, 42, END)
    silent = {r["patient_id"] for r in roster if r["synthetic_pattern"] == "never_reported"}
    assert silent and not silent & {r["patient_id"] for r in readings}


def test_includes_messy_rows_and_typos():
    readings, _ = gen.generate(2, 42, END)
    assert any(r["reading_datetime"] == "not a date" for r in readings)
    assert any(r["systolic"] == "12O" for r in readings)
    assert sum(r["systolic"] == 1400 for r in readings) == 2


def test_no_readings_after_end_date():
    readings, _ = gen.generate(2, 42, END)
    dates = [r["reading_datetime"][:10] for r in readings if r["reading_datetime"] != "not a date"]
    assert max(dates) == END.isoformat()


def test_write_csv(tmp_path):
    readings, roster = gen.generate(1, 42, END)
    gen.write_csv(tmp_path / "r.csv", readings,
                  ["patient_id", "reading_datetime", "systolic", "diastolic"])
    lines = (tmp_path / "r.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "patient_id,reading_datetime,systolic,diastolic"
    assert len(lines) == len(readings) + 1
