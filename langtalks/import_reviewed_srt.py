"""Import a fully reviewed SRT into an agent-ready bilingual transcript.

SRT times start at zero for the review MP3 excerpt. Add the original audio
window offset when writing absolute podcast timestamps. Corrected transcript
text and previously reviewed concept annotations have independent provenance.
No network calls or paid services are used.

python -m langtalks.import_reviewed_srt \
  --draft episode71-transcript.json --srt LangTalks71_EDIT_THIS.srt \
  --reference langtalks/reference/<guid>.json --out-dir out/reviewed

Only pass --full-audio-reviewed when the listener has actually checked and
corrected the entire relevant audio window.
"""
import argparse
import copy
import hashlib
import json
import re
from pathlib import Path

from .agent_format import apply_reference, render_markdown, validate

_SRT_TIME = re.compile(
    r"^(\d{2,}):([0-5]\d):([0-5]\d),(\d{3})$"
)
_SRT_RANGE = re.compile(
    r"^(\d{2,}:[0-5]\d:[0-5]\d,\d{3})\s*-->\s*"
    r"(\d{2,}:[0-5]\d:[0-5]\d,\d{3})$"
)


def _time(value):
    m = _SRT_TIME.fullmatch(value.strip())
    if not m:
        raise ValueError(f"Invalid SRT timecode: {value!r}")
    h, minutes, seconds, millis = (int(x) for x in m.groups())
    return 3600 * h + 60 * minutes + seconds + millis / 1000


def parse_srt(contents):
    """Fail closed on malformed, overlapping, blank or duplicate captions."""
    chunks = re.split(r"\r?\n\s*\r?\n+", contents.lstrip("\ufeff").strip())
    if not chunks or not chunks[0]:
        raise ValueError("SRT is empty")
    cues = []
    for block in chunks:
        lines = block.replace("\r", "").split("\n")
        if not lines:
            continue
        try:
            n = int(lines[0].strip())
        except ValueError:
            raise ValueError(f"SRT cue must start with a number: {lines[0]!r}")
        if n != len(cues) + 1:
            raise ValueError("SRT cue numbering must be consecutive from 1")
        if len(lines) < 3:
            raise ValueError(f"SRT cue {n} is missing text or time range")
        match = _SRT_RANGE.fullmatch(lines[1].strip())
        if not match:
            raise ValueError(f"Invalid SRT time range in cue {n}")
        a, b = (_time(part) for part in match.groups())
        if b <= a:
            raise ValueError(f"SRT cue {n} has zero or negative duration")
        if cues and a < cues[-1]["end"] - .001:
            raise ValueError(f"SRT cue {n} overlaps earlier cue")
        body = "\n".join(lines[2:]).strip()
        if not body:
            raise ValueError(f"SRT cue {n} is empty")
        cues.append({"start": a, "end": b, "text": body})
    return cues


def import_srt(draft, srt_contents, *, reference=None, full_audio_reviewed=False):
    validate(draft)
    cues = parse_srt(srt_contents)
    if len(cues) < 2:
        raise ValueError("At least two timed cues are needed for a full audio review")
    original = draft["turns"]
    offset = float(draft["provenance"].get("source_time_offset_s", original[0]["start_s"]))
    first_orig = min(float(t["start_s"]) for t in original)
    last_orig = max(float(t["end_s"]) for t in original)
    if abs((offset + cues[0]["start"]) - first_orig) > 3.5:
        raise ValueError("SRT appears to have the wrong start offset")
    if abs((offset + cues[-1]["end"]) - last_orig) > 4.0:
        raise ValueError("SRT appears to cover a different audio window")
    result = copy.deepcopy(draft)
    result["turns"] = [{
        "id": f"turn-{i:04d}",
        "start_s": round(offset + c["start"], 3),
        "end_s": round(offset + c["end"], 3),
        "speaker_id": None,
        "text": c["text"],  # no translation, lexical normalization or deletion
        "timestamp_precision": "human_reviewed_cues" if full_audio_reviewed else "asr_edit_cues",
        "review_status": "verified" if full_audio_reviewed else "suggested",
    } for i, c in enumerate(cues, 1)]
    # Explicitly reset unsupported speaker labels, because SRT has none.
    # Rewrite topic turn links against the new time-aligned segments.
    old_index = {t["id"]: t for t in original}
    new_topics = []
    for topic in draft.get("topics", []):
        intervals = [
            (old_index[tid]["start_s"], old_index[tid]["end_s"])
            for tid in topic.get("turn_ids", []) if tid in old_index
        ]
        related = [
            t["id"] for t in result["turns"]
            if any(t["start_s"] <= stop and t["end_s"] >= start
                   for start, stop in intervals)
        ]
        if related:
            new_topics.append({
                "id": topic.get("id"),
                "title": topic["title"],
                "turn_ids": related,
                "status": "suggested",  # transcript review does not verify topics
            })
    result["topics"] = new_topics
    # No old guessed concept/turn references survive. Apply only separately
    # user-verified reference labels if supplied.
    result["concept_mentions"] = []
    result["provenance"]["original_draft_hash"] = hashlib.sha256(
        json.dumps(draft, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    result["provenance"]["review_format"] = "SRT"
    result["provenance"]["review_window_offset_s"] = offset
    result["provenance"]["transcript_review"] = (
        "entire_audio_window_verified_by_listener"
        if full_audio_reviewed else "edited_draft_not_yet_verified"
    )
    if reference is not None:
        result = apply_reference(result, reference)
    result["status"] = "human_reviewed" if full_audio_reviewed else "machine_draft"
    if full_audio_reviewed:
        result["provenance"]["editorial_review"] = (
            "transcript_audio_verified_and_terminology_separately_reviewed"
            if reference is not None else "transcript_audio_verified_only"
        )
    validate(result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draft", required=True, type=Path)
    parser.add_argument("--srt", required=True, type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--full-audio-reviewed", action="store_true")
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    draft = json.loads(args.draft.read_text(encoding="utf-8"))
    ref = json.loads(args.reference.read_text(encoding="utf-8")) if args.reference else None
    result = import_srt(
        draft, args.srt.read_text(encoding="utf-8-sig"),
        reference=ref, full_audio_reviewed=args.full_audio_reviewed,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = result["episode"]["id"]
    (args.out_dir / f"{stem}.transcript.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.out_dir / f"{stem}.transcript.md").write_text(
        render_markdown(result), encoding="utf-8"
    )
    print(f"Exported {len(result['turns'])} timed turns and "
          f"{len(result['concept_mentions'])} separately reviewed concepts")


if __name__ == "__main__":
    main()
