"""7. Draft message (disposable component; no LLM involved).

Input:  group str, first_name str ("" if unknown), templates dict
        {group: text with {placeholders}} from message_templates.json,
        program dict {clinic_name, clinic_phone} from config.yaml
Output: draft message str

Patient-facing wording stays fixed and reviewed: code only fills the
{first_name}, {clinic_name} and {clinic_phone} slots. An unknown first
name becomes "there" ("Hi there"). A missing template raises KeyError, and
an unknown placeholder raises KeyError, so a broken template never reaches
staff silently.
"""

from __future__ import annotations


def check_templates(templates: dict, groups: list[str]) -> None:
    missing = [g for g in groups if g not in templates]
    if missing:
        raise ValueError(f"message_templates.json is missing groups: {missing}")


def draft_message(group: str, first_name: str, templates: dict, program: dict) -> str:
    fields = {"first_name": first_name.strip() or "there", **program}
    return templates[group].format_map(fields)
