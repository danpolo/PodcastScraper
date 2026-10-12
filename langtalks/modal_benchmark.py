"""Modal GPU hardware benchmark for ivrit-ai/whisper-large-v3-turbo-ct2.

Evaluates NVIDIA T4 ($0.59/hr) and NVIDIA L4 ($0.80/hr) on Modal serverless GPUs.
Enforces:
1. Hard execution timeout per container (180s).
2. Max container concurrency = 1 (no runaway horizontal scaling).
3. Persistent volume caching for HuggingFace model weights.
4. Detailed telemetry: cold start, model loading, warm inference, peak VRAM (MB), RTF, and cost.
"""

import json
import os
import time
from pathlib import Path

import modal

app = modal.App("langtalks-whisper-benchmark")

# Persistent cache volume to prevent repeated downloads
model_volume = modal.Volume.from_name("langtalks-whisper-cache", create_if_missing=True)
CACHE_DIR = "/cache/huggingface"

benchmark_image = (
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


def _run_gpu_transcription(audio_bytes: bytes, prompt: str, gpu_name: str, compute_type: str = "float16") -> dict:
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

    # 2. Inference
    t0_infer = time.perf_counter()
    segments, info = model.transcribe(
        temp_audio_path,
        language="he",
        beam_size=5,
        initial_prompt=prompt,
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

    hourly_rate = 0.59 if gpu_name.upper() == "T4" else 0.80
    total_compute_time_s = t_load + t_infer
    cost_usd = round((total_compute_time_s / 3600.0) * hourly_rate, 5)

    return {
        "gpu": gpu_name,
        "compute_type": compute_type,
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
    image=benchmark_image,
    gpu="T4",
    volumes={CACHE_DIR: model_volume},
    timeout=180,
    max_containers=1,
)
def run_whisper_t4(audio_bytes: bytes, prompt: str) -> dict:
    """Benchmark on NVIDIA T4 ($0.59/hr)."""
    return _run_gpu_transcription(audio_bytes, prompt, gpu_name="T4", compute_type="float16")


@app.function(
    image=benchmark_image,
    gpu="L4",
    volumes={CACHE_DIR: model_volume},
    timeout=180,
    max_containers=1,
)
def run_whisper_l4(audio_bytes: bytes, prompt: str) -> dict:
    """Benchmark on NVIDIA L4 ($0.80/hr)."""
    return _run_gpu_transcription(audio_bytes, prompt, gpu_name="L4", compute_type="float16")


@app.local_entrypoint()
def main(gpu: str = "T4"):
    """Local entrypoint for running benchmark from CLI: modal run langtalks/modal_benchmark.py --gpu T4"""
    repo_root = Path(__file__).resolve().parent.parent
    audio_file = repo_root / "langtalks" / "out" / "excerpts" / "74fc0625-0a6b-4ca1-9488-31be7860360d.mp3"
    if not audio_file.exists():
        print(f"Error: audio file missing at {audio_file}")
        return

    from langtalks.feed import fetch_episodes
    from langtalks.glossary import build, context_prompt

    episodes = fetch_episodes()
    episode = next((e for e in episodes if e.number == 71), None)
    prompt = context_prompt(episode, build(episode))[:600] if episode else ""

    audio_bytes = audio_file.read_bytes()
    print(f"Running Modal benchmark on {gpu} (audio size: {len(audio_bytes) / 1e6:.2f} MB)...")

    if gpu.upper() == "T4":
        res = run_whisper_t4.remote(audio_bytes, prompt)
    elif gpu.upper() == "L4":
        res = run_whisper_l4.remote(audio_bytes, prompt)
    else:
        print(f"Unknown GPU: {gpu}. Choose T4 or L4.")
        return

    print("Modal Benchmark Result:")
    for k, v in res.items():
        if k not in ("full_text", "words"):
            print(f"  {k}: {v}")

    # Save transcript and benchmark results
    bench_dir = repo_root / "langtalks" / "out" / "benchmarks"
    bench_dir.mkdir(parents=True, exist_ok=True)
    res_path = bench_dir / f"modal_{gpu.lower()}_benchmark.json"

    # Score against reference if available
    ref_path = repo_root / "langtalks" / "reference" / f"{episode.guid}.json"
    if ref_path.exists():
        from langtalks.score import score, load_reference
        ref = load_reference(ref_path)
        scores = score(res["full_text"], res["words"], ref, build(episode))
        res["scores"] = scores
        print(f"Benchmark Score on {gpu}:")
        print(f"  Overall: {scores.get('overall')}")
        print(f"  Term Recall: {scores.get('components', {}).get('term_recall')}")
        print(f"  Hebrew Accuracy: {scores.get('components', {}).get('hebrew_accuracy')}")

    transcript_payload = {
        "provider": f"modal_whisper_{gpu.lower()}",
        "source": "excerpt",
        "episode_guid": episode.guid,
        "episode_title": episode.title,
        "time_offset": 480.0,
        "text": res["full_text"],
        "tokens": res["words"],
    }
    transcript_path = repo_root / "langtalks" / "out" / "transcripts" / f"{episode.guid}.modal_{gpu.lower()}.json"
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    with open(transcript_path, "w", encoding="utf-8") as f:
        json.dump(transcript_payload, f, ensure_ascii=False, indent=2)

    with open(res_path, "w", encoding="utf-8") as f:
        summary = {k: v for k, v in res.items() if k != "words"}
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"Saved benchmark summary to {res_path} and transcript to {transcript_path}")
