"""
Manager class to contain the pipeline of creating a local CPG graph from an AST 
"""
#TODO: needs rework
import logging
import time

from tree_sitter import Tree

from graph_builder import ASTInserter
from ray_implementation.builders import SymbolBuilder, CPGBuilder, LocalOutputBuilder
from ray_implementation.structures import SymbolTable

logger = logging.getLogger(__name__)

class GraphManager:
    
    def __init__(self, lst: SymbolTable):
        self.local_out_builder = LocalOutputBuilder()
        self._local_symbol_table = lst
        self.knowledge_graph_builder: CPGBuilder | None = None
        self.file = ""
        self._ran = False
        self.timings: dict = {}

    
    def generate_graph(self, ast: Tree, file_path: str):
        self.file = file_path
        self.timings = {}
        wid = self._local_symbol_table.worker_id
        try:
            t0 = time.perf_counter()
            self.ast_inserter = ASTInserter(self.local_out_builder)
            self.ast_inserter.insert_node(ast.root_node, file=file_path)
            self.timings["ast_insert_s"] = time.perf_counter() - t0

            t0 = time.perf_counter()
            self.symbol_builder = SymbolBuilder(self.local_out_builder, self._local_symbol_table, file_path)
            self.symbol_builder.build(ast.root_node)
            self.timings["symbol_s"] = time.perf_counter() - t0

            t0 = time.perf_counter()
            self.knowledge_graph_builder = CPGBuilder(self.local_out_builder, self._local_symbol_table, file_path)
            self.knowledge_graph_builder.build(ast.root_node, file_path)
            self.timings["cpg_build_s"] = time.perf_counter() - t0
        except Exception as e:
            logger.error(f"[graph_manager][worker_id={wid}] Pipeline failed for {file_path}: {e}")
            raise

        self._ran = True

    def get_graphs(self):
        """Returns a json format of ast_graph, knowledge_graph, and unresolved_edges"""
        if not self._ran:
            logger.error(f"[graph_manager][worker_id={self._local_symbol_table.worker_id}] exporting empty graph...")
            raise RuntimeError('Cannot .get_graphs() because the graph has not been generated yet. run .generate_graph() first')


        logger.info(f"[graph_manager][worker_id={self._local_symbol_table.worker_id}] Creating export graphs...")
        ast_graph = self.local_out_builder.export_ast_graph()
        knowledge_graph = self.local_out_builder.export_knowledge_graph()
        logger.info(f"[graph_manager][worker_id={self._local_symbol_table.worker_id}] Exporting graphs complete")
        # CPGBuilder accumulates unresolved edges as Dict[symbol_name, list[{node_id, edge_type, ...}]].
        # SymbolTable.unresolved is never populated, so we take from the builder directly.
        cpg_unresolved = self.knowledge_graph_builder.unresolved_edges if self.knowledge_graph_builder else {}
        return {
            "file": self.file,
            "ast_graph": ast_graph,
            "knowledge_graph": knowledge_graph,
            "unresolved_edges": cpg_unresolved,
            "exports": self._local_symbol_table.get_exports(),
            "imports": self._local_symbol_table.get_imports()
        }
    def clear(self):
        self._ran = False
        self.local_out_builder.clear()
        logger.info(f"[graph_manager][worker_id={self._local_symbol_table.worker_id}] Cleared stored graphs.")
        self._local_symbol_table.clear_all()
        logger.info(f"[graph_manager][worker_id={self._local_symbol_table.worker_id}] Cleared symbol table.")
        return
