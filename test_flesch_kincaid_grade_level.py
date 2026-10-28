"""Unit tests for the Flesch-Kincaid Grade Level readability protocol,
as used by the Open BP Review Assistant's readability check node.

Protocol
    Flesch-Kincaid Grade Level (FKGL), computed with
    ``textstat.flesch_kincaid_grade`` and applied by ``readability_node``.

Citable sources
    Kincaid JP, Fishburne RP Jr, Rogers RL, Chissom BS. Derivation of New
    Readability Formulas (Automated Readability Index, Fog Count and Flesch
    Reading Ease Formula) for Navy Enlisted Personnel. Research Branch Report
    8-75. Millington, TN: Naval Technical Training Command; 1975.
    FKGL = 0.39 * (words / sentences) + 11.8 * (syllables / words) - 15.59

    READABILITY_NODE_CONTRACT.md v0.1: the node's input rules (C1-C5),
    language handling (L1-L4), output (O1-O4) and config (G1-G4). Tests
    whose expected behavior textstat does not document cite these clauses.

Input -> output contract
    Input:  check_readability({"text": str, "language": str}, ReadabilityConfig)
    Output: dict with text (unchanged), language, grade (float, may be
            negative; None if not assessed), target_grade, passed
            (grade <= target_grade; None if not assessed), status
            ("pass" | "flag" | "not_assessed"), textstat_version.
    Config: config.yaml target_grade, default 6.0, valid range 1-12.
    Failing drafts are flagged for staff review, never blocked or rewritten.

Written for
    Python 3.14, textstat 0.7.4 (pyphen 0.16.0, cmudict 1.0.32), PyYAML 6.0.3,
    pytest 8.3.3. See requirements.txt.
"""

from __future__ import annotations

import copy
import json
import math
import os
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
import textstat

from readability_node import ReadabilityConfig, check_readability, load_config

LANG = "en_US"

HERE = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("READABILITY_CONFIG", HERE / "config.yaml"))
TEMPLATES_PATH = Path(
    os.environ.get("READABILITY_TEMPLATES", HERE / "message_templates.json")
)

# ---------------------------------------------------------------------------
# Shared test inputs (synthetic only; no real patient data)
# ---------------------------------------------------------------------------

PLAIN = "Please check your blood pressure two times each day."
PLAIN_HAND_GRADE = 0.39 * 9 + 11.8 * 10 / 9 - 15.59  # = 1.03

HARD = (
    "Notwithstanding antihypertensive pharmacotherapeutic considerations, "
    "comprehensive cardiovascular reassessment is indicated."
)

# 13 words, 19 syllables: grade about 6.7-7.2, i.e. between 6 and 8.
MID = (
    "Please write your blood pressure numbers in the notebook "
    "after breakfast and dinner."
)

RUN_ON = (
    "Your nurse looked at the blood pressure numbers you sent this week and "
    "most of them were a little high so she would like you to keep taking "
    "your pill each morning and check again before bed and call the clinic "
    "if you feel dizzy or have a headache"
)

SPANISH = "Su presión arterial está bien esta semana."

RESULT_KEYS = {
    "text", "language", "grade", "target_grade", "passed", "status", "textstat_version",
}

SYNTHETIC_FIELDS = {
    "first_name": "Alex",
    "last_name": "Rivera",
    "patient_name": "Alex Rivera",
    "name": "Alex",
    "systolic": "128",
    "diastolic": "82",
    "average_bp": "128/82",
    "bp": "128/82",
    "date": "10/12/2026",
    "week_start": "10/05/2026",
    "week_end": "10/11/2026",
    "readings_count": "12",
    "clinic_name": "Main Street Clinic",
    "clinic_phone": "555-0100",
    "care_team": "your care team",
}


class _SyntheticFields(dict):
    """Fills unknown template placeholders with a neutral synthetic word."""

    def __missing__(self, key):
        return "Alex"


def _msg(text, language="en"):
    return {"text": text, "language": language}


