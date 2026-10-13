"""Optimized ivrit.ai execution on Modal NVIDIA L4 GPU.

Runs ivrit-ai/whisper-large-v3-turbo-ct2 using:
1. Fair automated glossary initial_prompt (<= 400 chars, Hebrew prefix, high-priority terms first)
2. Decoding parameters: beam_size=5, temperature=0.0, condition_on_previous_text=False
3. Word-level timestamps & VAD filtering
4. Float16 precision on NVIDIA L4 (CUDA)
5. Safeguards: 180s container timeout, max_containers=1, persistent volume caching
"""

import json
import logging
import os
import time
from pathlib import Path

import modal

app = modal.App("langtalks-ivrit-optimized")

# Persistent cache volume to prevent repeated downloads
model_volume = modal.Volume.from_name("langtalks-whisper-cache", create_if_missing=True)
CACHE_DIR = "/cache/huggingface"

ivrit_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "faster-whisper==1.2.1",
        "ctranslate2==4.8.2",
        "nvidia-cublas-cu12",
        "nvidia-cudnn-cu12",
        "huggingface_hub>=0.21",
        "nvidia-ml-py",
    )
    .env({
        "HF_HOME": CACHE_DIR,
        "LD_LIBRARY_PATH": "/usr/local/lib/python3.11/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.11/site-packages/nvidia/cudnn/lib:$LD_LIBRARY_PATH",
    })
)


def _transcribe_on_l4(audio_bytes: bytes, initial_prompt: str, compute_type: str = "float16") -> dict:
    from faster_whisper import WhisperModel

    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        def get_vram_mb() -> float:
            info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            return round(info.used / (1024 * 1024), 1)
    except Exception:
        def get_vram_mb() -> float:
            return 0.0

    vram_before = get_vram_mb()

    # 1. Model Loading
    t0_load = time.perf_counter()
    model = WhisperModel(
        "ivrit-ai/whisper-large-v3-turbo-ct2",
        device="cuda",
        compute_type=compute_type,
        download_root=CACHE_DIR,
    )
    t_load = time.perf_counter() - t0_load
    try:
        model_volume.commit()
    except Exception as e:
        print(f"Volume commit notice: {e}")
    vram_loaded = get_vram_mb()

    # Write temporary audio file
    temp_audio_path = "/tmp/audio_excerpt.mp3"
    with open(temp_audio_path, "wb") as f:
        f.write(audio_bytes)

    # 2. Optimized Inference
    t0_infer = time.perf_counter()
    segments, info = model.transcribe(
        temp_audio_path,
        language="he",
        beam_size=5,
        temperature=0.0,
        condition_on_previous_text=False,
        initial_prompt=initial_prompt,
        word_timestamps=True,
        vad_filter=True,
    )
    segments_list = list(segments)
    t_infer = time.perf_counter() - t0_infer
    vram_peak = get_vram_mb()

    audio_duration = 300.0  # 5 minutes
    rtf = t_infer / audio_duration

    # Extract words
    words = []
    text_pieces = []
    for seg in segments_list:
        text_pieces.append(seg.text)
        for w in seg.words or []:
            words.append({
                "text": w.word,
                "start": round(w.start + 480.0, 2),
                "end": round(w.end + 480.0, 2),
                "speaker": None,
                "confidence": round(float(w.probability), 4) if getattr(w, "probability", None) is not None else None,
            })

    full_text = " ".join(text_pieces).strip()

    hourly_rate = 0.80  # NVIDIA L4 rate
    total_compute_time_s = t_load + t_infer
    cost_usd = round((total_compute_time_s / 3600.0) * hourly_rate, 5)

    return {
        "gpu": "L4",
        "compute_type": compute_type,
        "initial_prompt": initial_prompt,
        "model_load_s": round(t_load, 2),
        "inference_s": round(t_infer, 2),
        "total_compute_s": round(total_compute_time_s, 2),
        "real_time_factor": round(rtf, 4),
        "vram_before_mb": vram_before,
        "vram_loaded_mb": vram_loaded,
        "vram_peak_mb": vram_peak,
        "cost_usd": cost_usd,
        "words_count": len(words),
        "chars_count": len(full_text),
        "full_text": full_text,
        "words": words,
    }


@app.function(
    image=ivrit_image,
    gpu="L4",
    volumes={CACHE_DIR: model_volume},
    timeout=180,
    max_containers=1,
)
def run_optimized_ivrit_l4(audio_bytes: bytes, initial_prompt: str) -> dict:
    """Execute optimized ivrit transcription on NVIDIA L4 ($0.80/hr)."""
    return _transcribe_on_l4(audio_bytes, initial_prompt, compute_type="float16")


