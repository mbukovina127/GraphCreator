from typing import Any, Dict, List
from warnings import catch_warnings

from .ast_utils import ASTUtils
from .local_output_builder import LocalOuputBuilder
from .local_symbol_table import SymbolTable
from .util_enums import Context

#TODO move to a different file
class ContextStack:

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

    #FIXME add try block
    def peek_context(self, offset: int = -1) -> Context:
            return self.context_stack[offset]
    #FIXME add try block
    def get_context(self, offset: int = -1) -> tuple[Context, str]:
        """@returns: context_type and a list of relevant_node_ids"""
        return self.context_stack[offset], self.context_relevant_node_ids[offset]

    def pop_context(self) -> tuple[Context, str]:
        """Pops the stack and @returns: context_type and a list of relevant_node_ids"""
        return self.context_stack.pop(), self.context_relevant_node_ids.pop()



class CPGBuilder:
    """
    Builds the Code Property Graph (CPG) from the AST and Local Symbol Table
    """
    def __init__(self, local_builder: LocalOuputBuilder, lst: SymbolTable):
        self.local_builder = local_builder
        self._lst = lst
        self._scope_stack: List[str] = []
        self._context_stack = ContextStack()
        self._astId_nodeId_map: Dict[str, str] = {} # TODO move this to local builder

        self.knowledge_nodes = self.local_builder.get_collection("knowledge_nodes")
        self.knowledge_edges = self.local_builder.get_collection("knowledge_edges")
        self.unresolved_edges: Dict[str, list[Dict]] = {}

        self._n_counter = 0
        self._e_counter = 0

    def gen_id(self, type: str = "node") -> str:
        """
        Unique ID generator
        """
        if type == "node":
            self._n_counter += 1
            return str(self._n_counter)
        else:
            self._e_counter += 1
            return str(self._e_counter)

    def _push_scope(self, s_id: str):
        self._scope_stack.append(s_id)
        return
    
    def _pop_scope(self):
        return self._scope_stack.pop()
    
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
            self._astId_nodeId_map[str(node.id)] = node_id
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

    #TODO move this to symbol table
    def _create_unresolved_edge(self, node_id: str, symbol_name: str, edge_type: str, scope: str, file: str) -> None:
        #the edge has a symbol_name (the one it tried to look up) as one of the ids
        unk_edge = {
            "node_id": node_id,
            "symbol_name": symbol_name,
            "edge_type": edge_type,
            "scope": scope,
            "file": file,
            #maybe need of worker id
        }
        self.unresolved_edges.setdefault(symbol_name, []).append(unk_edge)

    def _update_knowledge_node(self, node):
        self.knowledge_nodes.insert(node)
        return

    def create_relation_if_possible(self, node, file_path: str):
        """
            Creates relation between edges
            Handles context dependent nodes
        """
        k_node = None
        RECURSIVE: bool = False

        type = ASTUtils.is_relation_node(node)
        if type is not None:
            #===========================================
            # knowledge nodes with edge creation
            #===========================================
            # cookie cutter variable identifier
            if type == 'ident' and self._context_stack != Context.VAR_DECL: # TODO no paramater and argument types / write read differentiation
                k_node = self._create_knowledge_node(node, file_path)
                # if node.parent() == "variable_list": #TODO write/ call properties
                #     pass
                name = ASTUtils.get_text(node)
                symbol = self._lst.scope_lookup_by_name(self._scope_stack[-1], name)
                if symbol is not None:
                    found_node_id = self._astId_nodeId_map[str(symbol.ast_id)]
                    self._create_knowledge_edge(k_node["_key"], found_node_id, "refers_to") # TODO later more edge types with helper functions less hardocded?
                elif self._context_stack:
                    # self._create_unresolved_edge(k_node["_key"], name, "refers_to", self._scope_stack[-1], file_path)
                    pass

            if type == 'assign' and self._context_stack.peek_context() != Context.VAR_DECL:
                #assignment all identifiers have write property and expressions are assigned to the identifier
                #get the identifiers
                var_list = ASTUtils.first_node_of_type(node, "variable_list")
                for i in var_list.children:
                    if i.type == "identifier":
                        k_node = self._create_knowledge_node(i, file_path, {"write": "True"})
                        self._context_stack.push_context(k_node["_key"], Context.ASSIGNMENT) #FIXME for now only one variable
                        break

                # move to the expression
                exp_list = ASTUtils.first_node_of_type(node, "expression_list")
                if exp_list is not None:
                    if self._context_stack.peek_context() == Context.ASSIGNMENT:
                        for exp in exp_list.children:
                            self.build_cpg(exp, file_path)
                        self._context_stack.pop_context()
                        RECURSIVE = True
                    else:
                        raise ValueError("Something happened while processing an assignment :(")
            # recursive function call
            if type == 'call':
                k_node = self._create_knowledge_node(node, file_path)

                name = ASTUtils.get_text(ASTUtils.first_node_of_type(node, "identifier"))
                definition = self._lst.scope_lookup_by_name(self._scope_stack[-1], name)
                if definition is not None:
                    found_node_id = self._astId_nodeId_map[str(definition.ast_id)]
                    self._create_knowledge_edge(found_node_id, k_node["_key"], "defines")
                else:
                    self._create_unresolved_edge(k_node["_key"], name, "defines", self._scope_stack[-1],
                                                 file_path)
                    pass

                arguments = ASTUtils.first_node_of_type(node, "arguments")
                if arguments.child_count > 2:  # parenthesis count as children
                    self._context_stack.push_context(k_node["_key"], Context.ARGUMENTS)
                    for arg in arguments.children:
                        self.build_cpg(arg, file_path)
                    RECURSIVE = True
                    self._context_stack.pop_context()

            if type == 'block':
                k_node = self._create_knowledge_node(node, file_path)
                #find the function with context
                con, id = self._context_stack.get_context()
                if con == Context.FUN_DECL: # TODO for now just a function but it could also apply to control statements
                    self._create_knowledge_edge(k_node["_key"], id, "has_block")
                    self._context_stack.push_context(k_node["_key"], Context.BLOCK)
                    for c in node.children:
                        self.build_cpg(c, file_path)
                    self._context_stack.pop_context()
                    RECURSIVE = True

            # ===========================================
            # knowledge nodes with context creation
            # ===========================================
            if type == 'exp_list':
                k_node = self._create_knowledge_node(node, file_path)
                self._context_stack.push_context(k_node["_key"], Context.EXPRESSION)
                for exp in node.children:
                    self.build_cpg(exp, file_path)
                self._context_stack.pop_context()
                RECURSIVE = True

            if type == 'return':
                k_node = self._create_knowledge_node(node, file_path)
                if self._context_stack.peek_context() == Context.BLOCK and self._context_stack.peek_context(-2) == Context.FUN_DECL:
                    # FIXME HORRIBLE TERRIBLE PLEASE FIX
                    self._context_stack.push_context(self._context_stack.get_context(-2)[1] + "$" + k_node["_key"], Context.RETURN) # !important adds to the context stack the node of the function call
                    for c in node.children:
                        self.build_cpg(c, file_path)
                    self._context_stack.pop_context()
                    RECURSIVE = True
                else:
                    raise ValueError("Something happened while processing a return :(")

            #===========================================
            # Context dependant edges
            #===========================================
            if k_node is not None: # meaning a node was created at some point so it needs to be linked to the relevant node
                context, relevant_id = self._context_stack.get_context()
                if context == Context.ARGUMENTS:
                    self._create_knowledge_edge(relevant_id, k_node["_key"], "has_argument") # directional edge
                if context == Context.VAR_DECL:
                    self._create_knowledge_edge(k_node["_key"], relevant_id, "initializes")
                if context == Context.EXPRESSION:
                    self._create_knowledge_edge(relevant_id, k_node["_key"], "contains")
                if context == Context.ASSIGNMENT:
                    self._create_knowledge_edge(k_node["_key"], relevant_id, "assigns_to")
                if context == Context.RETURN:
                    ids = self._context_stack.get_context()[1] # getting the node of function declaration
                    ids = ids.split("$")
                    self._create_knowledge_edge(ids[0], k_node["_key"], "returns") #function returns
                    self._create_knowledge_edge(ids[1], k_node["_key"], "contains") #return_statement contains
                if context == Context.PARAMETERS:
                    self._create_knowledge_edge(relevant_id, k_node["_key"], "has_parameters")
                if context == Context.BLOCK:
                    self._create_knowledge_edge(relevant_id, k_node["_key"], "contains")


        return RECURSIVE

    def create_knowledge_node_if_possible(self, node, file_path: str) -> bool:
        """
            ONLY creates nodes that are in symbol table ~mostly~
        """
        if ASTUtils.is_knowledge_node(node):
            k_node = self._create_knowledge_node(node, file_path)
            # adding contains/implements edges for files
            # if k_node["type"] in ["function_declaration", "variable_declaration"]:
            #     root_chunk_id = self._astId_nodeId_map.get(str(self._scope_stack[0]))
            #     if root_chunk_id is not None:
            #         self._create_knowledge_edge(root_chunk_id, k_node["_key"],"contains")

            #is the variable initialized property
            if k_node["type"] == "variable_declaration":
                assignment = ASTUtils.first_node_of_type(node, "assignment_statement")
                if assignment is not None:
                    k_node["properties"] = {
                        "initialized": "True"
                    }
                    self._update_knowledge_node(k_node)

                # TODO local / global
                if self._context_stack == Context.GLOBAL or self._context_stack == Context.BLOCK:
                    r_id = self._context_stack.get_context()[1]
                    if r_id is not None:
                        self._create_knowledge_edge(r_id, k_node["_key"], "contains")


                self._context_stack.push_context(k_node["_key"], Context.VAR_DECL)
                for c in node.children:
                    self.build_cpg(c, file_path)
                self._context_stack.pop_context()
                return True

            if k_node["type"] == "function_declaration":
                #TODO add properties {local, end...}

                # TODO local / global
                if self._context_stack == Context.GLOBAL or self._context_stack == Context.BLOCK:
                    r_id = self._context_stack.get_context()[1]
                    if r_id is not None:
                        self._create_knowledge_edge(r_id, k_node["_key"], "contains")

                # asssinging paramters
                parameters = ASTUtils.first_node_of_type(node, "parameters")
                if parameters is None:
                    raise ValueError("Something happened while processing a function :( (Couldnt find a paramters field)")
                self._context_stack.push_context(k_node["_key"], Context.PARAMETERS)
                for param in parameters.children:
                    self.build_cpg(param, file_path)
                self._context_stack.pop_context()

                # assigning blocks
                block = ASTUtils.first_node_of_type(node, "block")
                if block is None:
                    raise ValueError("Something happened while processing a function :( (Couldnt find a block)")
                self._context_stack.push_context(k_node["_key"], Context.FUN_DECL)
                self.build_cpg(block, file_path) #I donno
                self._context_stack.pop_context()
                return True

            # FIXME not compatible
            # if k_node["type"] == "block":
            #     self._context_stack.push_context(k_node["_key"], Context.BLOCK)
            #     for c in node.children:
            #         self.build_cpg(c, file_path)
            #     self._context_stack.pop_context()
            #     return True

            if k_node["type"] == "chunk":
                self._context_stack.push_context(k_node["_key"], Context.GLOBAL)
                for c in node.children:
                    self.build_cpg(c, file_path)
                self._context_stack.pop_context()
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