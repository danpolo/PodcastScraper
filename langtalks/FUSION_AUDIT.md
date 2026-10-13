# Hybrid fusion audit — evidence-based v2

**Repository/branch:** `danpolo/PodcastScraper` / `dev` only.  
**Benchmark:** LangTalks episode 71, 480–780 seconds, human-reviewed.  
**Status:** Offline validation successful; **not production-validated**. No external ASR requests, Modal invocations, archive backfills, or reference modifications were made.

## Executive finding

The original fusion engine was **not a reliable general-purpose aligner**. It applied episode-specific text substitutions even without donor agreement and fabricated donor confidence. Its headline 95.56% composite score concealed a severe repeated-mention regression: Soniox recognized six `OneCLI` occurrences; the old hybrid retained only one.

The replacement uses Soniox **as time-local evidence, not as authority**. It edits only when temporal alignment, phonetic/lexical compatibility, and model-reported confidence pass conservative checks. Every accepted edit links back to exact base and donor token indices.

## Prioritized audit and fixes

| Priority | Defect / risk | Remediation |
|---|---|---|
| P0 | Episode 71 hard-coded rewrites (`1.cli`, `והרמז`, etc.) executed **without** a corresponding donor observation | Removed the rewrite table and special compound branches; no donor evidence means no change |
| P0 | First time-overlapping donor phrase could win with no lexical alignment | Compare local candidate spans on timing, phonetics, and edit compatibility; reject ambiguity |
| P0 | Absent donor confidence was replaced by fabricated values around 0.95–0.99 | Require genuine numeric Soniox confidence; keep missing/invalid confidence from triggering an edit |
| P1 | Repeated proper nouns, split products, Hebrew affixes, and mixed-script stems were undercorrected | One-to-one donor occurrence use; token-span matching; evidence-based Hebrew clitic handling |
| P1 | Phrase fusion could consume correct neighboring words, drop punctuation, or romanize split Hebrew loanwords | Introduced span containment, per-word agreement, script/morphology protection, and no-style-only-change guards |
| P1 | Soniox missing times were coerced to 0s; weak subword confidence could be hidden in averages | Preserve null timestamps, validate ranges, retain word confidence plus subword floor |
| P1 | Fused token retained its original short span and stale ivrit confidence | Extend fused token time over its full base span and clear stale confidence; retain exact provenance |
| P2 | Unique term recall and Latin-script density overstated correctness; glossary precision did not cover hallucinations | Added strict one-to-one occurrence diagnostic, WER/CER, loanword recall, and review-only unsupported-Latin flags, with **no changes to old scoring weights** |
| P2 | Existing cached-benchmark test pointed to an absent `out/transcripts` folder and silently skipped; main CI lacked `pytest` | Added tracked-cache replay checks in offline CI and fixed the test environment |

## Reproducible Episode 71 results

All values below were recomputed with the **same current evaluation code and approved reference**, using only immutable cached outputs. Because this excerpt informed development, **none of these figures demonstrate generalization**.

| Metric | ivrit.ai L4 | Soniox V5 | Previous hybrid | Revised hybrid |
| --- | ---: | ---: | ---: | ---: |
| Unique technical terms | 20/34 (58.82%) | 32/34 (94.12%) | 33/34 (97.06%) | **32/34 (94.12%)** |
| Verified timed term occurrences¹ | 21/46 (45.65%) | **43/46 (93.48%)** | 35/46 (76.09%) | **42/46 (91.30%)** |
| `OneCLI` mentions | 0/6 | 6/6 | 1/6 | **6/6** |
| Hebrew-only character accuracy | 90.99% | 87.41% | 91.23% | **92.90%** |
| Whole-transcript WER ↓ | 11.85% | 18.33% | 11.06% | **9.79%** |
| Whole-transcript normalized CER ↓ | 8.18% | 11.50% | 7.80% | **6.54%** |
| Known Hebrewized loanword surface recall | 15/19 | 5/19 | 15/19 | **15/19** |
| Latin-script character-density similarity² | 79.60% | 47.49% | 99.18% | 90.04% |
| **Legacy weighted composite²** | 75.27% | 89.53% | 95.56% | 93.73% |

¹ Time alignment is a **one-to-one diagnostic**, still subject to word-timestamp uncertainty; not independent audio adjudication.  
² These aggregate/density scores remain for backward comparison **only**. The lower legacy score is not evidence of worse transcript quality: WER, CER, Hebrew accuracy, and occurrence recall all improved. Neither density nor glossary-limited precision proves absence of hallucinations.

