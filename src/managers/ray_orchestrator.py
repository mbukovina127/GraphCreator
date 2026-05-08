import os
from pathlib import Path
from typing import List

import ray

from .cgp_worker import analyze_file

_SRC_DIR = str(Path(__file__).parents[1])


class RayOrchestrator:
    def __init__(self):
        address = os.getenv("RAY_ADDRESS")
        existing_pythonpath = os.getenv("PYTHONPATH", "")
        pythonpath = f"{_SRC_DIR}:{existing_pythonpath}" if existing_pythonpath else _SRC_DIR
        ray.init(
            address=address,
            ignore_reinit_error=True,
            runtime_env={"env_vars": {"PYTHONPATH": pythonpath}},
        )

    def distribute_work(self, files: list) -> List[ray.ObjectRef]:
        """Submit one analyze_file task per file; returns futures."""
        if not files:
            raise IndexError("No files provided")
        return [analyze_file.remote(f["path"]) for f in files]

    def cleanup(self):
        ray.shutdown()
