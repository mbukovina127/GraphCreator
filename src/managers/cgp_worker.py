import logging
import time
import uuid
from typing import Any, Dict, Optional

import ray

from parser import ParallelASTManager
from structures import SymbolTable
from .graph_manager import GraphManager

logger = logging.getLogger(__name__)


def _analyze_single(file_path: str) -> Optional[Dict[str, Any]]:
    """Core per-file analysis. Returns graph dict with embedded _timing breakdown."""
    worker_id = str(uuid.uuid4())
    ast_manager = ParallelASTManager(worker_id)
    lst = SymbolTable(worker_id)
    graph_manager = GraphManager(lst)

    try:
        t0 = time.perf_counter()
        ast = ast_manager.parse(file_path)
        parse_s = time.perf_counter() - t0
    except Exception as e:
        logger.error(f"[task][worker_id={worker_id}] Failed to parse {file_path}: {e}")
        return None

    graph_manager.generate_graph(ast, file_path)
    result = graph_manager.get_graphs()
    result["_timing"] = {"parse_s": parse_s, **graph_manager.timings}
    return result


@ray.remote(num_cpus=1)
def analyze_file(file_path: str) -> Optional[Dict[str, Any]]:
    """Stateless Ray task: parse one Lua file and return its local CPG graphs."""
    return _analyze_single(file_path)
