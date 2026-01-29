"""
GraphOutputBuilder - In-memory graph builder that replaces ArangoHandler.

Instead of writing directly to ArangoDB, this class accumulates vertices and edges
in memory and can export them as a JSON structure for publishing to the
graph-updates Dapr topic.
"""

from typing import Dict, List, Any, Optional
import uuid


class GraphOutputBuilder:
    """
    In-memory graph builder that mimics ArangoHandler interface.
    Accumulates vertices and edges for later export to Graph Store Adapter.
    """
    
    def __init__(self):
        # Main AST graph collections (equivalent to lua_graph)
        self._nodes: Dict[str, Dict[str, Any]] = {}
        self._edges: List[Dict[str, Any]] = []
        
        # Knowledge graph collections (equivalent to knowledge_graph)
        self._knowledge_nodes: Dict[str, Dict[str, Any]] = {}
        self._knowledge_edges: List[Dict[str, Any]] = []
        
        # Counter for generating unique IDs
        self._node_counter = 1
        
        # Path to node ID mapping for quick lookups
        self._path_to_id: Dict[str, str] = {}

    def clear(self):
        """Clear all stored data - useful for processing new projects"""
        self._nodes.clear()
        self._edges.clear()
        self._knowledge_nodes.clear()
        self._knowledge_edges.clear()
        self._node_counter = 1
        self._path_to_id.clear()

    # =========================================================================
    # Node collection access (mimics ArangoHandler.get_collection)
    # =========================================================================
    
    def get_collection(self, name: str) -> 'CollectionProxy':
        """Return a proxy object that mimics ArangoDB collection interface"""
        if name == "nodes":
            return CollectionProxy(self._nodes, self._path_to_id)
        elif name == "edges":
            return EdgeCollectionProxy(self._edges)
        elif name == "knowledge_nodes":
            return CollectionProxy(self._knowledge_nodes, self._path_to_id)
        elif name == "knowledge_edges":
            return EdgeCollectionProxy(self._knowledge_edges)
        else:
            raise ValueError(f"Unknown collection: {name}")

    # =========================================================================
    # ID generation (mimics ArangoHandler.get_next_node_id)
    # =========================================================================
    
    def get_next_node_id(self, collection_name: str = "nodes") -> str:
        """Generate next unique node ID"""
        node_id = str(self._node_counter)
        self._node_counter += 1
        return node_id
    
    def get_node_id_from_path(self, collection_name: str, path: str) -> Optional[str]:
        """Get node ID by file path"""
        return self._path_to_id.get(path)

    # =========================================================================
    # Direct insert methods (for compatibility)
    # =========================================================================
    
    def insert_node(self, collection_name: str, node: Dict[str, Any]) -> str:
        """Insert a node into the specified collection"""
        collection = self.get_collection(collection_name)
        return collection.insert(node)
    
    def insert_edge(self, collection_name: str, edge: Dict[str, Any]):
        """Insert an edge into the specified collection"""
        collection = self.get_collection(collection_name)
        collection.insert(edge)

    # =========================================================================
    # Query interface (for GraphQueries compatibility)
    # =========================================================================
    
    def get_node(self, collection_name: str, key: str) -> Optional[Dict[str, Any]]:
        """Get a node by key"""
        if collection_name == "nodes":
            return self._nodes.get(key)
        elif collection_name == "knowledge_nodes":
            return self._knowledge_nodes.get(key)
        return None
    
    def get_nodes_by_type(self, collection_name: str, node_type: str) -> List[Dict[str, Any]]:
        """Get all nodes of a specific type"""
        if collection_name == "nodes":
            return [n for n in self._nodes.values() if n.get("type") == node_type]
        elif collection_name == "knowledge_nodes":
            return [n for n in self._knowledge_nodes.values() if n.get("type") == node_type]
        return []
    
    def get_outbound_edges(self, collection_name: str, from_key: str) -> List[Dict[str, Any]]:
        """Get all outbound edges from a node"""
        prefix = f"{collection_name.replace('_edges', '_nodes')}/{from_key}"
        if collection_name == "edges":
            return [e for e in self._edges if e.get("_from") == f"nodes/{from_key}"]
        elif collection_name == "knowledge_edges":
            return [e for e in self._knowledge_edges if e.get("_from") == f"knowledge_nodes/{from_key}"]
        return []
    
    def get_inbound_edges(self, collection_name: str, to_key: str) -> List[Dict[str, Any]]:
        """Get all inbound edges to a node"""
        if collection_name == "edges":
            return [e for e in self._edges if e.get("_to") == f"nodes/{to_key}"]
        elif collection_name == "knowledge_edges":
            return [e for e in self._knowledge_edges if e.get("_to") == f"knowledge_nodes/{to_key}"]
        return []
    
    def get_children(self, collection_name: str, parent_key: str, relation: str = None) -> List[Dict[str, Any]]:
        """Get all child nodes connected via outbound edges"""
        if collection_name == "nodes":
            edges = self._edges
            nodes = self._nodes
            node_prefix = "nodes"
        else:
            edges = self._knowledge_edges
            nodes = self._knowledge_nodes
            node_prefix = "knowledge_nodes"
        
        children = []
        for edge in edges:
            if edge.get("_from") == f"{node_prefix}/{parent_key}":
                if relation is None or edge.get("relation") == relation:
                    to_key = edge.get("_to", "").split("/")[-1]
                    if to_key in nodes:
                        children.append(nodes[to_key])
        return children

    # =========================================================================
    # Export methods
    # =========================================================================
    
    def export_ast_graph(self) -> Dict[str, Any]:
        """Export the AST graph (nodes + edges) as a dictionary"""
        return {
            "vertices": list(self._nodes.values()),
            "edges": self._edges.copy()
        }
    
    def export_knowledge_graph(self) -> Dict[str, Any]:
        """Export the knowledge graph as a dictionary"""
        return {
            "vertices": list(self._knowledge_nodes.values()),
            "edges": self._knowledge_edges.copy()
        }
    
    def export_all(self) -> Dict[str, Any]:
        """Export both graphs as a single structure for Graph Store Adapter.
        
        Returns a structure compatible with the storage adapter's GraphUpdateEvent:
        {
            "vertices": {"collection_name": [docs...]},
            "edges": {"collection_name": [docs...]},
            "name": "...",
            "metadata": {...}
        }
        """
        return {
            "vertices": {
                "ast_nodes": list(self._nodes.values()),
                "knowledge_nodes": list(self._knowledge_nodes.values())
            },
            "edges": {
                "ast_edges": self._edges.copy(),
                "knowledge_edges": self._knowledge_edges.copy()
            },
            "name": "Lua Analysis Graph",
            "metadata": {
                "total_nodes": len(self._nodes),
                "total_knowledge_nodes": len(self._knowledge_nodes),
                "total_edges": len(self._edges),
                "total_knowledge_edges": len(self._knowledge_edges)
            }
        }

    def export_cpg_v1(self, project_id: str) -> Dict[str, Any]:
        """
        Export the graph in the new Universal CPG v1 format.
        
        Args:
            project_id: The ID of the project being analyzed.
            
        Returns:
            A dictionary compliant with schema/v1/cpg.export.schema.json
        """
        import datetime
        
        nodes = []
        edges = []
        
        # 1. Process all nodes (AST + Knowledge)
        # We use a set to avoid duplicates if a node exists in both (though unlikely here)
        processed_node_keys = set()
        
        # Helper to process a node collection
        def process_collection(internal_nodes, is_knowledge=False):
            for node in internal_nodes:
                key = node["_key"]
                if key in processed_node_keys:
                    continue
                processed_node_keys.add(key)
                
                internal_type = node.get("type", "UNKNOWN")
                cpg_type = self._map_type(internal_type)
                
                cpg_node = {
                    "id": f"{project_id}:{key}",
                    "type": cpg_type,
                    "properties": {
                        "kind": internal_type,
                        "language": "lua"
                    }
                }
                
                # Map text to code
                if "text" in node:
                    cpg_node["properties"]["code"] = node["text"]
                
                # Map name
                if "name" in node:
                    cpg_node["properties"]["name"] = node["name"]
                
                # Map other properties
                for k, v in node.items():
                    if k not in ["_key", "type", "text", "name", "location", "parent", "ast_id"]:
                        cpg_node["properties"][k] = v
                
                # Map location if present
                if "location" in node:
                    cpg_node["location"] = node["location"]
                elif "start_byte" in node and "end_byte" in node:
                    # Basic location from tree-sitter bytes
                    cpg_node["location"] = {
                        "start_offset": node["start_byte"],
                        "end_offset": node["end_byte"]
                    }
                    if "path" in node:
                        cpg_node["location"]["file"] = node["path"]
                
                nodes.append(cpg_node)

        process_collection(self._nodes.values())
        process_collection(self._knowledge_nodes.values(), is_knowledge=True)
        
        # 2. Process all edges
        def process_edges(internal_edges, source_prefix, target_prefix):
            for edge in internal_edges:
                source_id = edge["_from"].split("/")[-1]
                target_id = edge["_to"].split("/")[-1]
                relation = edge.get("relation", "UNKNOWN")
                
                # Determine CPG edge type
                cpg_edge_type = self._map_edge_type(relation, source_id, target_id)
                
                cpg_edge = {
                    "source": f"{project_id}:{source_id}",
                    "target": f"{project_id}:{target_id}",
                    "type": cpg_edge_type,
                    "properties": {}
                }
                
                # Map other edge properties
                for k, v in edge.items():
                    if k not in ["_from", "_to", "relation"]:
                        cpg_edge["properties"][k] = v
                
                edges.append(cpg_edge)

        process_edges(self._edges, "nodes", "nodes")
        process_edges(self._knowledge_edges, "knowledge_nodes", "knowledge_nodes")
        
        return {
            "meta_data": {
                "schema_version": "v1",
                "languages": ["lua"],
                "analysis_date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "graph_id": project_id,
                "project_id": project_id
            },
            "nodes": nodes,
            "edges": edges
        }

    def _map_type(self, internal_type: str) -> str:
        """Map internal Lua/Tree-sitter types to CPG v1 types"""
        mapping = {
            "file": "FILE",
            "dir": "DIRECTORY",
            "function_definition": "FUNCTION",
            "local_function_definition": "FUNCTION",
            "variable_declaration": "VARIABLE",
            "local_declaration": "VARIABLE",
            "identifier": "IDENTIFIER",
            "string": "LITERAL",
            "number": "LITERAL",
            "boolean": "LITERAL",
            "nil": "LITERAL",
            "call_expression": "CALL",
            "if_statement": "CONTROL_STRUCTURE",
            "while_statement": "CONTROL_STRUCTURE",
            "for_statement": "CONTROL_STRUCTURE",
            "repeat_statement": "CONTROL_STRUCTURE",
            "do_statement": "BLOCK",
            "block": "BLOCK",
            "comment": "COMMENT",
            # Knowledge graph types
            "MODULE": "NAMESPACE",
            "FUNCTION": "FUNCTION",
            "VARIABLE": "VARIABLE",
            "PARAMETER": "VARIABLE",
            "BLOCK": "BLOCK",
            "STATEMENT": "UNKNOWN"
        }
        return mapping.get(internal_type, "UNKNOWN")

    def _map_edge_type(self, relation: str, source_id: str, target_id: str) -> str:
        """Map internal relations to CPG v1 edge types"""
        # Special case: child_of can be CONTAINS for directories or AST_CHILD for code
        if relation == "child_of":
            source_node = self._nodes.get(source_id) or self._knowledge_nodes.get(source_id)
            target_node = self._nodes.get(target_id) or self._knowledge_nodes.get(target_id)
            
            if source_node and target_node:
                if source_node.get("type") in ["dir", "file"] and target_node.get("type") in ["dir", "file"]:
                    return "CONTAINS"
            return "AST_CHILD"
            
        mapping = {
            "contains": "CONTAINS",
            "executes": "FLOWS_TO",
            "calls": "CALLS",
            "defines": "DEFINES",
            "declares": "DECLARES",
            "refers_to": "REFERS_TO",
            "has_parameter": "HAS_PARAMETER",
            "returns": "RETURNS",
            "has_block": "AST_CHILD",
            "imports": "IMPORTS",
            "requires": "IMPORTS",
            "child_of": "AST_CHILD",
            "executes": "FLOWS_TO",
            "calls": "CALLS",
            "defines": "DEFINES",
            "declares": "DECLARES",
            "refers_to": "REFERS_TO",
            "UNKNOWN": "AST_CHILD"  # Fallback for unmapped relations
        }
        return mapping.get(relation, "AST_CHILD")

    # =========================================================================
    # Statistics
    # =========================================================================
    
    def get_stats(self) -> Dict[str, int]:
        """Get statistics about the accumulated graph"""
        return {
            "nodes": len(self._nodes),
            "edges": len(self._edges),
            "knowledge_nodes": len(self._knowledge_nodes),
            "knowledge_edges": len(self._knowledge_edges)
        }


