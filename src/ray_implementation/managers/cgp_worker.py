import logging
import uuid

import ray

from code_analyzer.parse_code import ParallelASTManager
from ray_implementation.structures import SymbolTable
from .graph_manager import GraphManager

logger = logging.getLogger(__name__)


@ray.remote
def analyze_file(file_path: str):
    """Stateless Ray task: parse one Lua file and return its local CPG graphs."""
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
