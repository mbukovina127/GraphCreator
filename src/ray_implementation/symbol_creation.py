

from typing import List, Optional
from .ast_utils import ASTUtils
from .local_output_builder import LocalOuputBuilder
from .local_symbol_table import SymbolTable, ScopeStack


class SymbolBuilder:
    def __init__(self, local_builder: LocalOuputBuilder, lst: SymbolTable, file_path: str):
        self.local_builder = local_builder
        self.lst = lst
        self.scope_stack = ScopeStack(self.lst.worker_id, file_path, lst)
        self.nodes = local_builder.get_collection("nodes")
        self.edges = local_builder.get_collection("edges")
        self.knowledge_nodes = self.local_builder.get_collection("knowledge_nodes")
        self.knowledge_nodes = self.local_builder.get_collection("knowledge_edges")

        self.parameter_stack: List = []
      
    def __add_symbol(self, name: str, ast_node, kind: str):
        """
        Adds symbol to current scope and local symbol table
        """
        self.scope_stack.add_to_scope(name, ast_node.id, kind, ast_node.start_byte, ast_node.end_byte) #FIXME probable wrong name
        return

    def _push_scope(self, s_id: str):
        """
        Push a new scope onto the scope stack
        """
        self.scope_stack.push_scope(s_id)
        return
    
    def _pop_scope(self):
        """
        Pop the current scope from the scope stack
        """
        return self.scope_stack.pop_scope()
    
    def _create_declaration_symbol(self, type: str, node) -> bool:
        """
        Create a declaration symbol in the current scope
        """
        if type == "variable":
            kind = "local_var" if node.children[0].type == "local" else "global_var"
            var_list = ASTUtils.first_node_of_type(node, "variable_list")
            
            identifiers = ASTUtils.nodes_of_type(var_list, "identifier") # list in case of multiple declaration
            for ident in identifiers:
                name = ident.text.decode("utf-8") if isinstance(ident.text, bytes) else ident.text
                self.__add_symbol(name, node, kind)
            # TODO: expresion handling            
        
        elif type == "function":
            kind = "function_declaration"
            ident = ASTUtils.first_node_of_type(node, 'identifier') # ident 
            if ident is not None:
                name = ident.text.decode("utf-8") if isinstance(ident.text, bytes) else ident.text
                self.__add_symbol(name, node, kind)

                p = ASTUtils.first_node_of_type(node, 'parameters')
                parameters = ASTUtils.nodes_of_type(p, 'identifier') # finds all parameters of the function
                if parameters.__len__() > 0:
                    self.parameter_stack.extend(parameters) # pushes them onto the stack as they need to be create inside inner scope
        
        elif type == "block":            
            for param in self.parameter_stack: # Parameters of a function
                kind = "local_var"
                name = param.text.decode("utf-8") if isinstance(param.text, bytes) else param.text
                self.__add_symbol(name, param, kind)

        elif type == "module":
            pass

        elif type == "chunk":
            pass
        
        return True
    
    def walk(self, node):
        """
        Recursively walk the AST and create symbols
        """
        # TODO: Robust id generation

        # pushes scope stack if needed
        if ASTUtils.is_different_scope_node(node):
            self._push_scope(node.id)
        
        # adding to local symbol table
        type = ASTUtils.is_declaration_node(node) # TODO remake into a single function call
        if type is not None:
            self._create_declaration_symbol(type, node)

        # walk
        for child in node.children:
            self.walk(child)

        # pops scope stack
        if ASTUtils.is_different_scope_node(node):
            self._pop_scope()
            pass