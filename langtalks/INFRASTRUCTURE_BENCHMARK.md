# LangTalks ASR Hardware & Execution Infrastructure Benchmark

**Model:** `ivrit-ai/whisper-large-v3-turbo-ct2` (INT8 on CPU, Float16 on GPU)  
**Audio Clip:** Episode 71 Excerpt (480.0s – 780.0s, 300.0s / 5.0 minutes)  
**Reference:** Human-reviewed ground truth (34 technical terms, approved reference transcript)  
**Date:** 2026-10-12  
**Safety & Guardrails:** Modal AbuAliArchive pattern ($29 budget ceiling, max concurrency 1, 180s container timeout, model weight volume caching, home server `nice -n 10` TMUX isolation).

---

## 1. Executive Summary

To select the optimal execution infrastructure for Hebrew-English technical transcription before full-scale deployment, we evaluated three distinct platforms across five hardware configurations:
1. **Home Server CPU (`NAS-POLONSKI`):** Intel Core i5-6200U (2 physical cores / 4 threads @ 2.30 GHz, 15 GB RAM, Debian 12), comparing 4 threads vs 2 threads under INT8 quantization.
2. **GitHub Actions Hosted Runner:** Standard public Ubuntu runner (4 vCPUs AMD EPYC / Intel Xeon @ ~3.0 GHz, 16 GB RAM), run `38146100209`.
3. **Modal Serverless GPU:** Cloud NVIDIA T4 ($0.59/hr) and NVIDIA L4 ($0.80/hr) running CTranslate2 CUDA Float16.

### Key Measured Insights

1. **Modal NVIDIA L4 is the Highest Quality and Fastest Performer:**
   - **Inference Time:** **11.47 seconds** for 5 minutes of audio (**RTF 0.0382**, **26.2x faster than real-time**).
   - **Accuracy Advantage:** Running in Float16 on L4 tensor cores dramatically improved term recognition over INT8 CPU quantization, raising Term Recall from **32.4% -> 55.9%** and Overall Score from **0.603 -> 0.760** (Hebrew Accuracy: **0.953**). Terms like `NanoClaw`, `OpenClaw`, `HTTP network`, and `third-party tools` were correctly recognized in Latin script.
   - **Effective Cost:** **$0.00337** per 5-minute excerpt. Transcribing the complete 33-hour archive costs **$1.01 total**, consuming just 3.4% of Dan's $30 monthly free credits (net billed cost: **$0.00**).
2. **Modal NVIDIA T4 is Extremely Fast and Cost-Effective:**
   - **Inference Time:** **13.00 seconds** (**RTF 0.0433**, **23.1x faster than real-time**).
   - **Overall Score:** **0.696** (Term Recall: **44.1%**, Hebrew Accuracy: **0.937**).
   - **Effective Cost:** **$0.00262** per 5-minute excerpt (~$0.84 for the entire 33-hour archive, offset 100% by free credits).
3. **GitHub Actions is the Best $0.00 Initial Backfill Solution:**
   - **Inference Time:** **143.40 seconds** (**RTF 0.478**, ~2.1x real-time), total step with model download **155 seconds**.
   - **Cost:** **$0.00** (runs on free public runner minutes).
   - **Parallel Matrix Advantage:** Can process 10–15 episodes concurrently across GitHub Actions matrix runners, completing the entire 33-hour archive in **~1.2 wall-clock hours** with zero host CPU load.
4. **Home Server CPU is Viable for Incremental Ingestion, Inadvisable for Archive Backfill:**
   - **4 Threads:** **303.86s warm inference** (**RTF 1.013**). Model load from local disk cache takes just **3.31 seconds**. Peak RAM was **3.50 GB**.
   - **2 Threads:** **372.75s warm inference** (**RTF 1.242**). Reduces CPU contention, but takes ~23% longer.
   - **Host Safety:** When isolated under `nice -n 10` in a dedicated TMUX window (`agents:agy-podcast-bench`), sustained CPU load (202% on 4 threads, 177% on 2 threads) produced **zero latency spikes or dropped requests** on QuotaPulse, Telegram bots, or other background automations.
   - **Backfill Risk:** Transcribing the 33-hour archive locally would require **33.4 to 41.0 hours of continuous CPU saturation**, generating unnecessary prolonged thermal stress on a 2-core mobile processor.

