"""
LocalOutputBuilder - In-memory graph builder for the Ray CPG pipeline.

Accumulates AST and knowledge graph vertices/edges in memory and exports
them for downstream processing. Intentionally minimal: only the methods
actually called by CPGBase, ASTInserter, and GraphManager are kept here.
"""

from typing import Dict, List, Any, Optional


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


class CollectionProxy:
    """Proxy object that mimics ArangoDB collection interface for vertices"""

    def __init__(self, storage: Dict[str, Dict[str, Any]], path_index: Dict[str, str]):
        self._storage = storage
        self._path_index = path_index

    def insert(self, doc: Dict[str, Any]) -> str:
        key = doc.get("_key")
        if not key:
            raise ValueError("Document must have _key field")
        self._storage[key] = doc.copy()
        if "path" in doc:
            self._path_index[doc["path"]] = key
        return key

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        return self._storage.get(key)

    def update(self, key: str, updates: Dict[str, Any]):
        if key in self._storage:
            self._storage[key].update(updates)

    def all(self) -> List[Dict[str, Any]]:
        return list(self._storage.values())


class EdgeCollectionProxy:
    """Proxy object that mimics ArangoDB collection interface for edges"""

    def __init__(self, storage: List[Dict[str, Any]]):
        self._storage = storage

    def insert(self, doc: Dict[str, Any]):
        self._storage.append(doc.copy())

    def all(self) -> List[Dict[str, Any]]:
        return self._storage.copy()