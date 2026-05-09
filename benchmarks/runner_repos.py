"""
Repository benchmark runner.

Runs the full CPG pipeline against every subdirectory inside a Lua repository
folder and saves per-repo BenchmarkResult JSON files.

Usage:
    python -m benchmarks.runner_repos                          # 1/2/4 CPUs
    python -m benchmarks.runner_repos --cpus 1 2 4            # explicit sweep
    python -m benchmarks.runner_repos --repo-dir /path/repos --cpus 4
    python -m benchmarks.runner_repos --limit 20 --filter "lua*"
    python -m benchmarks.runner_repos --force                  # re-run all

Loop order is config-outer, repo-inner: Ray is initialised once per CPU count
and kept alive for all repos in that config.  If Ray crashes mid-config
it is automatically restarted before the next repo.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import ray

_ROOT = Path(__file__).parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_RESULTS_DIR = Path(__file__).parent / "results" / "repos"
_RESULTS_DIR.mkdir(parents=True, exist_ok=True)

_DEFAULT_REPO_DIR = _ROOT.parent / "Repository"


# ── helpers ───────────────────────────────────────────────────────────────────

def _already_ran(repo_name: str, num_cpus: int, runner: str) -> bool:
    """True if a result JSON already exists for this (repo, num_cpus, runner) triple."""
    runner_tag = f"_{runner}" if runner != "ray" else ""
    return any(_RESULTS_DIR.glob(f"{repo_name}_cpu{num_cpus}{runner_tag}_*.json"))


def _discover_repos(repo_dir: Path, pattern: Optional[str], limit: Optional[int]) -> List[Path]:
    repos = sorted(p for p in repo_dir.iterdir() if p.is_dir())
    if pattern:
        repos = [p for p in repos if fnmatch.fnmatch(p.name, pattern)]
    if limit:
        repos = repos[:limit]
    return repos


def _save_result(br, repo_name: str) -> Path:
    br.timestamp = datetime.utcnow().isoformat()
    runner_tag = f"_{br.runner}" if br.runner != "ray" else ""
    fname = f"{repo_name}_cpu{br.num_cpus}{runner_tag}_{br.timestamp[:19].replace(':', '-')}.json"
    out = _RESULTS_DIR / fname
    out.write_text(json.dumps(asdict(br), indent=2))
    return out


def _start_ray(num_cpus: int) -> None:
    if ray.is_initialized():
        ray.shutdown()
    ray.init(
        num_cpus=num_cpus,
        runtime_env={"env_vars": {"PYTHONPATH": str(_SRC)}},
    )


# ── core runner ───────────────────────────────────────────────────────────────

def run_all_repos(
    repo_dir: Path,
    cpu_counts: List[int] = None,
    limit: Optional[int] = None,
    pattern: Optional[str] = None,
    force: bool = False,
) -> List[dict]:
    """
    Run every repo under repo_dir for each CPU configuration.

    Loop structure is config-outer, repo-inner so Ray is initialised only once
    per CPU budget instead of once per repo — this is both faster and more stable.
    """
    from benchmarks.datasets import load_repo_directory
    from benchmarks.runner import run_benchmark_on_dir

    if cpu_counts is None:
        cpu_counts = [1, 2, 4]

    repos = _discover_repos(repo_dir, pattern, limit)
    if not repos:
        print(f"No repositories found in {repo_dir}")
        return []

    configs: List[Tuple[str, int]] = [("ray", cpu) for cpu in sorted(cpu_counts)]

    print(f"Found {len(repos)} repo(s) in {repo_dir}")
    print(f"Configurations: {configs}")

    saved: List[dict] = []

    for runner, num_cpus in configs:
        heading = f"ray / {num_cpus} CPU{'s' if num_cpus > 1 else ''}"
        print(f"\n{'─' * 55}\n  {heading}\n{'─' * 55}")

        if runner == "ray":
            _start_ray(num_cpus)

        for i, repo_path in enumerate(repos, 1):
            repo_name = repo_path.name
            prefix = f"[{i}/{len(repos)}] {repo_name}"

            if not force and _already_ran(repo_name, num_cpus, runner):
                print(f"{prefix}  — skipped (exists)")
                continue

            # Load file list (cheap — no Ray involved)
            try:
                extract_dir, files = load_repo_directory(repo_path)
                if not files:
                    print(f"{prefix}  — skipped (no .lua files)")
                    continue
            except Exception as exc:
                print(f"{prefix}  — skipped (load error: {exc})")
                continue

            print(f"{prefix}  ({len(files)} files) … ", end="", flush=True)
            t0 = time.perf_counter()

            try:
                br = run_benchmark_on_dir(
                    extract_dir, files, repo_name, num_cpus,
                    # We manage the Ray lifecycle ourselves (config-outer loop),
                    # so ray_restart=False prevents runner.py from shutting down
                    # the shared cluster between repos.
                    ray_restart=False,
                )
                elapsed = time.perf_counter() - t0
                print(f"{elapsed:.2f}s  kg={br.n_knowledge_nodes} nodes")

                _save_result(br, repo_name)
                saved.append(asdict(br))

            except Exception as exc:
                elapsed = time.perf_counter() - t0
                print(f"FAILED ({elapsed:.1f}s) — {exc}")

                # Ray may have died (OOM, worker crash).  Restart it so the
                # remaining repos in this config can still run.
                if not ray.is_initialized():
                    print("  Ray cluster died — restarting…")
                    try:
                        _start_ray(num_cpus)
                    except Exception as restart_exc:
                        print(f"  Ray restart failed: {restart_exc} — skipping rest of this config")
                        break

        if ray.is_initialized():
            ray.shutdown()

    return saved


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark all repos in a directory")
    parser.add_argument(
        "--repo-dir", type=Path, default=_DEFAULT_REPO_DIR,
        help=f"Directory containing Lua repos (default: {_DEFAULT_REPO_DIR})",
    )
    parser.add_argument(
        "--cpus", nargs="+", type=int, default=[1, 2, 4],
        help="CPU budgets to sweep (default: 1 2 4)",
    )
    parser.add_argument("--limit", type=int, default=None, help="Max repos to benchmark")
    parser.add_argument(
        "--filter", dest="pattern", default=None,
        help="Glob pattern to match repo names (e.g. 'lua*')",
    )
    parser.add_argument("--force", action="store_true",
                        help="Re-run repos that already have results")
    parser.add_argument("--no-plots", action="store_true",
                        help="Skip chart generation after benchmarks complete")
    args = parser.parse_args()

    if not args.repo_dir.exists():
        print(f"Repository directory not found: {args.repo_dir}")
        sys.exit(1)

    saved = run_all_repos(
        repo_dir=args.repo_dir,
        cpu_counts=args.cpus,
        limit=args.limit,
        pattern=args.pattern,
        force=args.force,
    )

    print(f"\nDone. {len(saved)} result(s) saved to {_RESULTS_DIR}")

    if not args.no_plots and saved:
        from benchmarks.plots_repos import generate_all
        print("\nGenerating repo charts…")
        paths = generate_all()
        for p in paths:
            print(f"  Saved: {p.name}")


if __name__ == "__main__":
    main()
