"""Unit tests for 7. Draft message (openbp/draft_message.py)."""

import json

import pytest

from conftest import ROOT
from openbp.draft_message import check_templates, draft_message
from openbp.triage import GROUPS

PROGRAM = {"clinic_name": "Main Street Clinic", "clinic_phone": "555-0100"}
TEMPLATES = json.loads((ROOT / "message_templates.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("group", GROUPS)
def test_every_group_fills_all_slots(group):
    text = draft_message(group, "Alex", TEMPLATES, PROGRAM)
    assert text.startswith("Hi Alex, this is Main Street Clinic.")
    assert "555-0100" in text
    assert "{" not in text and "}" not in text


def test_unknown_name_becomes_there():
    assert draft_message("routine", "  ", TEMPLATES, PROGRAM).startswith("Hi there,")


def test_same_inputs_same_message():
    a = draft_message("above_threshold", "Maria", TEMPLATES, PROGRAM)
    assert a == draft_message("above_threshold", "Maria", TEMPLATES, PROGRAM)


def test_no_clinical_numbers_in_patient_messages():
    # Messages never quote BP values; numbers stay in the staff report.
    for group in GROUPS:
        text = draft_message(group, "Alex", TEMPLATES, PROGRAM).replace("555-0100", "")
        assert not any(ch.isdigit() for ch in text), group


def test_template_file_covers_every_group():
    check_templates(TEMPLATES, GROUPS)


def test_missing_group_raises():
    with pytest.raises(ValueError, match="missing groups"):
        check_templates({"routine": "Hi"}, GROUPS)


def test_unknown_placeholder_raises():
    with pytest.raises(KeyError):
        draft_message("routine", "Alex", {"routine": "Hi {nickname}"}, PROGRAM)
