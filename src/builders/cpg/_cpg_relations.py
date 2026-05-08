import logging
from typing import Any, Dict, Tuple

import ast_metrics
from ast_utils import ASTUtils
from dto.edges import Edges
from structures import Context
from ._cpg_base import CPGBase, logger

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CPGRelationsMixin(CPGBase):
    """
    Handles relation nodes: identifiers, calls, assignments, blocks, etc.
    Populates the _relation_handlers map used by create_relation_if_possible().
    """

    def _init_relation_handlers(self):
        self._relation_handlers = {
            'identifier':                   self._handle_identifier,
            'assignment_statement':         self._handle_assignment,
            'function_call':                self._handle_call,
            'if_statement':                 self._handle_control_statement,
            'else_statement':               self._handle_control_statement,
            'elseif_statement':             self._handle_control_statement,
            'block':                        self._handle_block,
            'expression_list':              self._handle_expression_container,
            'binary_expression':            self._handle_expression_container,
            'return_statement':             self._handle_return,
            # loops
            'for_statement':                self._handle_loops,
            'while_statement':              self._handle_loops,
            'repeat_statement':             self._handle_loops,
            'for_numeric_clause':           self._handle_for_clause,
            'for_generic_clause':           self._handle_for_clause,
            # indexing
            'bracket_index_expression':     self._handle_bracket_index_expression,
            'dot_index_expression':         self._handle_dot_index_expression,
            # table constructors
            'table_constructor':            self._handle_table_constructor,
            'field':                        self._handle_field,
            # literals
            'number':                       self._handle_literal,
            'string':                       self._handle_literal,
            'true':                         self._handle_literal,
            'false':                        self._handle_literal,
            'nil':                          self._handle_literal,
        }

    # ------------------------------------------------------------------
    # Context edge dispatcher
    # ------------------------------------------------------------------

    def _apply_context_edge(self, k_node: Dict[str, Any] | None):
        """Applies the edge that connects k_node to the current context node."""
        if k_node is None or self._context_stack.peek_context() is None:
            return

        context, relevant_id = self._context_stack.get_context()
        logger.info(f"Applying context edge to node {k_node['_key']} in context of {context}")
        match context:
            case Context.ARGUMENTS:
                self._create_knowledge_edge(relevant_id, k_node["_key"], Edges.HAS_ARGUMENT)

            case Context.VAR_DECL:
                self._create_knowledge_edge(k_node["_key"], relevant_id, Edges.INITIALIZES)

            case Context.EXPRESSION:
                self._create_knowledge_edge(k_node["_key"], relevant_id, Edges.INSIDE_OF)

            case Context.ASSIGNMENT:
                self._create_knowledge_edge(k_node["_key"], relevant_id, Edges.ASSIGNS_TO)

            case Context.CONTROL_STATEMENT:
                relation = {
                    "block": None,  # blocks already create edges
                    "binary_expression": Edges.HAS_CONDITION,
                    "exp_list": Edges.HAS_CONDITION,
                }.get(k_node["type"], Edges.FLOWS_TO)
                if relation is not None:
                    self._create_knowledge_edge(relevant_id, k_node["_key"], relation)

            case Context.LOOP:
                loop_relation = {
                    'block': None,
                    'for_generic_clause': Edges.HAS_CONDITION,
                    'for_numeric_clause': Edges.HAS_CONDITION,
                    'binary_expression': Edges.HAS_CONDITION,
                }.get(k_node["type"], Edges.FLOWS_TO)
                if loop_relation is not None:
                    self._create_knowledge_edge(relevant_id, k_node["_key"], loop_relation)

            case Context.RETURN:
                return_node_id = self._context_stack.get_context()[1]
                fun_id = self._context_stack.find_in_wider_context([Context.FUN_DECL])
                self._create_knowledge_edge(fun_id, k_node["_key"], Edges.RETURNS)
                self._create_knowledge_edge(return_node_id, k_node["_key"], Edges.CONTAINS)

            case Context.PARAMETERS:
                self._create_knowledge_edge(relevant_id, k_node["_key"], Edges.HAS_PARAMETERS)

            case Context.TABLE_CONSTRUCTOR:
                self._create_knowledge_edge(relevant_id, k_node["_key"], Edges.HAS_FIELD)

            case Context.BLOCK:
                block_relation = {
                    "variable_declaration": Edges.DECLARES,
                    "if_statement":         Edges.EXECUTES,
                    "function_call":        Edges.CALLS,
                }.get(k_node["type"], Edges.FLOWS_TO)
                self._create_knowledge_edge(relevant_id, k_node["_key"], block_relation)

            case Context.CHUNK:
                chunk_relation = {
                    "for_statement":   Edges.EXECUTES,
                    "if_statement":    Edges.EXECUTES,
                    "repeat_statement": Edges.EXECUTES,
                    "while_statement": Edges.EXECUTES,
                }.get(k_node["type"])
                if chunk_relation is not None:
                    self._create_knowledge_edge(relevant_id, k_node["_key"], chunk_relation)
    # ------------------------------------------------------------------
    # Individual handlers — each returns (k_node | None, recursive: bool)
    # ------------------------------------------------------------------

    def _handle_identifier(self, node, file_path: str) -> Tuple[Dict | None, bool]:
        if self._context_stack == Context.VAR_DECL:
            return None, True

        name = ASTUtils.get_text(node)
        k_node = self._create_knowledge_node(node, file_path,properties={"name": name})
        symbol = self._lst.scope_lookup_by_name(self._lexical_scope_stack[-1], name)
        if symbol is None:
            self._create_unresolved_edge(k_node["_key"], name, Edges.REFERS_TO, self._lexical_scope_stack[-1], file_path)
            logger.info(f"Created unresolved edge[{k_node['_key']}, {name}]")
        else:
            try:
                found_node_id = self._get_nodeid_from_astid(str(symbol.ast_id))
                if symbol.kind in ["module_representation", "local_module_representation"]:
                    self._create_knowledge_edge(k_node["_key"], found_node_id, Edges.REFERS_TO)
                    #TODO do something with module importing
                else:
                    self._create_knowledge_edge(k_node["_key"], found_node_id, Edges.REFERS_TO)

            except KeyError:
                logger.error(f"Symbol {symbol} not found in created knowledge nodes")

        return k_node, False

    def _handle_assignment(self, node, file_path: str) -> Tuple[Dict | None, bool]:
        # Lefthand side
        k_node = None
        var_list = ASTUtils.first_node_of_type(node, "variable_list")
        for i_nodes in var_list.children:
            if i_nodes.type == "identifier":
                name = ASTUtils.get_text(i_nodes)
                k_node = self._create_knowledge_node(i_nodes, file_path, properties={"name": name, "write": "True"})
                symbol = self._lst.scope_lookup_by_name(self._lexical_scope_stack[-1], name)
                if symbol is not None:
                    try:
                        found_node_id = self._get_nodeid_from_astid(str(symbol.ast_id))
                        self._create_knowledge_edge(k_node["_key"], found_node_id, Edges.REFERS_TO)
                    except KeyError:
                        logger.error(f"Symbol {symbol} not found in created knowledge nodes")
                else:
                    self._create_unresolved_edge(k_node["_key"], name, Edges.REFERS_TO, self._lexical_scope_stack[-1], file_path)
                    logger.info(f"Created unresolved edge[ {k_node['_key']}, {name}]")

        #Righthand side — push once (for the last LHS node) after the loop
        exp_list = ASTUtils.first_node_of_type(node, "expression_list")
        if exp_list is not None and k_node is not None:
            self._context_stack.push_context(k_node["_key"], Context.ASSIGNMENT)
            try:
                [self.build(exp, file_path) for exp in exp_list.children]
            finally:
                self._context_stack.pop_context()
            return k_node, True

        return k_node, False

    def _handle_call(self, node, file_path: str) -> Tuple[Dict | None, bool]:
        callee = node.children[0]
        is_method_call = callee.type in ("dot_index_expression", "bracket_index_expression")

        if is_method_call:
            base = callee.children[0]
            name = ASTUtils.get_text(base) if base.type == "identifier" else (
                ASTUtils.get_text(ASTUtils.first_node_of_type(callee, "identifier")) or ""
            )
        else:
            name = ASTUtils.get_text(ASTUtils.first_node_of_type(node, "identifier"))

        if name == 'require':
            # require() is handled at the variable_declaration level by _node_variable.
            # No call-site knowledge node is created for the import mechanism itself.
            return None, True

        k_node = self._create_knowledge_node(node, file_path, properties={"name": name})

        if is_method_call:
            # callee is an index-expression (obj.method or obj[key]); wire it explicitly
            if callee.type == "dot_index_expression":
                callee_k, _ = self._handle_dot_index_expression(callee, file_path)
            else:
                callee_k, _ = self._handle_bracket_index_expression(callee, file_path)
            if callee_k is not None:
                self._create_knowledge_edge(k_node["_key"], callee_k["_key"], Edges.HAS_CALLEE)
        else:
            definition = self._lst.scope_lookup_by_name(self._lexical_scope_stack[-1], name)
            if definition is not None:
                try:
                    found_node_id = self._get_nodeid_from_astid(str(definition.ast_id))
                    self._create_knowledge_edge(found_node_id, k_node["_key"], Edges.DEFINES)
                except KeyError:
                    self._create_unresolved_edge(k_node["_key"], name, Edges.DEFINES, self._lexical_scope_stack[-1], file_path)
                    logger.info(f"Created unresolved edge (ast_id not in map)[{k_node['_key']}, {name}]")
            else:
                self._create_unresolved_edge(k_node["_key"], name, Edges.DEFINES, self._lexical_scope_stack[-1], file_path)
                logger.info(f"Created unresolved edge[{k_node['_key']}, {name}]")

        arguments = ASTUtils.first_node_of_type(node, "arguments")
        if arguments.child_count > 2:  # parentheses count as children
            self._recurse_with_different_context(arguments, file_path, k_node["_key"], Context.ARGUMENTS)

        return k_node, True

    def _handle_control_statement(self, node, file_path: str) -> Tuple[Dict | None, bool]:
        k_node = self._create_knowledge_node(node, file_path, properties= {"kind": node.type})
        self._recurse_with_different_context(node, file_path, k_node["_key"], Context.CONTROL_STATEMENT)

        self._handle_metrics(node, k_node,
                             lambda: ast_metrics.calculate_cyclomatic_complexity_agr(node),
                             lambda: ast_metrics.calculate_halstead_metrics_agr(node),
                             lambda: ast_metrics.calculate_loc_agr(node),
        )
        return k_node, True

    def _handle_block(self, node, file_path: str) -> Tuple[Dict | None, bool]:
        k_node = self._create_knowledge_node(node, file_path)
        con, con_id = self._context_stack.get_context()
        if con in [Context.FUN_DECL, Context.CONTROL_STATEMENT, Context.LOOP]:
            self._create_knowledge_edge(con_id, k_node["_key"], Edges.HAS_BLOCK)
            self._recurse_with_different_context(node, file_path, k_node["_key"], Context.BLOCK)
            return k_node, True
        return k_node, False

    #TODO add to schema
    def _handle_expression_container(self, node, file_path: str) -> Tuple[Dict | None, bool]:
        """Shared handler for exp_list and binary_expression."""
        k_node = self._create_knowledge_node(node, file_path)
        self._recurse_with_different_context(node, file_path, k_node["_key"], Context.EXPRESSION)
        return k_node, True

    def _handle_return(self, node, file_path: str) -> Tuple[Dict | None, bool]:
        k_node = self._create_knowledge_node(node, file_path)
        if self._context_stack.find_in_wider_context([Context.FUN_DECL]) is not None:
            self._recurse_with_different_context(node, file_path, k_node["_key"], Context.RETURN)
            return k_node, True
        return k_node, False

    def _handle_bracket_index_expression(self, node, file_path: str) -> Tuple[Dict | None, bool]:
        """
        bracket_index_expression → base_expr '[' index_expr ']'
        The base_expr is either a plain identifier (t[i])
        BUG: the ast parser incorrectly parses t[][] multiple indexes no way to implement it correctly at this point
        """
        base = node.children[0]
        ident_node = base if base.type == "identifier" else ASTUtils.first_node_of_type(base, "identifier")
        name = ASTUtils.get_text(ident_node) if ident_node is not None else ASTUtils.get_text(node)

        k_node = self._create_knowledge_node(node, file_path,
                                             type="index_expression",
                                             properties={"name": name})

        symbol = self._lst.scope_lookup_by_name(self._lexical_scope_stack[-1], name)
        if symbol is not None:
            try:
                found_node_id = self._get_nodeid_from_astid(str(symbol.ast_id))
                self._create_knowledge_edge(k_node["_key"], found_node_id, Edges.ACCESSES_MEMBER_OF)
            except KeyError:
                logger.error(f"Symbol '{name}' not found in created knowledge nodes")
        else:
            self._create_unresolved_edge(k_node["_key"], name, Edges.ACCESSES_MEMBER_OF,
                                         self._lexical_scope_stack[-1], file_path)
            logger.info(f"Created unresolved edge [{k_node['_key']}, {name}]")

        self._recurse_with_different_context(node, file_path, k_node["_key"], Context.EXPRESSION, 1)

        return k_node, True

    def _handle_dot_index_expression(self, node, file_path: str) -> Tuple[Dict | None, bool]:
        """
        dot_index_expression → base_expr '.' field_name
        """
        base = node.children[0]
        field_name = ASTUtils.get_text(node.children[2])

        if base.type == "identifier":
            base_name = ASTUtils.get_text(base)
        else:
            ident = ASTUtils.first_node_of_type(base, "identifier")
            base_name = ASTUtils.get_text(ident) if ident is not None else ""

        k_node = self._create_knowledge_node(node, file_path, type="index_expression", properties={"name": base_name, "field": field_name})

        symbol = self._lst.scope_lookup_by_name(self._lexical_scope_stack[-1], base_name)
        if symbol is not None:
            try:
                found_node_id = self._get_nodeid_from_astid(str(symbol.ast_id))
                self._create_knowledge_edge(k_node["_key"], found_node_id, Edges.ACCESSES_MEMBER_OF)
            except KeyError:
                logger.error(f"Symbol '{base_name}' not found in created knowledge nodes")
        else:
            self._create_unresolved_edge(k_node["_key"], base_name, Edges.ACCESSES_MEMBER_OF, self._lexical_scope_stack[-1], file_path)
            logger.info(f"Created unresolved edge [{k_node['_key']}, {base_name}]")

        if base.type == "dot_index_expression":
            self.build(base, file_path)

        return k_node, True

    def _handle_table_constructor(self, node, file_path: str) -> Tuple[Dict | None, bool]:
        fields = [c for c in node.children if c.type == "field"]
        positional_idx = 1  # Lua tables are 1-indexed
        field_keys = []
        for f in fields:
            if len(f.children) >= 3 and f.children[1].type == "=":
                field_keys.append(ASTUtils.get_text(f.children[0]))
            else:
                field_keys.append(str(positional_idx))
                positional_idx += 1

        k_node = self._create_knowledge_node(node, file_path,properties={"table_keys": ",".join(field_keys)})
        self._recurse_with_different_context(node, file_path, k_node["_key"], Context.TABLE_CONSTRUCTOR)
        return k_node, True

    def _handle_field(self, node, file_path: str) -> Tuple[Dict | None, bool]:
        value = node.children[2] if (len(node.children) >= 3 and node.children[1].type == "=") else node.children[0]
        self.build(value, file_path)
        return None, True

    def _handle_literal(self, node, file_path: str) -> Tuple[Dict | None, bool]:
        k_node = self._create_knowledge_node(node, file_path, type="literal", properties={"value": ASTUtils.get_text(node), "kind": node.type})
        return k_node, False

    def _handle_loops(self, node, file_path: str) -> Tuple[Dict | None, bool]:
        k_node = self._create_knowledge_node(node, file_path)
        self._recurse_with_different_context(node, file_path, k_node["_key"], Context.LOOP)
        return k_node, True

    def _handle_for_clause(self, node, file_path: str) -> Tuple[Dict | None, bool]:
        k_node = self._create_knowledge_node(node, file_path)

        # finding the iterators of the loop
        identifier = ASTUtils.first_node_of_type(node, "identifier")  # finding the first variable
        while True:
            if identifier is not None:
                name = ASTUtils.get_text(identifier)
                block_node = ASTUtils.first_node_of_type(node.parent, "block")
                symbol = self._lst.scope_lookup_by_name(block_node.id, name)
                if symbol is not None:
                    var_node = self._create_knowledge_node(identifier, file_path, type="local_variable")
                    self._create_knowledge_edge(k_node["_key"], var_node["_key"], Edges.DECLARES)
            if identifier.next_sibling is None or identifier.next_sibling.type != ",":
                break
            else:
                identifier = identifier.next_sibling.next_sibling  # skipping to the next variable


        #FIXME due to incompleteness of tree sitter parsing structure the lua code can't be parsed effectively
        #   the documentation for for_loops is (for var=exp1, exp2, exp3 do ...) the parser gives var = number, ...

        return k_node, True

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def create_relation_if_possible(self, node, file_path: str) -> bool:
        """
        Dispatches to the appropriate handler based on the node's relation type.
        Returns True if the handler already recursed into children.
        """

        handler = self._relation_handlers.get(node.type)
        if handler is None:
            return False
        logger.info(f"\tEntering handler for relation {handler.__name__}")
        k_node, recursive = handler(node, file_path)
        try:
            self._apply_context_edge(k_node)
        except Exception as e:
            logger.error(f"Exception {e} while handling relation of: {k_node}")
            logger.error(f"Status: context stack -- {self._context_stack}")
        return recursive