# Held-out full-episode transcription evaluation protocol (v1.1)

**Status:** Pre-registered methodology, 2026-10-13. **v1.1 clarification:** adds an explicit Hebrew-script-to-English-concept linking check, without using reference annotations to alter ASR or glossary outputs. **Scope:** one complete previously unseen LangTalks episode. **Authority:** this document; any subsequent changes must be versioned and disclosed. This document does **not** assert that an experiment has run, that an engine commit has already been frozen, or that human review has happened.

## 1. Objective and experiment design

Test whether the revised Hebrew/English fusion engine generalizes beyond the Episode 71 development excerpt. Judge transcript fidelity, *all* technical-term mentions, correct Hebrewized speech, and harmful fusion changes; do not optimize the legacy weighted composite.

1. Before examining any candidate transcript or ASR performance, select and record one full, available LangTalks episode not used for fusion development, benchmarking, editorial reference creation, or threshold setting. Prefer a different subject/guest if eligible. Record eligible alternatives and reason for selection/exclusion. Episode 71 is ineligible as held-out data.
2. Use the entire episode, not a favorable excerpt. Record full duration, episode GUID, feed metadata, audio checksum, all processed intervals, and any unavoidable excluded intervals (e.g., genuinely non-speech content). Never silently drop difficult intervals.
3. Run existing Episode 71 **offline** regression tests before processing the held-out episode. Episode 71 is a development safety check, not another held-out result.
4. Freeze the revised fusion **implementation, thresholds, provider models/configurations, input glossary generation, prompting, and comparison/scoring definitions** before the held-out run. Record exact git commit(s), versions, and configuration hashes. The protocol is frozen by this document; the operational freeze occurs in the experiment manifest before any new ASR output is inspected.
5. Provider requests can incur costs: require explicit user approval and record anticipated costs **before** remote ASR calls, even if the provider advertises a free tier. No production deploy, archive backfill, PR, or changes to `main`.

## 2. Preserve the three terminology layers — mandatory

The user's explicit requirement is to retain the **original engine-produced technical-term inventory**, then compare it to the corrected one. Preserve *both* senses of “engine inventory,” as they answer different questions:

**A. Pre-ASR expected glossary (machine prior).** Save the exact ordered output of `glossary.build(episode)` before ASR, plus the metadata inputs, provider-specific injected term lists/context/prompts, generators' versions, and hashes. This is a *prediction of possible vocabulary*, **not a claim that each item was spoken**.

**B. Post-ASR engine-detected inventory (machine observation).** After providers and the original revised hybrid complete, but **before receiving any user-corrected SRT**, run the existing `reference_draft`/concept-discovery process (adapted as necessary for full episodes) on **machine transcripts only**. Preserve:
- Raw unfiltered candidate phrases and exact observed spellings; canonical guesses/aliases separate from surfaces.
- Every machine-estimated occurrence interval, detection method, source provider(s), per-provider votes, any confidence available, and uncertain/unmatched phrases.
- Per-provider candidate inventories, if produced; the original combined engine inventory and revised-hybrid-derived inventory must be distinguishable.
- Original ASR transcripts and fusion edits/provenance, without any user reference-derived changes.
- Generator version and exact JSON snapshot with SHA-256 hashes. No rewriting, back-filling, re-running with corrected text, or silently replacing these snapshots.

**C. Human-approved ground truth (reference).** Only after the user corrects the SRT, automatically derive candidate technical expressions and occurrences from **that corrected SRT**; produce the later review HTML and let the user resolve genuinely ambiguous/missing terms. Only then label the term/occurrence annotations approved. The user-approved data is not a modification of A or B.

A glossary item absent from C is **not automatically an ASR hallucination**: A is an expectation list. A detected term in B absent from C is a *candidate false detection*, to adjudicate using its context/timing. Preserve historical A/B data regardless of the outcome.

## 3. Roles and gated workflow

**Phase 1 (Codex executes the existing engine).** Freeze and manifest engine/settings; select the episode by the protocol; record A; run the already-built provider/fusion pipeline and preserve raw outputs; compute and lock B before any human reference; export **the complete episode MP3 and a properly timed SRT from the revised hybrid**. Do not independently transcribe, rephrase, correct, or use another model to improve the SRT. SRT conversion may adjust cue splits/punctuation-neutral formatting but must not insert, remove, or replace words. Validate text completeness, absolute-relative time mapping, and duration. Deliver the actual MP3 + draft SRT to the user by their existing send-to-me workflow. **No reference-review HTML yet.**

