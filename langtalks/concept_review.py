"""Semantic-first assistant pre-review for LangTalks #71.

Never marks reference labels verified. Proposed compounds are made from
temporally adjacent ASR word candidates, with traceable source timestamps.
A phrase can be one concept regardless of the underlying ASR tokenization.
"""

import json
from copy import deepcopy
from pathlib import Path


# A small, explicitly editorial vocabulary for this sample, NOT a general
# classifier. The user-supplied audio transcript provides contextual hints;
# timestamps remain the ASR engines' estimates.
COMPOUNDS = [
    ("supply chain security", "supply chain security", "technical_concept",
     [("supply", "supply-chain"), ("chain",), ("security",)], 1.5),
    ("code review", "code review", "technical_practice",
     [("code",), ("review",)], 1.1),
    ("security best practices", "security best practices", "technical_practice",
     [("security",), ("practices",)], 1.8),
    ("human-in-the-loop approval", "human-in-the-loop approval", "technical_practice",
     [("human",), ("loop",), ("approval",)], 1.4),
    ("managed hosted version", "managed hosting", "descriptive_concept",
     [("managed",), ("hosted",), ("version",)], 2.5),
    ("mounted directory", "mounted directory", "technical_concept",
     [("mounted",), ("directory",)], 2.0),
    ("file system", "file system", "technical_concept",
     [("file",), ("system",)], 1.2),
    ("third-party tools", "third-party tools", "technical_concept",
     [("third-party", "third"), ("party",), ("tools",)], 1.2),
    ("refresh token", "refresh token", "technical_concept",
     [("refresh",), ("token",)], 1.3),
    ("standalone", "standalone", "technical_concept",
     [("stand",), ("alone",)], 1.0),
]
# Deliberately keep a short queue: basic English function words and isolated
# adjectives are not independently meaningful concepts for retrieval.
SINGLES = {
    "nanoclaw": ("NanoClaw", "product"),
    "openclaw": ("OpenClaw", "product"),
    "composio": ("Composio", "product"),
    "cli": ("OneCLI", "product"),  # tentative: may actually mean generic CLI
    "auth": ("OAuth", "protocol"),  # tentative phonetic capture
    "api": ("API", "protocol"),
    "gmail": ("Gmail", "product"),
    "calendar": ("Google Calendar", "product"),
    "drive": ("Google Drive", "product"),
    "gateway": ("credential gateway", "technical_concept"),
    "credentials": ("credentials", "technical_concept"),
    "orchestation": ("orchestration", "technical_concept"),
    "agent": ("AI agent", "technical_concept"),
}
HIGH_REVIEW = {
    "cli": "Possible OneCLI reference. Verify whether the speaker said OneCLI or generic CLI.",
    "auth": "Possible OAuth; transcription may confuse 'auth' with OAuth.",
    "orchestation": "Likely 'orchestration'; check the audio rather than assuming.",
    "agent": "Generic term retained as context: do not verify every occurrence unless useful.",
}


def _norm(v):
    return "".join(c for c in str(v or "").casefold() if c.isalnum())


def _get(groups, alternatives):
    aliases = {_norm(x) for x in alternatives}
    return [g for g in groups if _norm(g.get("term")) in aliases]


def _times(group):
    return sorted(group.get("occurrences") or [], key=lambda o: o["start"])


