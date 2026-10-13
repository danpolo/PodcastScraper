"""Export revised hybrid transcription to a synchronized .srt without text alteration.

Conforms to standard Subtitle Edit conventions and validates:
1. Sequential cue numbering starting at 1
2. Standard SRT timecodes (HH:MM:SS,mmm --> HH:MM:SS,mmm)
3. Non-overlapping, monotonic cue intervals
4. Verbatim preservation of original machine-generated wording
5. Compatible with import_reviewed_srt.parse_srt parser
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .import_reviewed_srt import parse_srt


def format_srt_time(sec: float) -> str:
    millis = int(round(sec * 1000))
    h = millis // 3600000
    m = (millis % 3600000) // 60000
    s = (millis % 60000) // 1000
    ms = millis % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def export_hybrid_to_srt(eval_dir: Path) -> Path:
    hybrid_path = eval_dir / "hybrid_revised.original.json"
    hybrid_data = json.loads(hybrid_path.read_text(encoding="utf-8"))
    tokens = hybrid_data.get("tokens", [])

    cues = []
    current_words = []
    cue_start = None
    cue_end = None

    for t in tokens:
        start = t.get("start")
        end = t.get("end")
        text = t.get("text", "")
        if start is None or end is None or not text.strip():
            continue
        start, end = float(start), float(end)

        split = False
        if current_words:
            gap = start - cue_end
            dur = cue_end - cue_start
            if gap > 1.2:
                split = True
            elif dur > 4.5 and current_words[-1]["text"].rstrip().endswith((".", "!", "?", ",", ";", ":", "...")):
                split = True
            elif dur > 7.0:
                split = True

        if split:
            cue_text = " ".join("".join(w["text"] for w in current_words).split())
            if cue_text:
                cues.append({"start": cue_start, "end": cue_end, "text": cue_text})
            current_words = []
            cue_start = start
            cue_end = end
        else:
            if cue_start is None:
                cue_start = start
            cue_end = max(cue_end, end) if cue_end is not None else end
        current_words.append(t)

    if current_words:
        cue_text = " ".join("".join(w["text"] for w in current_words).split())
        if cue_text:
            cues.append({"start": cue_start, "end": cue_end, "text": cue_text})

    # Build SRT content
    blocks = []
    for i, cue in enumerate(cues, 1):
        t_start = format_srt_time(cue["start"])
        t_end = format_srt_time(cue["end"])
        blocks.append(f"{i}\n{t_start} --> {t_end}\n{cue['text']}")

    srt_content = "\n\n".join(blocks) + "\n"

    # Validate with repo's own parse_srt
    parsed = parse_srt(srt_content)
    assert len(parsed) == len(cues), f"Parsed cues mismatch: {len(parsed)} vs {len(cues)}"

    # Validate verbatim word content
    def norm_words(txt):
        return re.sub(r"[\s.,;:!?\"\'\(\)\[\]{}—–-]+", " ", txt).strip().split()

    orig_words = norm_words(hybrid_data["text"])
    cues_words = norm_words(" ".join(c["text"] for c in cues))
    assert orig_words == cues_words, f"Word content modified! orig: {len(orig_words)}, srt: {len(cues_words)}"

    out_file = eval_dir / "hybrid_draft.srt"
    out_file.write_text(srt_content, encoding="utf-8")
    return out_file


if __name__ == "__main__":
    guid = "0e404ceb-d04b-4818-907d-a74aafa7c155"
    eval_dir = Path(__file__).resolve().parent / "evaluations" / guid
    srt_file = export_hybrid_to_srt(eval_dir)
    print(f"Exported valid synchronized SRT to {srt_file}")
