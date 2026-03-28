from typing import List

import ray

from .cgp_worker import CGPWorker

class RayOrchestrator:
    def __init__(self):
        self.workers: List = []
        pass

    def create_workers(self, number_of_workers) -> List:
        ray.init()
        self.workers = [
            CGPWorker.remote(worker_id=f"worker_{i}")
            for i in range(number_of_workers)
        ]
        return self.workers

    def distribute_work(self, files: list) -> List[ray.ObjectRef]:
        """distribute work to workers @returns futures"""
        if self.workers.__len__() == 0:
            raise IndexError("No workers")

        futures = []

        for i, files in enumerate(files):
            worker = self.workers[ i % len(self.workers) ]
            futures.append(worker.analyze_file.remote(files["path"]))

        return futures

    def cleanup(self):
        self.workers = []
        ray.shutdown()