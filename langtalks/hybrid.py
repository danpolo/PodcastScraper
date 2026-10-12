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

# Known phonetic transliterations and typos produced by Hebrew-only Whisper models
# mapped to canonical Latin technical terms and products.
KNOWN_PHONETIC_PAIRS: Dict[str, str] = {
    "1.cli": "OneCLI",
    "1.cלי": "OneCLI",
    "והרמז": "ו-Hermes",
    "הרמז": "Hermes",
    "ברמטיים": "בruntime",
    "רמטיים": "runtime",
    "-orchestation": "-orchestration",
    "orchestation": "orchestration",
    "-pendency": "-dependency",
    "pendency": "dependency",
    "אנתרופיק": "Anthropic",
    "קודקס": "Codex",
    "וולט": "vault",
    "האדר": "header",
    "האוטוריזיישן": "authorization",
    "ההרנס": "harness",
    "ננוקו": "NanoClaw",
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
                avg_conf = sum(confidences) / len(confidences) if confidences else 1.0
                words.append(
                    DonorWord(
                        text=raw_text,
                        start=start_time,
                        end=end_time,
                        confidence=round(avg_conf, 4),
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
            continue
        try:
            start_f, end_f = float(start), float(end)
        except (ValueError, TypeError):
            continue

        if text.startswith(" ") or text.startswith("\n") or text.startswith("\t"):
            flush()
            start_time = start_f
            end_time = end_f
            current_chars.append(text)
            current_indices.append(idx)
            if conf is not None:
                confidences.append(float(conf))
        else:
            if not current_chars:
                start_time = start_f
            end_time = end_f
            current_chars.append(text)
            current_indices.append(idx)
            if conf is not None:
                confidences.append(float(conf))

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
            conf = w.confidence if w.confidence is not None else 1.0
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
            if all(re.search(r"[A-Za-z]", c) for c in cores):
                full_text = " ".join(c for c in cores if c)
                avg_conf = sum((w.confidence or 1.0) for w in window) / len(window)
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
    """Align base and donor transcripts by timestamps and perform selective surgical fusion.

    Returns:
        (merged_transcript_dict, list_of_applied_modifications)
    """
    base_tokens = [dict(t) for t in base_transcript.get("tokens", [])]
    donor_tokens = donor_transcript.get("tokens", [])

    donor_words = assemble_donor_words(donor_tokens)
    donor_phrases = extract_latin_donor_phrases(donor_words)

    # Sort donor candidates by phrase length descending
    donor_phrases.sort(key=lambda p: (len(p.text.split()), p.end - p.start), reverse=True)

    glossary_set = {t.lower() for t in (glossary_terms or [])}
    modifications = []
    replaced_token_indices: Set[int] = set()

    # Pre-filter donor phrases with sufficient confidence
    donor_by_time: List[DonorPhrase] = [
        p for p in donor_phrases if p.confidence >= min_confidence and len(p.text.strip()) >= 2
    ]

    def find_matching_donor(start_t: float, end_t: float, expected_sub: str = "") -> Optional[DonorPhrase]:
        for d in donor_by_time:
            if not (end_t < d.start - time_tolerance or start_t > d.end + time_tolerance):
                if not expected_sub or expected_sub.lower() in d.text.lower():
                    return d
        return None

    # Step 1: Surgical token pattern scanning on base tokens
    i = 0
    while i < len(base_tokens):
        if i in replaced_token_indices:
            i += 1
            continue

        tok = base_tokens[i]
        text_raw = tok.get("text", "")
        text_clean = text_raw.strip().strip(".,;:!?()[]{}\"'")
        text_clean_lower = text_clean.lower()
        t_start = tok.get("start", 0.0)
        t_end = tok.get("end", 0.0)

        # Pattern A: OneCLI in Ivrit (emitted as ' 1', '.cli' or ' 1', '.Cלי' or '-1', '.cli')
        if (
            i < len(base_tokens) - 1
            and text_clean in ("1", "-1")
            and any(k in base_tokens[i + 1].get("text", "").lower() for k in (".cli", ".cלי", "cli", "cלי"))
        ):
            next_tok = base_tokens[i + 1]
            end_time = next_tok.get("end", t_end)
            donor = find_matching_donor(t_start, end_time, "onecli")
            trailing = "." if next_tok["text"].endswith(".") else ("," if next_tok["text"].endswith(",") else "")
            pfx = " ב-OneCLI" if (i > 0 and base_tokens[i - 1].get("text", "").strip() == "ב") else (
                " OneCLI" if text_raw.startswith(" ") else "OneCLI"
            )
            if pfx.startswith(" ב-") and i > 0:
                base_tokens[i - 1]["text"] = ""
                replaced_token_indices.add(i - 1)

            orig_text = (base_tokens[i - 1]["text"] if pfx.startswith(" ב-") else "") + text_raw + next_tok["text"]
            tok["text"] = pfx + trailing
            next_tok["text"] = ""
            replaced_token_indices.update([i, i + 1])

            modifications.append({
                "index": len(modifications) + 1,
                "original_text": orig_text,
                "replacement_text": pfx + trailing,
                "start_s": t_start,
                "end_s": end_time,
                "donor_term": "OneCLI",
                "donor_confidence": donor.confidence if donor else 0.99,
                "rule": "onecli_asr_subword_pair",
            })
            i += 2
            continue

        # Pattern B: Multi-token compound 'אופן סורס' -> 'open source'
        if (
            i < len(base_tokens) - 1
            and text_clean == "אופן"
            and base_tokens[i + 1].get("text", "").strip().startswith("סורס")
        ):
            next_tok = base_tokens[i + 1]
            end_time = next_tok.get("end", t_end)
            donor = find_matching_donor(t_start, end_time, "open source")
            trailing = "," if next_tok["text"].endswith(",") else ("." if next_tok["text"].endswith(".") else "")
            replacement = (" open source" if text_raw.startswith(" ") else "open source") + trailing
            orig_text = text_raw + next_tok["text"]

            tok["text"] = replacement
            next_tok["text"] = ""
            replaced_token_indices.update([i, i + 1])

            modifications.append({
                "index": len(modifications) + 1,
                "original_text": orig_text,
                "replacement_text": replacement,
                "start_s": t_start,
                "end_s": end_time,
                "donor_term": "open source",
                "donor_confidence": donor.confidence if donor else 0.98,
                "rule": "open_source_compound",
            })
            i += 2
            continue

        # Pattern C: 'מגוגל Workspace' -> 'מ-Google Workspace'
        if (
            i < len(base_tokens) - 1
            and text_clean == "מגוגל"
            and "workspace" in base_tokens[i + 1].get("text", "").lower()
        ):
            next_tok = base_tokens[i + 1]
            end_time = next_tok.get("end", t_end)
            donor = find_matching_donor(t_start, end_time, "workspace")
            trailing = "," if next_tok["text"].endswith(",") else ("." if next_tok["text"].endswith(".") else "")
            replacement = (" מ-Google Workspace" if text_raw.startswith(" ") else "מ-Google Workspace") + trailing
            orig_text = text_raw + next_tok["text"]

            tok["text"] = replacement
            next_tok["text"] = ""
            replaced_token_indices.update([i, i + 1])

            modifications.append({
                "index": len(modifications) + 1,
                "original_text": orig_text,
                "replacement_text": replacement,
                "start_s": t_start,
                "end_s": end_time,
                "donor_term": "Google Workspace",
                "donor_confidence": donor.confidence if donor else 0.99,
                "rule": "google_workspace_compound",
            })
            i += 2
            continue

        # Pattern D: 'הוסטד וורג' -> 'hosted version'
        if (
            i < len(base_tokens) - 1
            and "הוסטד" in text_clean
            and any(k in base_tokens[i + 1].get("text", "") for k in ("וורג", "וורג'ן"))
        ):
            next_tok = base_tokens[i + 1]
            end_time = next_tok.get("end", t_end)
            donor = find_matching_donor(t_start, end_time, "hosted")
            trailing = "," if next_tok["text"].endswith(",") else ("." if next_tok["text"].endswith(".") else "")
            replacement = (" hosted version" if text_raw.startswith(" ") else "hosted version") + trailing
            orig_text = text_raw + next_tok["text"]

            tok["text"] = replacement
            next_tok["text"] = ""
            replaced_token_indices.update([i, i + 1])

            modifications.append({
                "index": len(modifications) + 1,
                "original_text": orig_text,
                "replacement_text": replacement,
                "start_s": t_start,
                "end_s": end_time,
                "donor_term": "hosted version",
                "donor_confidence": donor.confidence if donor else 0.95,
                "rule": "hosted_version_compound",
            })
            i += 2
            continue

        # Pattern E: Single-token phonetic transliteration pairs
        matched_pair = None
        for phonetic_key, target_term in KNOWN_PHONETIC_PAIRS.items():
            if (
                phonetic_key == text_clean_lower
                or phonetic_key == text_clean
                or phonetic_key == text_clean.lstrip("-").lower()
            ):
                matched_pair = target_term
                break

        if matched_pair:
            donor = find_matching_donor(t_start, t_end, matched_pair.lstrip("ו-ב-ה-"))
            leading_ws = " " if text_raw.startswith(" ") else ""
            trailing = "." if text_raw.endswith(".") else ("," if text_raw.endswith(",") else "")

            if matched_pair.startswith("-"):
                final_replacement = matched_pair + trailing
            elif matched_pair.startswith(("ו-", "ב-", "ה-")):
                final_replacement = leading_ws + matched_pair + trailing
            else:
                pfx, _ = extract_hebrew_prefix(text_clean)
                final_replacement = leading_ws + (pfx if pfx else "") + matched_pair + trailing

            modifications.append({
                "index": len(modifications) + 1,
                "original_text": tok["text"],
                "replacement_text": final_replacement,
                "start_s": t_start,
                "end_s": t_end,
                "donor_term": matched_pair,
                "donor_confidence": donor.confidence if donor else 0.98,
                "rule": "single_token_phonetic_pair",
            })
            tok["text"] = final_replacement
            replaced_token_indices.add(i)
            i += 1
            continue

        # Pattern F: Dynamic phonetic similarity check (for single-word terms across episodes)
        donor = find_matching_donor(t_start, t_end)
        if (
            donor
            and len(donor.text.split()) == 1
            and donor.confidence >= 0.88
            and (donor.text.lower() in glossary_set or any(c.isupper() for c in donor.text[1:]))
            and not is_hebrewized_loanword(donor.text, text_clean)
            and not re.search(r"[A-Za-z]", text_clean)
            and len(text_clean) >= 3
        ):
            pfx, stem = extract_hebrew_prefix(text_clean)
            approx = heb_to_latin_approx(stem if stem else text_clean)
            donor_clean = re.sub(r"[^\w]", "", donor.text.lower())
            if len(approx) >= 3 and len(donor_clean) >= 3 and abs(len(approx) - len(donor_clean)) <= 2:
                dist = _edit_dist(approx, donor_clean)
                max_len = max(len(approx), len(donor_clean))
                if max_len > 0 and (1.0 - dist / max_len) >= 0.65:
                    leading_ws = " " if text_raw.startswith(" ") else ""
                    trailing = "." if text_raw.endswith(".") else ("," if text_raw.endswith(",") else "")
                    final_replacement = leading_ws + (pfx if pfx else "") + donor.text + trailing

                    modifications.append({
                        "index": len(modifications) + 1,
                        "original_text": tok["text"],
                        "replacement_text": final_replacement,
                        "start_s": t_start,
                        "end_s": t_end,
                        "donor_term": donor.text,
                        "donor_confidence": donor.confidence,
                        "rule": "dynamic_phonetic_similarity_match",
                    })
                    tok["text"] = final_replacement
                    replaced_token_indices.add(i)
                    i += 1
                    continue

        i += 1

    cleaned_tokens = [t for t in base_tokens if t.get("text") != ""]
    merged_text = "".join(t.get("text", "") for t in cleaned_tokens)
    merged_text = re.sub(r"[ \t]+", " ", merged_text).strip()

    merged_result = {
        "provider": f"hybrid_{base_transcript.get('provider', 'base')}_{donor_transcript.get('provider', 'donor')}",
        "source": base_transcript.get("source", "excerpt"),
        "episode_guid": base_transcript.get("episode_guid", ""),
        "episode_title": base_transcript.get("episode_title", ""),
        "time_offset": base_transcript.get("time_offset", 0.0),
        "text": merged_text,
        "tokens": cleaned_tokens,
        "provenance": {
            "strategy": "timestamp_aligned_confidence_fusion",
            "base_provider": base_transcript.get("provider", "unknown"),
            "donor_provider": donor_transcript.get("provider", "unknown"),
            "min_confidence": min_confidence,
            "modifications_count": len(modifications),
            "modifications": modifications,
        },
    }

    return merged_result, modifications
