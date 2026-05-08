"""
Charts for per-repository benchmark results.

Usage:
    python -m benchmarks.plots_repos                     # reads benchmarks/results/repos/
    python -m benchmarks.plots_repos --results path/to/  # custom directory
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

_FIGURES_DIR = Path(__file__).parent / "figures"
_FIGURES_DIR.mkdir(exist_ok=True)

_RESULTS_DIR = Path(__file__).parent / "results" / "repos"

_PALETTE = ["#4472C4", "#ED7D31", "#A9D18E", "#FFC000", "#5A9BD5", "#70AD47"]
_STYLE = {
    "axes.facecolor": "#F2F2F2",
    "axes.edgecolor": "#CCCCCC",
    "grid.color": "#FFFFFF",
    "grid.linewidth": 1.2,
    "font.size": 10,
}


# ── data loading ──────────────────────────────────────────────────────────────

def _load_results(results_dir: Path) -> List[Dict]:
    """Load JSONs, keeping only the latest run per (dataset, num_cpus) pair."""
    latest: dict[tuple, Dict] = {}
    for f in sorted(results_dir.glob("*.json")):
        try:
            r = json.loads(f.read_text())
            key = (r["dataset"], r["num_cpus"])
            if key not in latest or r.get("timestamp", "") > latest[key].get("timestamp", ""):
                latest[key] = r
        except Exception:
            pass
    return list(latest.values())


# ── Chart 1: Time ranking (horizontal bar, top 50 slowest) ───────────────────

def plot_repo_time_ranking(results: List[Dict], top_n: int = 50) -> Path:
    """Horizontal bar chart of total time, sorted descending — shows the slow outliers."""
    # Pick one entry per repo (highest CPU run = fastest, most representative)
    by_repo: Dict[str, Dict] = {}
    for r in results:
        name = r["dataset"]
        if name not in by_repo or r["num_cpus"] > by_repo[name]["num_cpus"]:
            by_repo[name] = r

    ranked = sorted(by_repo.values(), key=lambda r: r["time_total_s"], reverse=True)[:top_n]
    if not ranked:
        raise ValueError("No repo results to plot")

    labels = [r["dataset"] for r in ranked]
    times  = [r["time_total_s"] for r in ranked]
    files  = [r["n_files"] for r in ranked]

    fig_height = max(5, len(ranked) * 0.28)
    with plt.rc_context(_STYLE):
        fig, ax = plt.subplots(figsize=(10, fig_height))
        y = np.arange(len(ranked))
        bars = ax.barh(y, times, color=_PALETTE[0], zorder=3)

        for bar, t, n in zip(bars, times, files):
            ax.text(bar.get_width() * 1.05, bar.get_y() + bar.get_height() / 2,
                    f"{t:.2f}s  ({n}f)", va="center", fontsize=8)

        ax.set_xscale("log")
        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=8)
        ax.invert_yaxis()
        ax.set_xlabel("Total pipeline time — log scale (seconds)")
        ax.set_title(f"Repository Time Ranking — Top {len(ranked)} Slowest (by max CPUs run)")
        ax.grid(axis="x", zorder=0)
        fig.tight_layout()

    out = _FIGURES_DIR / "repo_time_ranking.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


# ── Chart 2: Scatter — file count vs total time ───────────────────────────────

def plot_repo_scatter(results: List[Dict]) -> Path:
    """
    Scatter of file count vs total time with a linear regression line.
    Reveals whether the pipeline scales linearly with file count and highlights outliers.
    """
    by_repo: Dict[str, Dict] = {}
    for r in results:
        name = r["dataset"]
        if name not in by_repo or r["num_cpus"] > by_repo[name]["num_cpus"]:
            by_repo[name] = r

    if not by_repo:
        raise ValueError("No repo results to plot")

    names  = list(by_repo.keys())
    xs = np.array([by_repo[n]["n_files"]      for n in names], dtype=float)
    ys = np.array([by_repo[n]["time_total_s"]  for n in names], dtype=float)

    # Filter out zeros before taking log
    mask = (xs > 0) & (ys > 0)
    xs, ys, names = xs[mask], ys[mask], [n for n, m in zip(names, mask) if m]

    with plt.rc_context(_STYLE):
        fig, ax = plt.subplots(figsize=(9, 6))
        ax.scatter(xs, ys, color=_PALETTE[0], alpha=0.65, s=40, zorder=3)

        # Power-law fit in log-log space: log(y) = b*log(x) + log(a)  →  y = a * x^b
        # slope b ≈ 1 means linear scaling; b > 1 is super-linear.
        if len(xs) > 1:
            log_coeffs = np.polyfit(np.log10(xs), np.log10(ys), 1)
            b, log_a = log_coeffs
            x_line = np.logspace(np.log10(xs.min()), np.log10(xs.max()), 200)
            ax.plot(x_line, 10 ** log_a * x_line ** b, "--", color="#CC3333",
                    linewidth=1.5, label=f"Power-law fit  y ∝ x^{b:.2f}")

        # label the top-5 slowest
        top5_idx = np.argsort(ys)[-5:]
        for i in top5_idx:
            ax.annotate(names[i], (xs[i], ys[i]),
                        textcoords="offset points", xytext=(5, 3), fontsize=7)

        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("File count (.lua files) — log scale")
        ax.set_ylabel("Total pipeline time — log scale (seconds)")
        ax.set_title("Repository Scale: File Count vs Pipeline Time (log-log)")
        ax.legend(fontsize=9)
        ax.grid(zorder=0, which="both", alpha=0.5)
        fig.tight_layout()

    out = _FIGURES_DIR / "repo_scatter.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


# ── Chart 3: Phase breakdown (Ray vs Collect) for top repos ──────────────────

def plot_repo_phase_breakdown(results: List[Dict], top_n: int = 30) -> Path:
    """
    Stacked horizontal bar showing Ray analysis vs GraphCollector collect time
    for the top N slowest repos. Reveals whether the bottleneck is parallel work
    or sequential merging.
    """
    by_repo: Dict[str, Dict] = {}
    for r in results:
        name = r["dataset"]
        if name not in by_repo or r["num_cpus"] > by_repo[name]["num_cpus"]:
            by_repo[name] = r

    ranked = sorted(by_repo.values(), key=lambda r: r["time_total_s"], reverse=True)[:top_n]
    if not ranked:
        raise ValueError("No repo results to plot")

    labels  = [r["dataset"]      for r in ranked]
    ray_t   = np.array([r["time_ray_s"]     for r in ranked])
    coll_t  = np.array([r["time_collect_s"] for r in ranked])

    fig_height = max(5, len(ranked) * 0.28)
    with plt.rc_context(_STYLE):
        fig, ax = plt.subplots(figsize=(10, fig_height))
        y = np.arange(len(ranked))

        b1 = ax.barh(y, ray_t,  color=_PALETTE[0], label="Ray analysis",   zorder=3)
        b2 = ax.barh(y, coll_t, left=ray_t, color=_PALETTE[1], label="GraphCollector", zorder=3)

        for bars, vals in [(b1, ray_t), (b2, coll_t)]:
            for bar, v in zip(bars, vals):
                if v > 0.1:
                    ax.text(bar.get_x() + bar.get_width() / 2,
                            bar.get_y() + bar.get_height() / 2,
                            f"{v:.2f}s", ha="center", va="center", fontsize=7, color="white")

        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=8)
        ax.invert_yaxis()
        ax.set_xlabel("Time (seconds)")
        ax.set_title(f"Ray vs Collect Phase — Top {len(ranked)} Repos by Total Time")
        ax.legend(fontsize=9)
        ax.grid(axis="x", zorder=0)
        fig.tight_layout()

    out = _FIGURES_DIR / "repo_phase_breakdown.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


# ── Chart 4: GraphCollector sub-phase detail for top repos ───────────────────

def plot_repo_collector_phases(results: List[Dict], top_n: int = 30) -> Path:
    """
    Stacked horizontal bar of GraphCollector sub-phases for top N repos.
    Shows which internal phase (spine, resolve, schema, metrics…) dominates.
    """
    by_repo: Dict[str, Dict] = {}
    for r in results:
        name = r["dataset"]
        if name not in by_repo or r["num_cpus"] > by_repo[name]["num_cpus"]:
            by_repo[name] = r

    ranked = sorted(by_repo.values(), key=lambda r: r["time_total_s"], reverse=True)[:top_n]
    if not ranked:
        raise ValueError("No repo results to plot")

    phases = [
        ("time_collect_local_s", "Store results"),
        ("time_spine_s",         "Filesystem spine"),
        ("time_index_s",         "Index build"),
        ("time_resolve_s",       "Cross-file resolve"),
        ("time_metrics_s",       "Graph metrics"),
        ("time_schema_s",        "Schema validation"),
    ]

    labels = [r["dataset"] for r in ranked]
    fig_height = max(5, len(ranked) * 0.28)
    with plt.rc_context(_STYLE):
        fig, ax = plt.subplots(figsize=(11, fig_height))
        y = np.arange(len(ranked))
        lefts = np.zeros(len(ranked))

        for i, (field, label) in enumerate(phases):
            vals = np.array([r.get(field, 0) for r in ranked])
            bars = ax.barh(y, vals, left=lefts,
                           color=_PALETTE[i % len(_PALETTE)], label=label, zorder=3)
            for bar, v in zip(bars, vals):
                if v > 0.05:
                    ax.text(bar.get_x() + bar.get_width() / 2,
                            bar.get_y() + bar.get_height() / 2,
                            f"{v:.2f}s", ha="center", va="center", fontsize=7, color="white")
            lefts += vals

        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=8)
        ax.invert_yaxis()
        ax.set_xlabel("Time (seconds)")
        ax.set_title(f"GraphCollector Sub-Phase Breakdown — Top {len(ranked)} Repos")
        ax.legend(fontsize=8, loc="lower right")
        ax.grid(axis="x", zorder=0)
        fig.tight_layout()

    out = _FIGURES_DIR / "repo_collector_phases.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


# ── generate all ─────────────────────────────────────────────────────────────

def generate_all(results_dir: Path | None = None) -> List[Path]:
    if results_dir is None:
        results_dir = _RESULTS_DIR

    results = _load_results(results_dir)
    if not results:
        print(f"No benchmark JSON found in {results_dir}")
        return []

    generators = [
        plot_repo_time_ranking,
        plot_repo_scatter,
        plot_repo_phase_breakdown,
        plot_repo_collector_phases,
    ]

    paths = []
    for gen in generators:
        try:
            p = gen(results)
            paths.append(p)
            print(f"  Saved: {p.name}")
        except Exception as e:
            print(f"  Warning: {gen.__name__} failed — {e}")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate per-repo benchmark charts")
    parser.add_argument("--results", type=Path, default=None,
                        help="Directory containing repo benchmark JSON files")
    args = parser.parse_args()

    print("Generating repo charts…")
    paths = generate_all(args.results)
    print(f"\n{len(paths)} chart(s) saved to benchmarks/figures/")


if __name__ == "__main__":
    main()
