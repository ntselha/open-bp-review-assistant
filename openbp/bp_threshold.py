"""5. BP threshold check (atomic protocol).

Citable sources
    Whelton PK, Carey RM, Aronow WS, et al. 2017 ACC/AHA/AAPA/ABC/ACPM/AGS/
    APhA/ASH/ASPC/NMA/PCNA Guideline for the Prevention, Detection,
    Evaluation, and Management of High Blood Pressure in Adults.
    Hypertension. 2018;71(6):1269-1324.
    https://doi.org/10.1161/HYP.0000000000000066
    Shimbo et al. (2020), home-BP equivalents.

    Home BP of 130/80 or higher corresponds to stage 1 hypertension, so a
    mean at or above EITHER number counts as "above threshold". Programs can
    set their own numbers in config.yaml (threshold: systolic, diastolic).

Input:  mean_systolic float|None, mean_diastolic float|None,
        sufficient bool (from the adherence record),
        threshold dict {systolic, diastolic}
Output: BP category str: "above threshold" | "below threshold" | "not assessable"
        (not assessable when readings are insufficient or missing)
"""

from __future__ import annotations

CATEGORIES = ("above threshold", "below threshold", "not assessable")


def bp_threshold_check(mean_systolic, mean_diastolic, sufficient: bool,
                       threshold: dict) -> str:
    if not sufficient or mean_systolic is None or mean_diastolic is None:
        return "not assessable"
    if mean_systolic >= threshold["systolic"] or mean_diastolic >= threshold["diastolic"]:
        return "above threshold"
    return "below threshold"
