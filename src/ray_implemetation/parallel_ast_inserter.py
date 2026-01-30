"""
ASTInserter - Inserts AST nodes and directory structure into GraphOutputBuilder.

Adapted from the original ast_inserter.py to work with GraphOutputBuilder
instead of ArangoHandler.
"""
# TODO: ID generation problem -> local Ouput Builder

import json
from typing import Optional
from .local_output_builder import LocalOuputBuilder


class ParallelASTInserter: # TODO: might add polymorphism
    """
    Inserts AST nodes and file structure into the in-memory graph builder
    Different Id numbering to allow parralel file processing
    """
    
    def __init__(self, graph_builder: LocalOuputBuilder):
        self.graph_builder = graph_builder
        self.nodes = self.graph_builder.get_collection("nodes")
        self.edges = self.graph_builder.get_collection("edges")
        self.counter = 1

    def insert_node_from_json(self, node: dict, parent_id: Optional[str] = None):
        """Insert a node from JSON representation (for testing/import)"""
        node_id = self.graph_builder.get_next_node_id("nodes")

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
        node_id = str(self.counter) # FIXME
        self.counter += 1

        # Handle text encoding
        raw = node.text
        if isinstance(raw, bytes):
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("latin-1")
        else:
            text = raw
        
        self.nodes.insert({
            "_key": node_id, # FIXME
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

        # Recursively insert children
        for child in node.children:
            self.insert_node(child, parent_id=node_id)

    def insert_dir_struct(self, dir_struct: list):
        """
        Insert directory structure into the graph.
        
        Args:
            dir_struct: List of dictionaries with name, path, type, parent
        """
        # First pass: insert all nodes
        for item in dir_struct:

            node_id = str(self.counter) # FIXME
            self.counter += 1
            
            self.nodes.insert({
                "_key": node_id, #FIXME
                "name": item["name"],
                "path": item["path"],
                "type": item["type"],
                "parent": item["parent"]
            })

        # Second pass: create parent-child edges
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
        with open(file_path) as f:
            ast_data = json.load(f)
        self.insert_node_from_json(ast_data)
