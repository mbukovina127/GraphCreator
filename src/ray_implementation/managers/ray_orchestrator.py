import math
import os
from typing import List

import ray

from .cgp_worker import analyze_file, analyze_files_batch


def _size_balanced_batches(files: list, num_workers: int) -> List[list]:
    """Sort files by byte size ascending, cut into num_workers batches at equal cumulative-byte thresholds."""
    sized = sorted(files, key=lambda f: os.path.getsize(f["path"]))
    total = sum(os.path.getsize(f["path"]) for f in sized)
    target = total / num_workers

    batches, current, running = [], [], 0
    for f in sized:
        current.append(f)
        running += os.path.getsize(f["path"])
        if running >= target and len(batches) < num_workers - 1:
            batches.append(current)
            current, running = [], 0
    if current:
        batches.append(current)
    return batches


class RayOrchestrator:
    def __init__(self):
        address = os.getenv("RAY_ADDRESS")
        ray.init(address=address, ignore_reinit_error=True)

    def distribute_work(self, files: list) -> List[ray.ObjectRef]:
        """Submit one analyze_file task per file; returns futures."""
        if not files:
            raise IndexError("No files provided")
        return [analyze_file.remote(f["path"]) for f in files]

    def distribute_work_batched(self, files: list) -> List[ray.ObjectRef]:
        """Submit files in size-balanced batches (one task per CPU) to reduce dispatch overhead."""
        if not files:
            raise IndexError("No files provided")
        num_cpus = max(1, int(ray.cluster_resources().get("CPU", 1)))
        batches = _size_balanced_batches(files, num_cpus)
        return [analyze_files_batch.remote([f["path"] for f in batch]) for batch in batches]

    def cleanup(self):
        ray.shutdown()
