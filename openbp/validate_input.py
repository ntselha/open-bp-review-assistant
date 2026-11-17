"""1. Validate input (disposable component).

Input:  raw readings table (pandas DataFrame, every column as text) with
        columns patient_id, reading_datetime, systolic, diastolic.
Output: (clean, rejected)
        clean    DataFrame: patient_id str, reading_datetime datetime64,
                 systolic int, diastolic int, row_number int; sorted by
                 patient then time.
        rejected list of dicts: row_number, reason, and the raw values.

Each bad row gets the first reason that applies, in this order:
missing patient_id, unparseable reading_datetime, non-numeric systolic or
diastolic, duplicate row. A missing required column raises ValueError.
"""

from __future__ import annotations

import pandas as pd

REQUIRED_COLUMNS = ["patient_id", "reading_datetime", "systolic", "diastolic"]


def validate_input(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    missing = [c for c in REQUIRED_COLUMNS if c not in raw.columns]
    if missing:
        raise ValueError(f"readings file is missing required columns: {missing}")

    raw = raw.reset_index(drop=True)
    patient_id = raw["patient_id"].astype(str).str.strip()
    when = pd.to_datetime(raw["reading_datetime"], errors="coerce", format="mixed")
    sbp = pd.to_numeric(raw["systolic"], errors="coerce")
    dbp = pd.to_numeric(raw["diastolic"], errors="coerce")

    reason = pd.Series("", index=raw.index)
    checks = [
        (patient_id.isin(["", "nan", "None"]), "missing patient_id"),
        (when.isna(), "unparseable reading_datetime"),
        (sbp.isna() | dbp.isna(), "non-numeric systolic or diastolic"),
    ]
    for bad, why in checks:
        reason = reason.mask(bad & (reason == ""), why)
    key = pd.DataFrame({"p": patient_id, "t": when, "s": sbp, "d": dbp})
    reason = reason.mask(key.duplicated(keep="first") & (reason == ""), "duplicate row")

    row_number = raw.index + 2  # header is row 1 in a spreadsheet
    rejected = [
        {"row_number": int(row_number[i]), "reason": reason[i],
         **{c: str(raw.at[i, c]) for c in REQUIRED_COLUMNS}}
        for i in raw.index[reason != ""]
    ]
    ok = reason == ""
    clean = pd.DataFrame({
        "patient_id": patient_id[ok],
        "reading_datetime": when[ok],
        "systolic": sbp[ok].astype(int),
        "diastolic": dbp[ok].astype(int),
        "row_number": pd.Series(row_number, index=raw.index)[ok],
    }).sort_values(["patient_id", "reading_datetime"]).reset_index(drop=True)
    return clean, rejected
