# Episode 74 Held-Out Evaluation Report

**Protocol:** Held-out full-episode transcription evaluation protocol (v1.1)  
**Episode:** 74 - Jev (`0e404ceb-d04b-4818-907d-a74aafa7c155`)  
**Duration:** 1,848.89s (~30.8 minutes)  
**Date:** 2026-10-21  
**Guardrails Passed:** ✅ YES  

---

## 1. Executive Summary & Verdict

The revised Hebrew/English fusion engine (**`hybrid_modal_ivrit_l4_soniox`**) was evaluated against the authoritative human-corrected transcript and finalized Reference C.

### Key Generalization Findings:
1. **Whole-Episode Transcript Accuracy Dramatically Improved:**
   - **WER dropped from 4.20% (Base) to 2.39% (Revised Hybrid)** — a **43.1% relative reduction in word errors**.
   - **CER dropped from 2.44% to 1.02%** — a **58.2% relative reduction in character errors**.
   - **Hebrew Character Accuracy increased from 97.53% to 99.12%** (raw Hebrew errors reduced from 351 to 125).
2. **Technical Terminology Recognition Generalized Across Episode:**
   - **Unique Technical-Concept Recall:** Rose from **85.45%** (Base) to **94.55%** (Revised Hybrid), missing only 6 concepts compared to 16 missed by Base.
   - **One-to-One Timed Occurrence Recall (Strict Spoken Surface):** Rose from **74.65%** (268/359) to **86.35%** (310/359) — capturing **42 additional correctly timed occurrences** without sacrificing precision (**80.73%** vs Base 80.48%).
   - **Canonical Concept Recognition:** Reached **86.35%** recall with **80.73%** precision.
3. **Purity of Fusion Modifications:**
   - All **46 fusion modifications** were audited: **44 fixed ASR errors (+1)**, **2 were neutral orthographic variants (0)**, and **0 introduced errors (-1)**.
   - **Zero severe regressions:** No invented products, no omitted speech, and no altered Hebrew negations.
4. **Guardrail Verdict:**
   - Revised fusion **passed every predeclared favorable-evidence check** without regression against its base model.

---

## 2. Comparative Benchmark Matrix

| Metric | Base (`modal_ivrit_l4`) | Donor (`soniox`) | Revised Hybrid (`v2`) | Gain over Base |
| :--- | :--- | :--- | :--- | :--- |
| **Word Error Rate (WER)** | 4.20% (163/3,885) | 12.43% (483/3,885) | **2.39% (93/3,885)** | **-1.81% (-43% rel)** |
| **Character Error Rate (CER)** | 2.44% (472/19,374) | 7.89% (1,528/19,374) | **1.02% (197/19,374)** | **-1.42% (-58% rel)** |
| **Hebrew-Only Character Accuracy** | 97.53% (351 errors) | 91.46% (1,211 errors) | **99.12% (125 errors)** | **+1.59% (+226 chars)** |
| **Unique Concept Recall (TP / 110)** | 85.45% (94/110) | 89.09% (98/110) | **94.55% (104/110)** | **+9.10% (+10 concepts)** |
| **Unique Concept Misses (FN / 110)** | 16 concepts | 12 concepts | **6 concepts** | **-10 misses** |
| **Timed Occurrence Recall (Strict Surface)** | 74.65% (268/359) | 52.92% (190/359) | **86.35% (310/359)** | **+11.70% (+42 occs)** |
| **Timed Occurrence Precision (Strict Surface)**| 80.48% (268/333) | 48.97% (190/388) | **80.73% (310/384)** | **+0.25%** |
| **Canonical Concept Recall** | 74.65% (268/359) | 74.65% (268/359) | **86.35% (310/359)** | **+11.70%** |
| **Canonical Concept Precision** | 80.48% (268/333) | 69.07% (268/388) | **80.73% (310/384)** | **+0.25%** |

*Note: Previous hybrid (v1) was not cached for Episode 74 and is labeled unavailable per protocol Section 6/8.*

---

## 3. Cross-Script & Hebrewized Concept Linking Breakdown

Evaluated on the **359 scorable occurrences** across three script categories:

| Script Surface Type | Total Reference Mentions | Base Strict Recall | Donor Strict Recall | Hybrid Strict Recall |
| :--- | :--- | :--- | :--- | :--- |
| **Hebrew-only Script** (e.g., `ההרנס`, `ספייסים`, `ריפואים`) | 165 | 70.30% (116/165) | 16.97% (28/165) | **83.64% (138/165)** |
| **Latin-only Script** (e.g., `LLM`, `Jev`, `RAG`, `Claude Code`) | 127 | 78.74% (100/127) | 88.98% (113/127) | **89.76% (114/127)** |
| **Mixed-Script** (e.g., `בJev`, `ל-LLM`, `LLM'ים`, `ב-RAG`) | 67 | 77.61% (52/67) | 73.13% (49/67) | **86.57% (58/67)** |

