import logging
import uuid
from typing import List, Optional, Dict, Any

import ray

from code_analyzer.parse_code import ParallelASTManager
from ray_implementation.structures import SymbolTable
from .graph_manager import GraphManager

logger = logging.getLogger(__name__)


def _analyze_single(file_path: str) -> Optional[Dict[str, Any]]:
    """Core analysis logic shared by both task variants."""
    worker_id = str(uuid.uuid4())
    ast_manager = ParallelASTManager(worker_id)
    lst = SymbolTable(worker_id)
    graph_manager = GraphManager(lst)
    try:
        ast = ast_manager.parse(file_path)
    except Exception as e:
        logger.error(f"[task][worker_id={worker_id}] Failed to parse {file_path}: {e}")
        return None
    graph_manager.generate_graph(ast, file_path)
    return graph_manager.get_graphs()


@ray.remote
def analyze_file(file_path: str) -> Optional[Dict[str, Any]]:
    """Stateless Ray task: parse one Lua file and return its local CPG graphs."""
    return _analyze_single(file_path)


@ray.remote
def analyze_files_batch(file_paths: List[str]) -> List[Optional[Dict[str, Any]]]:
    """Stateless Ray task: parse a batch of files in one task to reduce dispatch overhead."""
    return [_analyze_single(p) for p in file_paths]
