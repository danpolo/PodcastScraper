"""Hybrid Hebrew-English ASR alignment and fusion engine.

Combines the superior Hebrew syntax and character accuracy of a Hebrew-specialized
base model (such as ivrit.ai Whisper) with the superior English technical-term recall
and code-switching recognition of a donor model (such as Soniox or Groq).

Core invariants:
1. Preserve Hebrew grammar, inflections, and Hebrewized loanwords (יוזרים, קונטיינרים,
   אייג'נטים) according to HEBREW_ENGLISH_POLICY.md. Never force Latin script on
   words naturally spoken in Hebrew.
2. Preserve Hebrew grammatical prefixes (ו-, ב-, ה-, ל-, מ-, כ-) when inserting Latin terms.
3. Surgical token replacement: only replace the exact matching token(s), never collapsing
   surrounding Hebrew words in the alignment window.
4. Timestamp-based alignment with confidence gating and ambiguity fallbacks.
5. Record exhaustive provenance for every modification.
"""

import json
import logging
import math
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Hebrew grammatical prefixes that can attach to Latin loanwords/products
HEBREW_PREFIXES = ("ו-", "ב-", "ה-", "ל-", "מ-", "כ-", "ו", "ב", "ה", "ל", "מ", "כ")

# Hebrewized loanwords that must remain in Hebrew script when spoken as Hebrew loanwords.
# These must NEVER be romanized by the hybrid engine.
HEBREWIZED_LOANWORDS: Dict[str, Set[str]] = {
    "users": {"יוזרים", "היוזרים", "ליוזרים", "ביוזרים", "מיוזרים"},
    "user": {"יוזר", "היוזר", "ליוזר", "ביוזר"},
    "agents": {"אייג'נטים", "אג'נטים", "איג'נטים", "האייג'נטים", "האג'נטים", "לאייג'נטים", "באייג'נטים"},
    "agent": {"אייג'נט", "אג'נט", "איג'נט", "האייג'נט", "האג'נט", "לאג'נט", "באג'נט"},
    "containers": {"קונטיינרים", "הקונטיינרים", "בקונטיינרים", "לקונטיינרים"},
    "container": {"קונטיינר", "הקונטיינר", "בקונטיינר", "לקונטיינר"},
    "multi-tenant": {"מולטי-טננט", "מולטי טננט", "מולטיטננט"},
    "multitenant": {"מולטי-טננט", "מולטי טננט", "מולטיטננט"},
    "processes": {"פרוססים", "הפרוססים", "בפרוססים", "פרוסססים"},
    "process": {"פרוסס", "הפרוסס", "בפרוסס"},
    "components": {"קומפוננטות", "הקומפוננטות"},
    "debug": {"לדבג", "דיבגתי", "מדבג"},
}

HEBREW_TO_LATIN_MAP = {
    "א": "a", "ב": "b", "ג": "g", "ד": "d", "ה": "h", "ו": "o", "ז": "z",
    "ח": "h", "ט": "t", "י": "i", "כ": "k", "ך": "k", "ל": "l", "מ": "m",
    "ם": "m", "נ": "n", "ן": "n", "ס": "s", "ע": "", "פ": "p", "ף": "p",
    "צ": "ts", "ץ": "ts", "ק": "k", "ר": "r", "ש": "s", "ת": "t",
}


def heb_to_latin_approx(text: str) -> str:
    """Rough phonetic conversion of Hebrew consonants to Latin for similarity checking."""
    return "".join(HEBREW_TO_LATIN_MAP.get(c, c) for c in text.lower())


