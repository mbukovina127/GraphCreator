from typing import Any, Dict, Tuple

from ray_implementation.ast_utils import ASTUtils
from ray_implementation.structures import Context
from ._cpg_base import CPGBase


class CPGRelationsMixin(CPGBase):
    """
    Handles relation nodes: identifiers, calls, assignments, blocks, etc.
    Populates the _relation_handlers map used by create_relation_if_possible().
    """

    def _init_relation_handlers(self):
        self._relation_handlers = {
            'ident':             self._handle_ident,
            'assign':            self._handle_assign,
            'call':              self._handle_call,
            'if_statement':      self._handle_if_statement,
            'block':             self._handle_block,
            'exp_list':          self._handle_expression_container,
            'binary_expression': self._handle_expression_container,
            'return':            self._handle_return,
        }

    # ------------------------------------------------------------------
    # Context edge dispatcher
    # ------------------------------------------------------------------

    def _apply_context_edge(self, k_node: Dict[str, Any] | None):
        """Applies the edge that connects k_node to the current context node."""
        if k_node is None or self._context_stack.peek_context() is None:
            return
        context, relevant_id = self._context_stack.get_context()

        match context:
            case Context.ARGUMENTS:
                self._create_knowledge_edge(relevant_id, k_node["_key"], "has_argument")

            case Context.VAR_DECL:
                self._create_knowledge_edge(k_node["_key"], relevant_id, "initializes")

            case Context.EXPRESSION:
                self._create_knowledge_edge(k_node["_key"], relevant_id, "inside_of")

            case Context.ASSIGNMENT:
                self._create_knowledge_edge(k_node["_key"], relevant_id, "assigns_to")

            case Context.CONTROL_STATEMNT:
                relation = {
                    "block": "has_block"
                }.get(k_node["type"], "has_condition")
                self._create_knowledge_edge(relevant_id, k_node["_key"], relation)

            case Context.RETURN:
                ids = self._context_stack.get_context()[1]
                ids = ids.split("$")  # FIXME: replace with tuple
                self._create_knowledge_edge(ids[0], k_node["_key"], "returns")
                self._create_knowledge_edge(ids[1], k_node["_key"], "contains")

            case Context.PARAMETERS:
                self._create_knowledge_edge(relevant_id, k_node["_key"], "has_parameters")

            case Context.BLOCK:
                block_relation = {
                    "variable_declaration": "declares",
                    "if_statement":         "executes",
                    "function_call":        "calls",
                }.get(k_node["type"], "flows_to")
                self._create_knowledge_edge(relevant_id, k_node["_key"], block_relation)

    # ------------------------------------------------------------------
    # Individual handlers — each returns (k_node | None, recursive: bool)
    # ------------------------------------------------------------------

    def _handle_ident(self, node, file_path: str) -> Tuple[Dict | None, bool]:
        if self._context_stack == Context.VAR_DECL:
            return None, False

        k_node = self._create_knowledge_node(node, file_path)
        name = ASTUtils.get_text(node)
        symbol = self._lst.scope_lookup_by_name(self._lexical_scope_stack[-1], name)
        if symbol is not None:
            try:
                found_node_id = self._get_nodeid_from_astid(str(symbol.ast_id))
            except KeyError:
                raise KeyError(f"Symbol {symbol} not found in created knowledge nodes")
            self._create_knowledge_edge(k_node["_key"], found_node_id, "refers_to")
        else:
            self._create_unresolved_edge(k_node["_key"], name, "refers_to", self._lexical_scope_stack[-1], file_path)

        return k_node, False

    def _handle_assign(self, node, file_path: str) -> Tuple[Dict | None, bool]:
        if self._context_stack.peek_context() == Context.VAR_DECL:
            return None, False

        k_node = None
        var_list = ASTUtils.first_node_of_type(node, "variable_list")
        for i in var_list.children:
            if i.type == "identifier":
                k_node = self._create_knowledge_node(i, file_path, {"write": "True"})
                self._context_stack.push_context(k_node["_key"], Context.ASSIGNMENT)  # FIXME: only one variable for now
                name = ASTUtils.get_text(i)
                symbol = self._lst.scope_lookup_by_name(self._lexical_scope_stack[-1], name)
                if symbol is not None:
                    try:
                        found_node_id = self._get_nodeid_from_astid(str(symbol.ast_id))
                    except KeyError:
                        raise KeyError(f"Symbol {symbol} not found in created knowledge nodes")
                    self._create_knowledge_edge(k_node["_key"], found_node_id, "refers_to")
                else:
                    self._create_unresolved_edge(k_node["_key"], name, "refers_to", self._lexical_scope_stack[-1], file_path)
                break

        exp_list = ASTUtils.first_node_of_type(node, "expression_list")
        if exp_list is not None and self._context_stack.peek_context() == Context.ASSIGNMENT:
            for exp in exp_list.children:
                self.build(exp, file_path)
            self._context_stack.pop_context()
            return k_node, True

        return k_node, False

    def _handle_call(self, node, file_path: str) -> Tuple[Dict | None, bool]:
        k_node = self._create_knowledge_node(node, file_path)
        name = ASTUtils.get_text(ASTUtils.first_node_of_type(node, "identifier"))

        if name == 'require':
            pass  # TODO: future require dependencies

        definition = self._lst.scope_lookup_by_name(self._lexical_scope_stack[-1], name)
        if definition is not None:
            found_node_id = self._get_nodeid_from_astid(str(definition.ast_id))
            self._create_knowledge_edge(found_node_id, k_node["_key"], "defines")
        else:
            self._create_unresolved_edge(k_node["_key"], name, "defines", self._lexical_scope_stack[-1], file_path)

        recursive = False
        arguments = ASTUtils.first_node_of_type(node, "arguments")
        if arguments.child_count > 2:  # parentheses count as children
            self._context_stack.push_context(k_node["_key"], Context.ARGUMENTS)
            for arg in arguments.children:
                self.build(arg, file_path)
            self._context_stack.pop_context()
            recursive = True

        return k_node, recursive

    def _handle_if_statement(self, node, file_path: str) -> Tuple[Dict | None, bool]:
        k_node = self._create_knowledge_node(node, file_path)
        self._context_stack.push_context(k_node["_key"], Context.CONTROL_STATEMNT)
        for c in node.children:
            self.build(c, file_path)
        self._context_stack.pop_context()
        return k_node, True

    def _handle_block(self, node, file_path: str) -> Tuple[Dict | None, bool]:
        # FIXME: faulty logic needs rework
        k_node = self._create_knowledge_node(node, file_path)
        con, con_id = self._context_stack.get_context()
        if con == Context.FUN_DECL:  # TODO: could also apply to control statements
            self._create_knowledge_edge(con_id, k_node["_key"], "has_block")
            self._context_stack.push_context(k_node["_key"], Context.BLOCK)
            for c in node.children:
                self.build(c, file_path)
            self._context_stack.pop_context()
            return k_node, True
        return k_node, False

    def _handle_expression_container(self, node, file_path: str) -> Tuple[Dict | None, bool]:
        """Shared handler for exp_list and binary_expression."""
        k_node = self._create_knowledge_node(node, file_path)
        self._context_stack.push_context(k_node["_key"], Context.EXPRESSION)
        for exp in node.children:
            self.build(exp, file_path)
        self._context_stack.pop_context()
        return k_node, True

    def _handle_return(self, node, file_path: str) -> Tuple[Dict | None, bool]:
        k_node = self._create_knowledge_node(node, file_path)
        if (self._context_stack.peek_context() == Context.BLOCK
                and self._context_stack.peek_context(-2) == Context.FUN_DECL):
            # FIXME HORRIBLE TERRIBLE PLEASE FIX — use tuple instead of "$"
            fun_id = self._context_stack.get_context(-2)[1]
            self._context_stack.push_context(fun_id + "$" + k_node["_key"], Context.RETURN)
            for c in node.children:
                self.build(c, file_path)
            self._context_stack.pop_context()
            return k_node, True
        return k_node, False

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def create_relation_if_possible(self, node, file_path: str) -> bool:
        """
        Dispatches to the appropriate handler based on the node's relation type.
        Returns True if the handler already recursed into children.
        """
        rel_type = ASTUtils.is_relation_node(node)
        if rel_type is None:
            return False

        handler = self._relation_handlers.get(rel_type)
        if handler is None:
            return False

        k_node, recursive = handler(node, file_path)
        self._apply_context_edge(k_node)
        return recursive