**Phase 2 (user corrects, Codex prepares reference).** User listens and corrects the SRT in Subtitle Edit, including technical expressions and cue timing, then returns it. Preserve the returned SRT verbatim with checksum, as the authority for transcript words. Import it with existing `import_reviewed_srt` functionality, preserving unknown speaker labels and unresolved uncertainties; do not substitute semantic canonical names for spoken text. Automatically extract and time technical occurrences from the corrected SRT. Reconcile against A and B to **propose** overlooked candidates without auto-accepting them. Produce the reference-review HTML *only after* the corrected SRT is supplied; it must already reflect every correction/addition in that SRT.

**Phase 3 (user approves ground truth).** HTML is a **terminology/ground-truth exception reviewer**, not a transcript editor or provider-comparison dashboard. Group technical expressions by canonical identity, showing actual spoken surface, all automatically populated occurrences/counts, timestamp/cue context and synchronized audio. Prioritize ambiguities, possible omissions and uncertain alignments. Permit confirmation, removal, correction or addition, with export of final terms and occurrences. Do not require confirming every unambiguous hit. The user explicitly approves the final annotation set; approval of a transcript does not automatically approve inferred terminology.

**Phase 4 (Codex computes, ChatGPT audits).** Run deterministic evaluation on the immutable raw provider/hybrid outputs against the approved transcript and technical-term reference. ChatGPT independently reviews methodology, output/provenance, invalid comparisons, and final conclusions. The user need not manually compare providers or diagnose fusion choices.

## 4. Ground-truth semantics and timing

- **Transcript surface != semantic identity.** Preserve faithful Hebrew-first bilingual speech under `HEBREW_ENGLISH_POLICY.md`: Hebrewized forms such as `אייג'נטים`, `יוזרים`, `קונטיינרים`, `ההרנס` stay Hebrew when actually spoken as Hebrewized words. Preserve inflection, negation, clitics and pronouns. Do not translate or standardize speech into a prettier concept name.
- Annotate product names, protocol/standards, acronyms, tools, software/security/infrastructure concepts, meaningful multiword technical phrases and salient technical actions. Exclude generic conversation words absent a clear technical use; record excluded candidates/reasons when material.
- An occurrence records `canonical` (semantic identity), `surface` (what was spoken/written), `aliases` (only verified lexical/orthographic variants), `start/end`, `timestamp_precision`, `source_cue(s)`, and `review_status`. A parent concept may group multiple spoken surfaces, but this **never** makes a wrong spoken word correct. Distinguish generic `CLI` from product `OneCLI`; `auth` from `OAuth`; unresolved identity stays unverified.
- Match all repeated occurrences automatically, including occurrences newly inserted by the user into the corrected SRT. Deduplicate identical proposals from multiple detectors; do not double-count overlapping compound/subphrase mentions as independent successes by default. Record meaningful nested concepts separately only when independently expressed and explicitly justified.
- SRT timestamps denote **cue intervals**, not guaranteed word timings. Derive word/phrase positions deterministically/with reference-independent audio alignment when possible, but label estimates. A phrase constrained only by an entire long cue is not a verified word-level instant. Flag genuinely uncertain timing for review or mark occurrence unscorable for tight time-matching; never fabricate precision.
- Reference must cover the entire audible spoken episode. Track skipped, unreviewed and unresolved regions. Do not report whole-episode verified metrics on incomplete review. Keep uncertain term identities out of confirmed denominators, report their count, and never silently drop them.
- Never feed the corrected SRT, human terminology annotations, or reference-derived pronunciations/glossary back into provider prompting, fusion, or outputs being evaluated.

## 5. Primary measurements (all against exactly the same approved reference)

**Transcript accuracy**
1. **WER** = word-level Levenshtein substitutions+deletions+insertions divided by reference word count; lower is better.
2. **CER** = normalized character-level edit distance / reference character count; lower is better.
3. **Hebrew-only character accuracy** = max(0, 1 - Hebrew-character edit distance / reference Hebrew characters), alongside raw Hebrew error counts. Do not reward replacing valid Hebrewized loanwords with English transliterations.
4. Use the existing `score._normalize`/audit WER/CER normalization as the predeclared baseline: Unicode NFKC, case-insensitive, punctuation removed, collapsed spaces; preserve actual words and language script. Record the scorer commit/version and publish normalizations on diagnostic examples before using held-out labels. Do not introduce result-driven transliteration, synonym, morphological, or semantic normalization. Report raw and normalized text samples for contentious cases.

