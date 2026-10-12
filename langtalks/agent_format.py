"""Agent-ready bilingual podcast transcript contract (version 1).

Faithful source text, timed turns and conceptual annotations are deliberately
separate. No inferred concept can silently rewrite words spoken in the audio.

Use:
    python -m langtalks.agent_format input_asr.json --output-dir out/agent-ready
    python -m langtalks.agent_format input_asr.json --proposal proposals/episode.json

Audio and provider input may contain imperfect ASR text: auto-generated output
is ALWAYS a draft. Approval requires human checking of the actual recording.
"""

import argparse
import json
import re
from pathlib import Path

SCHEMA_VERSION = "1.0"
KINDS = {
    "product", "organization", "protocol", "tool", "technical_concept",
    "technical_practice", "descriptive_concept", "other",
}
STATUSES = {"suggested", "needs_review", "verified", "rejected"}
_WS = re.compile(r"\s+")
_MARKDOWN = re.compile(r"([\\\`*_{}\[\]<>|])")


def clock(seconds):
    value = int(round(float(seconds)))
    return f"{value // 3600:02d}:{(value // 60) % 60:02d}:{value % 60:02d}"


def text_join(parts):
    """Preserve ASR word spacing while repairing only accidental collisions."""
    result = ""
    for text in parts:
        value = str(text or "")
        if not value:
            continue
        if (result and not result[-1].isspace() and not value[0].isspace()
                and (result[-1].isascii() and result[-1].isalnum())
                and (value[0].isascii() and value[0].isalnum())):
            result += " "
        result += value
    return result.strip()


def _finite_seconds(v, field):
    try:
        n = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number")
    if not (0 <= n < float("inf")):
        raise ValueError(f"{field} must be finite and nonnegative")
    return round(n, 2)


def _sort_tokens(tokens):
    output = []
    for token in tokens:
        if token.get("start") is None or token.get("end") is None:
            continue
        start = _finite_seconds(token["start"], "token.start")
        end = _finite_seconds(token["end"], "token.end")
        if end < start:
            raise ValueError("token.end precedes token.start")
        output.append({**token, "start": start, "end": end})
    return sorted(output, key=lambda t: t["start"])


def _to_turns(asr, start, end):
    raw_tokens = _sort_tokens(asr.get("tokens") or [])
    if not raw_tokens:
        return [{
            "id": "turn-0001", "start_s": start, "end_s": end,
            "speaker_id": None, "text": asr.get("text", "").strip(),
            "timestamp_precision": "window_only", "review_status": "suggested",
        }]
    chunks, chunk = [], []
    for t in raw_tokens:
        changed_speaker = chunk and t.get("speaker") is not None and (
            t.get("speaker") != chunk[-1].get("speaker"))
        long_gap = chunk and t["start"] - chunk[-1]["end"] > 2.1
        long_turn = chunk and t["end"] - chunk[0]["start"] > 75
        if chunk and (changed_speaker or long_gap or long_turn):
            chunks.append(chunk)
            chunk = []
        chunk.append(t)
    if chunk:
        chunks.append(chunk)
    return [{
        "id": f"turn-{i:04d}",
        "start_s": part[0]["start"], "end_s": max(t["end"] for t in part),
        "speaker_id": part[0].get("speaker"),
        "text": text_join(t.get("text", "") for t in part),
        "timestamp_precision": "asr_word_or_segment",
        "review_status": "suggested",
    } for i, part in enumerate(chunks, 1)]


def _turn_for_time(turns, at):
    exact = next((t for t in turns
                  if t["start_s"] - 0.4 <= at <= t["end_s"] + 0.4), None)
    return exact["id"] if exact else None


