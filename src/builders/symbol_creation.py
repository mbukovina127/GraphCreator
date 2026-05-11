from typing import List, Literal
from ast_utils import ASTUtils
from builders.local_output_builder import LocalOutputBuilder
from structures import SymbolTable, ScopeStack


class SymbolBuilder:
    def __init__(self, local_builder: LocalOutputBuilder, lst: SymbolTable, file_path: str):
        self.local_builder = local_builder
        self._lst = lst
        self._scope_stack = ScopeStack(self._lst.worker_id, file_path, lst)
        self.parameter_stack: List = []
        self.loop_variable_stack: List = []
        self._init_declaration_handlers()

    def _init_declaration_handlers(self):
        self._declaration_handlers = {
            "variable_declaration": self._handle_variable_declaration,
            "assignment_statement": self._handle_assignment_statement,
            "function_declaration": self._handle_function_declaration,
            "for_statement":        self._handle_for_statement,
            "block":                self._handle_block,
            "function_call":        self._handle_module_call,
        }

    # ------------------------------------------------------------------
    # Scope helpers
    # ------------------------------------------------------------------

    def __add_symbol(self, name: str, ast_node, kind: str):
        """
        Adds symbol to current scope and local symbol table
        """
        self._scope_stack.add_to_scope(name, ast_node.id, kind, ast_node.start_byte, ast_node.end_byte)

    def _push_scope(self, s_id: str):
        """
        Push a new scope onto the scope stack
        """
        self._scope_stack.push_scope(s_id)

    def _pop_scope(self):
        """
        Pop the current scope from the scope stack
        """
        return self._scope_stack.pop_scope()

    # ------------------------------------------------------------------
    # Shared helper
    # ------------------------------------------------------------------

    def _helper_variable_declarations(self, kind: str | Literal["global_variable", "local_variable"], node) -> None:
        var_list = ASTUtils.first_node_of_type(node, "variable_list")
        identifiers = ASTUtils.nodes_of_type(var_list, "identifier")  # list in case of multiple declaration

        exp_list = ASTUtils.first_node_of_type(node, "expression_list")
        modules = []  # list of module names
        if exp_list is not None:
            assignments = [x for x in exp_list.children if x.type in ["identifier", "function_call"]]

            if len(identifiers) == len(assignments):
                for a in assignments:
                    if a is None:
                        continue
                    ident = ASTUtils.get_text(ASTUtils.first_node_of_type(a, "identifier"))
                    if ident == "require":
                        module_name = ASTUtils.get_text(ASTUtils.first_node_of_type(a, "string_content"))
                        modules.append(module_name or "")
                    else:
                        modules.append("")

        for i, ident in enumerate(identifiers):
            name = ASTUtils.get_text(ident)
            if modules and modules[i]:
                kind_mod = "local_module_representation" if kind == "local_variable" else "module_representation"
                self.__add_symbol(name, node, kind_mod)
                self._lst.add_import(name, modules[i])
            else:
                self.__add_symbol(name, node, kind)

    # ------------------------------------------------------------------
    # Declaration handlers
    # ------------------------------------------------------------------

    def _handle_variable_declaration(self, node) -> bool:
        # going from variable declaration is always local
        kind = "local_variable" if node.children[0].type == "local" else "global_variable"
        self._helper_variable_declarations(kind, node)
        return True

    def _handle_assignment_statement(self, node) -> bool:
        if ASTUtils.parent_node_of_type(node, "variable_declaration", 1) is not None:
            return False  # this is inside of variable declaration

        kind = "local_variable" if node.parent.children[0].type == "local" else "global_variable"

        var_list = ASTUtils.first_node_of_type(node, "variable_list")
        identifiers = ASTUtils.nodes_of_type(var_list, "identifier")

        # more checks in case it is really a global variable and not just an assignment
        if kind == "global_variable":
            for i in identifiers:
                ident = ASTUtils.get_text(i)
                if self._lst.scope_lookup_by_name(self._scope_stack.view_scope(), ident) is not None:
                    return False  # the variable was just an identifier and not a global variable

        self._helper_variable_declarations(kind, node)
        return True

    def _handle_function_declaration(self, node) -> bool:
        kind = "local_function" if node.children[0].type == "local" else "global_function"
        ident = ASTUtils.first_node_of_type(node, "identifier")

        if ident is not None:
            name = ASTUtils.get_text(ident)
            self.__add_symbol(name, node, kind)

            p = ASTUtils.first_node_of_type(node, "parameters")
            parameters = ASTUtils.nodes_of_type(p, "identifier")  # finds all parameters of the function
            if len(parameters) > 0:
                self.parameter_stack.extend(parameters)  # pushed onto stack, created inside inner scope
        return True

    def _handle_for_statement(self, node) -> bool:
        clause = ASTUtils.first_node_of_type(node, "for_numeric_clause")
        if clause is not None:
            identifier = ASTUtils.first_node_of_type(node, "identifier")
            if identifier is not None:
                self.loop_variable_stack.append(identifier)

        clause = ASTUtils.nodes_of_type(node, "for_generic_clause")
        if clause is not None:
            identifier = ASTUtils.first_node_of_type(node, "identifier")
            while True:
                if identifier is not None:
                    self.loop_variable_stack.append(identifier)
                if identifier.next_sibling is None or identifier.next_sibling.type != ",":
                    break
                else:
                    identifier = identifier.next_sibling.next_sibling  # skipping to the next variable
        return True

    def _handle_block(self, node) -> bool:
        while len(self.parameter_stack) > 0:
            param = self.parameter_stack.pop()
            self.__add_symbol(ASTUtils.get_text(param), param, "parameter")
        while len(self.loop_variable_stack) > 0:
            var = self.loop_variable_stack.pop()
            self.__add_symbol(ASTUtils.get_text(var), var, "loop_variable")
        return True

    def _handle_module_call(self, node) -> bool:
        if ASTUtils.get_text(ASTUtils.first_node_of_type(node, "identifier")) == "module":
            module_name = ASTUtils.get_text(ASTUtils.first_node_of_type(node, "string_content"))
            self.__add_symbol(module_name, node, "module")
        return True

    # ------------------------------------------------------------------
    # Walk
    # ------------------------------------------------------------------

    def build(self, node):
        """Recursively walk the AST and create symbols."""
        if ASTUtils.is_different_scope_node(node):
            self._push_scope(node.id)

        handler = self._declaration_handlers.get(node.type)
        if handler is not None:
            handler(node)

        for child in node.children:
            self.build(child)

        if ASTUtils.is_different_scope_node(node):
            self._pop_scope()