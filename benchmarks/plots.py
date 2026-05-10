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
    "axes.facecolor": "white",
    "figure.facecolor": "white",
    "axes.edgecolor": "#CCCCCC",
    "grid.color": "#EEEEEE",
    "grid.linewidth": 1.0,
    "font.size": 11,
}


def _load_results(results_dir: Path) -> List[Dict]:
    """Load JSONs, keeping only the latest run per (dataset, num_cpus, runner) triple."""
    latest: dict[tuple, Dict] = {}
    for f in sorted(results_dir.glob("*.json")):
        try:
            r = json.loads(f.read_text())
            key = (r["dataset"], r["num_cpus"], r.get("runner", "ray"))
            if key not in latest or r.get("timestamp", "") > latest[key].get("timestamp", ""):
                latest[key] = r
        except Exception:
            pass
    return list(latest.values())


def _group_by(results: List[Dict], key: str) -> Dict[str, List[Dict]]:
    groups: Dict[str, List[Dict]] = defaultdict(list)
    for r in results:
        groups[r[key]].append(r)
    return groups


# ── Chart 1: Scalability — time vs worker count ──────────────────────────────

def plot_scalability(results: List[Dict]) -> Path:
    """Bar chart: total time per worker count."""
    ray_results = [r for r in results if r.get("runner", "ray") == "ray"]

    by_dataset = _group_by(ray_results, "dataset")
    datasets = list(by_dataset.keys())

    all_workers = sorted({r["num_cpus"] for r in ray_results})
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
        ax.set_ylabel("Celkový čas (sekundy)")
        ax.set_title("Škálovateľnosť CPG pipeline: čas vs počet CPU")
        ax.legend(fontsize=9)
        ax.grid(axis="y", zorder=0)
        ax.set_ylim(bottom=0)
        fig.tight_layout()

    out = _FIGURES_DIR / "scalability.png"
    fig.savefig(out, dpi=150, facecolor='white')
    plt.close(fig)
    return out


# ── Chart 2: Speedup curve ───────────────────────────────────────────────────

def plot_speedup(results: List[Dict]) -> Path:
    """Line chart: Ray speedup vs worker count, baseline = Ray@1cpu."""
    ray_results = [r for r in results if r.get("runner", "ray") == "ray"]

    by_dataset = _group_by(ray_results, "dataset")
    all_workers = sorted({r["num_cpus"] for r in ray_results})
    if not all_workers:
        all_workers = [1]
    ideal_x = np.linspace(min(all_workers), max(all_workers), 100)

    with plt.rc_context(_STYLE):
        fig, ax = plt.subplots(figsize=(8, 5))

        ax.plot(ideal_x, ideal_x / min(all_workers), "--", color="#999999",
                linewidth=1.5, label="Ideálne lineárne zrýchlenie")

        for i, ds in enumerate(sorted(by_dataset.keys())):
            ds_results = sorted(by_dataset[ds], key=lambda r: r["num_cpus"])
            workers = [r["num_cpus"] for r in ds_results]
            if not workers:
                continue
            baseline = next(
                (r["time_total_s"] for r in ds_results if r["num_cpus"] == min(workers)), None
            )
            if not baseline:
                continue
            speedups = [baseline / r["time_total_s"] if r["time_total_s"] > 0 else 0
                        for r in ds_results]
            ax.plot(workers, speedups, "o-", color=_PALETTE[i % len(_PALETTE)],
                    linewidth=2, markersize=7, label=f"{ds} (vs Ray@{min(workers)}cpu)")

        ax.set_xlabel("Počet CPU (num_cpus)")
        ax.set_ylabel("Faktor zrýchlenia")
        ax.set_title("Zrýchlenie CPG pipeline vs ideálne lineárne škálovanie")
        ax.legend(fontsize=9)
        ax.grid(zorder=0)
        ax.set_ylim(bottom=0)
        fig.tight_layout()

    out = _FIGURES_DIR / "speedup.png"
    fig.savefig(out, dpi=150, facecolor='white')
    plt.close(fig)
    return out


# ── Chart 3: Throughput — time vs file count ─────────────────────────────────

