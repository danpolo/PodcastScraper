# Bilingual technical transcript v1 (agent-ready output)

Goal: faithful, traceable material for future AI agents, NOT automatic implementation of podcast advice.

## Output contract

Every episode produces episode-id.transcript.json (canonical structured data) and episode-id.transcript.md (agent-readable view, rendered from JSON). Schema version: 1.0; module: langtalks/agent_format.py.

- episode: ID, title, languages Hebrew/English, original source URLs.
- turns: stable IDs, absolute seconds, exact ASR text (draft), speaker ID only if known, time precision, independent review flag.
- concepts: exact surface phrase, searchable canonical name, type, aliases, occurrence start/end, turn link if aligned, reviewer status and model evidence.
- topics: optional editorial sections whose suggested/verified status is explicit.
- provenance: models, episode origin, and editorial review state. Never claim ASR output is manually verified.

Transcript wording must never change merely because a concept was normalized. For example, preserve 'managed hosted version' in spoken text while indexing that mention as 'managed hosting' if supported by context.

## Semantic grouping rules

- code review, supply chain security, and human-in-the-loop approvals are meaningful single concepts regardless of how ASR tokenized their constituent words.
- managed hosted version is a descriptive spoken phrase; managed hosting is only a searchable interpretive concept.
- OneCLI is a distinct product, not generic CLI. OAuth is a protocol, not generic auth. Both require spelling verification.
- Common standalone adjectives and function words are not independent retrieval concepts. Do not duplicate code and review as additional concepts when they are part of one occurrence of code review.
- Compound detection and timestamps from ASR remain suggestions; only audio listening can verify them.

## Future agent consumption

Retrieve coherent Markdown sections with timestamps, speaker context, adjacent questions, caveats and trade-offs. Use JSON for search by aliases/concepts and to jump to exact source audio. Treat every technical claim as attributable speaker testimony, not independently established fact. Topic chunk sizes are tunable downstream, not a transcription hard requirement. This project does not extract actionable tasks or change software based on a podcast.

## CLI

Create initial editorial concept proposal:

    python -m langtalks.concept_review langtalks/reference/proposals/74fc0625-0a6b-4ca1-9488-31be7860360d.json --output episode71-concepts.json

Render transcript from cached local ASR:

    python -m langtalks.agent_format episode71.asr.json --proposal episode71-concepts.json --output-dir out/agent-ready

After review, apply the approved reference:

    python -m langtalks.agent_format episode71.asr.json --proposal episode71-concepts.json --review approved-reference.json --output-dir out/agent-ready

Even when English terminology is approved, Hebrew text and unknown speakers remain unverified.

## Best review workflow

1. Use two independent free offline ASR models and a semantic pre-pass. This reduces generic English word noise, merges obvious compounds and flags names/uncertainties.
2. Review the relevant occurrences, not every English token, in tools/reference-review.html with the actual episode audio. Verify product names and protocols first; then uncertain compounds; then search for missed concepts.
3. Reviewer supports timestamp seek and repeat, spoken surface vs canonical concept, type changes, merge/split, missed-term additions, saved sessions, and approved JSON export.
4. Do not mark an incomplete listening review approved, regardless of ASR agreement. A terminology-only approval never upgrades the full transcript.

All paid APIs require explicit user approval first. The benchmark blocks cloud API requests unless --allow-cloud-api is supplied, and the assistant must not supply that override without permission.
