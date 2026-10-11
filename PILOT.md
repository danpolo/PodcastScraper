# Controlled pilot: preserve discovery, measure transcription

**Actual goals:** maximal episode discovery/metadata coverage and accurate
Hebrew transcripts with English technical terms in Latin script. Hive is
downstream and not part of this decision.

## Discovery: RSS + YouTube + Spotify remain complementary

Do not remove a source just because an RSS feed exists. On AI Thinkers, compare
the original podcast RSS, YouTube feed/video listings and Spotify full episode
notes **at the episode and field level**, including Shorts.

For each source, record stable source ID, title, publish date, duration,
media type, description length, outbound links, transcript/caption availability
and audio URL availability. Build a reconciled union with source provenance.
Match platforms on verified episode identifiers when possible; otherwise use
title, duration and date with uncertainty flags. **Never pair descriptions to
YouTube episodes using list position.** Report ambiguous matches for review.

Acceptance criterion for any replacement: no loss of previously known episodes,
usable show notes or unique links; source outages must be visible, recoverable
and must not silently stop daily ingestion. Test against the known local archive
and recently released episodes. No source is removed before coverage is proven.

## Transcription: controlled code-switching benchmark

Choose difficult five-minute excerpts across: dense terminology, English
product names, multiple speakers, different voices, older audio and various
audio conditions. Each excerpt needs a human-checked list of the actual English
terms spoken, **not an ASR-generated reference**. Optionally add corrected
Hebrew text and speaker changes. Use the same clips for every provider.

Run the two Groq Whisper variants and Soniox (existing provider), comparing:
- English technical-term recall, **false English terms** and script fidelity
- Hebrew CER where human text is available
- Multi-speaker consistency; treat missing diarization as a capability gap
- Reliability, upload limits, actual cost and errors per episode

Potentially best free candidate: Groq free Whisper. No accuracy claim can be
made before provider audio requests and human scoring.

Groq adapters require GROQ_API_KEY. They use one model each, keep cache names
separate and provide segment timestamps, but no speaker labels. Their context
prompt intentionally prioritizes early episode-specific glossary terms,
does not rewrite transcription output, and conservatively limits length.

Example after keys and references are available:

    python -m langtalks.bench excerpt 71 --start 480 --end 780
    python -m langtalks.bench transcribe 71 --provider groq_v3
    python -m langtalks.bench transcribe 71 --provider groq_turbo
    python -m langtalks.bench transcribe 71 --provider soniox
    python -m langtalks.bench score 71
    python -m langtalks.bench report

This branch is a **benchmark pilot**, not an ingestion migration. It preserves
all three discovery sources and does not touch Hive.
