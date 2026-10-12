"""Tests for infrastructure benchmark data structures and results."""

import json
from pathlib import Path


def test_home_server_cpu_benchmark_results():
    repo_root = Path(__file__).resolve().parent.parent
    bench_file = repo_root / "langtalks" / "out" / "benchmarks" / "home_server_cpu_benchmark.json"
    assert bench_file.exists(), "home_server_cpu_benchmark.json must exist"

    data = json.loads(bench_file.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) == 3

    # Check 4t cold
    run_4t_cold = next(r for r in data if r["cpu_threads"] == 4 and r["run_label"] == "cold_or_init")
    assert run_4t_cold["model_load_s"] > 50.0
    assert 0.8 < run_4t_cold["real_time_factor"] < 1.3
    assert run_4t_cold["peak_rss_mb"] < 4500.0

    # Check 4t warm
    run_4t_warm = next(r for r in data if r["cpu_threads"] == 4 and r["run_label"] == "warm")
    assert run_4t_warm["model_load_s"] < 10.0
    assert 0.8 < run_4t_warm["real_time_factor"] < 1.3

    # Check 2t warm
    run_2t_warm = next(r for r in data if r["cpu_threads"] == 2 and r["run_label"] == "warm")
    assert run_2t_warm["real_time_factor"] > run_4t_warm["real_time_factor"]


def test_modal_gpu_benchmark_results():
    repo_root = Path(__file__).resolve().parent.parent
    t4_file = repo_root / "langtalks" / "out" / "benchmarks" / "modal_t4_benchmark.json"
    l4_file = repo_root / "langtalks" / "out" / "benchmarks" / "modal_l4_benchmark.json"

    assert t4_file.exists(), "modal_t4_benchmark.json must exist"
    assert l4_file.exists(), "modal_l4_benchmark.json must exist"

    t4_data = json.loads(t4_file.read_text(encoding="utf-8"))
    l4_data = json.loads(l4_file.read_text(encoding="utf-8"))

    assert t4_data["gpu"] == "T4"
    assert t4_data["real_time_factor"] < 0.10
    assert t4_data["cost_usd"] < 0.01
    assert t4_data["vram_peak_mb"] < 5000.0
    assert t4_data["scores"]["overall"] > 0.65

    assert l4_data["gpu"] == "L4"
    assert l4_data["real_time_factor"] < 0.06
    assert l4_data["cost_usd"] < 0.01
    assert l4_data["vram_peak_mb"] < 5000.0
    assert l4_data["scores"]["overall"] > 0.70
    assert l4_data["scores"]["components"]["term_recall"] > 0.50