def plot_throughput(results: List[Dict]) -> Path:
    """Grouped bar chart: one bar per CPU variant per dataset."""
    ray_by_ds_cpu: Dict[str, Dict[int, Dict]] = {}
    for r in results:
        if r.get("runner", "ray") == "ray":
            ray_by_ds_cpu.setdefault(r["dataset"], {})[r["num_cpus"]] = r

    all_cpus = sorted({r["num_cpus"] for r in results if r.get("runner", "ray") == "ray"})
    datasets = sorted(ray_by_ds_cpu.keys())

    variants: List[tuple] = [(f"{cpu} CPU{'s' if cpu > 1 else ''}", cpu) for cpu in all_cpus]

    n_v = len(variants)
    width = 0.8 / max(n_v, 1)
    x = np.arange(len(datasets))

    with plt.rc_context(_STYLE):
        fig, ax = plt.subplots(figsize=(max(8, len(datasets) * n_v * 0.5), 5))

        for vi, (label, cpu) in enumerate(variants):
            offset = (vi - n_v / 2 + 0.5) * width
            times = [ray_by_ds_cpu.get(ds, {}).get(cpu, {}).get("time_total_s", 0)
                     for ds in datasets]
            bars = ax.bar(x + offset, times, width * 0.9, label=label,
                          color=_PALETTE[vi % len(_PALETTE)], zorder=3)
            for bar, t in zip(bars, times):
                if t > 0:
                    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() * 1.02,
                            f"{t:.1f}s", ha="center", va="bottom", fontsize=7, rotation=45)

        n_files_per_ds = {
            ds: next((r["n_files"] for r in ray_by_ds_cpu.get(ds, {}).values()), 0)
            for ds in datasets
        }
        ax.set_xticks(x)
        ax.set_xticklabels([f"{ds}\n({n_files_per_ds[ds]} súborov)" for ds in datasets])
        ax.set_ylabel("Celkový čas analýzy (sekundy)")
        ax.set_title("Priepustnosť: čas analýzy per dataset — Ray varianty")
        ax.legend(fontsize=9)
        ax.grid(axis="y", zorder=0)
        ax.set_ylim(bottom=0)
        fig.tight_layout()

    out = _FIGURES_DIR / "throughput.png"
    fig.savefig(out, dpi=150, facecolor='white')
    plt.close(fig)
    return out


# ── Chart 4: Graph structure — stacked node types ────────────────────────────

def plot_graph_structure(results: List[Dict]) -> Path:
    """Stacked bar: node type distribution per dataset."""
    results = [r for r in results if r.get("runner", "ray") == "ray"]
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
        ax.set_ylabel("Počet uzlov")
        ax.set_title("CPG znalostný graf: rozloženie typov uzlov per dataset")
        ax.legend(loc="upper left", fontsize=9)
        ax.grid(axis="y", zorder=0)
        ax.set_ylim(bottom=0)
        fig.tight_layout()

    out = _FIGURES_DIR / "graph_structure.png"
    fig.savefig(out, dpi=150, facecolor='white')
    plt.close(fig)
    return out


# ── Chart 5: Cross-file resolution rate ──────────────────────────────────────

def plot_resolution_rate(results: List[Dict]) -> Path:
    """Horizontal bar: import resolution % per dataset."""
    results = [r for r in results if r.get("runner", "ray") == "ray"]
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
        ax.set_xlabel("Miera rozlíšenia medzisúborových importov (%)")
        ax.set_title("Presnosť rozlíšenia medzisúborových symbolov per dataset")
        ax.set_xlim(0, 115)
        ax.grid(axis="x", zorder=0)
        fig.tight_layout()

    out = _FIGURES_DIR / "resolution_rate.png"
    fig.savefig(out, dpi=150, facecolor='white')
    plt.close(fig)
    return out


# ── Chart 6: Per-file pipeline stage breakdown ───────────────────────────────

