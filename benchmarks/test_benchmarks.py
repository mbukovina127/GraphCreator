"""
Benchmark tests for the GraphCreator CPG pipeline.

Run with:
    pytest benchmarks/test_benchmarks.py -v
    pytest benchmarks/test_benchmarks.py --benchmark-json=benchmarks/results/benchmark.json -v

These are intentionally separate from tests/ so normal CI is unaffected.
Requires 'small' and 'medium' datasets (already present in tests/resources/).
"""

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from benchmarks.datasets import DATASETS, dataset_exists
from benchmarks.runner import BenchmarkResult, run_benchmark


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def small_result() -> BenchmarkResult:
    return run_benchmark("small", num_cpus=2)


@pytest.fixture(scope="module")
def medium_result() -> BenchmarkResult:
    return run_benchmark("medium", num_cpus=2)


# ── structural correctness ────────────────────────────────────────────────────

class TestGraphCorrectness:
    """Assert the CPG captures expected node types and structures."""

    def test_small_has_knowledge_nodes(self, small_result):
        assert small_result.n_knowledge_nodes > 0

    def test_small_has_knowledge_edges(self, small_result):
        assert small_result.n_knowledge_edges > 0

    def test_small_has_ast_nodes(self, small_result):
        assert small_result.n_ast_nodes > 0

    def test_small_contains_function_nodes(self, small_result):
        fn_count = (small_result.node_type_counts.get("global_function_definition", 0)
                    + small_result.node_type_counts.get("local_function_definition", 0))
        assert fn_count > 0, (
            f"Expected function nodes, got types: {list(small_result.node_type_counts.keys())}"
        )

    def test_small_contains_file_nodes(self, small_result):
        assert small_result.node_type_counts.get("file", 0) > 0, (
            "Expected file-level nodes from the directory spine"
        )

    def test_medium_contains_function_nodes(self, medium_result):
        fn_count = (medium_result.node_type_counts.get("global_function_definition", 0)
                    + medium_result.node_type_counts.get("local_function_definition", 0))
        assert fn_count > 0

    def test_medium_contains_chunk_nodes(self, medium_result):
        assert medium_result.node_type_counts.get("chunk", 0) > 0

    def test_medium_has_more_nodes_than_small(self, small_result, medium_result):
        assert medium_result.n_knowledge_nodes >= small_result.n_knowledge_nodes, (
            "Medium dataset should produce at least as many nodes as small"
        )

    def test_resolution_rate_reasonable(self, medium_result):
        assert medium_result.resolution_rate >= 0.0
        assert medium_result.resolution_rate <= 1.0

    def test_edge_relations_present(self, medium_result):
        assert len(medium_result.edge_relation_counts) > 0, (
            "Expected at least one edge relation type in the knowledge graph"
        )


# ── performance ───────────────────────────────────────────────────────────────

class TestPerformance:
    """Sanity-check timing and memory bounds."""

    def test_small_completes_in_reasonable_time(self, small_result):
        assert small_result.time_total_s < 120, (
            f"Small dataset took {small_result.time_total_s:.1f}s — expected < 120s"
        )

    def test_medium_completes_in_reasonable_time(self, medium_result):
        assert medium_result.time_total_s < 300, (
            f"Medium dataset took {medium_result.time_total_s:.1f}s — expected < 300s"
        )

    def test_peak_memory_not_excessive(self, medium_result):
        assert medium_result.peak_memory_mb < 2048, (
            f"Peak memory {medium_result.peak_memory_mb:.0f} MB exceeded 2 GB threshold"
        )

    def test_collect_phase_timing_recorded(self, small_result):
        assert small_result.time_collect_s >= 0
        assert small_result.time_ray_s >= 0

    def test_n_files_matches_dataset(self, small_result, medium_result):
        assert small_result.n_files > 0
        assert medium_result.n_files >= small_result.n_files


# ── scalability ───────────────────────────────────────────────────────────────

class TestScalability:
    """Verify that adding workers helps (or at least doesn't hurt significantly)."""

    def test_two_cpus_not_slower_than_one_on_medium(self):
        t1 = run_benchmark("medium", num_cpus=1).time_total_s
        t2 = run_benchmark("medium", num_cpus=2).time_total_s
        # allow 20% slack — Ray init overhead is real on small datasets
        assert t2 <= t1 * 1.2, (
            f"2 CPUs ({t2:.2f}s) was significantly slower than 1 CPU ({t1:.2f}s)"
        )

    def test_four_cpus_faster_than_one_on_medium(self):
        t1 = run_benchmark("medium", num_cpus=1).time_total_s
        t4 = run_benchmark("medium", num_cpus=4).time_total_s
        assert t4 <= t1, (
            f"4 CPUs ({t4:.2f}s) was not faster than 1 CPU ({t1:.2f}s)"
        )


# ── pytest-benchmark integration ──────────────────────────────────────────────

def test_pipeline_small_benchmark(benchmark):
    """pytest-benchmark: measures mean/stddev across repeated runs on small dataset."""
    result = benchmark(run_benchmark, "small", num_cpus=2)
    assert result.n_knowledge_nodes > 0


def test_pipeline_medium_benchmark(benchmark):
    """pytest-benchmark: measures mean/stddev across repeated runs on medium dataset."""
    result = benchmark(run_benchmark, "medium", num_cpus=2)
    assert result.n_knowledge_nodes > 0


# ── large dataset (skipped if not present) ───────────────────────────────────

@pytest.mark.skipif(not dataset_exists("large"), reason="large dataset not available")
def test_large_dataset_correctness():
    result = run_benchmark("large", n_workers=4)
    assert result.n_knowledge_nodes > 0
    assert result.node_type_counts.get("function", 0) > 0
    assert result.resolution_rate >= 0.5