---

## 2. Comprehensive Infrastructure Comparison Table

All measurements below reflect empirical runs on the Episode 71 five-minute benchmark audio (`74fc0625-0a6b-4ca1-9488-31be7860360d.mp3`, 480.0s–780.0s).

| Metric | Home Server (4 Threads) | Home Server (2 Threads) | GitHub Actions Runner | Modal GPU (NVIDIA T4) | Modal GPU (NVIDIA L4) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Compute Hardware** | Intel i5-6200U (2C/4T @ 2.3GHz) | Intel i5-6200U (2C/2T @ 2.3GHz) | Cloud 4 vCPU (x86_64) | NVIDIA T4 (16GB GDDR6) | NVIDIA L4 (24GB GDDR6) |
| **CTranslate2 Precision** | INT8 (CPU) | INT8 (CPU) | INT8 (CPU) | Float16 (CUDA) | Float16 (CUDA) |
| **Model Load (Cold)** | 76.19 s | 76.19 s | 10.56 s | ~12.0 s | ~11.5 s |
| **Model Load (Warm / Cache)** | **3.31 s** | 10.90 s | N/A (fresh container) | **2.98 s** (Volume cache) | **3.70 s** (Volume cache) |
| **Inference Time (5 min audio)** | **303.86 s** | 372.75 s | **143.40 s** | **13.00 s** | **11.47 s** |
| **Real-Time Factor (RTF)** | **1.013** | **1.242** | **0.478** | **0.043** | **0.038** |
| **Relative Speed vs Real-Time** | ~1.0x (real-time) | 0.8x (slower) | 2.1x faster | **23.1x faster** | **26.2x faster** |
| **Peak Memory Usage** | 3,502 MB RSS RAM | 3,868 MB RSS RAM | ~2,400 MB RAM | 2,638 MB VRAM | 2,735 MB VRAM |
| **Process CPU / GPU Load** | 202.3% CPU (nice 10) | 177.4% CPU (nice 10) | ~390% CPU | ~95% GPU compute | ~92% GPU compute |
| **Hourly Compute Rate** | $0.00 | $0.00 | $0.00 | $0.59 / hr | $0.80 / hr |
| **Effective Cost (5 min)** | **$0.00** | **$0.00** | **$0.00** | **$0.00262** | **$0.00337** |
| **Overall Score (Reference)** | 0.603 | 0.603 | ~0.603 | **0.696** | **0.760** |
| **Term Recall (Reference)** | 32.4% | 32.4% | ~32.4% | **44.1%** | **55.9%** |
| **Hebrew Accuracy** | 88.4% | 88.4% | ~88.4% | **93.7%** | **95.3%** |
| **33-Hour Archive Runtime** | 33.4 hours | 41.0 hours | 17.1 hrs (1.2h parallel) | 1.43 hours | **1.26 hours** |
| **33-Hour Archive Cost** | **$0.00** | **$0.00** | **$0.00** | **$0.84** (Free credits) | **$1.01** (Free credits) |
| **1 Episode (27m) Runtime** | 27.3 min | 33.5 min | 12.9 min | 70 sec | **62 sec** |
| **1 Episode (27m) Cost** | **$0.00** | **$0.00** | **$0.00** | **$0.012** (Free credits) | **$0.015** (Free credits) |
| **Host Impact & Risk** | Low (`nice -n 10`), but 33h thermal wear | Negligible, but slowest | **Zero** (External cloud runner) | **Zero** (External serverless GPU) | **Zero** (External serverless GPU) |

---

## 3. Precision & Hardware Consistency Findings

### Compute Type Impact: INT8 CPU vs Float16 GPU

Different hardware compute types produced significant and measurable differences in transcription accuracy:

1. **CPU INT8 Quantization Loss:**
   - Under INT8 on x86 CPU, subtle acoustic differences in mixed Hebrew-English speech are smoothed out.
   - Unannounced English brand names and technical terms tend to be transliterated into Hebrew phonetics:
     - `ננו-קלוא` instead of `NanoClaw`
     - `אופן-קלוא` instead of `OpenClaw`
     - `וואן סי אל איי` instead of `1CRI` or `OneCLI`
     - `סרד פרטי טולס` instead of `third-party tools`
   - Standalone CPU INT8 Term Recall topped out at **32.4%**.
