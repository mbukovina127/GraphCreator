"""
LocalOutputBuilder - In-memory graph builder for the Ray CPG pipeline.

Accumulates AST and knowledge graph vertices/edges in memory and exports
them for downstream processing. Intentionally minimal: only the methods
actually called by CPGBase, ASTInserter, and GraphManager are kept here.
"""

from typing import Dict, List, Any, Optional

from graph_builder.output_builder import CollectionProxy, EdgeCollectionProxy


class LocalOutputBuilder:
    def __init__(self):
        self._nodes: Dict[str, Dict[str, Any]] = {}
        self._edges: List[Dict[str, Any]] = []

        self.knowledge_nodes: Dict[str, Dict[str, Any]] = {}
        self.knowledge_edges: List[Dict[str, Any]] = []

        self._path_to_id: Dict[str, str] = {}

    def clear(self):
        """Clear all stored data"""
        self._nodes.clear()
        self._edges.clear()
        self.knowledge_nodes.clear()
        self.knowledge_edges.clear()
        self._path_to_id.clear()

    def get_collection(self, name: str) -> 'CollectionProxy':
        """Return a proxy object that mimics ArangoDB collection interface"""
        if name == "nodes":
            return CollectionProxy(self._nodes, self._path_to_id)
        elif name == "edges":
            return EdgeCollectionProxy(self._edges)
        elif name == "knowledge_nodes":
            return CollectionProxy(self.knowledge_nodes, self._path_to_id)
        elif name == "knowledge_edges":
            return EdgeCollectionProxy(self.knowledge_edges)
        else:
            raise ValueError(f"Unknown collection: {name}")

    def get_node_id_from_path(self, collection_name: str, path: str) -> Optional[str]:
        """Get node ID by file path"""
        return self._path_to_id.get(path)

    def get_nodes_by_type(self, collection_name: str, node_type: str) -> List[Dict[str, Any]]:
        """Get all nodes of a specific type"""
        if collection_name == "nodes":
            return [n for n in self._nodes.values() if n.get("type") == node_type]
        elif collection_name == "knowledge_nodes":
            return [n for n in self.knowledge_nodes.values() if n.get("type") == node_type]
        return []

    def export_ast_graph(self) -> Dict[str, Any]:
        """Export the AST graph (nodes + edges) as a dictionary"""
        return {
            "vertices": list(self._nodes.values()),
            "edges": self._edges.copy()
        }

    def export_knowledge_graph(self) -> Dict[str, Any]:
        """Export the knowledge graph as a dictionary"""
        return {
            "vertices": list(self.knowledge_nodes.values()),
            "edges": self.knowledge_edges.copy()
        }