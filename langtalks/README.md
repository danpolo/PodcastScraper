# LangTalks

[LangTalks](https://feeds.async.com/47/928fdaee-6711-4272-9695-e721488d8c33.rss) is a
Hebrew podcast about LLMs and AI agents — 71 episodes, 32.5 hours, averaging 27 minutes.

It cannot reuse the AI Thinkers pipeline, and the reason is measurable rather than
aesthetic. Roughly 30% of the words are English technical terms embedded in Hebrew
speech, and those terms are the entire reason to mine the show. Hebrew ASR
transliterates them into Hebrew letters, which destroys them.

The evidence is in this repo. The committed AI Thinkers transcripts are YouTube Hebrew
auto-captions: 433K characters at a **2.0% Latin-character ratio**, with damage like
`Supabase → סופבייס`, `database → הדatביס`, `customer facing → cסמר פייסingנ`,
`Base44 → ביס 44`. LangTalks' only YouTube caption track is `iw`, auto-generated — the
same engine. So the audio has to be transcribed properly.

**Which transcriber wins is an empirical question, so this package starts with a
benchmark rather than a pipeline.**

## Why not just use word error rate

Because WER treats an error in `אבל` the same as an error in `Model Context Protocol`,
and only the second one matters here. `score.py` therefore weights:

| Component | Weight | What it catches |
| --- | ---: | --- |
| `term_recall` | 45% | Did the English terms actually spoken survive in Latin script? |
| `hebrew_accuracy` | 30% | Character error rate over Hebrew characters only |
| `term_precision` | 10% | Did keyterm prompting *induce* a term nobody said? |
| `speaker_accuracy` | 10% | Do diarization boundaries land on real turn changes? |
| `script_fidelity` | 5% | Did Latin density collapse (i.e. silent transliteration)? |

Components the reference cannot support report `n/a` and their weight is redistributed,
so a provider is never punished for an annotation you did not write — or, in the case of
`speaker_accuracy`, for a capability it does not claim to have.

`term_precision` is deliberately measured against **the glossary the model was prompted
with**, not against all English. Telling a model to expect `LangGraph` does not license
it to resolve every unclear "Lang…" into LangGraph, and a confidently wrong product name
is worse than an obvious phonetic guess because it propagates silently into extracted
tips. Ordinary unlisted English ("best practices") is not a hallucination.

## Setup

Providers are selected by which API keys are present. Add to
`~/.config/PodcastScraper/.env`:

```
SONIOX_API_KEY=...
ELEVENLABS_API_KEY=...
OPENAI_API_KEY=...
RUNPOD_API_KEY=...          # ivrit.ai
RUNPOD_ENDPOINT_ID=...      # ivrit.ai
```

Archive-scale cost sits between roughly **$1 (ivrit.ai) and $7 (ElevenLabs)** for all
32.5 hours. That spread is real but small in absolute terms, so let the benchmark decide
on accuracy — with the caveat that ivrit.ai's cost advantage compounds if you ever
re-transcribe after a model upgrade, or extend this to the AI Thinkers backlog.

## Running the benchmark

```bash
python -m langtalks.bench episodes                    # list the feed
python -m langtalks.bench fetch 71 70 69              # download audio
python -m langtalks.bench excerpt 71                  # cut the 480-780s window
python -m langtalks.bench reference 71
#   ... listen to that window, fill in technical_terms ...
python -m langtalks.bench transcribe 71               # every configured provider
python -m langtalks.bench score 71
python -m langtalks.bench report                      # comparison table
```

Episodes are selected by number (`71`) or guid prefix. Transcripts are cached under
`out/transcripts/` and never overwritten without `--force`, so scoring is free to rerun.

### Why excerpts

`excerpt` cuts the scored window out of the episode with a pure-Python MP3 frame slicer
(`mp3.py`) — no ffmpeg, which is not installed here and would need root. This matters for
more than tidiness:

- RunPod rejects request bodies over 10 MB, and base64 inflates audio by 4/3. A full
  32 MB episode cannot be sent at all; the default 5-minute window is 4.8 MB → a 6.4 MB
  payload.
- OpenAI's transcription endpoint caps uploads at 25 MB, which full episodes exceed.
- A benchmark run costs cents rather than dollars.

`transcribe` prefers the excerpt automatically when one exists (`--full` overrides).
Excerpt timestamps start at zero while references are annotated in absolute episode time,
so the offset is added back at write time — every stored transcript is in episode time
regardless of what was actually uploaded.

### The one manual step

`technical_terms` in the reference file is the only annotation that cannot be generated,
and it is the cheap one: listen to the window once and write down the English terms you
hear, in their canonical spelling. That alone drives 55% of the score. `reference_text`
(a corrected transcript of the window) is optional and unlocks Hebrew accuracy and script
fidelity; `speaker_turns` unlocks diarization scoring.

Suggested windows — pick ~25 minutes total across episodes that differ:

| Episode | Why |
| --- | --- |
| 71 — Claw Architectures | New architecture and security terminology |
| 70 — Our Claude Code Tips | Dense tooling vocabulary, no guest |
| 69 — Marketing for Agents | Guest speaker, company and product names |
| One 2023–24 episode | Older audio quality, different recording setup |

## Providers

| Provider | Model | Notes |
| --- | --- | --- |
| `soniox` | `stt-async-v5` | Advertises mid-sentence language switching, which is exactly the problem here. Glossary goes in `context.terms`. Diarization + word timings. ~$0.10/hr. |
| `ivrit` | `ivrit-ai/whisper-large-v3-ct2` | Hebrew fine-tune, self-hosted on RunPod. Cheapest (~$0.03/hr) and the only contender with direct public evidence on the actual LangTalks archive. Needs a deployed endpoint, not just a key. |
| `elevenlabs` | `scribe_v2` | Largest keyterm budget (1,000). ElevenLabs rates Hebrew "good" rather than best-tier, so it is a contender, not a favourite. ~$0.22/hr. |
| `openai` | `gpt-4o-transcribe` | Free-text prompt is the most direct way to say "keep English in Latin script". No diarization, so it scores `n/a` there rather than zero. ~$0.36/hr. |

All four receive the same episode glossary, so no provider is handicapped. For ivrit.ai
that goes in via faster-whisper's `initial_prompt` — the RunPod worker forwards unknown
`transcribe_args` straight through — which is the closest equivalent to the others'
keyterm parameters.

### The ivrit.ai question

ivrit.ai has the **strongest evidence of any candidate**: a developer transcribed the
first 65 LangTalks episodes with it and reported that it handled the podcast's dense
technical Hebrew and its switches into English tool names cleanly, at under $1 for the
whole archive. That is evidence on *the actual target audio*, which beats any generic
Hebrew benchmark.

The counter-argument is mechanistic and unproven. The
[model card](https://huggingface.co/ivrit-ai/whisper-large-v3) states that language
detection "has been degraded during training" and that the model is "intended for
mostly-hebrew audio transcription". Its ~5,050 training hours are roughly **93% Knesset
parliamentary proceedings** — a domain containing almost no English AI-engineering
vocabulary. A Hebrew specialist trained mostly on Hebrew political speech is a plausible
candidate to transliterate exactly the terms this project exists to preserve.

Neither claim settles the other, and the published case study was a qualitative report
rather than a controlled measurement of English-term preservation. That is precisely what
`term_recall` measures, so run it.

Note that ivrit.ai's free web tool **forbids automated access and wrappers**; RunPod
self-hosting is the supported path and the one this provider uses.

### A free fourth opinion

`https://mcp.langrag.ai/mcp` is a public keyless MCP server indexing LangTalks. It is
**not** a corpus you can build on — as of August 2026 it covers only 2026-03-21 to
2026-07-26 (213 chunks, roughly the last dozen episodes) and returns ~200-character
snippets rather than transcripts. It is licensed CC BY-NC, so personal use is fine.

It is genuinely useful as a cross-check, because it is plain `faster-whisper large-v3`
with **no glossary and no keyterm prompting** — a free baseline for what a generic
multilingual model does on this audio. Spot-checking it showed English surviving cleanly
(`Blast Radius`, `Supply Chain Security`, `Expired At`, `MCP`) with errors concentrated
in product names (`Claude → Cloud`, `Postiz → פוסטים`) — precisely what a glossary is
supposed to fix.

That observation is a useful reference point for the ivrit.ai question above: a *generic*
multilingual model already preserves this podcast's English well without any glossary, so
a Hebrew specialist has to earn its place rather than being assumed better.

## Feed quirks handled in `feed.py`

- The enclosure host returns **403** without a browser `User-Agent`.
- Older enclosure URLs are **doubly percent-encoded** (`%2520`); the URL must be passed
  through byte-for-byte, since decoding it yields a 404.
- The feed is published oldest-first; `fetch_episodes()` reverses it.
- Episode identity is the RSS `guid` (a bare UUID), not the title or the audio URL.

## Layout

```
feed.py           RSS discovery, audio download, sha256
mp3.py            frame-accurate MP3 slicing, stdlib only (no ffmpeg)
glossary.py       per-episode keyterms + context prompt
providers/        soniox, ivrit, elevenlabs, openai (one output shape)
score.py          weighted scoring; the term-recall idea lives here
bench.py          CLI
reference/        your annotations, one JSON per benchmarked window
out/              audio, excerpts + transcripts (gitignored)
```
