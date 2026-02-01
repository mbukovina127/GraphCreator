"""
Functions for AST utilities like node type checking and tree traversal
"""
class ASTUtils:
    """
    Utility class for AST operations
    """
    @staticmethod
    def first_node_of_type(root, target_type: str):
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
    def is_different_scope_node(node) -> bool:
        """
        Determine if the AST node introduces a new scope
        """
        return node.type in [
            "chunk",
            "function_declaration",
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
    def is_declaration_node(node) -> str:
        """
        Check if the AST node is a declaration node
        """
        if node.type == "function_declaration":
            return "function"
        elif node.type == "variable_declaration":
            return "variable"
        else:
            return ""
    
    @staticmethod
    def is_reference_node(node) -> bool:
        """
        Check if the AST node is a reference node
        """
        return node.type in [
            "identifier",
            "function_call",
            # TODO: Add more types as needed
        ]