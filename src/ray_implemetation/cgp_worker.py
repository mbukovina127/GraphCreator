#TODO: description
#TODO: Implement graph Manager
import ray
import logging
from typing import Dict, Any, List, Optional


from code_analyzer import ASTManager
from .graph_manager import GraphManager

@ray.remote
class CGPWorker:
    """
    Ray Actor for analazing and creating a local cpg graph
    """
    def __init__(self):
        self.ast_manager = ASTManager() # TODO: doesn't have to be a singleton
        self.graph_manager = GraphManager()

    def analyze_file(self, file_path: str):
        """creates ast and local cgp graph"""
        try:
            ast= self.ast_manager.parse(file_path)
        except Exception as e:
            return # TODO: logging
        graph = self.graph_manager.generate_graph(ast, file_path)

        return graph









        