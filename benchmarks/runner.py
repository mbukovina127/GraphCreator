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
from benchmarks.datasets import extract_dataset, load_repo_directory, dataset_exists, DATASETS

_RESULTS_DIR = Path(__file__).parent / "results"
_RESULTS_DIR.mkdir(exist_ok=True)


# ── result dataclass ─────────────────────────────────────────────────────────

@dataclass
class BenchmarkResult:
    dataset: str
    num_cpus: int           # Ray CPU budget — the actual parallelism lever
    n_files: int
    # ── overall phase timings ──────────────────────────────────────────────────
    time_ray_s: float
    time_collect_s: float
    time_total_s: float
    peak_memory_mb: float
    rss_delta_mb: float
    # ── per-file pipeline breakdown (averages across all files) ───────────────
    avg_parse_s: float          # tree-sitter parse
    avg_ast_insert_s: float     # AST graph insertion
    avg_symbol_s: float         # symbol table build
    avg_cpg_build_s: float      # CPG / knowledge graph construction
    # ── GraphCollector sub-phase timings ──────────────────────────────────────
    time_collect_local_s: float # storing per-file results
    time_spine_s: float         # filesystem spine creation
    time_index_s: float         # module/chunk index build
    time_resolve_s: float       # cross-file edge resolution
    time_metrics_s: float       # graph-level metrics computation
    time_schema_s: float        # schema validation
    # ── Ray scheduling metrics ─────────────────────────────────────────────────
    tasks_submitted: int
    first_result_latency_s: float   # time from submission to first task done
    task_spread_s: float            # time between first and last task done
    # ── graph size ────────────────────────────────────────────────────────────
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


# ── per-file timing aggregation ─────────────────────────────────────────────

def _avg_timing(results: List[Dict], key: str) -> float:
    vals = [r["_timing"][key] for r in results if r and "_timing" in r and key in r["_timing"]]
    return round(sum(vals) / len(vals), 6) if vals else 0.0


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

def run_benchmark_on_dir(
    extract_dir: str,
    files: List[Dict],
    dataset_name: str,
    num_cpus: int = 4,
    *,
    ray_restart: bool = True,
) -> BenchmarkResult:
    """
    Run the full CPG pipeline on an already-extracted directory.

    Separates Ray analysis (Phase 1) from GraphCollector merge (Phase 2).
    Called by run_benchmark() and runner_repos.py.

    ray_restart=False skips the Ray shutdown/init cycle — use when the
    caller manages Ray lifetime across many consecutive runs.
    """
    n_files = len(files)

    proc = psutil.Process(os.getpid())
    rss_before = proc.memory_info().rss

    if ray_restart:
        if ray.is_initialized():
            ray.shutdown()
        ray.init(
            num_cpus=num_cpus,
            runtime_env={"env_vars": {"PYTHONPATH": str(_SRC)}},
        )

    orchestrator = RayOrchestrator()
    tracemalloc.start()

    # ── Phase 1: Ray analysis with scheduling metrics ────────────────────────
    t_submit = time.perf_counter()
    futures = orchestrator.distribute_work(files)
    tasks_submitted = len(futures)

    remaining = list(futures)
    completion_times: List[float] = []
    while remaining:
        done, remaining = ray.wait(remaining, num_returns=1)
        completion_times.append(time.perf_counter() - t_submit)

    t1 = time.perf_counter()
    _, peak_traced = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    time_ray = t1 - t_submit

    results = ray.get(futures)

    first_result_latency = round(completion_times[0], 4) if completion_times else 0.0
    task_spread = round(completion_times[-1] - completion_times[0], 4) if len(completion_times) > 1 else 0.0

    results = [r for r in results if r is not None]

    # ── Phase 2: GraphCollector ──────────────────────────────────────────────
    gc = GraphCollector()
    t2 = time.perf_counter()
    gc.collect(results, extract_dir)
    t3 = time.perf_counter()
    time_collect = t3 - t2

    rss_after = proc.memory_info().rss
    pt = gc.phase_timings

    resolved, unresolved = _count_resolution(gc)
    total_imports = resolved + unresolved
    resolution_rate = resolved / total_imports if total_imports > 0 else 1.0

    br = BenchmarkResult(
        dataset=dataset_name,
        num_cpus=num_cpus,
        n_files=n_files,
        time_ray_s=round(time_ray, 4),
        time_collect_s=round(time_collect, 4),
        time_total_s=round(time_ray + time_collect, 4),
        peak_memory_mb=round(peak_traced / 1024 / 1024, 2),
        rss_delta_mb=round((rss_after - rss_before) / 1024 / 1024, 2),
        avg_parse_s=_avg_timing(results, "parse_s"),
        avg_ast_insert_s=_avg_timing(results, "ast_insert_s"),
        avg_symbol_s=_avg_timing(results, "symbol_s"),
        avg_cpg_build_s=_avg_timing(results, "cpg_build_s"),
        time_collect_local_s=round(pt.get("collect_local_s", 0), 4),
        time_spine_s=round(pt.get("spine_s", 0), 4),
        time_index_s=round(pt.get("index_s", 0), 4),
        time_resolve_s=round(pt.get("resolve_s", 0), 4),
        time_metrics_s=round(pt.get("metrics_s", 0), 4),
        time_schema_s=round(pt.get("schema_s", 0), 4),
        tasks_submitted=tasks_submitted,
        first_result_latency_s=first_result_latency,
        task_spread_s=task_spread,
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

    if ray_restart:
        ray.shutdown()
    return br


def run_benchmark(dataset: str, num_cpus: int = 4) -> BenchmarkResult:
    """Run the full CPG pipeline on a named ZIP dataset."""
    extract_dir, files = extract_dataset(dataset)
    return run_benchmark_on_dir(extract_dir, files, dataset, num_cpus, ray_restart=True)


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
    print(f"  Ray phase:     {br.time_ray_s:.3f}s  (tasks={br.tasks_submitted}, "
          f"first={br.first_result_latency_s:.3f}s, spread={br.task_spread_s:.3f}s)")
    print(f"  Collect phase: {br.time_collect_s:.3f}s")
    print(f"    spine={br.time_spine_s:.3f}s  index={br.time_index_s:.3f}s  "
          f"resolve={br.time_resolve_s:.3f}s  metrics={br.time_metrics_s:.3f}s")
    print(f"  Total:         {br.time_total_s:.3f}s")
    print(f"  Peak mem:      {br.peak_memory_mb:.1f} MB  (RSS Δ {br.rss_delta_mb:+.1f} MB)")
    print(f"  Per-file avg:  parse={br.avg_parse_s*1000:.1f}ms  "
          f"ast={br.avg_ast_insert_s*1000:.1f}ms  "
          f"sym={br.avg_symbol_s*1000:.1f}ms  "
          f"cpg={br.avg_cpg_build_s*1000:.1f}ms")
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