class CollectionProxy:
    """Proxy object that mimics ArangoDB collection interface for vertices"""
    
    def __init__(self, storage: Dict[str, Dict[str, Any]], path_index: Dict[str, str]):
        self._storage = storage
        self._path_index = path_index
    
    def insert(self, doc: Dict[str, Any]) -> str:
        """Insert a document into the collection"""
        key = doc.get("_key")
        if not key:
            raise ValueError("Document must have _key field")
        
        self._storage[key] = doc.copy()
        
        # Index by path if present
        if "path" in doc:
            self._path_index[doc["path"]] = key
        
        return key
    
    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Get a document by key"""
        return self._storage.get(key)
    
    def update(self, key: str, updates: Dict[str, Any]):
        """Update a document"""
        if key in self._storage:
            self._storage[key].update(updates)
    
    def all(self) -> List[Dict[str, Any]]:
        """Get all documents"""
        return list(self._storage.values())


class EdgeCollectionProxy:
    """Proxy object that mimics ArangoDB collection interface for edges"""
    
    def __init__(self, storage: List[Dict[str, Any]]):
        self._storage = storage
    
    def insert(self, doc: Dict[str, Any]):
        """Insert an edge into the collection"""
        self._storage.append(doc.copy())
    
    def all(self) -> List[Dict[str, Any]]:
        """Get all edges"""
        return self._storage.copy()