def plot_pipeline_stages(results: List[Dict]) -> Path:
    """Stacked bar: average ms per pipeline stage (parse/AST/symbol/CPG) per dataset."""
    results = [r for r in results if r.get("runner", "ray") == "ray"]
    by_dataset = _group_by(results, "dataset")
    datasets = sorted(by_dataset.keys())

    stages = [
        ("avg_parse_s",      "Syntaktická analýza (tree-sitter)"),
        ("avg_ast_insert_s", "Vkladanie AST"),
        ("avg_symbol_s",     "Tabuľka symbolov"),
        ("avg_cpg_build_s",  "Konštrukcia CPG"),
    ]

    ds_data = {ds: max(by_dataset[ds], key=lambda r: r["num_cpus"]) for ds in datasets}
    datasets = [ds for ds in datasets if "avg_parse_s" in ds_data[ds]]
    if not datasets:
        raise ValueError("No results contain per-file stage timings — re-run benchmarks")

    x = np.arange(len(datasets))
    with plt.rc_context(_STYLE):
        fig, ax = plt.subplots(figsize=(8, 5))
        bottoms = np.zeros(len(datasets))

        for i, (field, label) in enumerate(stages):
            vals = np.array([ds_data[ds].get(field, 0) * 1000 for ds in datasets])
            bars = ax.bar(x, vals, bottom=bottoms, label=label,
                          color=_PALETTE[i % len(_PALETTE)], zorder=3)
            for bar, v in zip(bars, vals):
                if v > 0.5:
                    ax.text(bar.get_x() + bar.get_width() / 2,
                            bar.get_y() + bar.get_height() / 2,
                            f"{v:.1f}", ha="center", va="center", fontsize=8, color="white")
            bottoms += vals

        ax.set_xticks(x)
        ax.set_xticklabels(datasets)
        ax.set_ylabel("Priemerný čas na súbor (ms)")
        ax.set_title("Rozloženie fáz pipeline na súbor")
        ax.legend(fontsize=9)
        ax.grid(axis="y", zorder=0)
        ax.set_ylim(bottom=0)
        fig.tight_layout()

    out = _FIGURES_DIR / "pipeline_stages.png"
    fig.savefig(out, dpi=150, facecolor='white')
    plt.close(fig)
    return out


# ── Chart 7: GraphCollector sub-phase breakdown ──────────────────────────────

def plot_collector_phases(results: List[Dict]) -> Path:
    """Stacked bar: time per GraphCollector sub-phase per dataset."""
    results = [r for r in results if r.get("runner", "ray") == "ray"]
    by_dataset = _group_by(results, "dataset")
    datasets = sorted(by_dataset.keys())

    phases = [
        ("time_collect_local_s", "Ukladanie výsledkov"),
        ("time_spine_s",         "Hierarchia súborového systému"),
        ("time_index_s",         "Zostavenie indexu"),
        ("time_resolve_s",       "Medzisúborové rozlíšenie"),
        ("time_metrics_s",       "Metriky grafu"),
        ("time_schema_s",        "Validácia schémy"),
    ]

    ds_data = {ds: max(by_dataset[ds], key=lambda r: r["num_cpus"]) for ds in datasets}
    datasets = [ds for ds in datasets if "time_spine_s" in ds_data[ds]]
    if not datasets:
        raise ValueError("No results contain collector phase timings — re-run benchmarks")

    x = np.arange(len(datasets))
    with plt.rc_context(_STYLE):
        fig, ax = plt.subplots(figsize=(8, 5))
        bottoms = np.zeros(len(datasets))

        for i, (field, label) in enumerate(phases):
            vals = np.array([ds_data[ds].get(field, 0) for ds in datasets])
            bars = ax.bar(x, vals, bottom=bottoms, label=label,
                          color=_PALETTE[i % len(_PALETTE)], zorder=3)
            for bar, v in zip(bars, vals):
                if v > 0.002:
                    ax.text(bar.get_x() + bar.get_width() / 2,
                            bar.get_y() + bar.get_height() / 2,
                            f"{v*1000:.0f}ms", ha="center", va="center", fontsize=8, color="white")
            bottoms += vals

        ax.set_xticks(x)
        ax.set_xticklabels(datasets)
        ax.set_ylabel("Čas (sekundy)")
        ax.set_title("Rozloženie fáz GraphCollector")
        ax.legend(fontsize=9)
        ax.grid(axis="y", zorder=0)
        ax.set_ylim(bottom=0)
        fig.tight_layout()

    out = _FIGURES_DIR / "collector_phases.png"
    fig.savefig(out, dpi=150, facecolor='white')
    plt.close(fig)
    return out


# ── Chart 8: Ray scheduling — overhead vs work ───────────────────────────────

