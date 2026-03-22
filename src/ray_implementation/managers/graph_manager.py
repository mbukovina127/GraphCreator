"""
Manager class to contain the pipeline of creating a local CPG graph from an AST 
"""
#TODO: needs rework
import logging

from tree_sitter import Tree

from graph_builder import ASTInserter
from ray_implementation.builders.symbol_creation import SymbolBuilder
from ray_implementation.builders.cpg_builder import CPGBuilder
from ray_implementation.builders.local_output_builder import LocalOuputBuilder
from ray_implementation.structures.local_symbol_table import SymbolTable

logger = logging.getLogger(__name__)

class GraphManager:
    
    def __init__(self, lst: SymbolTable):
        self.local_out_builder = LocalOuputBuilder()
        self._local_symbol_table = lst
        self.file = ""
        self._ran = False

    
    def generate_graph(self, ast: Tree, file_path: str ): #TODO:  return type
        self.file = file_path
        logger.info(f"[graph_manager][worker_id={self._local_symbol_table.worker_id}] Inserting ast into a graph...")
        self.ast_insterter = ASTInserter(self.local_out_builder)
        self.ast_insterter.insert_node(ast.root_node) # inserts the ast and stores it into l_out_builder
        logger.info(f"[graph_manager][worker_id={self._local_symbol_table.worker_id}] Inserting ast into a graph complete.")

        # create a symbol table
        logger.info(f"[graph_manager][worker_id={self._local_symbol_table.worker_id}] Building local symbol table...")
        self.symbol_builder = SymbolBuilder(self.local_out_builder, self._local_symbol_table, file_path)
        self.symbol_builder.build(ast.root_node)
        logger.info(f"[graph_manager][worker_id={self._local_symbol_table.worker_id}] Local symbol table built.")

        # create a knowledge graph
        logger.info(f"[graph_manager][worker_id={self._local_symbol_table.worker_id}] Creating knowledge graph...")
        self.knowledge_graph_builder = CPGBuilder(self.local_out_builder, self._local_symbol_table)
        self.knowledge_graph_builder.build(ast.root_node, file_path)
        logger.info(f"[graph_manager][worker_id={self._local_symbol_table.worker_id}] Knowledge graph built.")


        self._ran = True
        return

    def get_graphs(self):
        """Returns a json format of ast_graph, knowledge_graph, and unresolved_edges"""
        if not self._ran:
            logger.error(f"[graph_manager][worker_id={self._local_symbol_table.worker_id}] exporting empty graph...")
            raise RuntimeError('Cannot .get_graphs() because the graph has not been generated yet. run .generate_graph() first')


        logger.info(f"[graph_manager][worker_id={self._local_symbol_table.worker_id}] Creating export graphs...")
        ast_graph = self.local_out_builder.export_ast_graph()
        knowledge_graph = self.local_out_builder.export_knowledge_graph()
        logger.info(f"[graph_manager][worker_id={self._local_symbol_table.worker_id}] Exporting graphs complete")
        return {
            "file": self.file,
            "ast_graph": ast_graph,
            "knowledge_graph": knowledge_graph,
            "unresolved_edges": self._local_symbol_table.get_unresolved_edges(),
            "exports": self._local_symbol_table.get_exports(),
            "imports": self._local_symbol_table.get_imports()
        }
