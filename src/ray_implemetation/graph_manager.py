"""
Manager class to contain the pipeline of creating a local CPG graph from an AST 
"""
#TODO: description
#TODO: implement ParrallelASTInserter -> LocalOutputBuiloder, LocalGraphQueries #TODO change name of Local Graph Queries
from typing import Dict

from tree_sitter import Tree
from .parallel_ast_inserter import ParallelASTInserter 
from .local_output_builder import LocalOuputBuilder
from .local_graph_queries import LocalGraphQueries

class GraphManager():
    
    def __init__(self, ast: Dict[str, Tree] = {}, file_path: str = ""):
        self._ast = ast
        self._file_path = file_path
        self.l_out_builder = LocalOuputBuilder()
        self.ast_insterter = ParallelASTInserter(self.l_out_builder)
        self.l_graph_queries = LocalGraphQueries(self.l_out_builder)
        pass
    
    def generate_graph(self, ast: Dict[str, Tree], file_path: str ): #TODO:  return type

            
        pass
