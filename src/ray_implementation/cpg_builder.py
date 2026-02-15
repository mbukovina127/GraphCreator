from enum import Enum, auto
from typing import Any, Dict, List

from .ast_utils import ASTUtils
from .local_output_builder import LocalOuputBuilder
from .local_symbol_table import SymbolTable

#TODO move context enum
class Context(Enum):
    GLOBAL = auto()
    VAR_DECL = auto()
    EXPRESSION = auto()
    ARGUMENTS = auto() #function calls

class ContextStack():

    def __init__(self):
        self.context_stack: List[Context] = []
        self.context_relevant_node_ids: List[str] = []


    def __eq__(self, other):
        if isinstance(other, Context):
            return self.context_stack[-1] == other
        return False
    def __ne__(self, other: Context):
        if isinstance(other, Context):
            return self.context_stack[-1] != other
        return False

    def push_context(self, ids, context: Context):
        """Push the context from the Context enum onto the stack"""
        self.context_stack.append(context)
        self.context_relevant_node_ids.append(ids)

    def peek_context(self) -> Context:
        return self.context_stack[-1]

    def get_context(self) -> tuple[Context, str]:
        """@returns: context_type and a list of relevant_node_ids"""
        return self.context_stack[-1], self.context_relevant_node_ids[-1]

    def pop_context(self) -> tuple[Context, str]:
        """Pops the stack and @returns: context_type and a list of relevant_node_ids"""
        return self.context_stack.pop(), self.context_relevant_node_ids.pop()



class CPGBuilder:
    """
    Builds the Code Property Graph (CPG) from the AST and Local Symbol Table
    """
    def __init__(self, local_builder: LocalOuputBuilder, lst: SymbolTable):
        self.local_builder = local_builder
        self.lst = lst
        self.scope_stack: List[str] = []
        self.context_stack = ContextStack()
        self.astId_nodeId_map: Dict[str, str] = {} # TODO move this to local builder

        self.knowledge_nodes = self.local_builder.get_collection("knowledge_nodes")
        self.knowledge_edges = self.local_builder.get_collection("knowledge_edges")

        self.n_counter = 0
        self.e_counter = 0

    def gen_id(self, type: str = "node") -> str:
        """
        Unique ID generator
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
    
    def _create_knowledge_node(self, node, file_path: str, add_properties: Dict = "") -> Dict[str, Any]:
        node_id = f"node:{node.type}:{self.gen_id()}"
        a_node = {
            "_key": node_id,
            "symbol_id": node.id,
            "type": node.type,
            "text": ASTUtils.get_text(node),
            "start_byte": node.start_byte,
            "end_byte": node.end_byte,
            "file_path": file_path,
            "properties": add_properties
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

    def _update_knowledge_node(self, node):
        self.knowledge_nodes.insert(node)
        return
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
            if type == 'ident' and self.context_stack != Context.VAR_DECL: # TODO no paramater and argument types / write read differentiation
                k_node = self._create_knowledge_node(node, file_path)
                # if node.parent() == "variable_list": #TODO write/ call properties
                #     pass

                symbol = self.lst.scope_lookup_by_name(self.scope_stack[-1], ASTUtils.get_text(node))
                if symbol is not None:
                    found_node_id = self.astId_nodeId_map[str(symbol.ast_id)]
                    self._create_knowledge_edge(k_node["_key"], found_node_id, "refers_to") # TODO later more edge types with helper functions less hardocded?


            if type == 'exp_list':
                k_node = self._create_knowledge_node(node, file_path)
                self.context_stack.push_context(k_node["_key"], Context.EXPRESSION)
                for exp in node.children:
                    self.build_cpg(exp, file_path)
                self.context_stack.pop_context()
                recursive = True

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
                    self.context_stack.push_context(k_node["_key"], Context.ARGUMENTS)
                    for arg in arguments.children:
                        self.build_cpg(arg, file_path)
                    recursive = True
                    self.context_stack.pop_context()
            #===========================================
            # Context dependant edges
            #===========================================
            if k_node is not None: # meaning a node was created at some point so it needs to be linked to the relevant node
                context, relevant_id = self.context_stack.get_context()
                if context == Context.ARGUMENTS:
                    self._create_knowledge_edge(relevant_id, k_node["_key"], "has_argument") # directional edge
                if context == Context.VAR_DECL:
                    self._create_knowledge_edge(k_node["_key"], relevant_id, "initializes")
                if context == Context.EXPRESSION:
                    self._create_knowledge_edge(relevant_id, k_node["_key"], "contains")


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

            #is the variable initialized property
            if k_node["type"] == "variable_declaration":
                assignment = ASTUtils.first_node_of_type(node, "assignment_statement")
                if assignment is not None:
                    k_node["properties"] = {
                        "initialized": "True"
                    }
                    self._update_knowledge_node(k_node)

                self.context_stack.push_context(k_node["_key"], Context.VAR_DECL)
                for c in node.children:
                    self.build_cpg(c, file_path)
                self.context_stack.pop_context()
                return True

            if k_node["type"] == "block":
                symbol = self.lst.scope_lookup_by_name(self.scope_stack[-1], self.scope_stack[-1])  # TODO test if this finds the correct function or control structure

            if k_node["type"] == "chunk":
                self.context_stack.push_context(k_node["_key"], Context.GLOBAL)
                for c in node.children:
                    self.build_cpg(c, file_path)
                self.context_stack.pop_context()
                return True

        return False

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