def _combine_candidate(groups, parts, max_gap):
    """Return grouped time ranges for ordered adjacent terms.

    Source candidates can overlap (e.g. 'third-party' contains 'party').
    Accept overlap but reject phrases spanning unrelated discussion.
    """
    options = [_get(groups, alt) for alt in parts]
    if any(not g for g in options):
        return []
    matches = []
    for g in options[0]:
        for first in _times(g):
            selected = [(g, first)]
            cursor = float(first["end"])
            for alternatives in options[1:]:
                next_hit = None
                for candidate in alternatives:
                    for item in _times(candidate):
                        begin = float(item["start"])
                        if first is item:
                            continue
                        if begin < float(first["start"]) - 0.1:
                            continue
                        if begin > cursor + max_gap:
                            continue
                        if begin < cursor - 1.0:
                            continue
                        cost = abs(begin - cursor)
                        if next_hit is None or cost < next_hit[0]:
                            next_hit = (cost, candidate, item)
                if next_hit is None:
                    break
                selected.append((next_hit[1], next_hit[2]))
                cursor = max(cursor, float(next_hit[2]["end"]))
            if len(selected) != len(parts):
                continue
            begin = float(first["start"])
            if any(abs(x["start"] - begin) < 1.2 for x in matches):
                continue
            sources = sorted({
                src for _, piece in selected for src in piece.get("sources", [])
            })
            matches.append({
                "start": round(begin, 2), "end": round(cursor, 2),
                "text": " ".join(str(piece.get("text") or group["term"])
                                 for group, piece in selected),
                "sources": sources, "alignment": "editorial_compound_estimate",
                "component_candidates": [
                    {"term": group["term"], "start": piece["start"]}
                    for group, piece in selected
                ],
            })
    return sorted(matches, key=lambda o: o["start"])


def build(initial):
    """Create prioritized concept queue while retaining excluded ASR evidence."""
    source = deepcopy(initial)
    groups = source.get("suggested_terms") or []
    relevant = []
    consumed = set()
    for phrase, canonical, kind, parts, gap in COMPOUNDS:
        occurrences = _combine_candidate(groups, parts, gap)
        if not occurrences:
            continue
        for item in occurrences:
            for component in item["component_candidates"]:
                consumed.add((_norm(component["term"]), round(component["start"], 1)))
        relevant.append({
            "term": phrase, "surface": phrase, "canonical": canonical,
            "kind": kind, "review_status": "needs_review",
            "editorial_reason": "Compound technical phrase from adjacent ASR tokens; check exact wording.",
            "seen_in": sorted({m for o in occurrences for m in o["sources"]}),
            "occurrences": occurrences,
        })
    for group in groups:
        name = _norm(group.get("term"))
        if name not in SINGLES:
            continue
        canonical, kind = SINGLES[name]
        occurrences = [
            o for o in group.get("occurrences", [])
            if (_norm(group["term"]), round(float(o["start"]), 1)) not in consumed
        ]
        if not occurrences:
            continue
        relevant.append({
            **group,
            "canonical": canonical, "surface": group["term"],
            "kind": kind, "review_status": "needs_review",
            "editorial_reason": HIGH_REVIEW.get(name, "Relevant technical named entity or concept."),
            "occurrences": occurrences,
        })
    relevant.sort(key=lambda x: min(o["start"] for o in x["occurrences"]))
    retained = {id(x) for x in relevant}  # Prevent accidental mutation below.
    del retained
    # No original source candidates are deleted; some contain useful evidence.
    excluded = [{
        "term": g.get("term"), "occurrences": len(g.get("occurrences", [])),
        "reason": "Generic word, constituent of a phrase, or unclear independent technical relevance",
    } for g in groups if _norm(g.get("term")) not in SINGLES
                   and not any(_norm(g.get("term")) == _norm(x["term"]) for x in relevant)]
    return {
        "episode_guid": source.get("episode_guid"),
        "episode_title": source.get("episode_title"),
        "window": source.get("window"),
        "audio_url": source.get("audio_url"),
        "draft_only": True,
        "review_status": "needs_review",
        "assistant_editorial_pass": {
            "status": "proposed_not_audio_verified",
            "notes": (
                "Terms merged into semantic concepts. Surface language in a compound "
                "is inferred from the speaker context and ASR pieces and MUST be "
                "checked against the recording; model disagreement isn't proof."
            ),
            "missing_from_asr_to_check": [
                "OneCLI", "OAuth", "container", "multi-tenant",
                "human-in-the-loop approvals", "Anthropic",
            ],
        },
        "provider_outputs_considered": source.get("provider_outputs_considered", []),
        "source_models": source.get("source_models", []),
        "suggested_terms": relevant,
        "excluded_candidates": excluded,
    }


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("proposal", type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)
    output = build(json.loads(args.proposal.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(f"{len(output['suggested_terms'])} concept groups requiring review")


if __name__ == "__main__":
    main()
