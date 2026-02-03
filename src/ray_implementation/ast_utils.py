"""
Functions for AST utilities like node type checking and tree traversal
"""
from typing import Any, Optional
from tree_sitter import Node

class ASTUtils:
    """
    Utility class for AST operations
    """
    @staticmethod
    def get_text(node: Node) -> str:
        """ Returns the text of the node """
        return node.text.decode("utf-8") if isinstance(node.text, bytes) else node.text

    @staticmethod
    def parent_node_of_type(root, target_type) -> Optional[tuple[Node, int]]:
        """
        find the parent node of type target_type
        @return: node and the distance
        """
        dist = 0
        while root is not None:
            if root.type == target_type:
                return (root, dist)
            root = root.parent # FIXME test if works
            dist += 1
        return None

    @staticmethod
    def first_node_of_type(root, target_type: str) -> Optional[Node]:
        """
        Helper function that returns the first node of type in ast subtree
        """
        if root.type == target_type:
            return root
        
        for child in root.children:
            result = ASTUtils.first_node_of_type(child, target_type)
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
            # "function_declaration", # FIXME decide
            "block",
            "do_statement",
            "while_statement",
            "for_statement",
            "if_statement",
            # TODO Add more types as needed
        ]
   
    @staticmethod
    def is_knowledge_node(node) -> bool:
        """
        Determine if the AST node should be represented as a knowledge node
        """
        return node.type in [
            "function_declaration",
            "variable_declaration",
            "class_declaration",
            "block",
            "chunk",
            # TODO Add more types as needed
        ]
    
    @staticmethod
    def is_declaration_node(node: Node) -> Optional[str]:
        """
        Check if the AST node is a declaration node
        """
        map = {
            "function_declaration": 'function',
            "variable_declaration": 'variable',
            "block": 'block',
        }
        
        return map.get(node.type)
    
    @staticmethod
    def is_relation_node(node) -> Optional[str]:
        """
        Check if the AST node is a reference node
        """
        #TODO need to add condition for indentifiers _is_assignment _is_argument
        map = {
            "identifier": 'ident',
            "function_call": 'call',
        }
        return map.get(node.type)
