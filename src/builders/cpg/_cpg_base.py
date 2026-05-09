import logging
from pathlib import Path
from typing import Any, Dict, List

from ast_utils import ASTUtils
from builders.local_output_builder import LocalOutputBuilder
from dto.edges import Edges
from structures import SymbolTable, ContextStack

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_VALID_NODE_TYPES = {
    "chunk", "local_function_definition", "global_function_definition",
    "local_variable_declaration", "global_variable_declaration",
    "module_import", "module", "identifier", "index_expression",
    "function_call", "if_statement", "else_statement", "elseif_statement",
    "for_statement", "while_statement", "repeat_statement",
    "for_numeric_clause", "for_generic_clause", "block",
    "expression_list", "binary_expression", "return_statement",
    "table_constructor", "literal",
    "directory", "file", "metric",
}


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

    def _recurse_with_different_context(self, root, file_path, context_rel_nodes, context, offset: int = 0):
        self._context_stack.push_context(context_rel_nodes, context)
        try:
            for c in root.children[offset:]:
                self.build(c, file_path)
        finally:
            self._context_stack.pop_context()

    def _get_nodeid_from_astid(self, ast_id: str):
        try:
            found = self._astId_nodeId_map[ast_id]
        except KeyError as e:
            logger.error(
                f"[CPGbuilder][worker_id={self._lst.worker_id}]: AST node({ast_id}) not found in astId->cpgId map")
            raise e
        return found

    def __insert_knowledge_node(self, ast_node, k_node):
        try:
            self.knowledge_nodes.insert(k_node)
            self._astId_nodeId_map[str(ast_node.id)] = k_node["_key"]
        except Exception as e:
            logger.error(f"[CPGbuilder][worker_id={self._lst.worker_id}]: {e}")

    def _create_metrics_node(self, properties, commit: bool = True) -> Dict[str, Any]:
        node_id = f"{self.file_name}:metric:{self.gen_id()}"
        m_node = {
            "_key": node_id,
            "symbol_id": None,
            "type": "metric",
            "text": "",
            "file_path": "",
            "properties": properties,
        }
        if commit:
            self.knowledge_nodes.insert(m_node) # Bypassing the
        return m_node

    def _create_knowledge_node(self, node, file_path: str, type: str | None = None, text: str | None = None, properties: Dict | None = None, commit: bool = True) -> Dict[str, Any]:
        """creates a knowledge node, defaulting to the AST node's properties. commit argument decides wheteher to automatically insert the knowledge node to the graph collection"""
        resolved_type = node.type if type is None else type
        if resolved_type not in _VALID_NODE_TYPES:
            raise ValueError(f"Unknown CPG node type '{resolved_type}' (file={file_path})")
        node_id = f"{self.file_name}:{resolved_type}:{self.gen_id()}"
        if not node_id:
            raise ValueError(f"Node _key must be a non-empty string (file={file_path})")
        a_node = {
            "_key": node_id,
            "symbol_id": node.id,
            "type": resolved_type,
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

    def _create_knowledge_edge(self, from_node_id: str, to_node_id: str, edge_type: Edges) -> Dict[str, Any]:
        if not from_node_id or not to_node_id:
            raise ValueError(f"Edge _from/_to must be non-empty strings: {from_node_id!r} → {to_node_id!r}")
        edge = {
            "_from": from_node_id,
            "_to": to_node_id,
            "relation": edge_type.value,
        }
        self.knowledge_edges.insert(edge)
        return edge

    def _create_unresolved_edge(self, node_id: str, symbol_name: str, edge_type: Edges, scope: str, file: str) -> None:
        unk_edge = {
            "node_id": node_id,
            "symbol_name": symbol_name,
            "edge_type": edge_type.value,
            "scope": scope,
            "file": file,
        }
        self.unresolved_edges.setdefault(symbol_name, []).append(unk_edge)

    def _update_knowledge_node(self, node):
        self.knowledge_nodes.insert(node)

    # ------------------------------------------------------------------
    # Metric creation
    # ------------------------------------------------------------------

    def _handle_metrics(self, ast_node, k_node, *functions, kind: str = ""):
        k_id = k_node["_key"]
        m_properties = {}
        if kind:
            m_properties["kind"] = kind
        for f in functions:
            name, result = f()
            m_properties[name] = result

        m_node = self._create_metrics_node(m_properties)
        self._create_knowledge_edge(m_node["_key"], k_id, Edges.HAS_METRICS)

