"""2. Flag implausible readings (disposable component).

Input:  clean readings DataFrame (systolic int, diastolic int) and the
        plausibility settings from config.yaml:
        {systolic_min, systolic_max, diastolic_min, diastolic_max}
Output: a copy with two new columns:
        flag_implausible   bool
        implausible_reason str ("" if plausible; reasons joined by "; ")

Rules: systolic outside its range, diastolic outside its range, or systolic
not above diastolic. Readings are flagged for staff, never deleted; flagged
readings are left out of adherence counts and averages downstream.
"""

from __future__ import annotations

import pandas as pd


def flag_implausible(df: pd.DataFrame, limits: dict) -> pd.DataFrame:
    out = df.copy()
    reasons = pd.Series("", index=out.index)
    rules = [
        (~out["systolic"].between(limits["systolic_min"], limits["systolic_max"]),
         f"systolic outside {limits['systolic_min']}-{limits['systolic_max']}"),
        (~out["diastolic"].between(limits["diastolic_min"], limits["diastolic_max"]),
         f"diastolic outside {limits['diastolic_min']}-{limits['diastolic_max']}"),
        (out["systolic"] <= out["diastolic"], "systolic not above diastolic"),
    ]
    for bad, why in rules:
        reasons = reasons.mask(bad, reasons.where(reasons == "", reasons + "; ") + why)
    out["implausible_reason"] = reasons
    out["flag_implausible"] = reasons != ""
    return out
