""" Improved Graph Output Builder"""
import os
from typing import Dict, List, Any, Optional

from ray_implementation import SymbolTable


class GraphCollector:

    def __init__(self):
        # Main AST graph collections (equivalent to lua_graph)
        self._ast_nodes: Dict[str, Dict[str, Any]] = {}
        self._ast_edges: List[Dict[str, Any]] = []

        # Knowledge graph collections (equivalent to knowledge_graph)
        self._knowledge_nodes: Dict[str, Dict[str, Any]] = {}
        self._knowledge_edges: List[Dict[str, Any]] = []

        self.results: Dict[str, Any] = {}
        self.global_symbol_table = SymbolTable("global")
        #ids
        self.ast_id = 0
        self.knowledge_id = 0
        pass

    def collect(self, results, root_directory: str):
        self._collect_local_results(results)
        self._create_spine(root_directory)

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
            locals = self.results.get(file_path, {}) #FIXME check file_path format and how its added to graphs

            #FIXME indexing zero is very hardcoded
            kg_chunk_node = locals['knowledge_graph']['vertices'][0]
            ast_chunk_node = locals['ast_graph']['vertices'][0]

            self._add_ast_edge(self._create_ast_edge(parent_ast, ast_chunk_node['_key'], "is"))
            self._add_knowledge_edge(self._create_knowledge_edge(parent_kg, kg_chunk_node['_key'], "is"))

            #adding the nodes to the global graph
            self._add_ast_nodes(locals['ast_graph']['vertices'])
            self._add_ast_edges(locals['ast_graph']['edges'])
            self._add_knowledge_nodes(locals['knowledge_graph']['vertices'])
            self._add_knowledge_edges(locals['knowledge_graph']['edges'])

            #TODO decide whether to normalize the ids
            #TODO IMPORTANT add things to global symbol table

    def _collect_local_results(self, results: List[Dict[str, Any]]):
        """Collects the results from ray results and stores them in memory"""
        #store them as a
        for result in results:
            self.results[result["file"]] = result

    def _resolve_local_graph(self, graph):
        pass

    def _create_simple_ids(self):
        pass


    #######################
    ### Node helpers
    #######################
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
