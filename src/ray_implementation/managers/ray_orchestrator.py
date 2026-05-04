import os
from typing import List

import ray

from .cgp_worker import analyze_file


class RayOrchestrator:
    def __init__(self):
        address = os.getenv("RAY_ADDRESS")
        ray.init(address=address, ignore_reinit_error=True)

    def distribute_work(self, files: list) -> List[ray.ObjectRef]:
        """Submit one analyze_file task per file; returns futures."""
        if not files:
            raise IndexError("No files provided")
        return [analyze_file.remote(f["path"]) for f in files]

    def cleanup(self):
        ray.shutdown()
