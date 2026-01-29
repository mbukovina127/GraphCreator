"""
Unit tests for GraphOutputBuilder.

Tests the in-memory graph building functionality.
"""

import os
import sys
import pytest

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from graph_builder.output_builder import GraphOutputBuilder  # type: ignore[import-not-found]


class TestGraphOutputBuilder:
    """Tests for GraphOutputBuilder class"""
    
    def test_init(self):
        """Test initialization"""
        builder = GraphOutputBuilder()
        stats = builder.get_stats()
        
        assert stats["nodes"] == 0
        assert stats["edges"] == 0
        assert stats["knowledge_nodes"] == 0
        assert stats["knowledge_edges"] == 0
    
    def test_get_collection_nodes(self):
        """Test getting nodes collection"""
        builder = GraphOutputBuilder()
        nodes = builder.get_collection("nodes")
        
        assert nodes is not None
        assert len(nodes.all()) == 0
    
    def test_get_collection_edges(self):
        """Test getting edges collection"""
        builder = GraphOutputBuilder()
        edges = builder.get_collection("edges")
        
        assert edges is not None
        assert len(edges.all()) == 0
    
    def test_insert_node(self):
        """Test inserting a node"""
        builder = GraphOutputBuilder()
        nodes = builder.get_collection("nodes")
        
        nodes.insert({
            "_key": "1",
            "type": "chunk",
            "text": "test code",
            "start_byte": 0,
            "end_byte": 100
        })
        
        assert len(nodes.all()) == 1
        assert nodes.get("1")["type"] == "chunk"
    
    def test_insert_edge(self):
        """Test inserting an edge"""
        builder = GraphOutputBuilder()
        nodes = builder.get_collection("nodes")
        edges = builder.get_collection("edges")
        
        # Insert two nodes
        nodes.insert({"_key": "1", "type": "parent"})
        nodes.insert({"_key": "2", "type": "child"})
        
        # Insert edge
        edges.insert({
            "_from": "nodes/1",
            "_to": "nodes/2",
            "relation": "child_of"
        })
        
        assert len(edges.all()) == 1
        assert edges.all()[0]["relation"] == "child_of"
    
    def test_get_next_node_id(self):
        """Test unique ID generation"""
        builder = GraphOutputBuilder()
        
        id1 = builder.get_next_node_id()
        id2 = builder.get_next_node_id()
        id3 = builder.get_next_node_id()
        
        assert id1 != id2
        assert id2 != id3
        assert id1 == "1"
        assert id2 == "2"
        assert id3 == "3"
    
    def test_get_node_id_from_path(self):
        """Test path to ID lookup"""
        builder = GraphOutputBuilder()
        nodes = builder.get_collection("nodes")
        
        nodes.insert({
            "_key": "42",
            "type": "file",
            "name": "test.lua",
            "path": "/project/src/test.lua"
        })
        
        found_id = builder.get_node_id_from_path("nodes", "/project/src/test.lua")
        assert found_id == "42"
        
        not_found = builder.get_node_id_from_path("nodes", "/nonexistent")
        assert not_found is None
    
    def test_get_children(self):
        """Test getting child nodes"""
        builder = GraphOutputBuilder()
        nodes = builder.get_collection("nodes")
        edges = builder.get_collection("edges")
        
        # Create parent and children
        nodes.insert({"_key": "1", "type": "parent", "name": "parent"})
        nodes.insert({"_key": "2", "type": "child", "name": "child1"})
        nodes.insert({"_key": "3", "type": "child", "name": "child2"})
        
        edges.insert({"_from": "nodes/1", "_to": "nodes/2", "relation": "contains"})
        edges.insert({"_from": "nodes/1", "_to": "nodes/3", "relation": "contains"})
        
        children = builder.get_children("nodes", "1")
        assert len(children) == 2
        
        # Test with relation filter
        children_filtered = builder.get_children("nodes", "1", "contains")
        assert len(children_filtered) == 2
    
    def test_export_ast_graph(self):
        """Test exporting AST graph"""
        builder = GraphOutputBuilder()
        nodes = builder.get_collection("nodes")
        edges = builder.get_collection("edges")
        
        nodes.insert({"_key": "1", "type": "chunk"})
        nodes.insert({"_key": "2", "type": "function"})
        edges.insert({"_from": "nodes/1", "_to": "nodes/2", "relation": "child_of"})
        
        export = builder.export_ast_graph()
        
        assert "vertices" in export
        assert "edges" in export
        assert len(export["vertices"]) == 2
        assert len(export["edges"]) == 1
    
    def test_export_knowledge_graph(self):
        """Test exporting knowledge graph"""
        builder = GraphOutputBuilder()
        kn = builder.get_collection("knowledge_nodes")
        ke = builder.get_collection("knowledge_edges")
        
        kn.insert({"_key": "1", "type": "module", "text": "mymodule"})
        kn.insert({"_key": "2", "type": "function", "text": "myfunc"})
        ke.insert({"_from": "knowledge_nodes/1", "_to": "knowledge_nodes/2", "relation": "declares"})
        
        export = builder.export_knowledge_graph()
        
        assert len(export["vertices"]) == 2
        assert len(export["edges"]) == 1
    
    def test_export_all(self):
        """Test exporting all graphs in storage adapter format"""
        builder = GraphOutputBuilder()
        
        # Add some data
        builder.get_collection("nodes").insert({"_key": "1", "type": "chunk"})
        builder.get_collection("knowledge_nodes").insert({"_key": "1", "type": "module"})
        
        export = builder.export_all()
        
        # Check new format compatible with storage adapter
        assert "vertices" in export
        assert "edges" in export
        assert "metadata" in export
        assert "name" in export
        
        # Check vertices structure
        assert "ast_nodes" in export["vertices"]
        assert "knowledge_nodes" in export["vertices"]
        assert len(export["vertices"]["ast_nodes"]) == 1
        assert len(export["vertices"]["knowledge_nodes"]) == 1
        
        # Check edges structure  
        assert "ast_edges" in export["edges"]
        assert "knowledge_edges" in export["edges"]
        
        # Check metadata
        assert export["metadata"]["total_nodes"] == 1
        assert export["metadata"]["total_knowledge_nodes"] == 1
    
    def test_clear(self):
        """Test clearing all data"""
        builder = GraphOutputBuilder()
        
        # Add data
        builder.get_collection("nodes").insert({"_key": "1", "type": "test"})
        builder.get_collection("edges").insert({"_from": "a", "_to": "b"})
        
        assert builder.get_stats()["nodes"] == 1
        
        # Clear
        builder.clear()
        
        stats = builder.get_stats()
        assert stats["nodes"] == 0
        assert stats["edges"] == 0


class TestCollectionProxy:
    """Tests for CollectionProxy class"""
    
    def test_insert_requires_key(self):
        """Test that insert requires _key field"""
        builder = GraphOutputBuilder()
        nodes = builder.get_collection("nodes")
        
        with pytest.raises(ValueError, match="_key"):
            nodes.insert({"type": "test"})  # Missing _key
    
    def test_update(self):
        """Test updating a document"""
        builder = GraphOutputBuilder()
        nodes = builder.get_collection("nodes")
        
        nodes.insert({"_key": "1", "type": "old", "value": 10})
        nodes.update("1", {"type": "new", "extra": "field"})
        
        updated = nodes.get("1")
        assert updated["type"] == "new"
        assert updated["value"] == 10  # Original field preserved
        assert updated["extra"] == "field"  # New field added
    
    def test_get_nonexistent(self):
        """Test getting a nonexistent document"""
        builder = GraphOutputBuilder()
        nodes = builder.get_collection("nodes")
        
        result = nodes.get("nonexistent")
        assert result is None