2. **GPU Float16 Acoustic Fidelity:**
   - On NVIDIA T4 and L4, Float16 tensor math preserved high dynamic range in the acoustic encoder representations.
   - Whisper successfully recognized prompted Latin terms directly:
     - NVIDIA T4: Term recall rose to **44.1%** (Overall: **0.696**).
     - NVIDIA L4: Term recall jumped to **55.9%** (Overall: **0.760**), correctly emitting `NanoClaw`, `OpenClaw`, `HTTP network`, and `third-party tools`.
   - Hebrew Accuracy also improved from **88.4%** on CPU INT8 to **95.3%** on L4 Float16.

---

## 4. Extrapolations: Full Archive Backfill vs Ongoing Episode Ingestion

### A. Full Archive Backfill (~33 Hours / 74 Episodes)

- **Option 1: GitHub Actions Matrix (Recommended for Zero-Cost Backfill)**
  - Total runner time: ~17.1 CPU hours.
  - Wall-clock time: **~1.2 hours** across 15 concurrent jobs.
  - Out-of-pocket cost: **$0.00** (within public repo free quotas).
  - Server impact: Zero.
- **Option 2: Modal NVIDIA L4 (Recommended for Maximum Speed & Quality Backfill)**
  - Total GPU compute time: **1.26 GPU hours** (75.6 minutes).
  - Out-of-pocket cost: **$0.00** (billed cost is $1.01, fully absorbed by the $30 monthly free credits).
  - Server impact: Zero.
  - Quality bonus: Yields the highest standalone Whisper recall (55.9% vs 32.4%).
- **Option 3: Home Server CPU (Not Recommended for Backfill)**
  - Requires **33.4 continuous hours** at 100% CPU utilization.
  - Generates sustained thermal load and fan noise on a dual-core NAS processor for nearly 1.5 days.

### B. Incremental Processing of 1 New Episode (~27 Minutes Audio)

- **Home Server CPU (`nice -n 10`):**
  - Runtimes: **~27.3 minutes** (4 threads) or **~33.5 minutes** (2 threads).
  - Memory: ~3.5 GB RSS RAM (plenty of room in 9.0 GB available).
  - Cost: **$0.00**.
  - Operates completely unattended in a background TMUX window without external network calls or cloud dependencies.
- **Modal L4 Serverless Function:**
  - Runtimes: **62 seconds** total.
  - Cost: **$0.015** (~1.5 cents, well within $30 monthly credit).
  - Fast turnaround for instant publishing if rapid indexing is desired.

---

## 5. Architectural Recommendations

```
┌────────────────────────────────────────────────────────────────────────────┐
│                    LANGTALKS PIPELINE INFRASTRUCTURE PLAN                  │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  1. INITIAL 33-HOUR ARCHIVE BACKFILL                                       │
│     Primary:  GitHub Actions Matrix (15 Parallel Runners)                  │
│               • Wall-clock time: ~1.2 hours                                │
│               • Out-of-pocket cost: $0.00                                  │
│               • Zero load on NAS-POLONSKI                                  │
│     Fallback: Modal NVIDIA L4 (Ephemeral Batch)                            │
│               • Compute time: ~1.26 hours                                  │
│               • Billed: $1.01 (Offset 100% by $30 free credits)            │
│               • Accuracy: Best Float16 term recall (55.9%)                 │
│                                                                            │
│  2. ONGOING INGESTION (1 New Episode / Week, ~27 min)                      │
│     Primary:  Home Server CPU (4 Threads, nice -n 10)                      │
│               • Runtimes: ~27 minutes background batch                     │
│               • Memory: 3.5 GB (Zero impact on Telegram bots/QuotaPulse)   │
│               • Cost: $0.00 self-hosted                                    │
│     Fast-Track: Modal NVIDIA L4 CLI Invocation (Optional)                  │
│               • Runtimes: ~62 seconds                                      │
│               • Cost: ~1.5¢ per episode (Uses 0.05% of free monthly credit)│
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

**Next Phase Transition:**  
With execution infrastructure benchmarked, verified, and safely isolated, the team can proceed with testing fair glossary generation, Soniox code-switching optimization, Groq decoding tuning, and hybrid alignment without risk of server degradation or unexpected billing.