### Key Diagnostic Insight:
- **Soniox Failure on Hebrewized Loanwords:** Donor model collapsed to **16.97%** on Hebrew-script loanwords because it forcefully transliterated them into English letters, violating the bilingual spoken policy.
- **Base Model Gap on English Acronyms:** Base model struggled with code-switched multiword terms (e.g., `vector database`, `DOM elements`, `low medium high risk`).
- **Hybrid Synergy:** The revised hybrid retained the Base model's faithful Hebrewized loanword representations while selectively adopting the Donor's high-confidence Latin terms.

---

## 4. Terminology Layers Analysis (A vs C and B vs C)

### 4.1 Layer A (Pre-ASR Machine Glossary Prior) vs Reference C
- **Glossary A Size:** 132 terms
- **Literal Coverage of Reference C:** 22.73% (25 / 110 concepts)
- **Alias-Aware Coverage of Reference C:** 26.36% (29 / 110 concepts)
- **Anticipation Misses (In C, absent in A):** 81 concepts (e.g., `A/B testing`, `AGENTS.md`, `Agentic search`, `Autonomous driving`, `Bulk operations`, `Computer use`, `DOM`, `DeBERTa`).
- **Unspoken Prior Terms (In A, absent in C):** 103 terms (e.g., `Anthropic`, `CI/CD`, `Codex`, `Docker`, `Git`, `Kubernetes`).
- **Takeaway:** Pre-ASR glossary provides useful domain hints but captures only ~26% of actual conversational vocabulary.

### 4.2 Layer B (Post-ASR Machine Observation) vs Reference C
- **Candidate Concepts Detected:** 186
- **True Positive Concepts:** 65 (Precision: **34.95%**)
- **False Positive Candidates:** 121 (noisy candidate discovery)
- **Missed Reference Concepts:** 48 (Recall: **56.36%**)
- **Takeaway:** Unfiltered machine concept discovery suffers from high candidate noise (35% precision), highlighting why Reference C ground-truth review was critical.

---

## 5. Fusion Modification Audit (46 Modifications)

- **Total Modifications:** 46
- **Fixed ASR Errors:** **44 (95.7%)**
- **Neutral Orthographic Variants:** **2 (4.3%)**
- **Introduced Errors:** **0 (0.0%)**
- **Severe Regressions / Hallucinations:** **0 (0.0%)**

### Representative Corrective Edits:
1. `לואו, מידיום, היי, ריסק` → `low medium high risk` (Edit 1, conf: 0.9989)
2. `סיסטם פרומפט,` → `system prompt,` (Edit 3, conf: 0.9979)
3. `לווקטור דאטאבייס,` → `ל-vector database,` (Edit 4, conf: 0.9930)
4. `דום אלמנטס` → `DOM elements` (Edit 6, conf: 0.9730)
5. `הטול קולינג` → `ה-tool calling` (Edit 7, conf: 0.9917)
6. `לקלוד קוד` → `ל-Claude Code` (Edit 8, conf: 0.8761)
7. `טיים סירייס,` → `time series,` (Edit 10, conf: 0.9677)

---

## 6. Remaining Failures & Next Development Priorities

### 6 Concepts Still Missed by Revised Hybrid:
1. `DOM` (standalone mention in cue 209: `DOM elements` captured, but standalone `DOM` missed)
2. `harness` (`ההרנס` in cue 4 recognized as `בארנס`)
3. `PR Score` (`PR Score` in cue 224 transcribed as `PR score`)
4. `legal tech` (`בlaw` in cue 235 not linked to legal tech)
5. `questions` (`Questions` in cue 226)
6. `safe to merge` (`safe to merge` in cue 224)

### Development Priorities:
1. **Phonetic Anchor Alignment for Hebrew Loanwords:** Refine acoustic alignment for tricky loanword onsets (e.g., `ההרנס` vs `בארנס`).
2. **Compound Subphrase Sensitivity:** Improve boundary handling for technical compounds where both the compound and its constituent are mentioned in proximity (e.g., `DOM elements` and `DOM`).
3. **Multi-Episode Generalization:** Validate on additional held-out episodes with varied audio quality, acoustic reverberation, and multiple concurrent speakers.