def _template_params():
    """One pytest.param per template in message_templates.json.

    Accepts a list of strings, a list of {"id", "text"} objects, or a
    {name: text} mapping. Placeholders use str.format syntax ({first_name}).
    """
    if not TEMPLATES_PATH.exists():
        return [
            pytest.param(
                None,
                id="no-templates-file",
                marks=pytest.mark.skip(reason=f"{TEMPLATES_PATH.name} not found"),
            )
        ]
    data = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
    items = data.items() if isinstance(data, dict) else enumerate(data)
    params = []
    for key, entry in items:
        if isinstance(entry, dict):
            text, name = entry["text"], entry.get("id", key)
        else:
            text, name = entry, key
        params.append(pytest.param(text, id=str(name)))
    return params


@contextmanager
def use_language(lang: str):
    """Temporarily switch textstat's global language; always restore en_US."""
    textstat.set_lang(lang)
    try:
        yield
    finally:
        textstat.set_lang(LANG)


# ---------------------------------------------------------------------------
# Fixtures (session scope: dictionaries, config and baselines built once)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _pin_language():
    textstat.set_lang(LANG)
    yield
    textstat.set_lang(LANG)


@pytest.fixture(scope="session")
def default_config():
    return ReadabilityConfig()


@pytest.fixture(scope="session")
def project_config(default_config):
    return load_config(CONFIG_PATH) if CONFIG_PATH.exists() else default_config


@pytest.fixture(scope="session")
def plain_result(default_config):
    return check_readability(_msg(PLAIN), default_config)


@pytest.fixture(scope="session")
def mid_grade(default_config):
    return check_readability(_msg(MID), default_config)["grade"]


# ---------------------------------------------------------------------------
# Typical inputs
# ---------------------------------------------------------------------------


def test_returns_float_and_bool(default_config):
    result = check_readability(
        _msg("Your readings look good this week. Please keep checking twice a day."),
        default_config,
    )
    assert isinstance(result["grade"], float)
    assert isinstance(result["passed"], bool)
    assert set(result) == RESULT_KEYS


def test_known_value(plain_result):
    assert plain_result["grade"] == pytest.approx(PLAIN_HAND_GRADE, abs=0.5)


def test_known_value_components():
    # Diagnostic: if test_known_value fails, these show which count changed.
    assert textstat.syllable_count(PLAIN) == 10
    assert textstat.lexicon_count(PLAIN) == 9
    assert textstat.sentence_count(PLAIN) == 1


def test_harder_text_scores_higher(default_config, plain_result):
    hard = check_readability(_msg(HARD), default_config)
    assert hard["grade"] > plain_result["grade"]
    assert hard["passed"] is False


@pytest.mark.parametrize("template", _template_params())
def test_each_template_passes(project_config, template):
    draft = template.format_map(_SyntheticFields(SYNTHETIC_FIELDS))
    result = check_readability(_msg(draft), project_config)
    assert result["passed"] is True, (
        f"grade {result['grade']} > target {project_config.target_grade}: {draft!r}"
    )


