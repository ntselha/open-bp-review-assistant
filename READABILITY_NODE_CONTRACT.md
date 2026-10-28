# Readability Check Node: Interface Contract

**Project:** Open BP Review Assistant
**Version:** 0.1 (draft)
**Protocol used:** Flesch-Kincaid Grade Level (Kincaid et al., 1975), computed with `textstat.flesch_kincaid_grade` (textstat 0.7.4, language `en_US`)

This contract defines what the readability node promises beyond what textstat documents. Tests for empty input, invalid types, language handling and config validation cite this document as their source.

---

## 1. Interface

```python
from readability_node import load_config, check_readability

config = load_config("config.yaml")          # -> ReadabilityConfig
result = check_readability(message, config)  # -> dict (see §4)
```

`message` is a dict with at least:

| Key | Type | Meaning |
|---|---|---|
| `text` | `str` | The draft patient message |
| `language` | `str` | The patient's preferred language from their record (e.g. `"en"`, `"en-US"`, `"es"`) |

---

## 2. Input rules (checked in this order)

| # | Condition | Behavior |
|---|---|---|
| C1 | `message` is not a dict | Raise `TypeError` |
| C2 | `message["text"]` is missing or not a `str` (includes `None`, `int`, `float`, `list`, `bytes`) | Raise `TypeError` |
| C3 | `message["language"]` is missing, `None`, or an empty/whitespace string | Raise `ValueError("missing language")` |
| C4 | `message["language"]` is not a `str` | Raise `TypeError` |
| C5 | `text` is empty or whitespace-only | Raise `ValueError("empty draft")` |

When any rule raises, no grade or pass flag is returned.

---

## 3. Language handling

| # | Rule |
|---|---|
| L1 | The language's primary subtag is compared case-insensitively. `"en"`, `"EN"`, `"en-US"` and `"en_GB"` all count as English. |
| L2 | **English:** the draft is scored (§4). |
| L3 | **Any other language:** the draft is not scored. `status = "not_assessed"`, `grade = None`, `passed = None`. FKGL is valid for English only. |
| L4 | The node sets textstat's language to `en_US` before scoring and leaves it set to `en_US` afterward, even if an error occurs. |

The language comes from the message's `language` field only. The node does not guess the language from the text.

---

## 4. Output

`check_readability` returns a dict with exactly these keys:

| Key | Type | Value |
|---|---|---|
| `text` | `str` | The original draft, unchanged |
| `language` | `str` | As supplied |
| `grade` | `float` or `None` | `textstat.flesch_kincaid_grade(text)` (rounded to 1 decimal by textstat); may be negative; `None` if not assessed |
| `target_grade` | `float` | From config |
| `passed` | `bool` or `None` | `grade <= target_grade`; `None` if not assessed |
| `status` | `str` | `"pass"`, `"flag"` or `"not_assessed"` |
| `textstat_version` | `str` | Installed textstat version, for the audit log |

| # | Rule |
|---|---|
| O1 | Pass rule: `passed = grade <= target_grade`. A grade equal to the target passes. |
| O2 | A failing draft gets `status = "flag"` and is **forwarded for staff review**. The node never blocks, drops or rewrites a draft. |
| O3 | Deterministic: the same `text`, `language` and config with the same pinned package versions always give the same result. |
| O4 | The node does not change the input `message`. |

---

## 5. Configuration (`config.yaml`)

```yaml
target_grade: 6.0
```

| # | Rule |
|---|---|
| G1 | `load_config(path)` reads the YAML file once. |
| G2 | If `target_grade` is absent, it defaults to `6.0`. |
| G3 | `target_grade` must be an `int` or `float` (not `bool`), finite, and between **1 and 12 inclusive**. Anything else (`null`, `-1`, `"six"`, `true`, `.inf`, `20`) raises `ValueError` at load time, before any draft is scored. |
| G4 | A missing config file raises `FileNotFoundError`. |

The 1–12 range is a project decision. Patient materials are usually aimed at grade 6–8, and 12 is the top of the K–12 scale. Change it here if your program needs a different range.

---

## 6. Out of scope

- Reading levels for non-English messages
- Checking accuracy, tone or medical content
- Rewriting drafts to lower their grade
- Readability formulas other than FKGL

---

## 7. Traceability: test plan rows → contract clauses

| Test | Clause |
|---|---|
| test_returns_float_and_bool | §4 `grade`, `passed` types |
| test_known_value, test_known_value_components, test_harder_text_scores_higher, test_very_long_input | Protocol (Kincaid et al., 1975; textstat) |
| test_each_template_passes | O1 + workflow requirement |
| test_default_target_is_six | G2 |
| test_config_override_respected | G1, O1 |
| test_failing_draft_flagged_not_blocked | O2, O4 |
| test_target_boundary_equal, test_target_boundary_just_above | O1 |
| test_empty_string, test_whitespace_only | C5 |
| test_single_word, test_no_end_punctuation, test_numbers_dates_units, test_unicode_and_emoji | L2, §4 (scored, finite float) |
| test_non_english_text | L3 |
| test_deterministic | O3 |
| test_language_restored_after_test | L4 |
| test_none_input, test_int_input, test_float_input, test_list_input, test_bytes_input | C2 |
| test_missing_language_field | C3 |
| test_bad_target_grade | G3 |
