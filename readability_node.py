"""Readability check node for the Open BP Review Assistant.

Implements READABILITY_NODE_CONTRACT.md v0.1. Scores English patient-message
drafts with the Flesch-Kincaid Grade Level (Kincaid et al., 1975) via
textstat, flags drafts above the configured target for staff review, and
never blocks or rewrites a draft.

Usage:
    config = load_config("config.yaml")
    result = check_readability({"text": draft, "language": "en"}, config)
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import textstat
import yaml

DEFAULT_TARGET_GRADE = 6.0          # G2
MIN_TARGET_GRADE = 1.0              # G3
MAX_TARGET_GRADE = 12.0             # G3
_TEXTSTAT_LANG = "en_US"            # L4

try:
    _TEXTSTAT_VERSION = version("textstat")
except PackageNotFoundError:  # pragma: no cover - only outside a normal install
    _TEXTSTAT_VERSION = "unknown"


# ---------------------------------------------------------------------------
# Configuration (contract §5)
# ---------------------------------------------------------------------------


def validate_target_grade(value: object) -> float:
    """G3: a finite int/float (not bool) between 1 and 12 inclusive."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"target_grade must be a number, got {value!r}")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"target_grade must be finite, got {value!r}")
    if not MIN_TARGET_GRADE <= value <= MAX_TARGET_GRADE:
        raise ValueError(
            f"target_grade must be between {MIN_TARGET_GRADE:g} and "
            f"{MAX_TARGET_GRADE:g}, got {value:g}"
        )
    return value


@dataclass(frozen=True)
class ReadabilityConfig:
    target_grade: float = DEFAULT_TARGET_GRADE

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_grade", validate_target_grade(self.target_grade))


def load_config(path: str | Path) -> ReadabilityConfig:
    """G1-G4: read config.yaml once and validate it before any scoring."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")      # G4
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("config.yaml must contain a mapping of settings")
    if "target_grade" not in data:
        return ReadabilityConfig()                                        # G2
    return ReadabilityConfig(target_grade=data["target_grade"])          # G3


# ---------------------------------------------------------------------------
# Scoring (contract §2-§4)
# ---------------------------------------------------------------------------


def _is_english(language: str) -> bool:
    """L1: compare the primary subtag case-insensitively (en, EN, en-US, en_GB)."""
    primary = re.split(r"[-_]", language.strip(), maxsplit=1)[0]
    return primary.lower() == "en"


def check_readability(message: dict, config: ReadabilityConfig | None = None) -> dict:
    """Score one draft message. See READABILITY_NODE_CONTRACT.md."""
    if config is None:
        config = ReadabilityConfig()

    # §2 input rules, in contract order
    if not isinstance(message, dict):
        raise TypeError("message must be a dict")                         # C1
    text = message.get("text")
    if not isinstance(text, str):
        raise TypeError(f"message['text'] must be str, got {type(text).__name__}")  # C2
    language = message.get("language")
    if language is None or (isinstance(language, str) and not language.strip()):
        raise ValueError("missing language")                              # C3
    if not isinstance(language, str):
        raise TypeError(
            f"message['language'] must be str, got {type(language).__name__}"
        )                                                                 # C4
    if not text.strip():
        raise ValueError("empty draft")                                   # C5

    result = {
        "text": text,                                                     # O2, O4
        "language": language,
        "grade": None,
        "target_grade": config.target_grade,
        "passed": None,
        "status": "not_assessed",
        "textstat_version": _TEXTSTAT_VERSION,
    }

    if not _is_english(language):
        return result                                                     # L3

    textstat.set_lang(_TEXTSTAT_LANG)                                     # L4
    grade = float(textstat.flesch_kincaid_grade(text))                    # L2
    passed = grade <= config.target_grade                                 # O1
    result.update(grade=grade, passed=passed, status="pass" if passed else "flag")
    return result
