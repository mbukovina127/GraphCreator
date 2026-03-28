from ray_implementation.builders.local_output_builder import LocalOutputBuilder
from ray_implementation.structures import SymbolTable
from ray_implementation.ast_utils import ASTUtils
from ._cpg_declarations import CPGDeclarationsMixin


class CPGBuilder(CPGDeclarationsMixin):
    """
    Orchestrates CPG construction by walking the AST.
    All implementation lives in the mixins:
      - _cpg_base.py         → node/edge creation, ID gen, scope stack
      - _cpg_relations.py    → relation handlers (calls, assignments, blocks …)
      - _cpg_declarations.py → declaration handlers (functions, variables, chunks …)
    """

    def __init__(self, local_builder: LocalOutputBuilder, lst: SymbolTable, file_path: str):
        super().__init__(local_builder, lst, file_path)
        self._init_relation_handlers()
        self._init_declaration_handlers()

    def build(self, node, file_path: str):
        """
        Recursively builds the CPG from an AST node.
        - Declaration nodes are handled by create_knowledge_node_if_possible
        - Relation nodes are handled by create_relation_if_possible
        - Everything else is walked depth-first
        """
        pushed = False
        if ASTUtils.is_different_scope_node(node):
            self._push_scope(node.id)
            pushed = True

        try:
            if self.create_knowledge_node_if_possible(node, file_path):
                return

            if self.create_relation_if_possible(node, file_path):
                return

            for child in node.children:
                self.build(child, file_path)
        finally:
            if pushed:
                self._pop_scope()