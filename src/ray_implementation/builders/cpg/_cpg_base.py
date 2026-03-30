import logging
from pathlib import Path
from typing import Any, Dict, List

from ray_implementation.ast_utils import ASTUtils
from ray_implementation.builders.local_output_builder import LocalOutputBuilder
from ray_implementation.structures import SymbolTable, ContextStack

logger = logging.getLogger(__name__)


class CPGBase:
    """
    Low-level graph operations: node/edge creation, ID generation, scope stack.
    All state that the rest of the builder depends on is initialized here.
    """

    def __init__(self, local_builder: LocalOutputBuilder, lst: SymbolTable, file_path: str):
        self.local_builder = local_builder
        self._lst = lst
        self._lexical_scope_stack: List[str] = []
        self._context_stack = ContextStack()
        self._astId_nodeId_map: Dict[str, str] = {}
        self._environment = "_G"

        self.knowledge_nodes = self.local_builder.get_collection("knowledge_nodes")
        self.knowledge_edges = self.local_builder.get_collection("knowledge_edges")
        self.unresolved_edges: Dict[str, list[Dict]] = {}

        self.file_name = Path(file_path).name
        self._n_counter = 0
        self._e_counter = 0

    def gen_id(self, kind: str = "node") -> str:
        """Unique ID generator"""
        if kind == "node":
            self._n_counter += 1
            return str(self._n_counter)
        else:
            self._e_counter += 1
            return str(self._e_counter)

    def _push_scope(self, s_id: str):
        self._lexical_scope_stack.append(s_id)

    def _pop_scope(self):
        return self._lexical_scope_stack.pop()

    def _recurse_with_different_context(self, root, file_path, context_rel_nodes, context):
        self._context_stack.push_context(context_rel_nodes, context)
        for c in root.children:
            self.build(c, file_path)
        self._context_stack.pop_context()

    def _get_nodeid_from_astid(self, ast_id: str):
        try:
            found = self._astId_nodeId_map[ast_id]
        except KeyError as e:
            logger.error(
                f"[CPGbuilder][worker_id={self._lst.worker_id}]: "
                f"AST node({ast_id}) not found in astId->cpgId map"
            )
            raise e
        return found

    def __insert_knowledge_node(self, ast_node, k_node):
        try:
            self.knowledge_nodes.insert(k_node)
            self._astId_nodeId_map[str(ast_node.id)] = k_node["_key"]
        except Exception as e:
            return {}
            # TODO: logging

    def _create_knowledge_node(self, node, file_path: str, type: str | None = None, text: str | None = None, properties: Dict | None = None, commit: bool = True) -> Dict[str, Any]:
        """creates a knowledge node, defaulting to the AST node's properties. commit argument decides wheteher to automatically insert the knowledge node to the graph collection"""
        node_id = f"{self.file_name}:{node.type if type is None else type}:{self.gen_id()}"
        a_node = {
            "_key": node_id,
            "symbol_id": node.id,
            "type": node.type if type is None else type,
            "text": ASTUtils.get_text(node) if text is None else text,
            "start_byte": node.start_byte,
            "end_byte": node.end_byte,
            "file_path": file_path,
            "properties": {} if properties is None else properties,
        }
        if commit:
            self.__insert_knowledge_node(node, a_node)
        return a_node

    # Expose the private helpers to subclasses under protected names
    def _insert_knowledge_node(self, ast_node, k_node):
        return self.__insert_knowledge_node(ast_node, k_node)

    def _create_knowledge_edge(self, from_node_id: str, to_node_id: str, edge_type: str) -> Dict[str, Any]:
        edge = {
            "_from": from_node_id,
            "_to": to_node_id,
            "relation": edge_type,
        }
        self.knowledge_edges.insert(edge)
        return edge

    def _create_unresolved_edge(self, node_id: str, symbol_name: str, edge_type: str, scope: str, file: str) -> None:
        unk_edge = {
            "node_id": node_id,
            "symbol_name": symbol_name,
            "edge_type": edge_type,
            "scope": scope,
            "file": file,
        }
        self.unresolved_edges.setdefault(symbol_name, []).append(unk_edge)

    def _update_knowledge_node(self, node):
        self.knowledge_nodes.insert(node)