**Technical terminology, evaluated separately at unique-term and occurrence levels**
5. **Unique-term recall/precision** for each post-ASR detected inventory B and each provider/hybrid output against C, under the approved term-scope and canonicalization policy. Publish TP, FP and FN and lists, not percentages alone. Inventory precision applies to actual **detected** claims, not expected glossary A.
6. **Occurrence recall** = reference technical-term mentions correctly emitted at the matching time / all verified, scorable reference mentions. **Occurrence precision** = correct matched emitted mentions / all scorable detected emitted mentions. Require one-to-one matching: one emission cannot satisfy two reference mentions and vice versa. Record per-term counts and misses, e.g. all six `OneCLI` mentions, never just presence/absence.
7. For timing, retain existing `strict_occurrence.timed_term_recall_strict` default **±1.5 seconds** for compatible timed word/short-segment emissions. Apply consistent absolute episode time axes. A lexical/canonical match without a trustworthy time is **not** a timed match. Report timestamp-quality coverage, missing/invalid times and unscorable counts; never assign zero to an unscorable provider and never silently remove it from coverage reports. If the current matcher is insufficient for precision, implement/test an occurrence-precision extension against synthetic cases and Episode 71 only, **before** inspecting held-out metrics; version it explicitly.
8. **Glossary A coverage** = proportion of approved unique technical terms in C whose identity was present in the original pre-ASR glossary (separate literal and alias-aware coverage). Also report glossary size and terms absent from C. Do **not** call this glossary recall at audio-mention level or treat unspoken glossary hints as hallucinations. Compare with B to determine whether misses arose during anticipation or recognition.

**Cross-script semantic concept linking — independently scored**
9. **Concept-linking precision and recall:** For every verified reference concept occurrence C, compare the machine-produced concept annotations B (and each provider/hybrid annotation when present) using one-to-one time-local matching, canonical concept IDs/labels and user-approved aliases. Report true links, missing links and incorrect links separately. Measure both per-unique-concept and per-occurrence results, with denominator, timestamp-quality coverage and an explicit distinction between Hebrew-script, Latin-script and mixed-script surfaces. **Do not count an alias merely present in a glossary as a successful detected link.**
10. **Hebrewized technical terminology test:** Explicitly test e.g. transcript surface `ההרנס` → canonical concept `harness` (with the Hebrew definite article separated as morphology), and distinguish it from (a) the verbatim transcript being correct, (b) a model incorrectly outputting Latin `harness` when a Hebrewized form was spoken, and (c) a false or ambiguous semantic link. Record link confidence/uncertainty; unresolved cases stay unverified. Reference C may propose cross-script aliases from the corrected SRT for user review, but machine baseline B must be created **without** access to that SRT or its aliases. Report technical concepts that are present in the original transcript but not recognized semantically.

**Additional diagnostics**
11. Preserve correct Hebrewized loanword surfaces and report recall on the finite known-form vocabulary **with denominator and an explicit “non-exhaustive” label**. Record improper romanizations and mixed-script forms separately.
12. Compare fusion modifications against the approved reference: exact before/after span, donor evidence, timestamp, affected Hebrew/context, and whether the change fixed an error, introduced an error, was neutral, or cannot be judged. Independently flag unsupported invented product/protocol names, meaningful word drops, and changed negations.
13. Publish the legacy composite, script-density and glossary-limited “precision” only as **historical diagnostics**, never as proof of fewer hallucinations or as the primary winner selection. Extra Latin words in output are candidates for review, not automatically hallucinations.

**Matching safeguards**
- Technical concept aliases are validated editorial metadata, not permission for a model to emit a different word. Report **strict spoken-surface** recognition and **canonical-identity** recognition separately. Product/protocol substitutions with different identities are errors even if phonetically similar.
- Candidate and reference technical-term tokenization/compound logic, normalization, time tolerance, confidence exclusions and overlapping-term rules must be pinned and documented **before scoring** held-out data. Do not use the held-out reference to tune them. Any exploratory re-scoring is separately labeled post-hoc and cannot replace the first frozen results.
- Show absolute counts and denominators plus per-term/per-occurrence evidence, with stable timestamps and provenance.

## 6. Fair, reproducible comparison

Evaluate the ivrit/base model, Soniox/donor, the revised hybrid, and the **previous hybrid** if it can be faithfully replayed with its original implementation against the **same captured base and donor outputs**, without new requests or episode-specific reference rewrites. If the previous hybrid cannot be reproduced comparably, label it unavailable rather than impute results. Include other previously run providers only when cached and relevant; do not spend money on optional providers without approval.

