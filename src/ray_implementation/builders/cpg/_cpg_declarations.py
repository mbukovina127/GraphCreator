import logging
from typing import Any, Dict

from code_analyzer import ast_metrics
from ray_implementation.ast_utils import ASTUtils
from ray_implementation.dto.edges import Edges
from ray_implementation.structures import Context
from ._cpg_relations import CPGRelationsMixin

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CPGDeclarationsMixin(CPGRelationsMixin):
    """
    Handles declaration nodes: functions, variables, chunks, modules.
    """

    def _apply_environment_edge(self, k_node: Dict[str, Any] | None):
        """Wires a declaration node to either its lexical scope or the global environment."""
        edge_type = {
            "local_function_definition":  (Edges.DEFINES,  True),
            "global_function_definition": (Edges.DEFINES,  False),
            "local_variable_declaration": (Edges.DECLARES, True),
            "global_variable_declaration":(Edges.DECLARES, False),
            "module":                     (Edges.DEFINES,  True),
            "module_import":              (Edges.IMPORTS,  True),
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
                    Edges.CONTAINS,
                )
            else:
                self._create_knowledge_edge(self._environment, k_node["_key"], relation)

    def _init_declaration_handlers(self):
        self._declaration_handlers = {
            "variable_declaration": self._node_variable,
            "assignment_statement": self._node_variable,  # assignment_statement = possible variable declaration
            "function_declaration": self._node_function,
            "chunk":                self._node_chunk,
            "function_call":        self._node_module,    # function_call = possible module definition
        }

    def _node_variable(self, node, file_path):
        if self._context_stack == Context.VAR_DECL:
            return False
        var = ASTUtils.first_node_of_type(node, "variable_list")
        identifiers = ASTUtils.nodes_of_type(var, "identifier")

        def _handle_variable_declaration(symbol, root):
            k_type = symbol.kind + "_declaration"
            k_properties = {
                "name": name
            }
            assignment = None
            if k_type == "local_variable_declaration":
                assignment = ASTUtils.first_node_of_type(root, "assignment_statement")
                if assignment is not None:
                    k_properties["initialized"] = "True"
                    if ASTUtils.first_node_of_type(assignment, "table_constructor") is not None:
                        k_properties["is_table"] = "True"

            k_node = self._create_knowledge_node(root, file_path, k_type, properties=k_properties)

            self._apply_environment_edge(k_node)

            # process only the expression list skipping the assignment Force None error as
            if assignment is not None:
                self._recurse_with_different_context(assignment, file_path, k_node["_key"], Context.VAR_DECL) #
            return True

        handled = False
        for ident in identifiers:
            name = ASTUtils.get_text(ident)
            symbol = self._lst.scope_lookup_by_name(self._lexical_scope_stack[-1], name)
            if symbol is None:
                continue

            if symbol.kind in ["local_variable", "global_variable"] and symbol.ast_id == node.id:
                _handle_variable_declaration(symbol, node)
                handled = True
                continue

            if symbol.kind in ["local_module_representation", "module_representation"]:
                module_path = self._lst.imports.get(name)  # e.g. "math.utils"
                k_node = self._create_knowledge_node(
                    node, file_path,
                    type="module_import",
                    properties={"name": name, "module_path": module_path or ""}
                )
                self._apply_environment_edge(k_node)
                handled = True
                # The "imports" edge to the actual module node is added later by GraphCollector

        return handled

    def _node_function(self, node, file_path):
        name = ASTUtils.get_text(ASTUtils.first_node_of_type(node, "identifier"))
        symbol = self._lst.scope_lookup_by_name(self._lexical_scope_stack[-1], name)
        if symbol is None:
            return False

        k_type = symbol.kind + "_definition"
        properties = { "name": name }
        k_node = self._create_knowledge_node(node, file_path, k_type, properties=properties)

        self._apply_environment_edge(k_node)

        parameters = ASTUtils.first_node_of_type(node, "parameters")
        if parameters is None:
            logger.error(f"Function node(name={name}, file={file_path}) has no parameters -- node: {node}")
        else:
            self._recurse_with_different_context(parameters, file_path, k_node["_key"], Context.PARAMETERS)

        block = ASTUtils.first_node_of_type(node, "block")
        if block is None:
            logger.error(f"Function node (name={name}, file={file_path}) has no block -- node: {node}")

        self._context_stack.push_context(k_node["_key"], Context.FUN_DECL)
        self.build(block, file_path)
        self._context_stack.pop_context()

        # handling metrics
        self._handle_metrics(node, k_node,
            lambda: ast_metrics.calculate_halstead_metrics_agr(node),
            lambda: ast_metrics.calculate_loc_agr(node)
        )
        return True

    def _node_chunk(self, node, file_path):
        k_node = self._create_knowledge_node(node, file_path)
        self._recurse_with_different_context(node, file_path, k_node["_key"], Context.CHUNK)

        # handling metrics
        self._handle_metrics(node, k_node,
            lambda: ast_metrics.calculate_halstead_metrics_agr(node),
            lambda: ast_metrics.calculate_loc_agr(node)
        )
        return True

    def _node_module(self, node, file_path):
        ident = ASTUtils.get_text(ASTUtils.first_node_of_type(node, "identifier"))
        if ident != "module":
            return False

        sym = self._lst.scope_lookup_by_astId(self._lexical_scope_stack[-1], node.id)
        if sym is None:
            logger.error(f"Couldn't find a module[{node}] in local symbol table")
            return False

        k_properties = {"module_name": sym.name}
        k_node = self._create_knowledge_node(node, file_path, type="module", properties=k_properties)
        self._insert_knowledge_node(node, k_node)

        self._environment = k_node["_key"]
        self._apply_environment_edge(k_node)
        return True  # prevents function_call node from being created

    def create_knowledge_node_if_possible(self, node, file_path: str) -> bool:
        """
        Creates nodes that correspond to declarations in the symbol table.
        Returns True if the node was handled (children already walked).
        """
        handler = self._declaration_handlers.get(node.type)
        if handler is None:
            return False
        logger.info(f"\tEntering handler for declaration {handler.__name__}")
        return handler(node, file_path)
