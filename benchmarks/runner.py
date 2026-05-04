"""
Benchmark runner for the GraphCreator CPG pipeline.

Usage:
    python -m benchmarks.runner                    # runs all datasets, saves JSON + prints summary
    python -m benchmarks.runner --dataset small    # single dataset
    python -m benchmarks.runner --cpus 1 2 4      # vary CPU budget (simulates hardware scale)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import tracemalloc
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import psutil
import ray

# ── project src on path ─────────────────────────────────────────────────────
_SRC = Path(__file__).parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ray_implementation.managers.ray_orchestrator import RayOrchestrator
from ray_implementation.builders.graph_collector import GraphCollector
from benchmarks.datasets import extract_dataset, dataset_exists, DATASETS

_RESULTS_DIR = Path(__file__).parent / "results"
_RESULTS_DIR.mkdir(exist_ok=True)


# ── result dataclass ─────────────────────────────────────────────────────────

@dataclass
class BenchmarkResult:
    dataset: str
    num_cpus: int           # Ray CPU budget — the actual parallelism lever
    n_files: int
    time_ray_s: float
    time_collect_s: float
    time_total_s: float
    peak_memory_mb: float
    rss_delta_mb: float
    n_knowledge_nodes: int
    n_knowledge_edges: int
    n_ast_nodes: int
    n_ast_edges: int
    resolved_imports: int
    unresolved_imports: int
    resolution_rate: float
    node_type_counts: Dict[str, int]
    edge_relation_counts: Dict[str, int]
    timestamp: str = ""

    def save(self) -> Path:
        self.timestamp = datetime.utcnow().isoformat()
        fname = f"{self.dataset}_cpu{self.num_cpus}_{self.timestamp[:19].replace(':', '-')}.json"
        out = _RESULTS_DIR / fname
        out.write_text(json.dumps(asdict(self), indent=2))
        return out


# ── resolution counting ──────────────────────────────────────────────────────

def _count_resolution(gc: GraphCollector) -> tuple[int, int]:
    """Count resolved and unresolved cross-file imports from collected results."""
    resolved = 0
    unresolved = 0
    for result in gc.results.values():
        for module_path in result.get("imports", {}).values():
            if module_path in gc._module_index:
                resolved += 1
            else:
                unresolved += 1
    return resolved, unresolved


# ── node / edge breakdowns ───────────────────────────────────────────────────

def _node_type_counts(gc: GraphCollector) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for node in gc._knowledge_nodes.values():
        t = node.get("type", "unknown")
        counts[t] = counts.get(t, 0) + 1
    return counts


def _edge_relation_counts(gc: GraphCollector) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for edge in gc._knowledge_edges:
        r = edge.get("relation", "unknown")
        counts[r] = counts.get(r, 0) + 1
    return counts


# ── core benchmark function ──────────────────────────────────────────────────

def run_benchmark(dataset: str, num_cpus: int = 4) -> BenchmarkResult:
    """
    Run the full CPG pipeline on *dataset* and return a BenchmarkResult.

    num_cpus caps how many analyze_file tasks Ray runs in parallel.
    Ray restarts between calls to enforce the CPU budget cleanly.

    Phases timed separately:
      Phase 1 — Ray analysis   (distribute_work + ray.get)
      Phase 2 — GraphCollector (merge + cross-file resolution)
    """
    extract_dir, files = extract_dataset(dataset)
    n_files = len(files)

    proc = psutil.Process(os.getpid())
    rss_before = proc.memory_info().rss

    # ── Phase 1: Ray analysis ────────────────────────────────────────────────
    # Restart Ray each run to enforce the CPU budget.
    # runtime_env propagates PYTHONPATH to task subprocesses.
    if ray.is_initialized():
        ray.shutdown()
    ray.init(
        num_cpus=num_cpus,
        runtime_env={"env_vars": {"PYTHONPATH": str(_SRC)}},
    )

    orchestrator = RayOrchestrator()
    tracemalloc.start()

    t0 = time.perf_counter()
    futures = orchestrator.distribute_work(files)
    results = ray.get(futures)
    t1 = time.perf_counter()

    _, peak_traced = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    time_ray = t1 - t0

    # filter None (failed parses)
    results = [r for r in results if r is not None]

    # ── Phase 2: GraphCollector ──────────────────────────────────────────────
    gc = GraphCollector()
    t2 = time.perf_counter()
    gc.collect(results, extract_dir)
    t3 = time.perf_counter()
    time_collect = t3 - t2

    rss_after = proc.memory_info().rss

    # ── metrics ──────────────────────────────────────────────────────────────
    resolved, unresolved = _count_resolution(gc)
    total_imports = resolved + unresolved
    resolution_rate = resolved / total_imports if total_imports > 0 else 1.0

    br = BenchmarkResult(
        dataset=dataset,
        num_cpus=num_cpus,
        n_files=n_files,
        time_ray_s=round(time_ray, 4),
        time_collect_s=round(time_collect, 4),
        time_total_s=round(time_ray + time_collect, 4),
        peak_memory_mb=round(peak_traced / 1024 / 1024, 2),
        rss_delta_mb=round((rss_after - rss_before) / 1024 / 1024, 2),
        n_knowledge_nodes=len(gc._knowledge_nodes),
        n_knowledge_edges=len(gc._knowledge_edges),
        n_ast_nodes=len(gc._ast_nodes),
        n_ast_edges=len(gc._ast_edges),
        resolved_imports=resolved,
        unresolved_imports=unresolved,
        resolution_rate=round(resolution_rate, 4),
        node_type_counts=_node_type_counts(gc),
        edge_relation_counts=_edge_relation_counts(gc),
    )

    ray.shutdown()
    return br


# ── scalability sweep ────────────────────────────────────────────────────────

def run_scalability_sweep(dataset: str, cpu_counts: List[int] = None) -> List[BenchmarkResult]:
    """Run the same dataset with increasing CPU budgets for speedup analysis."""
    if cpu_counts is None:
        cpu_counts = [1, 2, 4]
    results = []
    for n in cpu_counts:
        print(f"  [{dataset}] cpu={n} … ", end="", flush=True)
        br = run_benchmark(dataset, num_cpus=n)
        results.append(br)
        print(f"{br.time_total_s:.2f}s  ({br.n_files} files, {br.n_knowledge_nodes} kg-nodes)")
    return results


# ── CLI entry point ──────────────────────────────────────────────────────────

def _print_result(br: BenchmarkResult):
    print(f"\n{'─'*55}")
    print(f"  Dataset:       {br.dataset}  ({br.n_files} files)")
    print(f"  CPU budget:    {br.num_cpus}")
    print(f"  Ray phase:     {br.time_ray_s:.3f}s")
    print(f"  Collect phase: {br.time_collect_s:.3f}s")
    print(f"  Total:         {br.time_total_s:.3f}s")
    print(f"  Peak mem:      {br.peak_memory_mb:.1f} MB  (RSS Δ {br.rss_delta_mb:+.1f} MB)")
    print(f"  KG nodes:      {br.n_knowledge_nodes}   KG edges: {br.n_knowledge_edges}")
    print(f"  AST nodes:     {br.n_ast_nodes}   AST edges: {br.n_ast_edges}")
    print(f"  Resolution:    {br.resolution_rate:.0%}  ({br.resolved_imports}/{br.resolved_imports + br.unresolved_imports})")
    print(f"  Node types:    {br.node_type_counts}")


def main():
    parser = argparse.ArgumentParser(description="GraphCreator CPG benchmark runner")
    parser.add_argument("--dataset", choices=list(DATASETS.keys()) + ["all"], default="all")
    parser.add_argument("--cpus", nargs="+", type=int, default=[1, 2, 4],
                        help="CPU budgets to sweep (simulates hardware parallelism)")
    args = parser.parse_args()

    datasets = list(DATASETS.keys()) if args.dataset == "all" else [args.dataset]
    datasets = [d for d in datasets if dataset_exists(d)]

    if not datasets:
        print("No datasets found. Check benchmarks/datasets.py for paths.")
        sys.exit(1)

    all_results = []
    for ds in datasets:
        print(f"\nBenchmarking dataset: {ds}")
        sweep = run_scalability_sweep(ds, args.cpus)
        for br in sweep:
            path = br.save()
            _print_result(br)
            print(f"  Saved → {path.relative_to(Path(__file__).parent.parent)}")
        all_results.extend(sweep)

    print(f"\nDone. {len(all_results)} benchmark(s) saved to benchmarks/results/")
    return all_results


if __name__ == "__main__":
    main()