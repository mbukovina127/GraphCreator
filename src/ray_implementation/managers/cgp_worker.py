#TODO: description
#TODO: Implement graph Manager
import ray

from code_analyzer.parse_code import ParallelASTManager
from ray_implementation.structures.local_symbol_table import SymbolTable
from ray_implementation.managers.graph_manager import GraphManager

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

        try:
            ast = self.ast_manager.parse(file_path)
        except Exception as e:
            return # TODO: logging

        # Populating the graphs in
        self.graph_manager.generate_graph(ast, file_path)
        graphs = self.graph_manager.get_graphs()
        return graphs









        