def test_default_target_is_six(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("node: readability_check\n", encoding="utf-8")
    assert load_config(cfg).target_grade == pytest.approx(6.0)


def test_config_override_respected(tmp_path, default_config, mid_grade):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("target_grade: 8\n", encoding="utf-8")
    override = load_config(cfg)
    assert 6.0 < mid_grade <= 8.0, f"fixture draft out of range: {mid_grade}"
    assert check_readability(_msg(MID), override)["passed"] is True
    assert check_readability(_msg(MID), default_config)["passed"] is False


def test_failing_draft_flagged_not_blocked(default_config):
    message = _msg(HARD)
    before = copy.deepcopy(message)
    result = check_readability(message, default_config)
    assert result["passed"] is False
    assert result["status"] == "flag"
    assert math.isfinite(result["grade"])
    assert result["text"] == HARD          # forwarded unchanged for staff review
    assert message == before               # input not modified (O4)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_target_boundary_equal(mid_grade):
    result = check_readability(_msg(MID), ReadabilityConfig(target_grade=mid_grade))
    assert result["passed"] is True
    assert result["status"] == "pass"


def test_target_boundary_just_above(mid_grade):
    result = check_readability(
        _msg(MID), ReadabilityConfig(target_grade=mid_grade - 0.01)
    )
    assert result["passed"] is False
    assert result["status"] == "flag"


def test_empty_string(default_config):
    with pytest.raises(ValueError, match="empty draft"):
        check_readability(_msg(""), default_config)


def test_whitespace_only(default_config):
    with pytest.raises(ValueError, match="empty draft"):
        check_readability(_msg(" \n\t "), default_config)


def test_single_word(default_config):
    result = check_readability(_msg("Hello"), default_config)
    assert isinstance(result["grade"], float)
    assert math.isfinite(result["grade"])
    assert result["status"] in {"pass", "flag"}


def test_no_end_punctuation(default_config):
    assert textstat.sentence_count(RUN_ON) == 1
    result = check_readability(_msg(RUN_ON), default_config)
    assert math.isfinite(result["grade"])
    assert result["status"] == "flag"


def test_numbers_dates_units(default_config):
    result = check_readability(
        _msg("Your average was 142/91 mmHg on 10/12/2026."), default_config
    )
    assert math.isfinite(result["grade"])


def test_unicode_and_emoji(default_config):
    result = check_readability(
        _msg("Hi María 👋, your readings came in. Thank you!"), default_config
    )
    assert math.isfinite(result["grade"])


def test_very_long_input(default_config, plain_result):
    long_draft = " ".join([PLAIN] * 500)
    start = time.perf_counter()
    result = check_readability(_msg(long_draft), default_config)
    elapsed = time.perf_counter() - start
    assert result["grade"] == pytest.approx(plain_result["grade"], abs=0.1)
    assert elapsed < 1.0


def test_non_english_text(default_config):
    result = check_readability(_msg(SPANISH, language="es"), default_config)
    assert result["status"] == "not_assessed"
    assert result["grade"] is None
    assert result["passed"] is None


def test_deterministic(default_config):
    message = _msg("Your readings look good this week. Please keep checking twice a day.")
    first = check_readability(message, default_config)
    textstat.set_lang("es")  # another component changes the global language
    second = check_readability(message, default_config)
    assert first == second


def test_language_restored_after_test(default_config, plain_result):
    with pytest.raises(AssertionError):
        with use_language("es"):
            assert False, "deliberate failure inside a non-English block"
    # Suite isolation: the fixture put textstat back on en_US.
    assert textstat.flesch_kincaid_grade(PLAIN) == plain_result["grade"]
    # Node pinning (L4): even if something leaves textstat on another
    # language, the node scores in en_US and leaves en_US set afterward.
    textstat.set_lang("es")
    assert check_readability(_msg(PLAIN), default_config) == plain_result
    assert textstat.flesch_kincaid_grade(PLAIN) == plain_result["grade"]


# ---------------------------------------------------------------------------
# Invalid inputs
# ---------------------------------------------------------------------------


def test_none_input(default_config):
    with pytest.raises(TypeError):
        check_readability(_msg(None), default_config)


def test_int_input(default_config):
    with pytest.raises(TypeError):
        check_readability(_msg(123), default_config)


def test_float_input(default_config):
    with pytest.raises(TypeError):
        check_readability(_msg(4.5), default_config)


def test_list_input(default_config):
    with pytest.raises(TypeError):
        check_readability(_msg(["Please check your BP."]), default_config)


def test_bytes_input(default_config):
    with pytest.raises(TypeError):
        check_readability(_msg(b"Please check your BP."), default_config)


@pytest.mark.parametrize(
    "message",
    [{"text": PLAIN}, {"text": PLAIN, "language": ""}],
    ids=["missing", "empty"],
)
def test_missing_language_field(default_config, message):
    with pytest.raises(ValueError, match="missing language"):
        check_readability(message, default_config)


@pytest.mark.parametrize(
    "raw_value", ["null", "-1", "six"], ids=["none", "negative", "text"]
)
def test_bad_target_grade(tmp_path, raw_value):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"target_grade: {raw_value}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="target_grade"):
        load_config(cfg)
