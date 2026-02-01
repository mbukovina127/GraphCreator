"""
Manager class to contain the pipeline of creating a local CPG graph from an AST 
"""
#TODO: needs rework
#TODO: implement ParrallelASTInserter -> LocalOutputBuiloder, LocalGraphQueries #TODO change name of Local Graph Queries
from typing import Dict

from tree_sitter import Tree
from .local_output_builder import LocalOuputBuilder
from .local_symbol_table import SymbolTable

class GraphManager():
    
    def __init__(self, lst: SymbolTable, ast: Dict[str, Tree] = {}):
        self._ast = ast
        self._local_symbol_table = lst 
        self.l_out_builder = LocalOuputBuilder()
    
    def generate_graph(self, ast: Tree, file_path: str ): #TODO:  return type
        self.ast_insterter = ParallelASTInserter(self.l_out_builder, self._local_symbol_table, self._local_symbol_table.worker_id, file_path=file_path,)
        
        self.ast_insterter.insert_nodes(ast.root_node) # inserts the ast and stores it into l_out_builder
        
        return self._local_symbol_table
