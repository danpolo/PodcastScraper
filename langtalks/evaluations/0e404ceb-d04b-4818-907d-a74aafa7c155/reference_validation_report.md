# Episode 74 Held-Out Reference C: Semantic Audit Validation Report

**Episode:** 74 - Jev (`0e404ceb-d04b-4818-907d-a74aafa7c155`)  
**Status:** Frozen Ground-Truth Reference C (`v1.0-frozen`)  
**Date:** 2026-10-21  

---

## 1. Provenance & Authority Separation

Under the approved evaluation protocol and Dan's explicit instructions:
- **Transcript Authority:** Human-corrected in Subtitle Edit by Dan (`reference_user_corrected.original.srt`, SHA-256: `e5e2245dc8126bfc1fd6394cb6f4bfceeff06851ce1471fcb583cdd1365a5d53`). Spoken Hebrew/English words, inflection, and clitics are treated as authoritative.
- **Terminology Review Authority:** Assistant text-based semantic audit conducted independently by ChatGPT (`ep74_semantic_audit.json`, SHA-256: `598d92e0c0f7022b287b5601c6baa51b79f4cd94b366a58459e80824e1849cd0`).
- **Timing Alignment:** Derived from hybrid ASR token boundaries (`asr_token_aligned`) and position-proportional cue interpolation (`approximate_character_interpolated`). Timestamps are deterministic machine alignments, not individually human/audio-verified.

---

## 2. Quantitative Summary

| Metric | Proposed Draft | Final Reference C | Change |
| :--- | :--- | :--- | :--- |
| **Total Occurrences** | 330 | **361** | +31 (+35 additions, +1 split, -5 exclusions) |
| **Total Concepts** | 101 | **110** | +9 (new/reassigned concepts) |
| **Cross-Script Concepts** | 50 | **79** | +29 |
| **Uncertain Concepts** | 50 | **49** | -1 (resolved via audit) |
| **Excluded Mentions** | 0 | **9** | +9 (4 idioms, 1 nested token, 4 rejected suggestions) |
| **Scannable Cues** | 287 | 287 | Preserved 100% |

---

## 3. Occurrence Modifications (Audit Adjudication)

### 3.1 Inflection & Surface Normalization (4 occurrences)
- **Occ 54** (`turn-0039`), **Occ 59** (`turn-0045`), **Occ 61** (`turn-0046`), **Occ 183** (`turn-0169`):
  Surface was truncated to `LLM`; corrected to exact spoken Hebrew plural surface `LLM'ים` with Hebrew morphology `stem='LLM'`, `suffix="'ים"`.

### 3.2 Semantic Reassignments (16 occurrences)
- **Adjectival Agentic Expressions (7 occurrences):**
  Occs 41, 42 (`האג'נטי`, turn-0022), 108 (`אג'נטית`, turn-0091), 148 (`האג'נטיות`, turn-0135), 149 (`אג'נטיים`, turn-0137), 165 (`האג'נטיים`, turn-0155), 322 (`האיג'נטי`, turn-0271).
  *Reassigned from generic `AI agent` entity to `Agentic behavior` (adjective/process).*
- **Boolean Literal Values (3 occurrences):**
  Occ 38 (`true`, turn-0019), Occ 36 (`false`, turn-0019), Occ 37 (`false`, turn-0019).
  *Reassigned from `boolean` datatype to `Boolean literal`, with distinct word alignments (36: 118.19–118.43, 38: 118.61–118.71, 37: 118.87–118.99).*
- **Thinking Mode vs Tokens (3 occurrences):**
  Occ 197 (`thinking`, turn-0181), Occ 235 (`thinking`, turn-0205), Occ 236 (`thinking`, turn-0205).
  *Reassigned from `thinking tokens` to `Thinking / reasoning mode`, with distinct retimed intervals for turn-0205 (235: 1314.99–1315.25, 236: 1315.63–1315.89).*
- **Platform vs Spaces (1 occurrence):**
  Occ 65 (`מהגיד פייס`, turn-0048).
  *Reassigned from `Hugging Face Spaces` to `Hugging Face` (organization).*
- **Textual Features (1 occurrence):**
  Occ 102 (`פיצ'רים`, turn-0085).
  *Reassigned from `Feature extraction` action to `Text features` concept.*
- **Model-Based Judging (1 occurrence):**
  Occ 247 (`judging`, turn-0212).
  *Reassigned from `LLM judging` to `Model-based judging` (judging with non-LLM Jev classifier).*

### 3.3 Splits & Disambiguation (1 occurrence)
- **Occ 28** (`true false`, turn-0014):
  Split into two distinct occurrences under `Boolean literal`:
  - Occ 28: `true` (86.43–86.67s, `asr_token_aligned`)
  - Occ 331: `false` (86.67–87.03s, `asr_token_aligned`)

