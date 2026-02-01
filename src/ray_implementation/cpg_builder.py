from typing import Any, Dict, List

from .ast_utils import ASTUtils
from .local_output_builder import LocalOuputBuilder
from .local_symbol_table import SymbolTable, Scope


class CPGBuilder:
    """
    Builds the Code Property Graph (CPG) from the AST and Local Symbol Table
    """
    def __init__(self, local_builder: LocalOuputBuilder, lst: SymbolTable):
        self.local_builder = local_builder
        self.lst = lst
        self.scope_stack: List[str] = []
        self.astId_nodeId_map: Dict[str, str] = {}

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
            "text": node.text.decode("utf-8") if isinstance(node.text, bytes) else node.text,
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
    
    def build_cpg(self, node, file_path: str):
        """
        Build the CPG from the AST node and local symbol table
        """
        k_node = None 

        # pushes scope stack if needed
        if ASTUtils.is_different_scope_node(node):
            self._push_scope(node.id)


        if ASTUtils.is_knowledge_node(node):
            k_node = self._create_knowledge_node(node, file_path)
            if k_node["type"] in ["function_declaration", "variable_declaration"]:
                root_chunk = self.lst.scope_lookup(self.scope_stack[-1], self.scope_stack[0]) # FIXME very assignment to file/chunk
                if root_chunk is not None:
                    root_node_id = self.astId_nodeId_map.get(str(root_chunk.ast_id))
                    if root_node_id is not None:
                        self._create_knowledge_edge(root_node_id, k_node["_key"], "contains") #TODO temporary "contains" relation type

            if k_node["type"] == "block":
                self.lst.scope_lookup(self.scope_stack[-1], self.scope_stack[-1]) #TODO test if this finds the correct function or control structure
                pass # TODO: somehow map to to function or control structure decleration
        
        # adding to local symbol table
        if ASTUtils.is_reference_node(node):
            k_node = self._create_knowledge_node(node, file_path)

            symbol = self.lst.scope_lookup(self.scope_stack[-1], node.text.decode("utf-8") if isinstance(node.text, bytes) else node.text)
            
            if symbol is not None and k_node is not None:
                node_id = self.astId_nodeId_map[str(symbol.ast_id)]
                self._create_knowledge_edge(node_id, k_node["_key"], "declares") # TODO declares for now, later more edge types with helper functions

        # walk
        for child in node.children:
            self.build_cpg(child, file_path)

        # pops scope stack
        if ASTUtils.is_different_scope_node(node):
            self._pop_scope()
            pass
