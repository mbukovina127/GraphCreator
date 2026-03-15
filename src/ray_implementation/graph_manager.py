"""
Manager class to contain the pipeline of creating a local CPG graph from an AST 
"""
#TODO: needs rework
from typing import Dict

from tree_sitter import Tree

from graph_builder import ASTInserter
from .symbol_creation import SymbolBuilder
from .cpg_builder import CPGBuilder
from .local_output_builder import LocalOuputBuilder
from .local_symbol_table import SymbolTable

class GraphManager:
    
    def __init__(self, lst: SymbolTable, ast: Dict[str, Tree]):
        self.local_out_builder = LocalOuputBuilder()
        self._ast = ast
        self._local_symbol_table = lst
        self._ran = False

    
    def generate_graph(self, ast: Tree, file_path: str ): #TODO:  return type

        self.ast_insterter = ASTInserter(self.local_out_builder)
        self.ast_insterter.insert_nodes(ast.root_node) # inserts the ast and stores it into l_out_builder

        # create a symbol table
        self.symbol_builder = SymbolBuilder(self.local_out_builder, self._local_symbol_table, file_path)
        self.symbol_builder.build(ast.root_node)

        # create a knowledge graph
        self.knowledge_graph_builder = CPGBuilder(self.local_out_builder, self._local_symbol_table)
        self.knowledge_graph_builder.build_graph(ast.root_node)

        self._ran = True

        return

    def get_graphs(self):
        """Returns a json format of ast_graph, cpg_graph, and unresolved_edges"""
        if not self._ran:
            raise RuntimeError('Cannot .get_graphs() because the graph has not been generated yet. run .generate_graph() first')
        ast_graph = self.local_out_builder.export_ast_graph()
        cpg_graph = self.local_out_builder.export_knowledge_graph()

        return {
            "ast_graph": ast_graph,
            "cpg_graph": cpg_graph,
            "unresolved_edges": self._local_symbol_table.get_unresolved_edges()
        }
