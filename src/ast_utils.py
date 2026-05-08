"""
Functions for AST utilities like node type checking and tree traversal
"""
from typing import Optional

from tree_sitter import Node


class ASTUtils:
    """
    Utility class for AST operations
    """
    @staticmethod
    def get_text(node: Node) -> str | None:
        """ Returns the text of the node, or None if node is None """
        if node is None:
            return None
        return node.text.decode("utf-8") if isinstance(node.text, bytes) else node.text

    @staticmethod
    def parent_node_of_type(root, target_type, threshold: int = 5) -> Optional[tuple[Node, int]]:
        """
        find the parent node of type target_type
        @threshold: give up after default = `5` parents
        @return: node and the distance
        """
        dist = 0
        while root is not None:
            if root.type == target_type:
                return (root, dist)
            if dist >= threshold:
                return None
            root = root.parent
            dist += 1
        return None

    @staticmethod
    def first_node_of_type(root, target_type: str, depth: int | None = None) -> Optional[Node]:
        """
        Helper function that returns the first node of type in ast subtree
        """
        if depth is not None:
            if depth < 0:
                return None
            depth -= 1

        if root.type == target_type:
            return root
        
        for child in root.children:
            result = ASTUtils.first_node_of_type(child, target_type, depth)
            if result is not None:
                return result
        return None

    @staticmethod
    def nodes_of_type(root, target_type: str) -> list:
        """
        Helper function that returns every node of type in ast subtree
        """
        found_nodes = []
        if root.type == target_type:
            found_nodes.append(root)
        
        for child in root.children:
            found_nodes.extend(ASTUtils.nodes_of_type(child, target_type))
        
        return found_nodes
    
    @staticmethod
    def nodes_of_type_trigger(root, trigger_type: str, target_type: str, single: bool = False) -> list:
        """ Function that first searches parents until it hits the trigger type than searches children""" # propably useless but kinda cool
        parent = ASTUtils.parent_node_of_type(root, trigger_type)
        if parent is not None:
            if single:
                return [ASTUtils.first_node_of_type(parent, target_type)]
            else:
                return ASTUtils.nodes_of_type(parent, target_type)
        return []

    @staticmethod
    def is_different_scope_node(node) -> bool:
        """
        Determine if the AST node introduces a new scope
        """
        return node.type in [
            "chunk",
            "block",
        ]