### 3.4 Expansions & Cross-Cue Phrases (4 occurrences)
- **Occ 186** (`Flash`, turn-0174): Expanded to full model version `ג'מיני 3.8 Flash` (1113.67–1115.99s).
- **Occ 198** (`thinking`, turn-0182): Expanded to full multiword term `ה-thinking tokens` (1162.43–1163.25s).
- **Occ 227** (`Flash`, turn-0199): Expanded to cross-cue multiword term `ג'מיני Flash` spanning `turn-0198` and `turn-0199` (1268.51–1269.79s).
- **Occ 175** (`לבאלק`, turn-0164): Expanded to cross-cue multiword term `לבאלק אופריישנס` spanning `turn-0164` and `turn-0165` (1046.79–1050.69s).
- **Occ 240** (`browser`, turn-0208): Expanded and reassigned to `browser use` (canonical `Browser use`, 1339.01–1339.97s).

### 3.5 Specific Renames & Domain Nuances (2 occurrences)
- **Occ 229** (`gpt 5.6`, turn-0200): Specific model canonical `GPT-5.6`.
- **Occ 276** (`בlaw`, turn-0235): Reassigned from `legal tech` to vertical domain `Law`.

### 3.6 Timestamp Retimings (2 occurrences)
- **Occ 288 & 289** (`SLA`, turn-0243): Disambiguated duplicate timestamps from identical 1563.63–1564.07s into:
  - Occ 288: 1563.31–1563.63s
  - Occ 289: 1563.63–1564.07s

---

## 4. Benchmark Exclusions

| Occ ID / Sug ID | Expression | Canonical | Cue ID | Rationale |
| :--- | :--- | :--- | :--- | :--- |
| **Occ 199** | `tokens` | token | `turn-0182` | Nested inside multiword expression `thinking tokens`; excluded to prevent double counting. |
| **Occ 63** | `best in Class` | best in class | `turn-0047` | General conversational idiom; excluded from strict technical concept inventory. |
| **Occ 107** | `double down` | double down | `turn-0090` | General conversational idiom; excluded from strict technical concept inventory. |
| **Occ 228** | `sweet spot` | sweet spot | `turn-0200` | General conversational idiom; excluded from strict technical concept inventory. |
| **Occ 330** | `סילבר בולט` | Silver bullet | `turn-0286` | General conversational idiom; excluded from strict technical concept inventory. |
| **Sug 25** | `browser use` | Browser use | `turn-0208` | Duplicate with Occurrence 240, which was already expanded to `browser use`. |
| **Sug 26** | `ג'מיני` | Gemini | `turn-0174` | Nested inside multiword model expression `ג'מיני 3.8 Flash` (Occ 186). |
| **Sug 27** | `ג'מיני` | Gemini | `turn-0198` | Nested inside cross-cue multiword model expression `ג'מיני Flash` (Occ 227). |
| **Sug 30** | `לקונטקסט` | context | `turn-0010` | Nested inside multiword concept `context window` (`לקונטקסט ווינדוס`, Occ 21). |

---

## 5. Candidate Additions from Audit (35 Accepted)

- **`use case` (5 occurrences):** `יוזקיסים` (turn-0033), `יוז קייס` (turn-0166), `יוז קייסים` (turn-0172, turn-0226, turn-0285).
- **`repository` (6 occurrences):** `הריפו` (turn-0081), `ריפוים` (turn-0081), `ריפואים` (turn-0097, turn-0099 [3 distinct mentions]).
- **`batch` (1 occurrence):** `באץ'` (turn-0038).
- **`benchmark` (2 occurrences):** `בנצ'מארקים` (turn-0201, turn-0202).
- **`state` (1 occurrence):** `ובסטייט` (turn-0010).
- **`token` (3 occurrences):** `טוקן` (turn-0055 [2 distinct mentions: טוקן ביי טוקן], turn-0178).
- **`cache` (2 occurrences):** `קאש` (turn-0040), `קאש היט` (turn-0041).
- **`labels` (2 occurrences):** `כלייבלים` (turn-0015), `הלייבלים` (turn-0024).
- **`latency` (1 occurrence):** `לייטנסיה` (turn-0204).
- **`gradual discovery` (1 occurrence):** `gradual discovery` (turn-0093).
- **`tool calling` (1 occurrence):** `tool call` (turn-0217).
- **`Gemini` (2 occurrences):** `וג'מיני` (turn-0204), `ג'מיני` (turn-0204).
- **`context` (7 occurrences):** `הקונטקסט` / `קונטקסט` (turn-0017, turn-0032, turn-0072, turn-0103, turn-0145, turn-0151, turn-0160).
- **`Computer use` (1 occurrence):** `computer use` (spanning turn-0208 and turn-0209).

---

## 6. Residual Ambiguities & Denominator Handling

1. **Occ 137 (`-pobability`, turn-0118):** Surface spelling indicates a spoken slip or clitic detachment at cue boundary. Retained under `Probability` with explicit `uncertainty_flag = True`.
2. **Occ 270 (`רלבילי`, turn-0230):** Hebrewized adjective (reliable) referring to production suitability. Retained under `reliable / reliability` with `uncertainty_flag = True`.
3. **Strict Scorable Denominators:**
   - Total verified occurrences in Reference C: **361**
   - Verified scorable occurrences excluding residual uncertainties: **359** (excluding Occ 137 and Occ 270 from strict surface matching).
