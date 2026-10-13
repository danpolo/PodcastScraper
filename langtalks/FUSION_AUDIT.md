# Hybrid fusion correctness audit (dev)

**Scope:** \`langtalks/hybrid.py\`, new \`fusion_safe.py\`, cached Episode 71
480–780s outputs, human-approved reference, \`score.py\`, Soniox adapter, and
existing tests. No ASR calls, paid compute, archive backfill, or reference edits.

## Priority findings

| Priority | Original defect | Impact | Response |
| --- | --- | --- | --- |
| P0 | Rule-based substitution fired with \`donor=None\` and fabricated donor confidence (0.95–0.99) | Unsupported corrections incorrectly presented as corroborated speech | Removed all episode-specific rewrite branches; every edit now requires actual donor token indices, valid timing and sufficient donor confidence |
| P0 | \`find_matching_donor\` returned the first temporally overlapping phrase, ordered by phrase length, without a local lexical match | Nearby unrelated words could be treated as evidence | Replaced with local time **and** phonetic matching; ambiguous spans are rejected |
| P1 | Product-specific spellings and error variants were embedded in \`KNOWN_PHONETIC_PAIRS\` | Reference leakage into inference, overfit Episode 71 | Removed correction dictionary; tests retain known regressions without exposing ground-truth terms to the engine |
| P1 | Six reference-timed OneCLI mentions in donor; only one in the saved hybrid | Unique-term recall concealed five missing occurrences | Added donor-occurrence matching and six-variant repeat test; cached-data replay required before numerical claims |
| P1 | Fixed pattern cases for English compounds and Hebrew prefixes | Phrases outside the hard-coded list could not be corrected | Generic contiguous multiword candidates; prefix inference from phonetic fit; conservative rejection if identity unclear |
| P1 | Missing Soniox timestamps were silently coerced to zero | False synchronization with early audio | Preserve missing timestamps as null; reject malformed timing |
| P1 | Missing donor confidence was interpreted as 1.0 | False high-confidence evidence | Require actual model confidence; unknown confidence no longer triggers a rewrite |
| P2 | Subword assembly could merge speech across invalid/gapped timestamps; phrases could cross sentence boundaries | Incorrect word and phrase candidates | Validate token times, break at gaps, and reject punctuation-crossing phrase windows |
| P2 | Protected Hebrewized forms were finite and nominally enumerated | Inflected/unlisted loans vulnerable | Keep explicit protections plus conservative Hebrew suffix guard; mixed-script donor substitutions are rejected |
| P2 | Provenance recorded only textual donor claim and time | Weak auditability | Add exact donor/base token indices, source time, similarity and rejected candidate samples |

## Why the old aggregate metrics are inadequate

The historical 0.9556 weighted score used **unique** English term recall
(33/34), Hebrew-only character accuracy, glossary-limited precision, and
script *density*. It **excluded** timed occurrence recall, despite the
hybrid retaining only 35/46 verified mentions versus Soniox's 43/46.
Script-density similarity is not lexical script fidelity: a text could put
the right overall quantity of Latin characters in the wrong locations.
A glossary hit without a reference hit does not provide a comprehensive
hallucination check, and 100% *glossary-limited* precision does **not**
prove zero unsupported words, claims, or technical names.

The reviewed reference also contains manually confirmed non-technical
corrections (such as the Hebrew isolation wording) that a
**technical-term substitution engine** should not silently inject from the
reference. The remaining mistakes must be reported, not patched as
Episode 71-specific transcription substitutions.

## Design decisions

1. Keep ivrit.ai as an immutable base. Do not translate or paraphrase Hebrew.
2. Treat Soniox as **candidate evidence**, not the truth. Require time, donor
   confidence, and lexical/phonetic compatibility together.
3. Refuse candidate collisions and ambiguous spans rather than guessing.
4. Require stronger evidence when changing an all-Hebrew word than when
   repairing a partly Latin technical name.
5. Keep unrecognized Hebrewized loans intact, including productive suffixes.
6. Record source token indices for every amendment. A donor-provided phrase
   cannot be reused to justify several distinct edits.
7. Keep human annotations out of inference. The reference is exclusively
   for evaluation and regression development.

**Trade-off:** A strict engine may miss genuine English entities that both
models render very differently (e.g., short Hebrew approximations of product
names). These should be flagged for review, not invented.

## Available results and reproducible offline replay

Historical cached Episode 71 measurements (from the unchanged original output):

| Metric | Ivrit L4 | Soniox V5 | Old hybrid |
| --- | ---: | ---: | ---: |
| Unique technical-term recall | 20/34 | 32/34 | 33/34 |
| Timed technical-term occurrences | 21/46 | 43/46 | 35/46 |
| Hebrew-only character accuracy | 0.9099 | 0.8741 | 0.9123 |
| Script character-density score | 0.7960 | 0.4749 | 0.9918 |
| Old weighted composite | 0.7527 | 0.8958 | 0.9556 |

The new engine's exact cached-replay scores **have not been established by
this audit environment**. Do not replace the last column with synthetic
test expectations. To calculate objective results *offline* against all
three saved inputs, the frozen old hybrid, and the approved reference:

\`\`\`bash
python -m langtalks.fusion_audit_eval --output /tmp/podcasts-fusion-ep71-v2.json
pytest -q tests/test_langtalks_hybrid.py tests/test_langtalks_hybrid_v2.py tests/test_langtalks_scoring.py
\`\`\`

The replay generates legacy metrics alongside WER, whole-transcript CER,
known Hebrewized-loanword preservation, unique term recall, occurrence
recall, script density, and a **review-only** list of Latin words absent
from the reference. None of these additional measures changes the score
weights. The script never sends requests and refuses to overwrite existing
report paths. Existing archived ASR JSON and human references remain intact.

## Validation actually completed

The replacement algorithm passed 15 local synthetic offline tests covering
repeated named entities, six corrupted product spellings, phonetic Hebrew
clitics, missing/unconfident donor evidence, unrelated speech, loanword
preservation, compound English corrections, time separation, and invalid
configuration. New repository-level tests are committed on \`dev\`;
**the complete checked-out repository test suite and full Episode 71
cached replay were not executed in the current environment**.

## Open risks and acceptance gates

- The current phonetic approximation is intentionally simple; transliteration
  variants outside its coverage may be rejected, not corrected.
- Confidence is model-reported and uncalibrated. True error rates cannot be
  inferred from numeric confidence gates alone.
- Hebrew clitic inference can remain ambiguous, particularly with product
  names sharing common Hebrew consonants.
- Multiword candidates need further testing against timestamp drift and long
  uninterrupted English passages.
- The old timed matcher is tolerance-based, not a rigorously one-to-one
  temporal assignment. Its results remain diagnostic.
- \`agentים\` requires a morphology/loanword correction policy and
  \`ועידוד\` requires independent Hebrew transcription verification; the
  hybrid deliberately does not invent a rewrite for either.

**Recommendation:** NOT production-ready. First execute offline replay,
inspect every revised change (including regressions against Soniox and
ivrit.ai), and resolve any errors. If satisfactory, test on a separately
chosen **unseen** episode with independent human review. Only then consider
deployment; do not infer archive accuracy or safety from Episode 71.