def _edit_dist(a: str, b: str) -> int:
    """Levenshtein distance, single-row DP."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = curr
    return prev[-1]


@dataclass
class DonorWord:
    text: str
    start: float
    end: float
    confidence: Optional[float]
    token_indices: List[int] = field(default_factory=list)


@dataclass
class DonorPhrase:
    text: str
    start: float
    end: float
    confidence: float
    words: List[DonorWord] = field(default_factory=list)


def assemble_donor_words(tokens: List[dict]) -> List[DonorWord]:
    """Assemble sub-word tokens (such as Soniox character/subword pieces) into words.

    Soniox uses leading spaces (' One', 'C', 'L', 'I') to mark word starts.
    Subsequent characters without leading spaces belong to the preceding word.
    """
    words: List[DonorWord] = []
    current_chars: List[str] = []
    current_indices: List[int] = []
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    confidences: List[float] = []

    def flush():
        nonlocal current_chars, current_indices, start_time, end_time, confidences
        if current_chars:
            raw_text = "".join(current_chars)
            clean_text = raw_text.strip()
            if clean_text and start_time is not None and end_time is not None:
                avg_conf = (sum(confidences) / len(confidences) if len(confidences) == len(current_indices) else None)
                words.append(
                    DonorWord(
                        text=raw_text,
                        start=start_time,
                        end=end_time,
                        confidence=round(avg_conf, 4) if avg_conf is not None else None,
                        token_indices=list(current_indices),
                    )
                )
        current_chars = []
        current_indices = []
        start_time = None
        end_time = None
        confidences = []

    for idx, tok in enumerate(tokens or []):
        text = tok.get("text", "")
        start = tok.get("start")
        end = tok.get("end")
        conf = tok.get("confidence")

        if start is None or end is None:
            flush()
            continue
        try:
            start_f, end_f = float(start), float(end)
        except (ValueError, TypeError):
            flush()
            continue
        if not math.isfinite(start_f) or not math.isfinite(end_f) or start_f < 0 or end_f < start_f:
            flush()
            continue
        if not text:
            flush()
            continue
        if end_time is not None and (start_f - end_time > 0.70 or start_f < end_time - 0.50):
            flush()
        if conf is not None:
            try:
                conf_val = float(conf)
                if not math.isfinite(conf_val) or not 0 <= conf_val <= 1:
                    conf_val = None
            except (ValueError, TypeError):
                conf_val = None
        else:
            conf_val = None

        if text.startswith(" ") or text.startswith("\n") or text.startswith("\t"):
            flush()
            start_time = start_f
            end_time = end_f
            current_chars.append(text)
            current_indices.append(idx)
            if conf_val is not None:
                confidences.append(conf_val)
        else:
            if not current_chars:
                start_time = start_f
            end_time = end_f
            current_chars.append(text)
            current_indices.append(idx)
            if conf_val is not None:
                confidences.append(conf_val)

    flush()
    return words


def extract_latin_donor_phrases(
    words: List[DonorWord], max_phrase_words: int = 4
) -> List[DonorPhrase]:
    """Find multi-word or single-word Latin phrases in donor speech."""
    phrases: List[DonorPhrase] = []
    n_words = len(words)

    # Single-word Latin candidates
    for i, w in enumerate(words):
        stripped = w.text.strip(".,;:!?()[]{}\"' ")
        core = stripped
        for pfx in ("ו-", "ב-", "ה-", "ל-", "מ-", "כ-", "-"):
            if core.startswith(pfx):
                core = core[len(pfx) :]
                break

        if re.search(r"[A-Za-z]", core):
            conf = w.confidence if w.confidence is not None else 0.0
            phrases.append(
                DonorPhrase(
                    text=core,
                    start=w.start,
                    end=w.end,
                    confidence=conf,
                    words=[w],
                )
            )

    # Multi-word Latin sequences (e.g. "Google Workspace", "code review", "hosted version")
    for length in range(2, max_phrase_words + 1):
        for i in range(n_words - length + 1):
            window = words[i : i + length]
            cores = [w.text.strip(".,;:!?()[]{}\"' ") for w in window]
            if (all(re.search(r"[A-Za-z]", c) for c in cores)
                    and all(window[k + 1].start - window[k].end <= 0.70
                            and not window[k].text.rstrip().endswith((".", "!", "?"))
                            for k in range(len(window) - 1))):
                full_text = " ".join(c for c in cores if c)
                avg_conf = min((w.confidence if w.confidence is not None else 0.0) for w in window)
                phrases.append(
                    DonorPhrase(
                        text=full_text,
                        start=window[0].start,
                        end=window[-1].end,
                        confidence=round(avg_conf, 4),
                        words=list(window),
                    )
                )

    return phrases


def is_hebrewized_loanword(donor_term: str, base_context: str) -> bool:
    """Check if donor term corresponds to a spoken Hebrewized loanword in base text.

    If speaker said 'יוזרים' and donor has 'users', or speaker said 'קונטיינרים'
    and donor has 'containers', we MUST NOT replace it with English.
    """
    donor_norm = donor_term.strip().lower()
    base_norm = re.sub(r"[^\w֐-׿]", " ", base_context).strip()
    base_words = set(base_norm.split())

    for eng_key, hebrew_forms in HEBREWIZED_LOANWORDS.items():
        if donor_norm == eng_key or donor_norm.startswith(eng_key):
            if any(h in base_words for h in hebrew_forms) or any(h in base_context for h in hebrew_forms):
                return True

    return False


def extract_hebrew_prefix(text: str) -> Tuple[str, str]:
    """Separate Hebrew grammatical prefix from stem, e.g. 'ו-Hermes' -> ('ו-', 'Hermes')."""
    text_clean = text.strip()
    for pfx in ("ו-", "ב-", "ה-", "ל-", "מ-", "כ-"):
        if text_clean.startswith(pfx):
            return pfx, text_clean[len(pfx) :]
    for pfx in ("ו", "ב", "ה", "ל", "מ", "כ"):
        if text_clean.startswith(pfx) and len(text_clean) > 1 and text_clean[1] == "-":
            return text_clean[:2], text_clean[2:]
        if text_clean.startswith(pfx) and len(text_clean) > 2 and text_clean[1].isascii():
            return pfx + "-", text_clean[1:]
    return "", text_clean


def align_and_merge(
    base_transcript: dict,
    donor_transcript: dict,
    glossary_terms: Optional[List[str]] = None,
    min_confidence: float = 0.70,
    time_tolerance: float = 1.5,
) -> Tuple[dict, List[dict]]:
    """Conservative donor-grounded fusion; original inputs remain untouched.

    See fusion_safe.py for the v2 alignment implementation. The public API is
    preserved for existing callers and benchmarks.
    """
    from .fusion_safe import align_and_merge_v2

    return align_and_merge_v2(
        base_transcript, donor_transcript, glossary_terms,
        min_confidence=min_confidence, time_tolerance=time_tolerance,
    )
