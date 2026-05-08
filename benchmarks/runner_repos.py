"""
Repository benchmark runner.

Runs the full CPG pipeline against every subdirectory inside a Lua repository
folder and saves per-repo BenchmarkResult JSON files.

Usage:
    python -m benchmarks.runner_repos                          # all repos, 4 CPUs
    python -m benchmarks.runner_repos --repo-dir /path/repos  # custom repo directory
    python -m benchmarks.runner_repos --cpus 4 --limit 20     # first 20 repos
    python -m benchmarks.runner_repos --filter "lua*"         # glob filter
    python -m benchmarks.runner_repos --force                  # re-run existing results
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
from typing import List, Optional

import ray

_ROOT = Path(__file__).parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_RESULTS_DIR = Path(__file__).parent / "results" / "repos"
_RESULTS_DIR.mkdir(parents=True, exist_ok=True)

_DEFAULT_REPO_DIR = _ROOT.parent / "Repository"


def _already_ran(repo_name: str, num_cpus: int) -> bool:
    """True if a result JSON already exists for this (repo, cpus) pair."""
    return any(_RESULTS_DIR.glob(f"{repo_name}_cpu{num_cpus}_*.json"))


def _discover_repos(repo_dir: Path, pattern: Optional[str], limit: Optional[int]) -> List[Path]:
    """Return sorted list of repo directories, optionally filtered and capped."""
    repos = sorted(p for p in repo_dir.iterdir() if p.is_dir())
    if pattern:
        repos = [p for p in repos if fnmatch.fnmatch(p.name, pattern)]
    if limit:
        repos = repos[:limit]
    return repos


def run_all_repos(
    repo_dir: Path,
    num_cpus: int = 4,
    limit: Optional[int] = None,
    pattern: Optional[str] = None,
    force: bool = False,
) -> List[dict]:
    from benchmarks.datasets import load_repo_directory
    from benchmarks.runner import run_benchmark_on_dir

    repos = _discover_repos(repo_dir, pattern, limit)
    if not repos:
        print(f"No repositories found in {repo_dir}")
        return []

    print(f"Found {len(repos)} repo(s) in {repo_dir}  (cpus={num_cpus})")

    # Initialise Ray once for the whole sweep.
    if ray.is_initialized():
        ray.shutdown()
    ray.init(
        num_cpus=num_cpus,
        runtime_env={"env_vars": {"PYTHONPATH": str(_SRC)}},
    )

    saved: List[dict] = []
    for i, repo_path in enumerate(repos, 1):
        repo_name = repo_path.name
        prefix = f"[{i}/{len(repos)}] {repo_name}"

        if not force and _already_ran(repo_name, num_cpus):
            print(f"{prefix}  — skipped (result exists, use --force to re-run)")
            continue

        try:
            extract_dir, files = load_repo_directory(repo_path)
            if not files:
                print(f"{prefix}  — skipped (no .lua files)")
                continue

            t0 = time.perf_counter()
            print(f"{prefix}  ({len(files)} files) … ", end="", flush=True)

            br = run_benchmark_on_dir(
                extract_dir, files, repo_name, num_cpus, ray_restart=False
            )

            elapsed = time.perf_counter() - t0
            print(f"{elapsed:.2f}s  kg={br.n_knowledge_nodes} nodes")

            br.timestamp = datetime.utcnow().isoformat()
            fname = f"{repo_name}_cpu{num_cpus}_{br.timestamp[:19].replace(':', '-')}.json"
            out = _RESULTS_DIR / fname
            out.write_text(json.dumps(asdict(br), indent=2))
            saved.append(asdict(br))

        except Exception as exc:
            print(f"ERROR — {exc}")

    ray.shutdown()
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark all repos in a directory")
    parser.add_argument(
        "--repo-dir", type=Path, default=_DEFAULT_REPO_DIR,
        help=f"Directory containing Lua repos (default: {_DEFAULT_REPO_DIR})",
    )
    parser.add_argument("--cpus", type=int, default=4, help="Ray CPU budget")
    parser.add_argument("--limit", type=int, default=None, help="Max repos to run")
    parser.add_argument("--filter", dest="pattern", default=None,
                        help="Glob pattern to match repo names (e.g. 'lua*')")
    parser.add_argument("--force", action="store_true",
                        help="Re-run repos that already have results")
    parser.add_argument("--no-plots", action="store_true",
                        help="Skip chart generation after benchmarks")
    args = parser.parse_args()

    if not args.repo_dir.exists():
        print(f"Repository directory not found: {args.repo_dir}")
        sys.exit(1)

    saved = run_all_repos(
        repo_dir=args.repo_dir,
        num_cpus=args.cpus,
        limit=args.limit,
        pattern=args.pattern,
        force=args.force,
    )

    print(f"\nDone. {len(saved)} result(s) saved to {_RESULTS_DIR}")

    if not args.no_plots and saved:
        from benchmarks.plots_repos import generate_all
        print("\nGenerating charts…")
        paths = generate_all()
        for p in paths:
            print(f"  Saved: {p.name}")


if __name__ == "__main__":
    main()
