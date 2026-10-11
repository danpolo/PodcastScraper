# Hebrew/English transcription policy

Purpose: produce faithful Hebrew-first technical speech that an AI agent can read, search and cite, while distinguishing speech from interpretation.

## When to use Hebrew letters

- Keep **Hebrewized English loanwords** in Hebrew exactly as spoken: יוזרים, אייג'נטים, קונטיינרים, דיבגתי. Preserve Hebrew prefixes, suffixes and conjugations (e.g. ליוזרים, באייג'נטים, לדבג).
- These forms are legitimate mixed-language Hebrew, **not automatic English ASR mistakes** and not a reason to force Latin script.
- Don't auto-create one concept occurrence per generic loanword. A future search/indexing layer may attach a separate alias to a meaningful concept, such as יוזרים → users, without changing the spoken text.
- Retain colloquial Hebrew and meaningful grammatical inflection. Don't translate, rephrase or silently remove wording to sound more formal.

## When to use English (Latin script)

- Preserve **distinct English technical expressions** when pronounced as English phrases: code review, supply chain security, mounted directory, managed hosted version. They can span multiple ASR tokens but should form one semantic concept mention when appropriate.
- Use verified official English spelling for product/protocol identities when the actual referent is clear: NanoClaw, OpenClaw, OneCLI, OAuth, API, Google Workspace.
- When the speaker pronounces an ambiguous sound (e.g. auth vs OAuth, CLI vs OneCLI), store the speech and mark the identity as **unverified**. Context helps propose a canonical referent, but never certifies it.
- If a term is pronounced as a fully Hebrewized loanword rather than an English phrase, preserve Hebrew in the transcript while optionally adding an English search alias to a concept annotation.

## Two layers, never one rewrite

1. **Transcript surface:** faithful speaker words, Hebrew loanwords stay Hebrew; uncertain ASR text is flagged as a draft.
2. **Semantic concept mention:** optional type, aliases, searchable canonical form and time range; this is editorial metadata, not replacement speech.

Example: transcript 'היוזרים מריצים כמה אייג׳נטים בקונטיינרים'; optional concept annotation `{surface: 'אייג׳נטים', canonical: 'AI agents'}` **only if retrieval would benefit**, with explicit unverified/verified status. Do not create that annotation automatically for every occurrence.

## Review and scoring

- Review high-value named entities, protocol names, security concepts, and unclear bilingual phrasing first.
- Do NOT flag Hebrewized common words for correction solely because the source language was originally English.
- Do not artificially reward a model for converting יוזרים to users when the speaker said the Hebrewized form. Score English terminology recall on phrases actually spoken in English, not loanwords intentionally retained in Hebrew.
- The concept index may contain one multiword term even if ASR emits two/three tokens. The original sentence and token timing remain intact.

Implementation: `langtalks/agent_format.py` copies the original bilingual speech into turns and maintains separately typed `concept_mentions`. `langtalks/reference_draft.py` selects Latin technical candidates but does not rewrite Hebrewized speech. Regression tests enforce no unwanted romanization.

Cost rule: do not call potentially billed ASR models without explicit approval, regardless of whether a plan has an advertised free tier.