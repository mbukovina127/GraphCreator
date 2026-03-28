from typing import Any, Dict

from ray_implementation.ast_utils import ASTUtils
from ray_implementation.structures import Context
from ._cpg_relations import CPGRelationsMixin


class CPGDeclarationsMixin(CPGRelationsMixin):
    """
    Handles declaration nodes: functions, variables, chunks, modules.
    """

    def _apply_environment_edge(self, k_node: Dict[str, Any] | None):
        """Wires a declaration node to either its lexical scope or the global environment."""
        edge_type = {
            "local_function_definition":  ("defines",  True),
            "global_function_definition": ("defines",  False),
            "local_variable_declaration": ("declares", True),
            "global_variable_declaration":("declares", False),
            "module":                     ("defines",  True),
        }.get(k_node["type"])

        if edge_type is None:
            return

        relation, is_local = edge_type
        if is_local:
            scope_node_id = self._astId_nodeId_map[str(self._lexical_scope_stack[-1])]
            self._create_knowledge_edge(scope_node_id, k_node["_key"], relation)
        else:
            if self._environment == "_G":
                self._create_knowledge_edge("_G", k_node["_key"], relation)
                self._create_knowledge_edge(
                    self._astId_nodeId_map[str(self._lexical_scope_stack[-1])],
                    k_node["_key"],
                    "contains",  # TODO: confirm convention
                )
            else:
                self._create_knowledge_edge(self._environment, k_node["_key"], relation)

    def _init_declaration_handlers(self):
        self._declaration_handlers = {
            "variable_declaration": self._node_variable,
            "possible_variable": self._node_variable,
            "function_declaration": self._node_function,
            "if_statement": self._node_if_statement,
            "chunk": self._node_chunk,
            "module": self._node_module,
        }

    def _node_variable(self, node, file_path, k_properties):
        try:
            var = ASTUtils.first_node_of_type(node, "variable_list")
            identifiers = ASTUtils.nodes_of_type(var, "identifier")
        except Exception:
            return False  # TODO: log

        for ident in identifiers:
            name = ASTUtils.get_text(ident)
            symbol = self._lst.scope_lookup_by_name(self._lexical_scope_stack[-1], name)
            if symbol is None:
                continue
            if symbol.kind not in ["local_variable", "global_variable"] or symbol.ast_id != node.id:
                continue

            k_type = symbol.kind + "_declaration"
            k_properties["identifier"] = name

            if k_type == "local_variable_declaration":
                assignment = ASTUtils.first_node_of_type(node, "assignment_statement")
                if assignment is not None:
                    k_properties["initialized"] = "True"

            k_node = self._create_knowledge_node_custom(node, k_type, file_path=file_path, properties=k_properties)
            self._insert_knowledge_node(node, k_node)

            _apply_environment_edge = self._apply_environment_edge
            _apply_environment_edge(k_node)

            self._context_stack.push_context(k_node["_key"], Context.VAR_DECL)
            for c in node.children:
                self.build(c, file_path)
            self._context_stack.pop_context()
            return True

    def _node_function(self, node, file_path, k_properties):
        try:
            name = ASTUtils.get_text(ASTUtils.first_node_of_type(node, "identifier"))
            symbol = self._lst.scope_lookup_by_name(self._lexical_scope_stack[-1], name)
            if symbol is None:
                return False
        except Exception:
            return False

        k_type = symbol.kind + "_definition"
        k_node = self._create_knowledge_node_custom(node, type=k_type, file_path=file_path)
        self._insert_knowledge_node(node, k_node)

        self._apply_environment_edge(k_node)

        parameters = ASTUtils.first_node_of_type(node, "parameters")
        if parameters is None:
            raise ValueError("Something happened while processing a function :( (Couldn't find a parameters field)")
        self._context_stack.push_context(k_node["_key"], Context.PARAMETERS)
        for param in parameters.children:
            self.build(param, file_path)
        self._context_stack.pop_context()

        block = ASTUtils.first_node_of_type(node, "block")
        if block is None:
            raise ValueError("Something happened while processing a function :( (Couldn't find a block)")
        self._context_stack.push_context(k_node["_key"], Context.FUN_DECL)
        self.build(block, file_path)
        self._context_stack.pop_context()
        return True

    def _node_if_statement(self, node, file_path, k_properties):
        k_node = self._create_knowledge_node(node, file_path)
        self._context_stack.push_context(k_node["_key"], Context.IF_STATEMENT)
        for c in node.children:
            self.build(c, file_path)
        self._context_stack.pop_context()
        return True

    def _node_chunk(self, node, file_path, k_properties):
        k_node = self._create_knowledge_node(node, file_path)
        self._context_stack.push_context(k_node["_key"], Context.CHUNK)
        for c in node.children:
            self.build(c, file_path)
        self._context_stack.pop_context()
        return True

    def _node_module(self, node, file_path, k_properties):
        ident = ASTUtils.get_text(ASTUtils.first_node_of_type(node, "identifier"))
        if ident != "module":
            return False

        sym = self._lst.scope_lookup_by_astId(self._lexical_scope_stack[-1], node.id)
        if sym is None:
            raise IndexError(
                "Something happened while processing a module :( "
                "(Couldn't find a module in local symbol table)"
            )

        k_properties = {"module_name": sym.name}
        k_node = self._create_knowledge_node_custom(node, "module", file_path, properties=k_properties)
        self._insert_knowledge_node(node, k_node)

        self._environment = k_node["_key"]
        self._apply_environment_edge(k_node)
        return True  # prevents function_call node from being created

    def create_knowledge_node_if_possible(self, node, file_path: str) -> bool:
        """
        Creates nodes that correspond to declarations in the symbol table.
        Returns True if the node was handled (children already walked).
        """
        k_type = ASTUtils.is_declaration_node(node)
        if k_type is None:
            return False

        k_properties = {}

        handler = self._declaration_handlers.get(k_type)
        if handler is None:
            return False
        return handler(node, file_path, k_properties)
