"""9. Number-match check (disposable component).

Catches made-up values in the LLM summary before staff see it.

    number_match(summary, source_json) -> (passed bool, invented list[str])
        Every number in the summary must appear somewhere in the source
        JSON. Numbers are normalized so 128.0 and 128 match; dates count as
        their parts (2026-11-15 -> 2026, 11, 15).

    verified_summary(source_json, generate, fallback_text) -> dict
        Calls generate() (the LLM step). If the summary fails the check,
        regenerates once. If it fails again, or the LLM step is skipped,
        uses fallback_text. Returns {text, source: "llm"|"template", attempts}.

    template_summary(meta) -> str
        The plain fallback summary, built only from the run's counts.

Known limitation: the check confirms a number exists in the source, not that
it is attached to the right patient (see the xfail test).
"""

from __future__ import annotations

import re
from typing import Callable

_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def numbers_in(text: str) -> set[str]:
    return {f"{float(n):g}" for n in _NUMBER.findall(text)}


def number_match(summary: str, source_json: str) -> tuple[bool, list[str]]:
    invented = sorted(numbers_in(summary) - numbers_in(source_json), key=float)
    return (not invented), invented


def template_summary(meta: dict) -> str:
    c = meta["group_counts"]
    return (
        f"Review week {meta['window_start']} to {meta['report_date']}: "
        f"{meta['patients_reviewed']} patients reviewed. "
        f"{c['no_recent_readings']} with no recent readings, "
        f"{c['too_few_readings']} with too few readings to interpret, "
        f"{c['above_threshold']} above threshold, and {c['routine']} routine. "
        f"{meta['implausible_readings']} implausible readings were flagged and "
        f"{meta['rejected_rows']} input rows were rejected; see the audit log."
    )


def verified_summary(source_json: str, generate: Callable[[], tuple],
                     fallback_text: str) -> dict:
    attempts = []
    for _ in range(2):  # first try + one regeneration
        text, note = generate()
        if text is None:
            attempts.append({"status": "skipped", "note": note})
            break
        ok, invented = number_match(text, source_json)
        attempts.append({"status": "pass" if ok else "fail", "note": note,
                         "invented_numbers": invented})
        if ok:
            return {"text": text, "source": "llm", "attempts": attempts}
    return {"text": fallback_text, "source": "template", "attempts": attempts}