**Delta versus previous hybrid:** +7/46 timed occurrences; `OneCLI` +5/6; Hebrew character accuracy +1.66 percentage points; WER −1.27 points; CER −1.26 points. Unique term coverage −1/34. The reference-independent algorithm makes **25** timed, donor-backed edits, preserving original ASR inputs.

## Accepted behavior and notable abstentions

Successful cached repairs include `OneCLI` in all six differing corruptions, `ה-dependency`, `ה-header`, `ו-Hermes`, `ב-runtime`, `ל-refresh token`, and `open source`. Hebrew prefixes attached to corrected terms remain visible. The engine rejects edits to split `האג'נט` tokens, common Hebrewized suffixes, unchanged English terms, and uncertain donor matches.

Four verified timed technical-term occurrences are still missed by the revised hybrid:

- `NanoClaw` at ~714.8s: corresponding Soniox candidate includes a low-confidence subword; the engine abstains
- `gateway` at ~629.5s: Hebrew phonetics remain too far from a safe Latin rewrite
- `process` at ~594.1s: donor and base speech/loanword forms disagree with the specific English surface
- `Log in with Google` at ~705.3s: the donor says `login with Google`; do not manufacture different wording

The transcript also retains `agentים`, `ועידוד`, and `Sum Security Best Practices`. These are genuine limitations against the human reference. The available donor text supports potential fixes in context, but correction would require more robust morphology/Hebrew-speech alignment or explicit review. No reference-derived rewrite was installed.

## Hallucination and provenance limitations

- **100% glossary-limited term precision is not a hallucination audit.** Technical names absent from the glossary, invented ordinary words, incorrect Hebrew, and contextually wrong substitutions still require inspection.
- Every applied edit has base/donor token indices, start/end times, confidence, similarity, and replacement text. Provenance demonstrates *why an edit was proposed*, **not that the resulting speech is verified**.
- Confidence values are model-provided, not calibrated probabilities. The reference-derived metrics do not independently confirm the episode's acoustic truth.
- A productive Hebrew suffix guard and simple consonant transliteration can reject genuine code-switches or occasionally accept false positives; some loanwords remain ambiguous without listening.
- The measured 15/19 known-loanword recall is **not exhaustive**; it is a finite vocabulary surface check.
- WER/CER conflate Hebrew morphology, punctuation, and code-switching; report them alongside the term and loanword metrics, not in place of them.

## Validation, reproducibility, and deliverables

The pinned development benchmark was replayed **offline** on GitHub Actions. The main project CI passed, and the focused fusion tests passed (45 passed, 1 skipped before the final reporting/quality-gate addition). References and saved baseline outputs are unchanged.

- [Full project CI (successful)](https://github.com/danpolo/PodcastScraper/actions/runs/38395972716)
- [Fusion regression tests and exact cached replay (successful)](https://github.com/danpolo/PodcastScraper/actions/runs/38395972763)

Run locally from the project root (no keys, network, or audio needed):

```bash
python -m pytest -q tests/test_langtalks_hybrid.py tests/test_langtalks_hybrid_v2.py tests/test_langtalks_strict_occurrence.py tests/test_langtalks_scoring.py tests/test_langtalks_fusion_quality_gate.py
python -m langtalks.fusion_audit_eval --output /tmp/fusion-episode71-comparison.json --merged-output /tmp/fusion-episode71-revised-hybrid.json
```

The offline CI also uploads both JSONs as a **30-day artifact** under the fusion workflow run. Its quality gate requires non-regression on timed mentions, WER, Hebrew-only CER-based accuracy, and known loanword preservation against the saved previous hybrid. This is a **development-set safety net**, not evidence of held-out generalization. The source files never overwrite existing outputs.

## Recommendation

**Ready for a new, unseen-episode *validation experiment*, but NOT production-ready.** Freeze this algorithm and its thresholds before selecting a new episode. Choose an episode independently (different guest/vocabulary if possible), collect human review without using it to tune the algorithm, and report all standalone and fused metrics plus per-edit false positives, omissions, prefix/morphology errors, and code-switch fidelity. Require zero severe unsupported rewrites before considering deployment. Keep production/archival fusion disabled until such a held-out review passes.
