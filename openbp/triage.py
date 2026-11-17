"""6. Triage grouping (disposable component, DECISION NODE).

Input:  sufficient bool (adherence record), bp_category str (threshold
        check), days_since_last_reading int|None, no_reading_cutoff_days int
Output: one outreach group str, from GROUPS

Ordered rules; the first match wins. Missing-data rules run first, so a
patient with no data can never land in "routine":

    1. no_recent_readings  never reported, or last reading more than
                           no_reading_cutoff_days before the report date
    2. too_few_readings    not enough readings to meet the home BP protocol
    3. above_threshold     mean BP at or above the program threshold
    4. routine             everyone else
"""

from __future__ import annotations

GROUPS = ["no_recent_readings", "too_few_readings", "above_threshold", "routine"]

GROUP_LABELS = {
    "no_recent_readings": "1. No recent readings",
    "too_few_readings": "2. Too few readings to interpret",
    "above_threshold": "3. Above threshold",
    "routine": "4. Routine",
}


def triage(sufficient: bool, bp_category: str, days_since_last_reading,
           no_reading_cutoff_days: int) -> str:
    if days_since_last_reading is None or days_since_last_reading > no_reading_cutoff_days:
        return "no_recent_readings"
    if not sufficient:
        return "too_few_readings"
    if bp_category == "above threshold":
        return "above_threshold"
    return "routine"