- Same episode, full audio coverage, timebase, underlying provider outputs and human reference for every evaluated system.
- Preserve provider-specific token timestamps and confidence exactly as returned; do not invent confidences.
- Report WER/CER, Hebrew accuracy, unique technical-term and one-to-one occurrence precision/recall, script/loanword diagnostics, and edit-level differences by system.
- Separate raw provider recognition, glossary-coverage failure, candidate-discovery failure, and fusion replacement failure. Avoid attributing model errors to fusion or vice versa.
- Use immutable experiment snapshots and SHA-256 manifest. Original datasets A/B remain fixed after reference C is submitted. If baseline implementation changes, it is a **different experimental run**.

## 7. Validity checks and interpretation

**Experiment invalid / incomplete:** missing full audio coverage; missing original A or B snapshots; missing raw provider data; user has not approved all transcript regions; unresolved term labels incorrectly counted as verified; corrected reference used to prompt/transcribe/fuse; scoring scripts changed in response to held-out scores; or uncontrolled different provider outputs between old/new fusion.

**Predeclared favorable-evidence checks (not automatic production authorization):**
- No confirmed severe unsupported named-product/protocol substitutions, omission of important speech, or altered Hebrew negation newly introduced by revised fusion.
- Revised fusion does not regress versus its base on whole-episode WER, Hebrew-only accuracy or scorable term-occurrence recall, with exact absolute counts and meaningful coverage.
- Explicitly compare with old hybrid where reproducible, but do not hide other regressions behind an average.
- If a check fails, describe the failing evidence and do not claim generalization success. An honest negative result is useful.

**Interpretation:** A single full held-out episode is a stronger generalization test than Episode 71 but **does not prove production readiness** across speakers, genres or episodes. Report uncertainties, severe false edits and further validation needs. No tuning against this episode until the original frozen evaluation is archived; after tuning it becomes development data.

## 8. Required immutable deliverables

Store under a GUID-keyed versioned evaluation directory or equivalent reproducible artifact storage, rather than overwriting existing files. Suggested names (adapt to existing conventions while preserving distinct roles):

- `manifest.preflight.json`: protocol version, selected GUID/reason, commit IDs, models/params, prompts, metadata/audio hash, timebase and selected runtime.
- `engine_glossary.original.json`: **A**, original ordered pre-ASR glossary and actual provider input hints.
- `provider_*.original.json`, `hybrid_previous.original.json` (if comparable), `hybrid_revised.original.json`, `fusion_edits.original.json`: exact machine outputs.
- `engine_terms_detected.original.json` plus `provider_terms_*.original.json` when applicable: **B**, pre-human machine-discovered phrases and every estimated occurrence.
- `audio.mp3` + `hybrid_draft.srt`: user-facing files, accompanied by hashes; SRT lexical content must reflect original revised hybrid.
- `reference_user_corrected.original.srt`: verbatim submitted transcript, unchanged.
- `reference_terms.proposed.json` then `reference_terms.approved.json`: **C**, occurrences/aliases/uncertainties, review provenance and decisions; HTML generated from the corrected SRT **after** receipt.
- `evaluations.frozen.json`, `diffs.json`, `report.md`: complete metrics and discrepancies including **A vs C, B vs C, provider/hybrid vs C**, terminology inventory additions/removals, and separate **cross-script concept-linking precision/recall** with case-level evidence (e.g., `ההרנס` → `harness`).
- `manifest.final.json`: checksum index for all artifacts plus any caveats or deviations.

Preserve all model outputs and original term inventories before user edits, including items later found wrong. User-facing comparison must make newly found technical terms and repeated mentions visible, without requiring duplicate manual entry.

## 9. Responsibility summary

- **Engine:** original glossary generation, transcription, fusion, existing candidate-term extraction.
- **Codex:** reproducible execution, original A/B preservation, MP3/SRT export, adapting reference discovery and ground-truth HTML, deterministic scoring and artifact production.
- **User:** correct SRT in Subtitle Edit; review only ambiguous/excluded/uncertain ground-truth terminology in HTML; approve final reference.
- **ChatGPT:** own the evaluation protocol; independently audit metrics, reference leakage, methodology, and recommendations.

**Stop points:** (1) cost approval before paid calls; (2) user receives MP3+SRT; (3) user returns corrected SRT; (4) user reviews terminology HTML; (5) full evaluation and ChatGPT audit. No need for user to compare providers manually.
