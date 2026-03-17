from typing import List, Literal
from .ast_utils import ASTUtils
from .local_output_builder import LocalOuputBuilder
from .local_symbol_table import SymbolTable, ScopeStack


class SymbolBuilder:
    def __init__(self, local_builder: LocalOuputBuilder, lst: SymbolTable, file_path: str):
        self.local_builder = local_builder
        self._lst = lst
        self._scope_stack = ScopeStack(self._lst.worker_id, file_path, lst)

        self.parameter_stack: List = []
      
    def __add_symbol(self, name: str, ast_node, kind: str):
        """
        Adds symbol to current scope and local symbol table
        """
        self._scope_stack.add_to_scope(name, ast_node.id, kind, ast_node.start_byte, ast_node.end_byte) #FIXME probable wrong name
        return

    def _push_scope(self, s_id: str):
        """
        Push a new scope onto the scope stack
        """
        self._scope_stack.push_scope(s_id)
        return
    
    def _pop_scope(self):
        """
        Pop the current scope from the scope stack
        """
        return self._scope_stack.pop_scope()
    
    def _create_declaration_symbol(self, type: str, node) -> bool:
        """
        Create a declaration symbol in the current scope
        """

        def helper_variable_declarations(kind: str | Literal["global_variable", "local_variable"], symbol_node):
            var_list = ASTUtils.first_node_of_type(symbol_node, "variable_list")
            identifiers = ASTUtils.nodes_of_type(var_list, "identifier")  # list in case of multiple declaration
            # find require calls

            exp_list = ASTUtils.first_node_of_type(symbol_node,"expression_list")  # TODO: check if expression list is correct type
            list = []  # list of module names
            if exp_list is not None:
                assignments = [x for x in exp_list.children if x.type in ["identifier", "function_call"]]

                if len(identifiers) == len(assignments):
                    for a in assignments:
                        if a is None:
                            continue
                        ident = ASTUtils.get_text(ASTUtils.first_node_of_type(a, "identifier"))
                        if ident == "require":
                            # find the module
                            module = ASTUtils.first_node_of_type(a, "string_content")
                            module_name = ASTUtils.get_text(module)
                            list.append(module_name)
                        else:
                            list.append("")

            for i, ident in enumerate(identifiers):
                name = ASTUtils.get_text(ident)
                if list.__len__() > 0 and list[i].__len__() > 0:
                    kind = "local_module_representation" if kind == "local_variable" else "module_representation"
                    self.__add_symbol(name, symbol_node, kind)
                    module_name = list[i]
                    self._lst.add_import(name, module_name)
                    pass
                else:
                    self.__add_symbol(name, symbol_node, kind)

            # TODO: expression handling

        match type:
            case "variable_declaration": # going from variable declaration is always local
                kind = "local_variable" if node.children[0].type == "local" else "global_variable"  # Redundant, is always local

                helper_variable_declarations(kind, node)

            case "possible_variable": #going from assignment
                if ASTUtils.parent_node_of_type(node, "variable_declaration", 1) is not None:
                    return False # this is inside of variable declaration

                kind = "local_variable" if node.parent.children[0].type == "local" else "global_variable" # TEST

                var_list = ASTUtils.first_node_of_type(node, "variable_list")
                identifiers = ASTUtils.nodes_of_type(var_list, "identifier")

                # more checks in case it is really a global variable and not just an assignment
                if kind == "global_variable":
                    #first look into the lst
                    for i in identifiers:
                        ident = ASTUtils.get_text(i)
                        if self._lst.scope_lookup_by_name(self._scope_stack.view_scope(), ident) is not None:
                            return False # the variable was just an identfier and not a global variable

                helper_variable_declarations(kind, node)

            case "function_declaration":
                kind = "local_function" if node.children[0].type == "local" else "global_function"
                ident = ASTUtils.first_node_of_type(node, 'identifier') # ident

                if ident is not None:
                    name = ASTUtils.get_text(ident)
                    self.__add_symbol(name, node, kind)

                    p = ASTUtils.first_node_of_type(node, 'parameters')
                    parameters = ASTUtils.nodes_of_type(p, 'identifier') # finds all parameters of the function
                    if parameters.__len__() > 0:
                        self.parameter_stack.extend(parameters) # pushes them onto the stack as they need to be create inside inner scope

            case "block":
                for param in self.parameter_stack: # Parameters of a function
                    kind = "parameter"
                    name = param.text.decode("utf-8") if isinstance(param.text, bytes) else param.text
                    self.__add_symbol(name, param, kind)

            case "module":
                #find module
                if ASTUtils.get_text(ASTUtils.first_node_of_type(node, "identifier")) == "module":
                    #find the name of the module
                    module_name = ASTUtils.get_text(ASTUtils.first_node_of_type(node, "string_content"))
                    kind = "module"
                    self.__add_symbol(module_name, node, kind)

                pass
            case "chunk":
                pass
        
        return False


    def build(self, node):
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
            self.build(child)

        # pops scope stack
        if ASTUtils.is_different_scope_node(node):
            self._pop_scope()
            pass