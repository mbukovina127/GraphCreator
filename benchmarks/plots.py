"""
Chart generator for benchmark results.

Usage:
    python -m benchmarks.plots                    # reads all JSON in benchmarks/results/
    python -m benchmarks.plots --results path/   # custom results directory
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

import matplotlib
matplotlib.use("Agg")  # headless — no display needed
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

_FIGURES_DIR = Path(__file__).parent / "figures"
_FIGURES_DIR.mkdir(exist_ok=True)

_PALETTE = ["#4472C4", "#ED7D31", "#A9D18E", "#FFC000", "#5A9BD5", "#70AD47"]
_STYLE = {
    "axes.facecolor": "#F2F2F2",
    "axes.edgecolor": "#CCCCCC",
    "grid.color": "#FFFFFF",
    "grid.linewidth": 1.2,
    "font.size": 11,
}


def _load_results(results_dir: Path) -> List[Dict]:
    results = []
    for f in sorted(results_dir.glob("*.json")):
        try:
            results.append(json.loads(f.read_text()))
        except Exception:
            pass
    return results


def _group_by(results: List[Dict], key: str) -> Dict[str, List[Dict]]:
    groups: Dict[str, List[Dict]] = defaultdict(list)
    for r in results:
        groups[r[key]].append(r)
    return groups


# ── Chart 1: Scalability — time vs worker count ──────────────────────────────

def plot_scalability(results: List[Dict]) -> Path:
    """Bar chart: total time per worker count, one group per dataset."""
    by_dataset = _group_by(results, "dataset")
    datasets = list(by_dataset.keys())

    all_workers = sorted({r["num_cpus"] for r in results})
    x = np.arange(len(all_workers))
    width = 0.8 / max(len(datasets), 1)

    with plt.rc_context(_STYLE):
        fig, ax = plt.subplots(figsize=(8, 5))

        for i, ds in enumerate(datasets):
            ds_results = {r["num_cpus"]: r for r in by_dataset[ds]}
            times = [ds_results.get(w, {}).get("time_total_s", 0) for w in all_workers]
            offset = (i - len(datasets) / 2 + 0.5) * width
            bars = ax.bar(x + offset, times, width * 0.9, label=ds,
                          color=_PALETTE[i % len(_PALETTE)], zorder=3)
            for bar, t in zip(bars, times):
                if t > 0:
                    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01,
                            f"{t:.2f}s", ha="center", va="bottom", fontsize=9)

        ax.set_xticks(x)
        ax.set_xticklabels([f"{w} CPU{'s' if w != 1 else ''}" for w in all_workers])
        ax.set_ylabel("Total time (seconds)")
        ax.set_title("CPG Pipeline Scalability: Time vs CPU Budget")
        ax.legend()
        ax.grid(axis="y", zorder=0)
        ax.set_ylim(bottom=0)
        fig.tight_layout()

    out = _FIGURES_DIR / "scalability.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


# ── Chart 2: Speedup curve ───────────────────────────────────────────────────

def plot_speedup(results: List[Dict]) -> Path:
    """Line chart: speedup factor vs worker count with ideal reference line."""
    by_dataset = _group_by(results, "dataset")

    all_workers = sorted({r["num_cpus"] for r in results})
    ideal_x = np.linspace(min(all_workers), max(all_workers), 100)

    with plt.rc_context(_STYLE):
        fig, ax = plt.subplots(figsize=(8, 5))

        ax.plot(ideal_x, ideal_x / min(all_workers), "--", color="#999999",
                linewidth=1.5, label="Ideal linear speedup")

        for i, ds in enumerate(sorted(by_dataset.keys())):
            ds_results = sorted(by_dataset[ds], key=lambda r: r["num_cpus"])
            workers = [r["num_cpus"] for r in ds_results]
            if not workers:
                continue
            baseline = next((r["time_total_s"] for r in ds_results if r["num_cpus"] == min(workers)), None)
            if baseline is None or baseline == 0:
                continue
            speedups = [baseline / r["time_total_s"] if r["time_total_s"] > 0 else 0
                        for r in ds_results]
            ax.plot(workers, speedups, "o-", color=_PALETTE[i % len(_PALETTE)],
                    linewidth=2, markersize=7, label=ds)

        ax.set_xlabel("CPU budget (num_cpus)")
        ax.set_ylabel("Speedup factor")
        ax.set_title("CPG Pipeline Speedup vs Ideal Linear Scaling")
        ax.legend()
        ax.grid(zorder=0)
        ax.set_ylim(bottom=0)
        fig.tight_layout()

    out = _FIGURES_DIR / "speedup.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


# ── Chart 3: Throughput — time vs file count ─────────────────────────────────

def plot_throughput(results: List[Dict]) -> Path:
    """Bar chart: analysis time per dataset (fixed max-worker run), showing file count."""
    # pick the run with most workers per dataset for a "full-power" view
    by_dataset = _group_by(results, "dataset")
    labels, times, file_counts = [], [], []

    for ds in sorted(by_dataset.keys()):
        best = max(by_dataset[ds], key=lambda r: r["num_cpus"])
        labels.append(f"{ds}\n({best['n_files']} files)")
        times.append(best["time_total_s"])
        file_counts.append(best["n_files"])

    with plt.rc_context(_STYLE):
        fig, ax = plt.subplots(figsize=(7, 5))
        x = np.arange(len(labels))
        bars = ax.bar(x, times, color=_PALETTE[:len(labels)], zorder=3)
        for bar, t in zip(bars, times):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.005,
                    f"{t:.2f}s", ha="center", va="bottom", fontsize=10)

        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_ylabel("Total analysis time (seconds)")
        ax.set_title("Throughput: Analysis Time per Dataset")
        ax.grid(axis="y", zorder=0)
        ax.set_ylim(bottom=0)
        fig.tight_layout()

    out = _FIGURES_DIR / "throughput.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


# ── Chart 4: Graph structure — stacked node types ────────────────────────────

def plot_graph_structure(results: List[Dict]) -> Path:
    """Stacked bar: node type distribution per dataset."""
    by_dataset = _group_by(results, "dataset")
    datasets = sorted(by_dataset.keys())

    # collect all node types across datasets
    all_types: set[str] = set()
    ds_type_counts: Dict[str, Dict[str, int]] = {}
    for ds in datasets:
        best = max(by_dataset[ds], key=lambda r: r["num_cpus"])
        counts = best.get("node_type_counts", {})
        ds_type_counts[ds] = counts
        all_types.update(counts.keys())

    # exclude metric nodes from the visual breakdown (they inflate the count)
    display_types = sorted(t for t in all_types if t != "metric")

    x = np.arange(len(datasets))
    with plt.rc_context(_STYLE):
        fig, ax = plt.subplots(figsize=(9, 5))
        bottoms = np.zeros(len(datasets))

        for i, node_type in enumerate(display_types):
            vals = [ds_type_counts[ds].get(node_type, 0) for ds in datasets]
            ax.bar(x, vals, bottom=bottoms, label=node_type,
                   color=_PALETTE[i % len(_PALETTE)], zorder=3)
            bottoms += np.array(vals, dtype=float)

        ax.set_xticks(x)
        ax.set_xticklabels(datasets)
        ax.set_ylabel("Node count")
        ax.set_title("CPG Knowledge Graph: Node Type Breakdown per Dataset")
        ax.legend(loc="upper left", fontsize=9)
        ax.grid(axis="y", zorder=0)
        ax.set_ylim(bottom=0)
        fig.tight_layout()

    out = _FIGURES_DIR / "graph_structure.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


# ── Chart 5: Cross-file resolution rate ──────────────────────────────────────

def plot_resolution_rate(results: List[Dict]) -> Path:
    """Horizontal bar: import resolution % per dataset."""
    by_dataset = _group_by(results, "dataset")
    datasets = sorted(by_dataset.keys())

    rates = []
    for ds in datasets:
        best = max(by_dataset[ds], key=lambda r: r["num_cpus"])
        rates.append(best.get("resolution_rate", 0) * 100)

    with plt.rc_context(_STYLE):
        fig, ax = plt.subplots(figsize=(7, 4))
        y = np.arange(len(datasets))
        bars = ax.barh(y, rates, color=_PALETTE[:len(datasets)], zorder=3)

        for bar, rate in zip(bars, rates):
            ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                    f"{rate:.1f}%", va="center", fontsize=10)

        ax.set_yticks(y)
        ax.set_yticklabels(datasets)
        ax.set_xlabel("Cross-file import resolution rate (%)")
        ax.set_title("Cross-File Symbol Resolution Accuracy per Dataset")
        ax.set_xlim(0, 115)
        ax.grid(axis="x", zorder=0)
        fig.tight_layout()

    out = _FIGURES_DIR / "resolution_rate.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


# ── generate all charts ──────────────────────────────────────────────────────

def generate_all(results_dir: Path | None = None) -> List[Path]:
    if results_dir is None:
        results_dir = Path(__file__).parent / "results"

    results = _load_results(results_dir)
    if not results:
        print(f"No benchmark JSON found in {results_dir}")
        return []

    generators = [
        plot_scalability,
        plot_speedup,
        plot_throughput,
        plot_graph_structure,
        plot_resolution_rate,
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


def main():
    parser = argparse.ArgumentParser(description="Generate benchmark charts")
    parser.add_argument("--results", type=Path, default=None,
                        help="Directory containing benchmark JSON files")
    args = parser.parse_args()

    print("Generating charts…")
    paths = generate_all(args.results)
    print(f"\n{len(paths)} chart(s) saved to benchmarks/figures/")


if __name__ == "__main__":
    main()