def from_asr(asr, proposal=None, *, source_urls=None):
    """Build an unverified draft; provider is provenance, never authority.

    Transcript text is copied from ASR intact except for safe word joining.
    A concept surface may describe a proposed phrase without modifying text.
    """
    if not isinstance(asr.get("text"), str):
        raise ValueError("Missing ASR text")
    start = _finite_seconds(asr.get("time_offset", 0), "time_offset")
    tokens = _sort_tokens(asr.get("tokens") or [])
    if tokens:
        end = max(t["end"] for t in tokens)
        if end <= start:
            end = start + 1
    elif proposal and proposal.get("window", {}).get("end") is not None:
        end = _finite_seconds(proposal["window"]["end"], "window.end")
    else:
        end = start
    turns = _to_turns(asr, start, end)
    guid = str(asr.get("episode_guid") or (proposal or {}).get("episode_guid") or "")
    urls = dict(source_urls or {})
    if proposal and proposal.get("audio_url"):
        urls.setdefault("original_audio", proposal["audio_url"])
    episode = {
        "id": guid,
        "title": asr.get("episode_title") or (proposal or {}).get("episode_title") or "",
        "languages": ["he", "en"], "source_urls": urls,
    }
    mentions = []
    for group in (proposal or {}).get("suggested_terms", []):
        for occurrence in group.get("occurrences") or []:
            t = _finite_seconds(occurrence["start"], "occurrence.start")
            last = _finite_seconds(occurrence.get("end", t), "occurrence.end")
            if last < t:
                continue
            index = len(mentions) + 1
            mentions.append({
                "id": f"mention-{index:04d}",
                "turn_id": _turn_for_time(turns, t),
                "start_s": t, "end_s": last,
                "surface": occurrence.get("text") or group["term"],
                "canonical": group.get("canonical") or group["term"],
                "kind": group.get("kind") or "other",
                "concept_id": group.get("concept_id"),
                "aliases": group.get("aliases") or [],
                "review_status": "suggested",
                "provenance": {
                    "models": occurrence.get("sources") or group.get("seen_in", []),
                    "timestamp_alignment": occurrence.get("alignment", "unknown"),
                },
            })
    draft = {
        "schema_version": SCHEMA_VERSION,
        "kind": "bilingual_technical_transcript",
        "episode": episode,
        "status": "machine_draft",
        "provenance": {
            "transcript_model": asr.get("provider", "unspecified"),
            "source": asr.get("source", "unknown"),
            "source_time_offset_s": start,
            "editorial_review": "not_approved",
        },
        "turns": turns,
        "topics": [
            {
                "id": t.get("id", f"topic-{i:03d}"),
                "title": t["title"],
                "turn_ids": t["turn_ids"],
                "status": "suggested",
            }
            for i, t in enumerate((proposal or {}).get("editorial_topics", []), 1)
        ],
        "concept_mentions": mentions,
    }
    validate(draft)
    return draft


def apply_reference(doc, reference):
    """Overlay user-reviewed terminology without modifying spoken transcript.

    Even a verified terminology reference does not magically verify all Hebrew
    text or establish speaker identity. Keep that distinction in provenance.
    """
    validate(doc)
    if (reference.get("episode_guid")
            and reference["episode_guid"] != doc["episode"]["id"]):
        raise ValueError("Reference episode does not match transcript episode")
    approved = (reference.get("review_status") == "approved"
                and reference.get("terms_exhaustive") is True)
    result = json.loads(json.dumps(doc, ensure_ascii=False))
    new_mentions = []
    for src in reference.get("concept_mentions") or reference.get("verified_occurrences") or []:
        if not approved:
            break
        a = _finite_seconds(src.get("start_s", src.get("start")), "mention.start")
        b = _finite_seconds(src.get("end_s", src.get("end", a)), "mention.end")
        if b < a:
            raise ValueError("Reference mention ends before it starts")
        phrase = src.get("surface") or src.get("term")
        canonical = src.get("canonical") or src.get("term")
        kind = src.get("kind", "other")
        if not phrase or not canonical or kind not in KINDS:
            raise ValueError("Invalid reviewed technical concept")
        # Approval of a reference's spoken terminology must not automatically
        # approve a *new* editorial semantic merge, inferred canonicalization,
        # or individually unreviewed occurrence. Preserve the local status.
        occurrence_status = src.get("review_status", "verified")
        if occurrence_status not in STATUSES:
            raise ValueError("Invalid reference concept review status")
        provenance = src.get("provenance") or {}
        new_mentions.append({
            "id": f"mention-{len(new_mentions)+1:04d}",
            "turn_id": _turn_for_time(result["turns"], a),
            "start_s": a, "end_s": b,
            "surface": phrase, "canonical": canonical,
            "concept_id": src.get("concept_id"),
            "aliases": src.get("aliases") or [],
            "kind": kind, "review_status": occurrence_status,
            "provenance": {
                "models": src.get("source_models") or provenance.get("models") or [],
                "human_review": (
                    "audio_listening_approved"
                    if occurrence_status == "verified" else "not_yet_approved"
                ),
                "semantic_classification": provenance.get("semantic_classification"),
                "editorial_note": provenance.get("editorial_note"),
            },
        })
    if approved:
        # Reviewed terms replace model suggestions in this reviewed window.
        result["concept_mentions"] = new_mentions
        result["provenance"]["editorial_review"] = "terminology_approved_only"
        result["provenance"]["reference_review_status"] = "approved"
    else:
        result["provenance"]["reference_review_status"] = "pending"
    validate(result)
    return result


