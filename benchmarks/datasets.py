"""
Dataset registry for benchmarks.

'small' and 'medium' are the existing test ZIPs already in the repo.
'large' is a placeholder — drop any real Lua project ZIP into
benchmarks/data/ and update the path here.
"""

import os
import tempfile
import zipfile
from pathlib import Path
from typing import List, Dict

_ROOT = Path(__file__).parent.parent

DATASETS: Dict[str, Path] = {
    "small":  _ROOT / "tests" / "resources" / "test_lua.zip",
    "medium": _ROOT / "tests" / "resources" / "test_lua_zipwriter.zip",
    # Drop a real Lua project ZIP here for the 'large' tier:
    "large":  _ROOT / "benchmarks" / "data" / "large.zip",
    "kong": _ROOT / "benchmarks" / "data" / "kong.zip",
}


def dataset_exists(name: str) -> bool:
    return name in DATASETS and DATASETS[name].exists()


def load_repo_directory(path: "str | Path") -> tuple[str, List[Dict]]:
    """
    Load a Lua project directly from a filesystem directory (no ZIP needed).
    Returns (str(path), file_list) in the same format as extract_dataset().
    """
    from pathlib import Path as _Path
    repo_path = str(_Path(path).resolve())
    from file_system_analyzer import analyze_project_structure
    structure = analyze_project_structure(repo_path)
    files = [item for item in structure if item["type"] == "file"]
    return repo_path, files


def extract_dataset(name: str) -> tuple[str, List[Dict]]:
    """
    Extract a dataset ZIP to a temp directory.
    Returns (extract_dir, file_list) where file_list is in the
    format expected by RayOrchestrator.distribute_work().
    """
    zip_path = DATASETS[name]
    if not zip_path.exists():
        raise FileNotFoundError(
            f"Dataset '{name}' not found at {zip_path}. "
            f"For 'large', drop a ZIP into benchmarks/data/large.zip"
        )

    temp_dir = tempfile.mkdtemp(prefix=f"benchmark_{name}_")
    extract_dir = os.path.join(temp_dir, "extracted")
    os.makedirs(extract_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_dir)

    from file_system_analyzer import analyze_project_structure
    structure = analyze_project_structure(extract_dir)
    files = [item for item in structure if item["type"] == "file"]

    return extract_dir, files