""" Improved Graph Output Builder"""
import importlib.util
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Any, Optional

from ray_implementation.dto.edges import Edges
from ray_implementation.structures import SymbolTable
from ray_implementation.graph_metrics import (
    compute_project_metrics,
    compute_dependency_metrics,
    compute_global_var_metrics,
)

logging.basicConfig(level=logging.INFO)
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
            "text": text if text is not None else "",
            "start_byte": start_byte,
            "end_byte": end_byte,
            "file_path": file_path if file_path is not None else "",
            "properties": {} if properties is None else properties,
        }

    def _create_knowledge_edge(
            self,
            from_node_id: str,
            to_node_id: str,
            edge_type: Edges,
    ) -> Dict[str, Any]:
        return {
            "_from": from_node_id,
            "_to": to_node_id,
            "relation": edge_type.value,
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
        logger.info("Starting graph collection for root_directory=%s", root_directory)
        self._collect_local_results(results)
        self._create_spine(root_directory)
        self._create_indexes()
        self._resolve_cross_file_edges()
        self._compute_graph_metrics()
        logger.info(
            "Graph collection complete: %d ast_nodes, %d ast_edges, %d kg_nodes, %d kg_edges",
            len(self._ast_nodes), len(self._ast_edges),
            len(self._knowledge_nodes), len(self._knowledge_edges),
        )
        self._validate_schema()

    def _validate_schema(self) -> None:
        """Validate all knowledge nodes against the JSON schema. Logs warnings for violations."""
        if importlib.util.find_spec("jsonschema") is None:
            logger.warning("[schema] jsonschema not installed — skipping node validation")
            return

        import jsonschema

        schema_path = Path(__file__).parents[3] / "schema_lua" / "cpg.node.schema.json"
        if not schema_path.exists():
            logger.warning("[schema] schema file not found at %s — skipping validation", schema_path)
            return

        import random
        schema = json.loads(schema_path.read_text())
        _SAMPLE_SIZE = 200
        items = list(self._knowledge_nodes.items())
        sample = random.sample(items, min(_SAMPLE_SIZE, len(items)))
        violations = []
        for key, node in sample:
            try:
                jsonschema.validate(node, schema)
            except jsonschema.ValidationError as e:
                violations.append(f"Node {key}: {e.message}")

        if violations:
            for v in violations[:10]:
                logger.warning("[schema] %s", v)
            if len(violations) > 10:
                logger.warning("[schema] ... and %d more violations", len(violations) - 10)
        else:
            logger.info("[schema] %d/%d sampled nodes passed schema validation", len(sample), len(self._knowledge_nodes))

    def _compute_graph_metrics(self):
        logger.info("Computing graph-level metrics")
        nodes = self._knowledge_nodes
        edges = self._knowledge_edges

        # reverse index: entity_node_id -> existing metric node
        existing_metric: Dict[str, Dict] = {}
        for edge in edges:
            if edge["relation"] == Edges.HAS_METRICS.value:
                m = nodes.get(edge["_from"])
                if m and m.get("type") == "metric":
                    existing_metric[edge["_to"]] = m

        # --- project-level metric node (always new — no pre-existing node to attach to) ---
        project_props = compute_project_metrics(nodes, edges)
        project_props["kind"] = "project"
        self._add_knowledge_node(
            self._create_knowledge_node(node_id="metric:project:1", type="metric", properties=project_props)
        )

        # --- per-function dependency and global-variable metrics ---
        dep_metrics = compute_dependency_metrics(nodes, edges)
        gv_metrics = compute_global_var_metrics(nodes, edges)

        for fn_id in set(dep_metrics) | set(gv_metrics):
            m_node = existing_metric.get(fn_id)
            if m_node is not None:
                m_node["properties"]["dependency"] = dep_metrics.get(fn_id, {})
                m_node["properties"]["global_var_access"] = gv_metrics.get(fn_id, {})
            else:
                props = {
                    "kind": "function",
                    "dependency": dep_metrics.get(fn_id, {}),
                    "global_var_access": gv_metrics.get(fn_id, {}),
                }
                new_m = self._create_knowledge_node(node_id=f"metric:{fn_id}", type="metric", properties=props)
                self._add_knowledge_node(new_m)
                self._add_knowledge_edge(self._create_knowledge_edge(new_m["_key"], fn_id, Edges.HAS_METRICS))

        logger.info("Graph metrics done: project node + %d functions", len(set(dep_metrics) | set(gv_metrics)))

    def _create_indexes(self):
        logger.info("Building indexes from %d knowledge nodes and %d edges",
                    len(self._knowledge_nodes), len(self._knowledge_edges))
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
            if edge["relation"] in (Edges.DECLARES.value, Edges.DEFINES.value):
                module_node = self._knowledge_nodes.get(edge["_from"])
                declaration_node = self._knowledge_nodes.get(edge["_to"])
                if module_node and declaration_node:
                    module_name = module_node.get("properties", {}).get("module_name")
                    # declaration name is stored in properties["name"] by _node_variable()/_node_function()
                    declaration_name = declaration_node.get("properties", {}).get("name")
                    if module_name and declaration_name:
                        self._export_index.setdefault(module_name, {})[declaration_name] = edge["_to"]

        logger.info("Indexes built: %d modules, %d chunks, %d export entries",
                    len(self._module_index), len(self._chunk_index),
                    sum(len(v) for v in self._export_index.values()))

    def _resolve_cross_file_edges(self):
        """
        For every file's unresolved edges, attempt to resolve them against:
          1. Known modules (require() imports)
          2. Global symbol definitions in other files
        """
        logger.info("Resolving cross-file edges for %d files", len(self.results))
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
                    logger.error("Unresolved import: module '%s' not found (referenced in %s)", module_path, file_path)
                    continue

                var_node_id = self._find_declaration_node(file_path, var_name)
                if var_node_id is None:
                    logger.error("Unresolved import: declaration node for '%s' not found in %s", var_name, file_path)
                    continue

                self._add_knowledge_edge(self._create_knowledge_edge(
                    from_node_id=var_node_id,
                    to_node_id=module_node_id,
                    edge_type=Edges.IMPORTS,
                ))

            # --- Step 2: resolve unresolved reference edges ---
            for symbol_name, pending_edges in unresolved_edges.items():
                for pending in pending_edges:
                    resolved_id = self._resolve_symbol(symbol_name, file_path, imports)
                    if resolved_id is None:
                        logger.error("Unresolved symbol '%s' in %s (edge_type=%s)",
                                     symbol_name, file_path, pending.get("edge_type"))
                        continue
                    self._add_knowledge_edge(self._create_knowledge_edge(
                        from_node_id=pending["node_id"],
                        to_node_id=resolved_id,
                        edge_type=Edges(pending["edge_type"]),
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
        logger.info("Building file-system spine from %s", root_directory)
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
                        from_node_id=parent_kg_id,
                        to_node_id=kg_id,
                        edge_type=Edges.CONTAINS,
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
                logger.warning("File_path=%s not found in results", file_path)
                return

            try:
                kg_chunk_node = result['knowledge_graph']['vertices'][0]
                ast_chunk_node = result['ast_graph']['vertices'][0]
            except (KeyError, IndexError) as exc:
                logger.error("Malformed result for %s: %s", file_path, exc)
                return

            self._add_ast_edge(self._create_ast_edge(parent_ast, ast_chunk_node['_key'], "is"))
            self._add_knowledge_edge(self._create_knowledge_edge(parent_kg, kg_chunk_node['_key'], Edges.IS))

            #adding the nodes to the global graph
            self._add_ast_nodes(result['ast_graph']['vertices'])
            self._add_ast_edges(result['ast_graph']['edges'])
            self._add_knowledge_nodes(result['knowledge_graph']['vertices'])
            self._add_knowledge_edges(result['knowledge_graph']['edges'])

            #TODO decide whether to normalize the ids
            #TODO IMPORTANT add things to global symbol table

    def _collect_local_results(self, results: List[Dict[str, Any]]):
        """Collects the results from ray results and stores them in memory"""
        logger.info("Collecting results for %d files", len(results))
        for result in results:
            self.results[result["file"]] = result

    def _resolve_local_graph(self, graph):
        pass

    def _create_simple_ids(self):
        pass


