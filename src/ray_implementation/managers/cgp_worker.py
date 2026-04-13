import logging

import ray

from code_analyzer.parse_code import ParallelASTManager
from ray_implementation.structures import SymbolTable
from .graph_manager import GraphManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@ray.remote
class CGPWorker:
    """
    Ray Actor for analazing and creating a local cpg graph
    """
    def __init__(self, worker_id: str):
        self.ast_manager = ParallelASTManager(worker_id)
        self.lst = SymbolTable(worker_id)
        self.graph_manager = GraphManager(self.lst)

    def analyze_file(self, file_path: str):
        """creates ast and local cgp graph"""
        # clean up before running the actor to keep it stateless
        self.ast_manager.clear()
        self.lst.clear_all()
        self.graph_manager.clear()
        logger.info(f"[Worker_id:{self.lst.worker_id}] Cleared previous state of CPGWorker: {file_path}")

        try:
            ast = self.ast_manager.parse(file_path)
        except Exception as e:
            logger.error(f"[Worker_id:{self.lst.worker_id}] Failed to parse file: {file_path}: {e}")
            return None

        # Populating the graphs in
        self.graph_manager.generate_graph(ast, file_path)
        graphs = self.graph_manager.get_graphs()
        return graphs









        