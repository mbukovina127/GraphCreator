"""
ASTInserter - Inserts AST nodes and directory structure into GraphOutputBuilder.

Adapted from the original ast_inserter.py to work with GraphOutputBuilder
instead of ArangoHandler.
"""

import json
from pathlib import Path
from typing import Optional
from .local_output_builder import LocalOutputBuilder


def _path_to_key(path: str) -> str:
    """Convert a filesystem path to a valid ArangoDB _key (no '/' allowed)."""
    return path.replace("/", "__")


class ASTInserter:
    """Inserts AST nodes and file structure into the in-memory graph builder"""

    def __init__(self, graph_builder: LocalOutputBuilder):
        self.graph_builder = graph_builder
        self.nodes = self.graph_builder.get_collection("nodes")
        self.edges = self.graph_builder.get_collection("edges")
        self._n_counter = 0
        self._current_file_stem = ""

    def gen_id(self) -> str:
        self._n_counter += 1
        return str(self._n_counter)

    def insert_node_from_json(self, node: dict, parent_id: Optional[str] = None):
        """Insert a node from JSON representation (for testing/import)"""
        node_id = f"{self._current_file_stem}:{node['type']}:{self.gen_id()}"

        self.nodes.insert({
            "_key": node_id,
            "type": node["type"],
            "text": node["text"],
            "start_byte": node["start_byte"],
            "end_byte": node["end_byte"]
        })

        if parent_id:
            self.edges.insert({
                "_from": f"nodes/{parent_id}",
                "_to": f"nodes/{node_id}",
                "relation": "child_of"
            })

        for child in node.get("children_nodes", []):
            self.insert_node_from_json(child, parent_id=node_id)

    def insert_node(self, node, parent_id: Optional[str] = None, file: Optional[str] = None):
        """
        Insert a tree-sitter AST node into the graph.

        Args:
            node: tree-sitter Node object
            parent_id: ID of the parent node (for creating child_of edge)
            file: File path (for creating edge from file node to AST root)
        """
        if file is not None:
            self._current_file_stem = Path(file).stem

        node_id = f"{self._current_file_stem}:{node.type}:{self.gen_id()}"

        raw = node.text
        if isinstance(raw, bytes):
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("latin-1")
        else:
            text = raw

        self.nodes.insert({
            "_key": node_id,
            "ast_id": node.id,
            "type": node.type,
            "start_byte": node.start_byte,
            "end_byte": node.end_byte,
            "text": text
        })

        if parent_id:
            self.edges.insert({
                "_from": f"nodes/{parent_id}",
                "_to": f"nodes/{node_id}",
                "relation": "child_of"
            })

        if file:
            file_id = self.graph_builder.get_node_id_from_path("nodes", file)
            if file_id:
                self.edges.insert({
                    "_from": f"nodes/{file_id}",
                    "_to": f"nodes/{node_id}",
                    "relation": "child_of"
                })

        for child in node.children:
            self.insert_node(child, parent_id=node_id)

    def insert_dir_struct(self, dir_struct: list):
        """
        Insert directory structure into the graph.

        Args:
            dir_struct: List of dictionaries with name, path, type, parent
        """
        for item in dir_struct:
            node_id = _path_to_key(item["path"])

            self.nodes.insert({
                "_key": node_id,
                "name": item["name"],
                "path": item["path"],
                "type": item["type"],
                "parent": item["parent"]
            })

        for item in dir_struct:
            if item["parent"]:
                parent_id = self.graph_builder.get_node_id_from_path("nodes", item["parent"])
                current_id = self.graph_builder.get_node_id_from_path("nodes", item["path"])

                if parent_id and current_id:
                    self.edges.insert({
                        "_from": f"nodes/{parent_id}",
                        "_to": f"nodes/{current_id}",
                        "relation": "child_of"
                    })

    def insert_ast_from_file(self, file_path: str):
        """Load and insert AST from a JSON file"""
        self._current_file_stem = Path(file_path).stem
        with open(file_path) as f:
            ast_data = json.load(f)
        self.insert_node_from_json(ast_data)

