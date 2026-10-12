"""Hardware and infrastructure benchmark for ivrit-ai/whisper-large-v3-turbo-ct2.

Measures:
1. Model loading time (cold vs warm).
2. Transcription time and Real-Time Factor (RTF = duration / audio_seconds).
3. System resource usage (peak RAM RSS in MB, sustained CPU load %).
4. Output transcription accuracy against human-reviewed ground truth.
5. Thread scaling (2 CPU threads vs 4 CPU threads).
"""

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Any, List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psutil
from faster_whisper import WhisperModel

from langtalks.feed import fetch_episodes
from langtalks.glossary import build, context_prompt
from langtalks.score import load_reference, score

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("hardware_bench")

ROOT = Path(__file__).resolve().parent.parent
EXCERPT_DIR = ROOT / "langtalks" / "out" / "excerpts"
TRANSCRIPT_DIR = ROOT / "langtalks" / "out" / "transcripts"
REFERENCE_DIR = ROOT / "langtalks" / "reference"
BENCH_RESULTS_DIR = ROOT / "langtalks" / "out" / "benchmarks"


class ResourceMonitor:
    """Background monitor sampling process RSS and CPU usage."""

    def __init__(self, interval: float = 0.5):
        self.interval = interval
        self.stop_event = threading.Event()
        self.thread = None
        self.process = psutil.Process()
        self.rss_samples: List[float] = []
        self.cpu_samples: List[float] = []
        self.system_cpu_samples: List[float] = []

    def _monitor(self):
        while not self.stop_event.is_set():
            try:
                mem = self.process.memory_info().rss / (1024 * 1024)  # MB
                cpu = self.process.cpu_percent(interval=None)
                sys_cpu = psutil.cpu_percent(interval=None)
                self.rss_samples.append(mem)
                self.cpu_samples.append(cpu)
                self.system_cpu_samples.append(sys_cpu)
            except Exception:
                pass
            time.sleep(self.interval)

    def start(self):
        self.stop_event.clear()
        self.process.cpu_percent(interval=None)  # prime cpu_percent
        psutil.cpu_percent(interval=None)
        self.thread = threading.Thread(target=self._monitor, daemon=True)
        self.thread.start()

    def stop(self) -> Dict[str, float]:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2.0)
        peak_rss = max(self.rss_samples) if self.rss_samples else 0.0
        avg_cpu = sum(self.cpu_samples) / len(self.cpu_samples) if self.cpu_samples else 0.0
        avg_sys_cpu = sum(self.system_cpu_samples) / len(self.system_cpu_samples) if self.system_cpu_samples else 0.0
        return {
            "peak_rss_mb": round(peak_rss, 1),
            "avg_process_cpu_pct": round(avg_cpu, 1),
            "avg_system_cpu_pct": round(avg_sys_cpu, 1),
            "samples_count": len(self.rss_samples),
        }