def validate(doc):
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported schema_version")
    if doc.get("kind") != "bilingual_technical_transcript":
        raise ValueError("Unsupported document kind")
    if not isinstance(doc.get("turns"), list) or not doc["turns"]:
        raise ValueError("At least one turn is required")
    ids = set()
    for turn in doc["turns"]:
        if not turn.get("id") or turn["id"] in ids:
            raise ValueError("Turn IDs must be unique and nonempty")
        ids.add(turn["id"])
        if not isinstance(turn.get("text"), str):
            raise ValueError("A turn must contain faithful text")
        a = _finite_seconds(turn["start_s"], "turn.start_s")
        b = _finite_seconds(turn["end_s"], "turn.end_s")
        if a > b:
            raise ValueError("Invalid turn bounds")
        if turn.get("review_status") not in STATUSES:
            raise ValueError("Invalid turn review status")
    seen = set()
    for mention in doc.get("concept_mentions", []):
        if mention.get("id") in seen or not mention.get("id"):
            raise ValueError("Mention IDs must be unique")
        seen.add(mention["id"])
        if mention.get("turn_id") is not None and mention["turn_id"] not in ids:
            raise ValueError("Mention refers to a nonexistent turn")
        if mention.get("kind") not in KINDS:
            raise ValueError("Unknown concept kind")
        if mention.get("review_status") not in STATUSES:
            raise ValueError("Unknown concept review status")
        a = _finite_seconds(mention["start_s"], "mention.start_s")
        b = _finite_seconds(mention["end_s"], "mention.end_s")
        if a > b:
            raise ValueError("Invalid concept timing")
        if not mention.get("surface") or not mention.get("canonical"):
            raise ValueError("Concept must preserve surface and canonical values")
    for topic in doc.get("topics", []):
        if not isinstance(topic.get("title"), str):
            raise ValueError("Topic requires title")
        if any(t not in ids for t in topic.get("turn_ids", [])):
            raise ValueError("Topic refers to a nonexistent turn")
        if topic.get("status") not in ("suggested", "verified"):
            raise ValueError("Topic must be explicitly qualified")


def _md(text):
    return _MARKDOWN.sub(r"\\\1", str(text or ""))


def render_markdown(doc):
    validate(doc)
    episode = doc["episode"]
    title = episode.get("title") or episode.get("id") or "Untitled episode"
    lines = [
        f"# {_md(title)}",
        "",
        "> Faithful bilingual audio transcript (Hebrew with English technical terms).",
        "> Machine-generated text and concept annotations may contain errors.",
        f"> Review status: **{_md(doc.get('status', 'unknown'))}**.",
        "> Speakers, facts and recommendations must not be inferred from missing labels.",
        "",
        f"- Source ID: \`{_md(episode.get('id', ''))}\`",
        f"- ASR model: \`{_md(doc['provenance'].get('transcript_model', 'unknown'))}\`",
        "",
    ]
    for name, url in episode.get("source_urls", {}).items():
        if url:
            lines.append(f"- {_md(name)}: {url}")
    lines += ["", "## Transcript", ""]
    for turn in doc["turns"]:
        speaker = turn.get("speaker_id") or "Speaker not verified"
        lines.append(
            f"**[{clock(turn['start_s'])}–{clock(turn['end_s'])}] "
            f"{_md(str(speaker))} · {turn['id']}**"
        )
        lines.append("")
        lines.append(_md(turn["text"]))
        lines.append("")
    approved = [m for m in doc.get("concept_mentions", [])
                if m["review_status"] == "verified"]
    if approved:
        lines += ["## Verified terminology", ""]
        for m in approved:
            lines.append(
                f"- **{_md(m['canonical'])}** — heard as "
                f"“{_md(m['surface'])}” at {clock(m['start_s'])} "
                f"({m.get('turn_id') or 'unmatched turn'})"
            )
        lines.append("")
    suggested = [m for m in doc.get("concept_mentions", [])
                 if m["review_status"] in {"suggested", "needs_review"}]
    if suggested:
        lines += [
            "## Unverified technical terminology",
            "",
            "> Hypotheses from ASR. Not verified and must not be treated as facts.",
            "",
        ]
        for m in suggested:
            lines.append(
                f"- {_md(m['canonical'])} ({clock(m['start_s'])}, "
                f"surface: {_md(m['surface'])}; {m['review_status']})"
            )
        lines.append("")
    if doc.get("topics"):
        lines += ["## Topic navigation (editorial annotations)", ""]
        for t in doc["topics"]:
            lines.append(
                f"- {_md(t['title'])} — {' '.join(t.get('turn_ids', []))} "
                f"({t['status']})"
            )
    return "\n".join(lines).strip() + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asr_file", type=Path)
    parser.add_argument("--proposal", type=Path)
    parser.add_argument("--review", type=Path, help="reviewer-exported reference JSON")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    asr = json.loads(args.asr_file.read_text(encoding="utf-8"))
    proposal = json.loads(args.proposal.read_text(encoding="utf-8")) if args.proposal else None
    doc = from_asr(asr, proposal)
    if args.review:
        reference = json.loads(args.review.read_text(encoding="utf-8"))
        doc = apply_reference(doc, reference)
    target = args.output_dir
    target.mkdir(parents=True, exist_ok=True)
    stem = doc["episode"]["id"] or args.asr_file.stem
    (target / f"{stem}.transcript.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (target / f"{stem}.transcript.md").write_text(
        render_markdown(doc), encoding="utf-8")
    print(f"Produced unverified bilingual transcript for {stem}")


if __name__ == "__main__":
    main()
