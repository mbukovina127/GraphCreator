"""
Grafy pre výsledky benchmarkov per-repozitár.

Použitie:
    python -m benchmarks.plots_repos                     # číta benchmarks/results/repos/
    python -m benchmarks.plots_repos --results cesta/    # vlastný adresár
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
    "axes.facecolor": "white",
    "figure.facecolor": "white",
    "axes.edgecolor": "#CCCCCC",
    "grid.color": "#EEEEEE",
    "grid.linewidth": 1.0,
    "font.size": 10,
}

_CPU_LABEL = staticmethod(lambda cpu: f"{cpu} CPU")


# ── načítanie dát ─────────────────────────────────────────────────────────────

def _load_results(results_dir: Path) -> List[Dict]:
    """Načíta JSON súbory, zachová iba najnovší beh pre každú trojicu (dataset, num_cpus, runner)."""
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


# ── Graf 1: Poradie repozitárov podľa času ────────────────────────────────────

def plot_repo_time_ranking(results: List[Dict], top_n: int = 50) -> Path:
    """Hustý skupinový horizontálny stĺpcový graf: každý variant CPU pre každý repozitár, zoradený podľa najpomalšieho."""
    by_repo_cpu: Dict[str, Dict[int, Dict]] = {}
    for r in results:
        by_repo_cpu.setdefault(r["dataset"], {})[r["num_cpus"]] = r

    all_cpus = sorted({r["num_cpus"] for r in results})

    ranked_names = sorted(
        by_repo_cpu.keys(),
        key=lambda name: max(v["time_total_s"] for v in by_repo_cpu[name].values()),
        reverse=True,
    )[:top_n]
    if not ranked_names:
        raise ValueError("Žiadne výsledky repozitárov na zobrazenie")

    n_cpus = len(all_cpus)
    bar_h = 0.8 / n_cpus
    fig_height = max(4, len(ranked_names) * n_cpus * 0.12)

    with plt.rc_context(_STYLE):
        fig, ax = plt.subplots(figsize=(11, fig_height))
        y = np.arange(len(ranked_names))

        for ci, cpu in enumerate(all_cpus):
            offset = (ci - n_cpus / 2 + 0.5) * bar_h
            times = [by_repo_cpu[name].get(cpu, {}).get("time_total_s", 0)
                     for name in ranked_names]
            ax.barh(y + offset, times, bar_h * 0.9,
                    label=_CPU_LABEL(cpu),
                    color=_PALETTE[ci % len(_PALETTE)], zorder=3)

        ax.set_yticks(y)
        ax.set_yticklabels(ranked_names, fontsize=6)
        ax.invert_yaxis()
        ax.set_xlabel("Celkový čas pipeline (sekundy)")
        ax.set_title(f"Poradie repozitárov podľa času — Top {len(ranked_names)} (všetky varianty CPU)")
        ax.legend(fontsize=6)
        ax.grid(axis="x", zorder=0)
        fig.tight_layout()

    out = _FIGURES_DIR / "repo_time_ranking.png"
    fig.savefig(out, dpi=150, facecolor='white')
    plt.close(fig)
    return out


# ── Graf 2: Rozptylový diagram — počet súborov vs celkový čas ─────────────────

def plot_repo_scatter(results: List[Dict]) -> Path:
    """
    Rozptylový diagram: počet súborov vs celkový čas s mocninovým fitom.
    Zobrazuje, či pipeline škáluje lineárne s počtom súborov, a zvýrazňuje odľahlé hodnoty.
    """
    by_repo: Dict[str, Dict] = {}
    for r in results:
        name = r["dataset"]
        if name not in by_repo or r["num_cpus"] > by_repo[name]["num_cpus"]:
            by_repo[name] = r

    if not by_repo:
        raise ValueError("Žiadne výsledky repozitárov na zobrazenie")

    names = list(by_repo.keys())
    xs = np.array([by_repo[n]["n_files"]     for n in names], dtype=float)
    ys = np.array([by_repo[n]["time_total_s"] for n in names], dtype=float)

    mask = (xs > 0) & (ys > 0)
    xs, ys, names = xs[mask], ys[mask], [n for n, m in zip(names, mask) if m]

    with plt.rc_context(_STYLE):
        fig, ax = plt.subplots(figsize=(9, 6))
        ax.scatter(xs, ys, color=_PALETTE[0], alpha=0.65, s=40, zorder=3)

        if len(xs) > 1:
            log_coeffs = np.polyfit(np.log10(xs), np.log10(ys), 1)
            b, log_a = log_coeffs
            x_line = np.linspace(xs.min(), xs.max(), 200)
            ax.plot(x_line, 10 ** log_a * x_line ** b, "--", color="#CC3333",
                    linewidth=1.5, label=f"Mocninový fit  y ∝ x^{b:.2f}")

        top5_idx = np.argsort(ys)[-5:]
        for i in top5_idx:
            ax.annotate(names[i], (xs[i], ys[i]),
                        textcoords="offset points", xytext=(5, 3), fontsize=7)

        ax.set_xlabel("Počet súborov (.lua)")
        ax.set_ylabel("Celkový čas pipeline (sekundy)")
        ax.set_title("Škálovanie repozitárov: počet súborov vs čas pipeline")
        ax.legend(fontsize=9)
        ax.grid(zorder=0, alpha=0.5)
        fig.tight_layout()

    out = _FIGURES_DIR / "repo_scatter.png"
    fig.savefig(out, dpi=150, facecolor='white')
    plt.close(fig)
    return out


# ── Graf 3: Rozklad fáz (Ray vs Zbieranie) pre top repozitáre ────────────────

def plot_repo_phase_breakdown(results: List[Dict], top_n: int = 30) -> Path:
    """
    Hustý vrstvený horizontálny stĺpcový graf: čas Ray analýzy vs čas zbierania GraphCollector,
    jedna skupina stĺpcov pre každý variant CPU pre každý repozitár.
    """
    by_repo_cpu: Dict[str, Dict[int, Dict]] = {}
    for r in results:
        by_repo_cpu.setdefault(r["dataset"], {})[r["num_cpus"]] = r

    all_cpus = sorted({r["num_cpus"] for r in results})

    ranked_names = sorted(
        by_repo_cpu.keys(),
        key=lambda name: max(v["time_total_s"] for v in by_repo_cpu[name].values()),
        reverse=True,
    )[:top_n]
    if not ranked_names:
        raise ValueError("Žiadne výsledky repozitárov na zobrazenie")

    n_cpus = len(all_cpus)
    bar_h = 0.8 / n_cpus
    fig_height = max(4, len(ranked_names) * n_cpus * 0.12)

    with plt.rc_context(_STYLE):
        fig, ax = plt.subplots(figsize=(11, fig_height))
        y = np.arange(len(ranked_names))

        for ci, cpu in enumerate(all_cpus):
            offset = (ci - n_cpus / 2 + 0.5) * bar_h
            ray_t  = np.array([by_repo_cpu[n].get(cpu, {}).get("time_ray_s", 0)
                                for n in ranked_names])
            coll_t = np.array([by_repo_cpu[n].get(cpu, {}).get("time_collect_s", 0)
                                for n in ranked_names])
            lbl = _CPU_LABEL(cpu)
            ax.barh(y + offset, ray_t, bar_h * 0.9,
                    label=f"{lbl} — analýza", color=_PALETTE[ci % len(_PALETTE)], zorder=3)
            ax.barh(y + offset, coll_t, bar_h * 0.9, left=ray_t,
                    label=f"{lbl} — zbieranie",
                    color=_PALETTE[(ci + 2) % len(_PALETTE)], alpha=0.6, zorder=3)

        ax.set_yticks(y)
        ax.set_yticklabels(ranked_names, fontsize=6)
        ax.invert_yaxis()
        ax.set_xlabel("Čas (sekundy)")
        ax.set_title(f"Fáza Ray vs Zbieranie — Top {len(ranked_names)} repozitárov (všetky varianty CPU)")
        ax.legend(fontsize=6, loc="lower right")
        ax.grid(axis="x", zorder=0)
        fig.tight_layout()

    out = _FIGURES_DIR / "repo_phase_breakdown.png"
    fig.savefig(out, dpi=150, facecolor='white')
    plt.close(fig)
    return out


# ── Graf 4: Detail podfáz GraphCollector pre top repozitáre ──────────────────

def plot_repo_collector_phases(results: List[Dict], top_n: int = 30) -> Path:
    """
    Hustý vrstvený horizontálny stĺpcový graf podfáz GraphCollector,
    jedna skupina stĺpcov pre každý variant CPU pre každý repozitár.
    """
    by_repo_cpu: Dict[str, Dict[int, Dict]] = {}
    for r in results:
        by_repo_cpu.setdefault(r["dataset"], {})[r["num_cpus"]] = r

    all_cpus = sorted({r["num_cpus"] for r in results})

    ranked_names = sorted(
        by_repo_cpu.keys(),
        key=lambda name: max(v["time_total_s"] for v in by_repo_cpu[name].values()),
        reverse=True,
    )[:top_n]
    if not ranked_names:
        raise ValueError("Žiadne výsledky repozitárov na zobrazenie")

    phases = [
        ("time_collect_local_s", "Ukladanie výsledkov"),
        ("time_spine_s",         "Hierarchia súborového systému"),
        ("time_index_s",         "Zostavenie indexu"),
        ("time_resolve_s",       "Medzisúborové rozlíšenie"),
        ("time_metrics_s",       "Metriky grafu"),
        ("time_schema_s",        "Validácia schémy"),
    ]

    n_cpus = len(all_cpus)
    bar_h = 0.8 / n_cpus
    fig_height = max(4, len(ranked_names) * n_cpus * 0.12)

    with plt.rc_context(_STYLE):
        fig, ax = plt.subplots(figsize=(12, fig_height))
        y = np.arange(len(ranked_names))

        for ci, cpu in enumerate(all_cpus):
            offset = (ci - n_cpus / 2 + 0.5) * bar_h
            lefts = np.zeros(len(ranked_names))
            for pi, (field, label) in enumerate(phases):
                vals = np.array([by_repo_cpu[n].get(cpu, {}).get(field, 0)
                                 for n in ranked_names])
                lbl = f"{_CPU_LABEL(cpu)} — {label}" if ci == 0 else ""
                ax.barh(y + offset, vals, bar_h * 0.9, left=lefts,
                        color=_PALETTE[pi % len(_PALETTE)],
                        label=lbl if lbl else None, zorder=3)
                lefts += vals

        ax.set_yticks(y)
        ax.set_yticklabels(ranked_names, fontsize=6)
        ax.invert_yaxis()
        ax.set_xlabel("Čas (sekundy)")
        ax.set_title(f"Podfázy GraphCollector — Top {len(ranked_names)} repozitárov (všetky varianty CPU)")
        ax.legend(fontsize=6, loc="lower right")
        ax.grid(axis="x", zorder=0)
        fig.tight_layout()

    out = _FIGURES_DIR / "repo_collector_phases.png"
    fig.savefig(out, dpi=150, facecolor='white')
    plt.close(fig)
    return out


# ── Graf 5: Poradie repozitárov podľa pamäte ─────────────────────────────────

def plot_repo_memory(results: List[Dict], top_n: int = 50) -> Path:
    """
    Hustý skupinový horizontálny stĺpcový graf: nárast RSS pamäte (MB) pre každý variant CPU,
    zoradený podľa najväčšej spotreby pamäte.
    """
    by_repo_cpu: Dict[str, Dict[int, Dict]] = {}
    for r in results:
        by_repo_cpu.setdefault(r["dataset"], {})[r["num_cpus"]] = r

    all_cpus = sorted({r["num_cpus"] for r in results})

    ranked_names = sorted(
        by_repo_cpu.keys(),
        key=lambda name: max(v.get("rss_delta_mb", 0) for v in by_repo_cpu[name].values()),
        reverse=True,
    )[:top_n]
    if not ranked_names:
        raise ValueError("Žiadne výsledky repozitárov na zobrazenie")

    n_cpus = len(all_cpus)
    bar_h = 0.8 / n_cpus
    fig_height = max(4, len(ranked_names) * n_cpus * 0.12)

    with plt.rc_context(_STYLE):
        fig, ax = plt.subplots(figsize=(11, fig_height))
        y = np.arange(len(ranked_names))

        for ci, cpu in enumerate(all_cpus):
            offset = (ci - n_cpus / 2 + 0.5) * bar_h
            mems = [by_repo_cpu[name].get(cpu, {}).get("rss_delta_mb", 0)
                    for name in ranked_names]
            ax.barh(y + offset, mems, bar_h * 0.9,
                    label=_CPU_LABEL(cpu),
                    color=_PALETTE[ci % len(_PALETTE)], zorder=3)

        ax.set_yticks(y)
        ax.set_yticklabels(ranked_names, fontsize=6)
        ax.invert_yaxis()
        ax.set_xlabel("Nárast RSS pamäte (MB)")
        ax.set_title(f"Poradie repozitárov podľa pamäte — Top {len(ranked_names)} (všetky varianty CPU)")
        ax.legend(fontsize=6)
        ax.grid(axis="x", zorder=0)
        fig.tight_layout()

    out = _FIGURES_DIR / "repo_memory.png"
    fig.savefig(out, dpi=150, facecolor='white')
    plt.close(fig)
    return out


# ── Graf 6: Rozdelenie časov spracovania (Gaussov + lognormálny fit) ──────────

def plot_repo_distribution(results: List[Dict]) -> Path:
    """
    Dvojpanelový graf rozdelenia časov spracovania repozitárov.

    Ľavý panel  — lineárna os s Gaussovým fitom. Pravostranné skreslenie je viditeľné
                  hneď: krivka zasahuje do záporných hodnôt a nehodí sa na dlhý chvost.
    Pravý panel — logaritmická os s lognormálnym fitom. V log-priestore sú dáta takmer
                  symetrické (šikmosť ≈ 0.14), čo potvrdzuje lognormálne rozdelenie —
                  typické pre metriky kódových repozitárov.

    Prerušované zvislé čiary označujú geometrický priemer (= medián lognormálneho rozdelenia).
    """
    by_repo_cpu: Dict[str, Dict[int, Dict]] = {}
    for r in results:
        by_repo_cpu.setdefault(r["dataset"], {})[r["num_cpus"]] = r

    all_cpus = sorted({r["num_cpus"] for r in results})

    with plt.rc_context(_STYLE):
        fig, (ax_raw, ax_log) = plt.subplots(1, 2, figsize=(14, 5))

        for ci, cpu in enumerate(all_cpus):
            times = np.array([
                by_repo_cpu[name][cpu]["time_total_s"]
                for name in by_repo_cpu
                if cpu in by_repo_cpu[name]
                and by_repo_cpu[name][cpu].get("time_total_s", 0) > 0
            ])
            if len(times) < 5:
                continue

            color = _PALETTE[ci % len(_PALETTE)]

            # ── Ľavý panel: lineárna os, Gaussov fit ──────────────────────────
            mu_raw, sig_raw = float(times.mean()), float(times.std())
            skew_raw = float((((times - mu_raw) / sig_raw) ** 3).mean())
            ax_raw.hist(times, bins=25, density=True, alpha=0.35, color=color,
                        label=f"{_CPU_LABEL(cpu)} (n={len(times)}, μ={mu_raw:.2f}s, σ={sig_raw:.2f}s, šikmosť={skew_raw:.2f})")
            x_raw = np.linspace(max(0, mu_raw - 4 * sig_raw), mu_raw + 4 * sig_raw, 300)
            pdf_raw = ((1 / (sig_raw * np.sqrt(2 * np.pi)))
                       * np.exp(-0.5 * ((x_raw - mu_raw) / sig_raw) ** 2))
            ax_raw.plot(x_raw, pdf_raw, color=color, linewidth=2)
            ax_raw.axvline(mu_raw, color=color, linestyle="--", linewidth=1.2, alpha=0.8)

            # ── Pravý panel: logaritmická os, lognormálny fit ──────────────────
            log_t = np.log(times)
            mu_log, sig_log = float(log_t.mean()), float(log_t.std())
            skew_log = float((((log_t - mu_log) / sig_log) ** 3).mean())
            geo_mean = float(np.exp(mu_log))
            bins_log = np.logspace(np.log10(times.min()), np.log10(times.max()), 25)
            ax_log.hist(times, bins=bins_log, density=True, alpha=0.35, color=color,
                        label=f"{_CPU_LABEL(cpu)} (n={len(times)}, geom. priemer={geo_mean:.3f}s, σ_log={sig_log:.2f}, šikmosť={skew_log:.2f})")
            x_log = np.logspace(np.log10(times.min()), np.log10(times.max()), 400)
            pdf_log = ((1 / (x_log * sig_log * np.sqrt(2 * np.pi)))
                       * np.exp(-0.5 * ((np.log(x_log) - mu_log) / sig_log) ** 2))
            ax_log.plot(x_log, pdf_log, color=color, linewidth=2)
            ax_log.axvline(geo_mean, color=color, linestyle="--", linewidth=1.2, alpha=0.8)

        ax_raw.set_xlabel("Celkový čas pipeline (s)")
        ax_raw.set_ylabel("Hustota pravdepodobnosti")
        ax_raw.set_title("Gaussov fit — lineárna os\n(pravostranné skreslenie: zlý fit)")
        ax_raw.legend(fontsize=7)
        ax_raw.grid(zorder=0, alpha=0.5)
        ax_raw.set_xlim(left=0)

        ax_log.set_xscale("log")
        ax_log.set_xlabel("Celkový čas pipeline (s, logaritmická os)")
        ax_log.set_ylabel("Hustota pravdepodobnosti")
        ax_log.set_title("Lognormálny fit — logaritmická os\n(takmer symetrický v log-priestore: dobrý fit)")
        ax_log.legend(fontsize=7)
        ax_log.grid(zorder=0, alpha=0.5)

        fig.suptitle("Rozdelenie časov spracovania repozitárov", fontsize=13, fontweight="bold")
        fig.tight_layout()

    out = _FIGURES_DIR / "repo_distribution.png"
    fig.savefig(out, dpi=150, facecolor='white')
    plt.close(fig)
    return out


# ── generovanie všetkých grafov ───────────────────────────────────────────────

def generate_all(results_dir: Path | None = None) -> List[Path]:
    if results_dir is None:
        results_dir = _RESULTS_DIR

    results = _load_results(results_dir)
    if not results:
        print(f"Žiadne benchmark JSON súbory nenájdené v {results_dir}")
        return []

    generators = [
        plot_repo_time_ranking,
        plot_repo_scatter,
        plot_repo_phase_breakdown,
        plot_repo_collector_phases,
        plot_repo_memory,
        plot_repo_distribution,
    ]

    paths = []
    for gen in generators:
        try:
            p = gen(results)
            paths.append(p)
            print(f"  Uložené: {p.name}")
        except Exception as e:
            print(f"  Upozornenie: {gen.__name__} zlyhalo — {e}")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Generovanie grafov benchmarkov per-repozitár")
    parser.add_argument("--results", type=Path, default=None,
                        help="Adresár s JSON súbormi benchmarkov repozitárov")
    args = parser.parse_args()

    print("Generovanie grafov repozitárov…")
    paths = generate_all(args.results)
    print(f"\n{len(paths)} graf(ov) uložených do benchmarks/figures/")


if __name__ == "__main__":
    main()
