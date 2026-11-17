"""Generate synthetic home blood pressure readings for testing.

TEST FIXTURE (not part of the live pipeline). No real patient data.

Every synthetic patient follows one pattern, so each triage path in the
workflow gets exercised:

    pattern             what the readings look like              expected group
    ------------------  ---------------------------------------  ------------------
    regular_controlled  AM + PM, 2 readings each, every day,     routine
                        average about 118/74
    regular_high        same schedule, average about 146/92      above_threshold
    sparse              only 2 days of readings this week        too_few_readings
    stopped             readings 3 weeks ago, then nothing       no_recent_readings
    never_reported      on the roster, no readings at all        no_recent_readings
    implausible         like regular_controlled, plus entry      routine (typos are
                        typos (1400/80, 70/110)                  flagged, not used)

The file also gets three "messy" rows (a duplicate, a bad date and a
non-numeric value) so the input validator has something to reject.

Usage (defaults shown):
    python generate_synthetic_data.py --per-pattern 2 --seed 42 \
        --end-date 2026-11-15 --out-dir data

Outputs:
    data/synthetic_readings.csv  patient_id, reading_datetime, systolic, diastolic
    data/synthetic_roster.csv    patient_id, first_name, preferred_language,
                                 synthetic_pattern (answer key for tests; the
                                 workflow ignores it)
"""

from __future__ import annotations

import argparse
import csv
import random
from datetime import date, datetime, timedelta
from pathlib import Path

PATTERNS = {
    # pattern: (mean systolic, mean diastolic, days with readings, counting back
    #           from the end date; 0 = the end date itself)
    "regular_controlled": (118, 74, range(0, 21)),
    "regular_high": (146, 92, range(0, 21)),
    "sparse": (124, 78, [1, 4]),
    "stopped": (126, 79, range(14, 21)),
    "never_reported": (None, None, []),
    "implausible": (119, 75, range(0, 21)),
}

EXPECTED_GROUP = {
    "regular_controlled": "routine",
    "regular_high": "above_threshold",
    "sparse": "too_few_readings",
    "stopped": "no_recent_readings",
    "never_reported": "no_recent_readings",
    "implausible": "routine",
}

FIRST_NAMES = [
    "Alex", "Maria", "James", "Aisha", "Wei", "Rosa", "Daniel", "Grace",
    "Omar", "Linh", "Sam", "Tenzin", "Priya", "Jamal", "Ana", "Kofi",
]


def sitting(rng: random.Random, day: date, hour: int, mean_sbp: float, mean_dbp: float):
    """One sitting = two readings taken 1-3 minutes apart (Shimbo et al., 2020)."""
    start = datetime(day.year, day.month, day.day, hour) + timedelta(minutes=rng.randint(0, 59))
    second = start + timedelta(minutes=rng.randint(1, 3))
    rows = []
    for when in (start, second):
        rows.append({
            "reading_datetime": when.strftime("%Y-%m-%d %H:%M:%S"),
            "systolic": round(rng.gauss(mean_sbp, 6)),
            "diastolic": round(rng.gauss(mean_dbp, 4)),
        })
    return rows


def generate(per_pattern: int = 2, seed: int = 42, end_date: date = date(2026, 11, 15)):
    """Return (readings, roster) as lists of dicts. Same seed -> same data."""
    rng = random.Random(seed)
    readings, roster = [], []
    number = 0
    for pattern, (mean_sbp, mean_dbp, days_back) in PATTERNS.items():
        for _ in range(per_pattern):
            number += 1
            pid = f"SYN-{number:03d}"
            roster.append({
                "patient_id": pid,
                "first_name": FIRST_NAMES[(number - 1) % len(FIRST_NAMES)],
                "preferred_language": "en",
                "synthetic_pattern": pattern,
            })
            for back in days_back:
                day = end_date - timedelta(days=back)
                for hour in (7, 19):  # morning and evening sittings
                    for row in sitting(rng, day, hour, mean_sbp, mean_dbp):
                        readings.append({"patient_id": pid, **row})
            if pattern == "implausible":
                # Typical entry typos: an extra zero, and numbers swapped.
                readings.append({"patient_id": pid, "reading_datetime":
                                 f"{end_date - timedelta(days=2)} 07:30:00",
                                 "systolic": 1400, "diastolic": 80})
                readings.append({"patient_id": pid, "reading_datetime":
                                 f"{end_date - timedelta(days=3)} 19:30:00",
                                 "systolic": 70, "diastolic": 110})

    # One patient prefers Spanish, to show the translation note in the report.
    roster[1]["preferred_language"] = "es"

    # Messy rows for the validator: duplicate, unparseable date, non-numeric.
    if readings:
        readings.append(dict(readings[0]))
        readings.append({"patient_id": readings[0]["patient_id"],
                         "reading_datetime": "not a date", "systolic": 120, "diastolic": 80})
        readings.append({"patient_id": readings[0]["patient_id"],
                         "reading_datetime": f"{end_date} 12:00:00",
                         "systolic": "12O", "diastolic": 80})  # letter O, not zero
    return readings, roster


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--per-pattern", type=int, default=2,
                        help="patients per pattern (default 2)")
    parser.add_argument("--seed", type=int, default=42,
                        help="random seed; same seed gives the same file (default 42)")
    parser.add_argument("--end-date", default="2026-11-15",
                        help="last day of the review week, YYYY-MM-DD (default 2026-11-15)")
    parser.add_argument("--out-dir", default="data", help="output folder (default data)")
    args = parser.parse_args()

    readings, roster = generate(args.per_pattern, args.seed,
                                date.fromisoformat(args.end_date))
    out = Path(args.out_dir)
    write_csv(out / "synthetic_readings.csv", readings,
              ["patient_id", "reading_datetime", "systolic", "diastolic"])
    write_csv(out / "synthetic_roster.csv", roster,
              ["patient_id", "first_name", "preferred_language", "synthetic_pattern"])
    print(f"Wrote {len(readings)} readings for {len(roster)} patients to {out}/")


if __name__ == "__main__":
    main()