def plot_ray_scheduling(results: List[Dict]) -> Path:
    """Stacked bar: Ray phase split into dispatch overhead / parallel work / collection."""
    results = [r for r in results if r.get("runner", "ray") == "ray"]
    by_dataset = _group_by(results, "dataset")
    datasets = sorted(by_dataset.keys())

    ds_data = {ds: max(by_dataset[ds], key=lambda r: r["num_cpus"]) for ds in datasets}
    datasets = [ds for ds in datasets if "first_result_latency_s" in ds_data[ds]]
    if not datasets:
        raise ValueError("No results contain scheduling metrics — re-run benchmarks")

    overhead = np.array([ds_data[ds]["first_result_latency_s"] for ds in datasets])
    spread   = np.array([ds_data[ds]["task_spread_s"]           for ds in datasets])
    collect  = np.array([ds_data[ds]["time_collect_s"]          for ds in datasets])

    x = np.arange(len(datasets))
    with plt.rc_context(_STYLE):
        fig, ax = plt.subplots(figsize=(8, 5))

        b1 = ax.bar(x, overhead, label="Réžia odoslania (latencia prvej úlohy)",
                    color=_PALETTE[0], zorder=3)
        b2 = ax.bar(x, spread,   bottom=overhead, label="Okno paralelnej práce",
                    color=_PALETTE[2], zorder=3)
        b3 = ax.bar(x, collect,  bottom=overhead + spread, label="Sekvenčné zbieranie",
                    color=_PALETTE[3], zorder=3)

        for bars, vals in [(b1, overhead), (b2, spread), (b3, collect)]:
            for bar, v in zip(bars, vals):
                if v > 0.05:
                    ax.text(bar.get_x() + bar.get_width() / 2,
                            bar.get_y() + bar.get_height() / 2,
                            f"{v:.2f}s", ha="center", va="center", fontsize=9, color="white")

        ax.set_xticks(x)
        ax.set_xticklabels(datasets)
        ax.set_ylabel("Čas (sekundy)")
        ax.set_title("Zloženie fáz Ray: réžia vs paralelná práca vs zbieranie")
        ax.legend(fontsize=9)
        ax.grid(axis="y", zorder=0)
        ax.set_ylim(bottom=0)
        fig.tight_layout()

    out = _FIGURES_DIR / "ray_scheduling.png"
    fig.savefig(out, dpi=150, facecolor='white')
    plt.close(fig)
    return out


# ── Chart 9: Memory consumption ─────────────────────────────────────────────

def plot_memory(results: List[Dict]) -> Path:
    """Grouped bar chart: RSS delta (MB) per CPU variant per dataset."""
    ray_by_ds_cpu: Dict[str, Dict[int, Dict]] = {}
    for r in results:
        if r.get("runner", "ray") == "ray":
            ray_by_ds_cpu.setdefault(r["dataset"], {})[r["num_cpus"]] = r

    all_cpus = sorted({r["num_cpus"] for r in results if r.get("runner", "ray") == "ray"})
    datasets = sorted(ray_by_ds_cpu.keys())

    variants: List[tuple] = [(f"{cpu} CPU{'s' if cpu > 1 else ''}", cpu) for cpu in all_cpus]

    if not variants or not datasets:
        raise ValueError("No memory data to plot")

    n_v = len(variants)
    width = 0.8 / max(n_v, 1)
    x = np.arange(len(datasets))

    with plt.rc_context(_STYLE):
        fig, ax = plt.subplots(figsize=(max(8, len(datasets) * n_v * 0.5), 5))

        for vi, (label, cpu) in enumerate(variants):
            offset = (vi - n_v / 2 + 0.5) * width
            mems = [ray_by_ds_cpu.get(ds, {}).get(cpu, {}).get("rss_delta_mb", 0)
                    for ds in datasets]
            bars = ax.bar(x + offset, mems, width * 0.9, label=label,
                          color=_PALETTE[vi % len(_PALETTE)], zorder=3)
            for bar, m in zip(bars, mems):
                if m > 0:
                    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() * 1.02,
                            f"{m:.0f}", ha="center", va="bottom", fontsize=7, rotation=45)

        n_files_per_ds = {
            ds: next((r["n_files"] for r in ray_by_ds_cpu.get(ds, {}).values()), 0)
            for ds in datasets
        }
        ax.set_xticks(x)
        ax.set_xticklabels([f"{ds}\n({n_files_per_ds[ds]} súborov)" for ds in datasets])
        ax.set_ylabel("RSS delta (MB)")
        ax.set_title("Spotreba pamäte: nárast RSS per dataset — všetky varianty")
        ax.legend(fontsize=9)
        ax.grid(axis="y", zorder=0)
        ax.set_ylim(bottom=0)
        fig.tight_layout()

    out = _FIGURES_DIR / "memory.png"
    fig.savefig(out, dpi=150, facecolor='white')
    plt.close(fig)
    return out