def run_single_benchmark(
    audio_path: Path,
    episode,
    cpu_threads: int,
    run_label: str,
    model_name: str = "ivrit-ai/whisper-large-v3-turbo-ct2",
) -> Dict[str, Any]:
    """Run transcription with full resource monitoring and scoring."""
    logger.info("=== Running benchmark: %s (cpu_threads=%d) ===", run_label, cpu_threads)
    monitor = ResourceMonitor(interval=0.5)

    # 1. Model Loading
    t0_load = time.perf_counter()
    monitor.start()
    model = WhisperModel(
        model_name,
        device="cpu",
        compute_type="int8",
        cpu_threads=cpu_threads,
    )
    t_load = time.perf_counter() - t0_load
    load_metrics = monitor.stop()
    logger.info("Model loaded in %.2fs (Peak RSS: %.1f MB)", t_load, load_metrics["peak_rss_mb"])

    # Build prompt matching production / previous pipeline
    prompt = context_prompt(episode, build(episode))[:600]

    # 2. Transcription
    monitor = ResourceMonitor(interval=0.5)
    t0_infer = time.perf_counter()
    monitor.start()

    segments, info = model.transcribe(
        str(audio_path),
        language="he",
        beam_size=5,
        initial_prompt=prompt,
        word_timestamps=True,
        vad_filter=True,
    )
    segments_list = list(segments)
    t_infer = time.perf_counter() - t0_infer
    infer_metrics = monitor.stop()

    audio_duration = 300.0  # 5 minutes excerpt
    rtf = t_infer / audio_duration
    logger.info("Inference completed in %.2fs (RTF: %.3f, Peak RSS: %.1f MB, CPU: %.1f%%)",
                t_infer, rtf, infer_metrics["peak_rss_mb"], infer_metrics["avg_process_cpu_pct"])

    # 3. Format words and transcript payload
    words = []
    full_text_pieces = []
    for seg in segments_list:
        full_text_pieces.append(seg.text)
        for w in seg.words or []:
            words.append({
                "text": w.word,
                "start": round(w.start + 480.0, 2),
                "end": round(w.end + 480.0, 2),
                "speaker": None,
                "confidence": getattr(w, "probability", None),
            })

    full_text = " ".join(full_text_pieces).strip()

    provider_name = f"local_cpu_{cpu_threads}t_{run_label}"
    payload = {
        "provider": provider_name,
        "source": "excerpt",
        "episode_guid": episode.guid,
        "episode_title": episode.title,
        "time_offset": 480.0,
        "text": full_text,
        "tokens": words,
    }

    # Save transcript
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    out_transcript_path = TRANSCRIPT_DIR / f"{episode.guid}.{provider_name}.json"
    with open(out_transcript_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # 4. Score against ground-truth reference
    ref_path = REFERENCE_DIR / f"{episode.guid}.json"
    scores = {}
    if ref_path.exists():
        reference = load_reference(ref_path)
        scores = score(full_text, words, reference, build(episode))

    return {
        "run_label": run_label,
        "cpu_threads": cpu_threads,
        "model_name": model_name,
        "audio_duration_s": audio_duration,
        "model_load_s": round(t_load, 2),
        "inference_s": round(t_infer, 2),
        "total_step_s": round(t_load + t_infer, 2),
        "real_time_factor": round(rtf, 4),
        "peak_rss_mb": infer_metrics["peak_rss_mb"],
        "avg_process_cpu_pct": infer_metrics["avg_process_cpu_pct"],
        "avg_system_cpu_pct": infer_metrics["avg_system_cpu_pct"],
        "words_count": len(words),
        "chars_count": len(full_text),
        "overall_score": scores.get("overall"),
        "term_recall": scores.get("components", {}).get("term_recall"),
        "hebrew_accuracy": scores.get("components", {}).get("hebrew_accuracy"),
        "term_precision": scores.get("components", {}).get("term_precision"),
        "script_fidelity": scores.get("components", {}).get("script_fidelity"),
        "timed_term_recall": scores.get("timed_term_recall", {}).get("recall"),
        "transcript_path": str(out_transcript_path),
    }


def main():
    BENCH_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    episodes = fetch_episodes()
    episode = next((e for e in episodes if e.number == 71), None)
    if not episode:
        logger.error("Episode 71 not found in feed")
        sys.exit(1)

    audio_path = EXCERPT_DIR / f"{episode.guid}.mp3"
    if not audio_path.exists():
        logger.error("Audio excerpt not found at %s", audio_path)
        sys.exit(1)

    results = []

    # Run 1: 4 Threads (Cold start if weights need downloading)
    logger.info(">>> Starting Test 1: 4 CPU Threads (Cold/Initial) <<<")
    res_4t_cold = run_single_benchmark(audio_path, episode, cpu_threads=4, run_label="cold_or_init")
    results.append(res_4t_cold)

    # Run 2: 4 Threads (Warm start - model already cached on disk)
    logger.info(">>> Starting Test 2: 4 CPU Threads (Warm) <<<")
    res_4t_warm = run_single_benchmark(audio_path, episode, cpu_threads=4, run_label="warm")
    results.append(res_4t_warm)

    # Run 3: 2 Threads (Warm start - testing host CPU thread throttling)
    logger.info(">>> Starting Test 3: 2 CPU Threads (Warm) <<<")
    res_2t_warm = run_single_benchmark(audio_path, episode, cpu_threads=2, run_label="warm")
    results.append(res_2t_warm)

    # Write summary report
    summary_path = BENCH_RESULTS_DIR / "home_server_cpu_benchmark.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    logger.info("Hardware benchmark completed. Summary written to %s", summary_path)
    print("\n" + "=" * 80)
    print("HOME SERVER CPU BENCHMARK SUMMARY (Intel i5-6200U, 2 Cores / 4 Threads)")
    print("=" * 80)
    print(f"{'Config':<22}{'Load (s)':<10}{'Infer (s)':<11}{'RTF':<8}{'Peak RAM':<12}{'CPU %':<10}{'Overall':<9}{'Term Rec':<10}")
    print("-" * 80)
    for r in results:
        cfg = f"{r['cpu_threads']}t ({r['run_label']})"
        ovr = f"{r['overall_score']:.3f}" if r['overall_score'] is not None else "n/a"
        rec = f"{r['term_recall']:.3f}" if r['term_recall'] is not None else "n/a"
        print(f"{cfg:<22}{r['model_load_s']:<10.2f}{r['inference_s']:<11.2f}{r['real_time_factor']:<8.3f}{r['peak_rss_mb']:<12.1f}{r['avg_process_cpu_pct']:<10.1f}{ovr:<9}{rec:<10}")
    print("=" * 80)


if __name__ == "__main__":
    main()
