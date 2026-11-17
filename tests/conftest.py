"""Shared test helpers. All test data is synthetic."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
REPORT_DATE = date(2026, 11, 15)


@pytest.fixture(scope="session")
def cfg() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def readings(rows, patient_id="SYN-T01") -> pd.DataFrame:
    """rows: list of (datetime str, systolic, diastolic)."""
    return pd.DataFrame({
        "patient_id": [patient_id] * len(rows),
        "reading_datetime": pd.to_datetime([r[0] for r in rows]),
        "systolic": [r[1] for r in rows],
        "diastolic": [r[2] for r in rows],
    })


def protocol_week(days: int, sbp: int = 120, dbp: int = 75, end: date = REPORT_DATE,
                  am: bool = True, pm: bool = True, gap_minutes: int = 2) -> pd.DataFrame:
    """A week following the home BP protocol for `days` days ending on `end`."""
    rows = []
    for back in range(days):
        d = end - timedelta(days=back)
        for hour, on in ((7, am), (19, pm)):
            if on:
                t = datetime(d.year, d.month, d.day, hour)
                rows += [(str(t), sbp, dbp), (str(t + timedelta(minutes=gap_minutes)), sbp, dbp)]
    return readings(rows)