# ── Chart 10: Combined throughput + collector phases ─────────────────────────

def plot_throughput_phases(results: List[Dict]) -> Path:
    """
    Two-panel chart combining pipeline phase breakdown and throughput.

    Top panel:    Grouped stacked bars — each bar's total height = time_total_s,
                  subsections = individual pipeline phases in order.
    Bottom panel: Throughput (files/s) for the same (dataset, variant) bars.

    Groups = datasets.  Within each group: one bar per (runner, cpu) variant,
    sequential first (if present), then Ray in ascending CPU order.
    """
    from matplotlib.transforms import blended_transform_factory

    # ── build per-(runner, cpu, dataset) lookup ───────────────────────────────
    lookup: Dict[tuple, Dict] = {}
    for r in results:
        k = (r.get("runner", "ray"), r["num_cpus"], r["dataset"])
        if k not in lookup or r.get("timestamp", "") > lookup[k].get("timestamp", ""):
            lookup[k] = r

    datasets = sorted({r["dataset"] for r in results})
    ray_cpus = sorted({r["num_cpus"] for r in results if r.get("runner", "ray") == "ray"})
    seq_cpus = sorted({r["num_cpus"] for r in results if r.get("runner") == "sequential"})

    variants: List[tuple] = (
        [("sequential", c) for c in seq_cpus] +
        [("ray", c) for c in ray_cpus]
    )
    if not variants or not datasets:
        raise ValueError("No results to plot")

    def vlabel(runner, cpu):
        return "Seq" if runner == "sequential" else f"R×{cpu}"

    # phase definitions: (json_field, label, color)
    PHASES = [
        ("time_ray_s",           "Analýza (Ray/sekv.)",  "#4472C4"),
        ("time_collect_local_s", "Ukladanie výsledkov",  "#9DC3E6"),
        ("time_spine_s",         "Hierarchia FS",         "#ED7D31"),
        ("time_index_s",         "Zostavenie indexu",     "#70AD47"),
        ("time_resolve_s",       "Rozlíšenie symbolov",   "#FFC000"),
        ("time_field_resolve_s", "Rozlíšenie polí",       "#FF6B6B"),
        ("time_metrics_s",       "Metriky grafu",         "#7030A0"),
        ("time_schema_s",        "Validácia schémy",      "#A5A5A5"),
    ]

    # ── compute bar positions ─────────────────────────────────────────────────
    n_v = len(variants)
    bar_w = 0.65 / max(n_v, 1)
    group_w = n_v * bar_w + 0.55      # width of one dataset group incl. padding

    bar_xs: Dict[tuple, float] = {}
    for gi, ds in enumerate(datasets):
        gc = gi * group_w
        for vi, (runner, cpu) in enumerate(variants):
            bar_xs[(ds, runner, cpu)] = gc + (vi - n_v / 2 + 0.5) * bar_w

    group_centers = [gi * group_w for gi in range(len(datasets))]
    x_tick_pos = [bar_xs[(ds, r, c)] for ds in datasets
                  for r, c in variants if (r, c, ds) in lookup]
    x_tick_lbl = [vlabel(r, c) for ds in datasets
                  for r, c in variants if (r, c, ds) in lookup]

    fig_w = max(9, len(datasets) * group_w * 2.2)

    with plt.rc_context(_STYLE):
        fig, (ax_t, ax_p) = plt.subplots(
            2, 1,
            figsize=(fig_w, 7.5),
            gridspec_kw={"height_ratios": [3, 1]},
            sharex=True,
        )

        # pre-compute max total for y-limit — gives stable headroom before labels
        max_total = max(
            (float(lookup[(r, c, ds)].get("time_total_s", 0))
             for ds in datasets for r, c in variants if (r, c, ds) in lookup),
            default=1.0,
        )
        y_ceil = max_total * 1.13   # 13% headroom for total-time labels + group badge

        # ── top panel: stacked phase bars ─────────────────────────────────────
        for ds in datasets:
            for runner, cpu in variants:
                key = (runner, cpu, ds)
                r = lookup.get(key)
                if r is None:
                    continue
                x = bar_xs[(ds, runner, cpu)]
                bar_total = float(r.get("time_total_s", 1))
                bottom = 0.0

                for field, _, color in PHASES:
                    v = float(r.get(field, 0))
                    if v <= 0:
                        continue
                    ax_t.bar(x, v, bar_w * 0.9, bottom=bottom, color=color, zorder=3)
                    # label only if the segment occupies > 4% of the y-axis height —
                    # this keeps analysis-phase labels on all bars while suppressing
                    # the dense collector-phase annotations that crowd on short bars
                    if v > y_ceil * 0.04:
                        ax_t.text(x, bottom + v / 2, f"{v * 1000:.0f}ms",
                                  ha="center", va="center", fontsize=6.5,
                                  color="white", fontweight="bold")
                    bottom += v

                # total time label — positioned relative to y_ceil for consistency
                ax_t.text(x, bottom + y_ceil * 0.012, f"{bar_total:.2f}s",
                          ha="center", va="bottom", fontsize=7, color="#333333")

        # legend
        patches = [mpatches.Patch(color=c, label=l) for _, l, c in PHASES]
        ax_t.legend(handles=patches, fontsize=7.5, loc="upper right",
                    ncol=2, framealpha=0.9, edgecolor="#CCCCCC")
        ax_t.set_ylabel("Čas pipeline (sekundy)", fontsize=9)
        ax_t.set_title("Čas pipeline podľa fáz  ·  Priepustnosť (súbory/s)",
                       fontsize=11, pad=14)
        ax_t.grid(axis="y", zorder=0)
        ax_t.set_ylim(0, y_ceil)

        # dataset group labels above the bars (blended transform: data x, axes y)
        trans_t = blended_transform_factory(ax_t.transData, ax_t.transAxes)
        for gi, ds in enumerate(datasets):
            gc = group_centers[gi]
            n_f = next((lookup[(r, c, ds)]["n_files"]
                        for r, c in variants if (r, c, ds) in lookup), "?")
            ax_t.text(gc, 1.02, f"{ds}  ({n_f} súborov)",
                      ha="center", va="bottom", fontsize=9, fontweight="bold",
                      transform=trans_t, clip_on=False,
                      bbox=dict(boxstyle="round,pad=0.2", fc="white",
                                ec="#CCCCCC", alpha=0.9))

        # vertical group separators
        for i in range(1, len(group_centers)):
            sep = (group_centers[i - 1] + group_centers[i]) / 2
            ax_t.axvline(sep, color="#BBBBBB", lw=0.8, ls="--", zorder=1)

        # ── bottom panel: throughput ──────────────────────────────────────────
        v_colors = {v: _PALETTE[vi % len(_PALETTE)] for vi, v in enumerate(variants)}

        for ds in datasets:
            for runner, cpu in variants:
                key = (runner, cpu, ds)
                r = lookup.get(key)
                if r is None:
                    continue
                x = bar_xs[(ds, runner, cpu)]
                total = float(r.get("time_total_s", 0))
                n_f = r.get("n_files", 0)
                tput = n_f / total if total > 0 else 0
                ax_p.bar(x, tput, bar_w * 0.9, color=v_colors[(runner, cpu)],
                         zorder=3, alpha=0.9)
                ax_p.text(x, tput * 1.03 + 0.02, f"{tput:.1f}",
                          ha="center", va="bottom", fontsize=6.5)

        for i in range(1, len(group_centers)):
            sep = (group_centers[i - 1] + group_centers[i]) / 2
            ax_p.axvline(sep, color="#BBBBBB", lw=0.8, ls="--", zorder=1)

        ax_p.set_ylabel("Priepustnosť\n(súbory/s)", fontsize=9)
        ax_p.set_xlabel(
            "Varianta: Seq = sekvenčná, R×N = Ray s N CPU",
            fontsize=8, labelpad=6,
        )
        ax_p.grid(axis="y", zorder=0)
        ax_p.set_ylim(bottom=0)

        # shared x ticks (visible only on bottom panel due to sharex)
        ax_p.set_xticks(x_tick_pos)
        ax_p.set_xticklabels(x_tick_lbl, rotation=45, ha="right", fontsize=7.5)

        xl = (group_centers[0] - group_w * 0.55,
              group_centers[-1] + group_w * 0.55)
        ax_p.set_xlim(*xl)

        fig.tight_layout()
        fig.subplots_adjust(hspace=0.08, top=0.91)

    out = _FIGURES_DIR / "throughput_phases.png"
    fig.savefig(out, dpi=150, facecolor="white")
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
        plot_memory,
        plot_graph_structure,
        plot_resolution_rate,
        plot_pipeline_stages,
        plot_collector_phases,
        plot_ray_scheduling,
        plot_throughput_phases,
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