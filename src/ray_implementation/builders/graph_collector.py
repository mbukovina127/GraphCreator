""" Improved Graph Output Builder"""
import logging
import os
from typing import Dict, List, Any, Optional

from ray_implementation.structures import SymbolTable

logger = logging.getLogger(__name__)


class GraphCollectorBase:
    def __init__(self):
        # Main AST graph collections (equivalent to lua_graph)
        self._ast_edges: List[Dict[str, Any]] = []
        self._ast_nodes: Dict[str, Dict[str, Any]] = {}

        # Knowledge graph collections (equivalent to knowledge_graph)
        self._knowledge_nodes: Dict[str, Dict[str, Any]] = {}
        self._knowledge_edges: List[Dict[str, Any]] = []

        self.knowledge_id = 0
        self.ast_id = 0

    def _gen_next_ast_id(self):
        self.ast_id += 1
        return self.ast_id

    def _gen_next_knowledge_id(self):
        self.knowledge_id += 1
        return self.knowledge_id

    def _add_ast_node(self, node: Dict[str, Any]):
        self._ast_nodes[node["_key"]] = node

    def _add_ast_nodes(self, nodes: List[Dict[str, Any]]):
        for node in nodes:
            self._add_ast_node(node)

    def _add_ast_edge(self, edge: Dict[str, Any]):
        self._ast_edges.append(edge)

    def _add_ast_edges(self, edges: List[Dict[str, Any]]):
        self._ast_edges.extend(edges)

    def _add_knowledge_node(self, node: Dict[str, Any]):
        self._knowledge_nodes[node["_key"]] = node

    def _add_knowledge_nodes(self, nodes: List[Dict[str, Any]]):
        for node in nodes:
            self._add_knowledge_node(node)

    def _add_knowledge_edge(self, edge: Dict[str, Any]):
        self._knowledge_edges.append(edge)

    def _add_knowledge_edges(self, edges: List[Dict[str, Any]]):
        self._knowledge_edges.extend(edges)

    def _create_ast_node(self, node_id: str, ast_id: str | None, type: str, start_byte, end_byte, text: str) -> Dict[str, Any]:
        return {
            "_key": node_id,
            "ast_id": ast_id,
            "type": type,
            "start_byte": start_byte,
            "end_byte": end_byte,
            "text": text
        }

    def _create_ast_edge(self, parent_id: str, node_id: str, relation: str = "child_of") -> Dict[str, Any]:
        return {
            "_from": f"{parent_id}",
            "_to": f"{node_id}",
            "relation": relation
        }

    def _create_knowledge_node(
            self,
            node_id: str,
            *,
            symbol_id: Optional[str] = None,
            type: Optional[str] = None,
            text: Optional[str] = None,
            start_byte: Optional[int] = None,
            end_byte: Optional[int] = None,
            file_path: Optional[str] = None,
            properties: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        return {
            "_key": node_id,
            "symbol_id": symbol_id,
            "type": type,
            "text": text,
            "start_byte": start_byte,
            "end_byte": end_byte,
            "file_path": file_path,
            "properties": {} if properties is None else properties,
        }

    def _create_knowledge_edge(
            self,
            # edge_id: str,
            from_node_id: str,
            to_node_id: str,
            edge_type: str
    ) -> Dict[str, Any]:
        return {
            # "_key": edge_id,
            "_from": from_node_id,
            "_to": to_node_id,
            "relation": edge_type,
        }

class GraphCollector(GraphCollectorBase):

    def __init__(self):

        super().__init__()
        self.results: Dict[str, Any] = {}
        self.global_symbol_table = SymbolTable("global")

        self._module_index: Dict[str, str] = {} # "module" -> node_id\
        self._chunk_index: Dict[str, str] = {}
        self._export_index: Dict[str, Dict[str, str]] = {} # "module" -> "function" -> function id

    def collect(self, results, root_directory: str):
        self._collect_local_results(results)
        self._create_spine(root_directory)
        self._create_indexes()
        self._resolve_cross_file_edges()

    def _create_indexes(self):
        for node in self._knowledge_nodes.values():
            match node["type"]:
                case "module":
                    # module name is stored in properties["module_name"] by _node_module()
                    module_name = node.get("properties", {}).get("module_name")
                    if module_name:
                        self._module_index[module_name] = node["_key"]
                case "chunk":
                    self._chunk_index[node["file_path"]] = node["_key"]

        # build export index: module_name -> { declaration_name -> node_id }
        for edge in self._knowledge_edges:
            if edge["relation"] in ("declares", "defines"):
                module_node = self._knowledge_nodes.get(edge["_from"])
                declaration_node = self._knowledge_nodes.get(edge["_to"])
                if module_node and declaration_node:
                    module_name = module_node.get("properties", {}).get("module_name")
                    # declaration name is stored in properties["name"] by _node_variable()/_node_function()
                    declaration_name = declaration_node.get("properties", {}).get("name")
                    if module_name and declaration_name:
                        self._export_index.setdefault(module_name, {})[declaration_name] = edge["_to"]

    def _resolve_cross_file_edges(self):
        """
        For every file's unresolved edges, attempt to resolve them against:
          1. Known modules (require() imports)
          2. Global symbol definitions in other files
        """
        for file_path, result in self.results.items():
            # imports: Dict[str, str]  — var_name -> module_path, e.g. {"m": "math.utils"}
            # Exported directly as a flat key by GraphManager.get_graphs().
            imports: Dict[str, str] = result.get("imports", {})

            # unresolved_edges: Dict[str, list[Dict]]  — symbol_name -> [{node_id, edge_type, scope, file}]
            # These come from CPGBase.unresolved_edges, re-exported by GraphManager.get_graphs().
            unresolved_edges: Dict = result.get("unresolved_edges", {})

            # --- Step 1: resolve require() imports ---
            for var_name, module_path in imports.items():
                module_node_id = self._module_index.get(module_path)
                if module_node_id is None:
                    continue  # module not found in any processed file

                var_node_id = self._find_declaration_node(file_path, var_name)
                if var_node_id is None:
                    continue

                self._add_knowledge_edge(self._create_knowledge_edge(
                    from_node_id=var_node_id,
                    to_node_id=module_node_id,
                    edge_type="imports"
                ))

            # --- Step 2: resolve unresolved reference edges ---
            for symbol_name, pending_edges in unresolved_edges.items():
                for pending in pending_edges:
                    resolved_id = self._resolve_symbol(symbol_name, file_path, imports)
                    if resolved_id is None:
                        continue
                    self._add_knowledge_edge(self._create_knowledge_edge(
                        from_node_id=pending["node_id"],
                        to_node_id=resolved_id,
                        edge_type=pending["edge_type"]
                    ))

    def _resolve_symbol(self, symbol_name: str, requesting_file: str, imports: Dict[str, str]) -> Optional[str]:
        """
        Try to find a knowledge node for symbol_name outside of requesting_file.
        Checks module exports first (using this file's imports map), then all module exports.
        """
        # check if this file imports a module that exports this symbol
        module_path = imports.get(symbol_name)
        if module_path:
            node_id = self._export_index.get(module_path, {}).get(symbol_name)
            if node_id:
                return node_id

        # fall back: check all known module exports
        for exports in self._export_index.values():
            if symbol_name in exports:
                return exports[symbol_name]

        return None

    def _find_declaration_node(self, file_path: str, var_name: str) -> Optional[str]:
        """Find the knowledge node id for a declared variable in a specific file."""
        for node in self._knowledge_nodes.values():
            if (node.get("file_path") == file_path
                    and node.get("properties", {}).get("name") == var_name):
                return node["_key"]
        return None

    def _create_spine(self, root_directory: str):
        #project root directory
        def traverse(current_path: str, parent_ast_id: str = None, parent_kg_id: str = None):
            name = os.path.basename(current_path) or current_path

            # determine type
            node_type = "directory" if os.path.isdir(current_path) else "file"

            # create ids
            ast_id = str(self._gen_next_ast_id())
            kg_id = str(self._gen_next_knowledge_id())

            # create nodes
            ast_node = self._create_ast_node(
                node_id=ast_id,
                ast_id=None,
                type=node_type,
                start_byte=0,
                end_byte=0,
                text=name
            )

            kg_node = self._create_knowledge_node(
                node_id=kg_id,
                type=node_type,
                text=name,
                file_path=current_path
            )

            # store
            self._add_ast_node(ast_node)
            self._add_knowledge_node(kg_node)

            if parent_kg_id:
                self._add_knowledge_edge(
                    self._create_knowledge_edge(
                        # edge_id=str(self.gen_next_knowledge_id()),
                        from_node_id=parent_kg_id,
                        to_node_id=kg_id,
                        edge_type="contains"
                    )
                )
            if parent_ast_id:
                self._add_ast_edge(self._create_ast_edge(
                    parent_id=parent_ast_id,
                    node_id=ast_id,
                ))

            #import local graph if file
            if node_type == "file":
                self._store_local_graph(ast_id, kg_id, current_path)

            # recurse if directory
            if os.path.isdir(current_path):
                for entry in os.listdir(current_path):
                    child_path = os.path.join(current_path, entry)
                    traverse(child_path, ast_id, kg_id)

        traverse(root_directory)
        return

    def _store_local_graph(self, parent_ast, parent_kg, file_path):
            result = self.results.get(file_path, {})
            if not result:
                logger.warning(f"File_path={file_path} not found in results")

            kg_chunk_node = result['knowledge_graph']['vertices'][0]
            ast_chunk_node = result['ast_graph']['vertices'][0]

            self._add_ast_edge(self._create_ast_edge(parent_ast, ast_chunk_node['_key'], "is"))
            self._add_knowledge_edge(self._create_knowledge_edge(parent_kg, kg_chunk_node['_key'], "is"))

            #adding the nodes to the global graph
            self._add_ast_nodes(result['ast_graph']['vertices'])
            self._add_ast_edges(result['ast_graph']['edges'])
            self._add_knowledge_nodes(result['knowledge_graph']['vertices'])
            self._add_knowledge_edges(result['knowledge_graph']['edges'])

            #TODO decide whether to normalize the ids
            #TODO IMPORTANT add things to global symbol table

    def _collect_local_results(self, results: List[Dict[str, Any]]):
        """Collects the results from ray results and stores them in memory"""
        #TODO create a check for result JSON schema
        for result in results:
            self.results[result["file"]] = result

    def _resolve_local_graph(self, graph):
        pass

    def _create_simple_ids(self):
        pass