@app.local_entrypoint()
def main():
    repo_root = Path(__file__).resolve().parent.parent
    audio_file = repo_root / "langtalks" / "out" / "excerpts" / "74fc0625-0a6b-4ca1-9488-31be7860360d.mp3"
    if not audio_file.exists():
        print(f"Error: audio file missing at {audio_file}")
        return

    from langtalks.feed import fetch_episodes
    from langtalks.glossary import build, initial_prompt_for_ivrit

    episodes = fetch_episodes()
    episode = next((e for e in episodes if e.number == 71), None)
    if not episode:
        print("Error: Episode 71 not found in feed")
        return

    prompt = initial_prompt_for_ivrit(episode)
    print(f"Optimized Ivrit initial_prompt ({len(prompt)} chars):\n  {prompt}")

    audio_bytes = audio_file.read_bytes()
    print(f"Submitting to Modal L4 (audio size: {len(audio_bytes) / 1e6:.2f} MB)...")

    res = run_optimized_ivrit_l4.remote(audio_bytes, prompt)

    print("\nModal L4 Optimized Result:")
    for k, v in res.items():
        if k not in ("full_text", "words"):
            print(f"  {k}: {v}")

    # Score against human reference
    ref_path = repo_root / "langtalks" / "reference" / f"{episode.guid}.json"
    scores = {}
    if ref_path.exists():
        from langtalks.score import score, load_reference
        ref = load_reference(ref_path)
        scores = score(res["full_text"], res["words"], ref, build(episode))
        res["scores"] = scores
        print(f"\nScore Against Ground Truth:")
        print(f"  Overall: {scores.get('overall'):.4f}")
        print(f"  Term Recall: {scores.get('components', {}).get('term_recall'):.4f}")
        print(f"  Hebrew Accuracy: {scores.get('components', {}).get('hebrew_accuracy'):.4f}")
        print(f"  Script Fidelity: {scores.get('components', {}).get('script_fidelity'):.4f}")
        print(f"  Timed Recall: {scores.get('timed_term_recall', {}).get('recall')}")

    # Save output separately to reviewed pilot dir AND out/transcripts
    pilot_dir = repo_root / "langtalks" / "reviewed" / "episode71" / "optimized-pilot"
    pilot_dir.mkdir(parents=True, exist_ok=True)
    out_transcript_path = pilot_dir / f"{episode.guid}.optimized_modal_l4.json"

    transcript_payload = {
        "provider": "optimized_modal_l4",
        "source": "excerpt",
        "episode_guid": episode.guid,
        "episode_title": episode.title,
        "time_offset": 480.0,
        "model": "ivrit-ai/whisper-large-v3-turbo-ct2",
        "initial_prompt": prompt,
        "decoding_params": {
            "beam_size": 5,
            "temperature": 0.0,
            "condition_on_previous_text": False,
            "language": "he",
            "compute_type": "float16",
        },
        "text": res["full_text"],
        "tokens": res["words"],
        "metrics": {
            "overall": scores.get("overall"),
            "term_recall": scores.get("components", {}).get("term_recall"),
            "hebrew_accuracy": scores.get("components", {}).get("hebrew_accuracy"),
            "script_fidelity": scores.get("components", {}).get("script_fidelity"),
            "timed_term_recall": scores.get("timed_term_recall", {}).get("recall"),
        },
    }

    with open(out_transcript_path, "w", encoding="utf-8") as f:
        json.dump(transcript_payload, f, ensure_ascii=False, indent=2)

    # Also mirror into out/transcripts
    mirror_path = repo_root / "langtalks" / "out" / "transcripts" / f"{episode.guid}.optimized_modal_l4.json"
    mirror_path.parent.mkdir(parents=True, exist_ok=True)
    with open(mirror_path, "w", encoding="utf-8") as f:
        json.dump(transcript_payload, f, ensure_ascii=False, indent=2)

    bench_summary_path = repo_root / "langtalks" / "out" / "benchmarks" / "optimized_modal_l4_benchmark.json"
    bench_summary_path.parent.mkdir(parents=True, exist_ok=True)
    with open(bench_summary_path, "w", encoding="utf-8") as f:
        summary = {k: v for k, v in res.items() if k != "words"}
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\nSaved transcript to {out_transcript_path}")
    print(f"Saved benchmark summary to {bench_summary_path}")
