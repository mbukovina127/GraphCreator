from typing import Any, Dict, List

from .ast_utils import ASTUtils
from .local_output_builder import LocalOuputBuilder
from .local_symbol_table import SymbolTable


class CPGBuilder:
    """
    Builds the Code Property Graph (CPG) from the AST and Local Symbol Table
    """
    def __init__(self, local_builder: LocalOuputBuilder, lst: SymbolTable):
        self.local_builder = local_builder
        self.lst = lst
        self.scope_stack: List[str] = []
        self.context_stack: List[str] = ["global"] # TODO replace with enum and repleca initialization
        self.context_relevant_node_id: List[str] = [""]
        self.astId_nodeId_map: Dict[str, str] = {} # TODO move this to local builder

        self.knowledge_nodes = self.local_builder.get_collection("knowledge_nodes")
        self.knowledge_edges = self.local_builder.get_collection("knowledge_edges")

        self.n_counter = 0
        self.e_counter = 0

    def gen_id(self, type: str = "node") -> str:
        """
        ArangoDB compatible unique ID generator
        """
        if type == "node":
            self.n_counter += 1
            return str(self.n_counter)
        else:
            self.e_counter += 1
            return str(self.e_counter)

    def _push_scope(self, s_id: str):
        self.scope_stack.append(s_id)
        return
    
    def _pop_scope(self):
        return self.scope_stack.pop()
    
    def _create_knowledge_node(self, node, file_path: str) -> Dict[str, Any]:
        node_id = f"knowledge_node:{self.gen_id()}"
        a_node = {
            "_key": node_id,
            "symbol_id": node.id,
            "type": node.type,
            "text": ASTUtils.get_text(node),
            "start_byte": node.start_byte,
            "end_byte": node.end_byte,
            "file_path": file_path,
        }
        try:
            self.knowledge_nodes.insert(a_node)
            self.astId_nodeId_map[str(node.id)] = node_id
        except Exception as e:
            return {}
             # TODO: logging

        return a_node

    def _create_knowledge_edge(self, from_node_id: str, to_node_id: str, edge_type: str) -> Dict[str, Any]:
        edge_id = f"knowledge_edge:{self.gen_id('edge')}"
        edge = {
            "_key": edge_id,
            "_from": from_node_id,
            "_to": to_node_id,
            "relation": edge_type,
        }
        self.knowledge_edges.insert(edge)
        return edge

    def create_relation_if_possible(self, node, file_path: str):
        """
            Creates relation between edges
            Handles context dependent nodes
        """
        k_node = None
        recursive: bool = False


        type = ASTUtils.is_relation_node(node)
        if type is not None:
            # cookie cutter variable identifier
            if type == 'ident': # TODO no paramater and argument types
                k_node = self._create_knowledge_node(node, file_path)

                symbol = self.lst.scope_lookup_by_name(self.scope_stack[-1], ASTUtils.get_text(node))
                if symbol is not None:
                    found_node_id = self.astId_nodeId_map[str(symbol.ast_id)]
                    self._create_knowledge_edge(k_node["_key"], found_node_id, "refers_to") # TODO later more edge types with helper functions less hardocded?

            #recursive function call
            if type == 'call':
                k_node = self._create_knowledge_node(node, file_path)

                name = ASTUtils.get_text(ASTUtils.first_node_of_type(node, "identifier"))
                definition = self.lst.scope_lookup_by_name(self.scope_stack[-1], name)
                if definition is not None:
                    found_node_id = self.astId_nodeId_map[str(definition.ast_id)]
                    self._create_knowledge_edge(found_node_id, k_node["_key"], "defines")
                else:
                    # TODO unresolved edge
                    pass

                arguments = ASTUtils.first_node_of_type(node, "arguments")
                if arguments.child_count > 2: # parenthesis count as children
                    self.context_stack.append('arguments')
                    self.context_relevant_node_id.append(k_node["_key"]) # link to the function call
                    for arg in arguments.children:
                        self.build_cpg(arg, file_path)
                    recursive = True
                    self.context_stack.pop()
                    self.context_relevant_node_id.pop()

            #===========================================
            # Context dependant edges
            #===========================================
            if k_node is not None: # meaning a node was created at some point so it needs to be linked to the relevant node
                if self.context_stack[-1] == 'arguments':
                    relevant_id = self.context_relevant_node_id[-1]
                    self._create_knowledge_edge(relevant_id, k_node["_key"], "has_argument") # directional edge


            if recursive: # doesn't feel good
                return True
        return False

    def create_knowledge_node_if_possible(self, node, file_path: str) -> bool:
        """
            ONLY creates nodes that are in symbol table ~mostly~
        """
        if ASTUtils.is_knowledge_node(node):
            k_node = self._create_knowledge_node(node, file_path)
            # adding contains/implements edges for files
            if k_node["type"] in ["function_declaration", "variable_declaration"]:
                root_chunk_id = self.astId_nodeId_map.get(str(self.scope_stack[0]))  # FIXME hardocoded
                if root_chunk_id is not None:
                    self._create_knowledge_edge(root_chunk_id, k_node["_key"],"contains")  # TODO temporary "contains" relation type

            if k_node["type"] == "block":
                symbol = self.lst.scope_lookup_by_name(self.scope_stack[-1], self.scope_stack[-1])  # TODO test if this finds the correct function or control structure


    def build_cpg(self, node, file_path: str):
        """
        Build the CPG from the AST node and local symbol table
        """


        # pushes scope stack if needed
        if ASTUtils.is_different_scope_node(node):
            self._push_scope(node.id)

        if self.create_knowledge_node_if_possible(node, file_path):
            return

        
        # adding reference edges and nodes
        if self.create_relation_if_possible(node, file_path):
            return

        # walk
        for child in node.children:
            self.build_cpg(child, file_path)

        # pops scope stack
        if ASTUtils.is_different_scope_node(node):
            self._pop_scope()
            pass