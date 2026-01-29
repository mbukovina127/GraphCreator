"""
GraphQueries - Builds knowledge graph from AST using in-memory operations.

Adapted from the original db_queries.py to work with GraphOutputBuilder
instead of executing AQL queries against ArangoDB.

The logic remains the same - we traverse the AST graph and build
a knowledge graph with semantic relationships.
"""

from typing import Dict, List, Any, Optional, Set
from .output_builder import GraphOutputBuilder


class GraphQueries:
    """
    Builds knowledge graph from AST data stored in GraphOutputBuilder.
    Replaces AQL queries with Python-based graph traversal.
    """
    
    def __init__(self, graph_builder: GraphOutputBuilder):
        self.gb = graph_builder
        
        self.control_statements = {
            "if_statement", "else_statement", "while_statement", 
            "for_statement", "repeat_statement", "do_statement"
        }

    # =========================================================================
    # Helper methods for graph traversal
    # =========================================================================
    
    def _get_node(self, key: str, collection: str = "nodes") -> Optional[Dict[str, Any]]:
        """Get a node by key from the specified collection"""
        return self.gb.get_node(collection, key)
    
    def _get_children(self, parent_key: str, collection: str = "nodes", 
                      relation: Optional[str] = None, 
                      node_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get children of a node, optionally filtered by relation and type"""
        children = self.gb.get_children(collection, parent_key, relation)
        if node_type:
            children = [c for c in children if c.get("type") == node_type]
        return children
    
    def _get_nodes_by_type(self, node_type: str, collection: str = "nodes") -> List[Dict[str, Any]]:
        """Get all nodes of a specific type"""
        return self.gb.get_nodes_by_type(collection, node_type)
    
    def _insert_knowledge_node(self, node: Dict[str, Any]):
        """Insert a node into knowledge_nodes collection"""
        kn = self.gb.get_collection("knowledge_nodes")
        kn.insert(node)
    
    def _insert_knowledge_edge(self, from_key: str, to_key: str, relation: str):
        """Insert an edge into knowledge_edges collection"""
        ke = self.gb.get_collection("knowledge_edges")
        ke.insert({
            "_from": f"knowledge_nodes/{from_key}",
            "_to": f"knowledge_nodes/{to_key}",
            "relation": relation
        })
    
    def _traverse_ast(self, start_key: str, max_depth: int = 10, 
                      stop_at_types: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
        """
        Traverse AST from a starting node up to max_depth.
        Optionally stop traversal when encountering certain node types.
        """
        visited = set()
        results = []
        
        def traverse(key: str, depth: int, path: List[str]):
            if depth > max_depth or key in visited:
                return
            visited.add(key)
            
            node = self._get_node(key)
            if not node:
                return
            
            # Check if we should stop at this type
            if stop_at_types and node.get("type") in stop_at_types:
                if depth > 0:  # Don't stop at the start node
                    return
            
            results.append({"node": node, "depth": depth, "path": path.copy()})
            
            # Get children and continue traversal
            children = self._get_children(key)
            for child in children:
                child_key = child.get("_key")
                if child_key:
                    traverse(child_key, depth + 1, path + [key])
        
        traverse(start_key, 0, [])
        return results

    # =========================================================================
    # Knowledge Graph Building Methods
    # =========================================================================
    
    def get_start_node(self):
        """Copy the root node (first node) to knowledge graph"""
        print("Getting start node...")
        start_node = self._get_node("1")
        if not start_node:
            return
        
        if start_node.get("type") == "chunk":
            doc = {
                "_key": start_node["_key"],
                "type": start_node["type"],
                "text": start_node.get("text", ""),
                "start_byte": start_node.get("start_byte", 0),
                "end_byte": start_node.get("end_byte", 0)
            }
        else:
            doc = {
                "_key": start_node["_key"],
                "type": start_node["type"],
                "text": start_node.get("name", ""),
                "path": start_node.get("path", "")
            }
        
        self._insert_knowledge_node(doc)
        
        if start_node.get("type") in ("file", "dir"):
            self.copy_file_struct(start_node["_key"])

    def copy_file_struct(self, node_id: str):
        """Recursively copy file structure to knowledge graph"""
        print(f"Copying file structure from node {node_id}...")
        
        children = self._get_children(node_id)
        
        for child in children:
            child_type = child.get("type")
            
            if child_type in ("file", "dir"):
                doc = {
                    "_key": child["_key"],
                    "type": child_type,
                    "text": child.get("name", ""),
                    "path": child.get("path", "")
                }
            elif child_type == "chunk":
                doc = {
                    "_key": child["_key"],
                    "type": "chunk",
                    "text": child.get("text", ""),
                    "start_byte": child.get("start_byte", 0),
                    "end_byte": child.get("end_byte", 0)
                }
            else:
                continue
            
            self._insert_knowledge_node(doc)
            self._insert_knowledge_edge(node_id, child["_key"], "contains")
            
            if child_type in ("file", "dir"):
                self.copy_file_struct(child["_key"])

    def find_module_calls(self) -> List[Dict[str, Any]]:
        """Find all module() function calls in the AST"""
        results = []
        
        func_calls = self._get_nodes_by_type("function_call")
        
        for func_call in func_calls:
            # Find identifier child with text "module"
            children = self._get_children(func_call["_key"])
            identifier = next((c for c in children if c.get("type") == "identifier" 
                              and c.get("text") == "module"), None)
            
            if not identifier:
                continue
            
            # Find arguments -> string -> string_content
            args = next((c for c in children if c.get("type") == "arguments"), None)
            if not args:
                continue
            
            args_children = self._get_children(args["_key"])
            string_node = next((c for c in args_children if c.get("type") == "string"), None)
            if not string_node:
                continue
            
            string_children = self._get_children(string_node["_key"])
            content = next((c for c in string_children if c.get("type") == "string_content"), None)
            if not content:
                continue
            
            # Find parent chunk
            inbound = self.gb.get_inbound_edges("edges", func_call["_key"])
            chunk_key = None
            for edge in inbound:
                from_key = edge.get("_from", "").split("/")[-1]
                from_node = self._get_node(from_key)
                if from_node and from_node.get("type") == "chunk":
                    chunk_key = from_key
                    break
            
            if chunk_key:
                results.append({
                    "new_node_id": func_call["_key"],
                    "from_node_id": chunk_key,
                    "text": content.get("text", ""),
                    "start_byte": func_call.get("start_byte", 0),
                    "end_byte": func_call.get("end_byte", 0)
                })
        
        return results

    def insert_module_nodes(self):
        """Insert module nodes into knowledge graph"""
        print("Inserting module nodes...")
        modules = self.find_module_calls()
        self._insert_nodes_and_edges("module", "defines", entities=modules)

    def _insert_nodes_and_edges(self, node_type: str, edge_relation: str, 
                                 entities: List[Dict[str, Any]]):
        """Helper to insert nodes and edges from entity list"""
        for entity in entities:
            new_node_id = entity.get("new_node_id")
            if not new_node_id:
                new_node_id = self.gb.get_next_node_id()
            
            node = {
                "_key": new_node_id,
                "type": node_type,
                "text": entity.get("text", ""),
                "start_byte": entity.get("start_byte", 0),
                "end_byte": entity.get("end_byte", 0)
            }
            
            # Check if node already exists
            existing = self.gb.get_node("knowledge_nodes", new_node_id)
            if not existing:
                self._insert_knowledge_node(node)
            
            from_id = entity.get("from_node_id")
            if from_id:
                self._insert_knowledge_edge(from_id, new_node_id, edge_relation)

    def find_local_var_declarations(self) -> List[Dict[str, Any]]:
        """Find local variable declarations at chunk level"""
        results = []
        
        chunks = self._get_nodes_by_type("chunk")
        
        for chunk in chunks:
            var_decls = self._get_children(chunk["_key"], node_type="variable_declaration")
            
            for var_decl in var_decls:
                vd_children = self._get_children(var_decl["_key"])
                
                # Check for 'local' keyword
                has_local = any(c.get("type") == "local" for c in vd_children)
                if not has_local:
                    continue
                
                # Find assignment_statement
                assign = next((c for c in vd_children if c.get("type") == "assignment_statement"), None)
                if not assign:
                    continue
                
                assign_children = self._get_children(assign["_key"])
                var_list = next((c for c in assign_children if c.get("type") == "variable_list"), None)
                if not var_list:
                    continue
                
                var_list_children = self._get_children(var_list["_key"])
                for identifier in var_list_children:
                    if identifier.get("type") == "identifier":
                        results.append({
                            "new_node_id": identifier["_key"],
                            "from_node_id": chunk["_key"],
                            "text": identifier.get("text", ""),
                            "start_byte": identifier.get("start_byte", 0),
                            "end_byte": identifier.get("end_byte", 0)
                        })
        
        return results

    def insert_local_var_nodes(self):
        """Insert local variable nodes"""
        print("Inserting local variable nodes...")
        local_vars = self.find_local_var_declarations()
        self._insert_nodes_and_edges("local_var", "declares", entities=local_vars)

    def find_required_modules(self) -> List[Dict[str, Any]]:
        """Find require() calls and link them to local variables"""
        results = []
        
        func_calls = self._get_nodes_by_type("function_call")
        
        for func_call in func_calls:
            children = self._get_children(func_call["_key"])
            
            # Check for require identifier
            identifier = next((c for c in children if c.get("type") == "identifier" 
                              and c.get("text") == "require"), None)
            if not identifier:
                continue
            
            # Find module name in arguments
            args = next((c for c in children if c.get("type") == "arguments"), None)
            if not args:
                continue
            
            args_children = self._get_children(args["_key"])
            string_node = next((c for c in args_children if c.get("type") == "string"), None)
            if not string_node:
                continue
            
            string_children = self._get_children(string_node["_key"])
            content = next((c for c in string_children if c.get("type") == "string_content"), None)
            if not content:
                continue
            
            # Traverse up to find the local variable storing this require
            inbound = self.gb.get_inbound_edges("edges", func_call["_key"])
            for edge in inbound:
                from_key = edge.get("_from", "").split("/")[-1]
                from_node = self._get_node(from_key)
                
                if from_node and from_node.get("type") == "expression_list":
                    # Go up to assignment_statement
                    assign_edges = self.gb.get_inbound_edges("edges", from_key)
                    for ae in assign_edges:
                        assign_key = ae.get("_from", "").split("/")[-1]
                        assign_node = self._get_node(assign_key)
                        
                        if assign_node and assign_node.get("type") == "assignment_statement":
                            # Find variable_list -> identifier
                            assign_children = self._get_children(assign_key)
                            var_list = next((c for c in assign_children 
                                           if c.get("type") == "variable_list"), None)
                            if var_list:
                                vl_children = self._get_children(var_list["_key"])
                                local_var = next((c for c in vl_children 
                                                 if c.get("type") == "identifier"), None)
                                if local_var:
                                    results.append({
                                        "func_call_id": func_call["_key"],
                                        "local_var_id": local_var["_key"],
                                        "module_text": content.get("text", ""),
                                        "start_byte": func_call.get("start_byte", 0),
                                        "end_byte": func_call.get("end_byte", 0)
                                    })
        
        return results

    def insert_required_modules(self):
        """Insert required modules and create represents edges"""
        print("Inserting required modules...")
        required = self.find_required_modules()
        
        for module in required:
            # Check if module already exists
            existing = None
            kn_collection = self.gb.get_collection("knowledge_nodes")
            for node in kn_collection.all():
                if node.get("type") == "module" and node.get("text") == module["module_text"]:
                    existing = node["_key"]
                    break
            
            if existing:
                module_id = existing
            else:
                module_id = self.gb.get_next_node_id()
                self._insert_knowledge_node({
                    "_key": module_id,
                    "type": "module",
                    "text": module["module_text"],
                    "start_byte": module["start_byte"],
                    "end_byte": module["end_byte"]
                })
            
            # Create represents edge
            self._insert_knowledge_edge(module["local_var_id"], module_id, "represents")

    def insert_functions(self):
        """Insert function declarations into knowledge graph"""
        print("Inserting functions...")
        
        chunks = self._get_nodes_by_type("chunk")
        
        for chunk in chunks:
            # Check if chunk exists in knowledge graph
            kg_chunk = self.gb.get_node("knowledge_nodes", chunk["_key"])
            if not kg_chunk:
                continue
            
            # Find module for this chunk
            module_node = None
            kg_children = self.gb.get_children("knowledge_nodes", chunk["_key"], "defines")
            for child in kg_children:
                if child.get("type") == "module":
                    module_node = child
                    break
            
            # Find function declarations
            func_decls = self._get_children(chunk["_key"], node_type="function_declaration")
            
            for func in func_decls:
                # Get function name (identifier or dot_index_expression)
                func_children = self._get_children(func["_key"])
                name_node = next((c for c in func_children 
                                 if c.get("type") in ("identifier", "dot_index_expression")), None)
                
                func_text = name_node.get("text", "") if name_node else ""
                
                # Check if it's local
                is_local = any(c.get("type") == "local" for c in func_children)
                
                func_node = {
                    "_key": func["_key"],
                    "type": "local_function" if is_local else "function",
                    "text": func_text,
                    "start_byte": func.get("start_byte", 0),
                    "end_byte": func.get("end_byte", 0)
                }
                
                self._insert_knowledge_node(func_node)
                
                # Link to module or chunk
                target = module_node if module_node else kg_chunk
                self._insert_knowledge_edge(target["_key"], func["_key"], "declares")
        
        # Classify functions (local vs global)
        self._classify_functions()

    def _classify_functions(self):
        """Classify functions as local_function, global_function, or function"""
        kn = self.gb.get_collection("knowledge_nodes")
        
        for node in kn.all():
            if node.get("type") != "function":
                continue
            
            # Check if declared by chunk (global) or has local keyword
            ast_node = self._get_node(node["_key"])
            if not ast_node:
                continue
            
            children = self._get_children(node["_key"])
            is_local = any(c.get("type") == "local" for c in children)
            
            # Check if declared by chunk
            inbound = self.gb.get_inbound_edges("knowledge_edges", node["_key"])
            declared_by_chunk = any(
                self.gb.get_node("knowledge_nodes", e.get("_from", "").split("/")[-1])
                and self.gb.get_node("knowledge_nodes", e.get("_from", "").split("/")[-1]).get("type") == "chunk"
                and e.get("relation") == "declares"
                for e in inbound
            )
            
            if is_local:
                node["type"] = "local_function"
            elif declared_by_chunk:
                node["type"] = "global_function"

    def insert_parameters(self):
        """Insert function parameters into knowledge graph"""
        print("Inserting parameters...")
        
        kn = self.gb.get_collection("knowledge_nodes")
        
        for func in kn.all():
            if func.get("type") not in ("function", "local_function", "global_function"):
                continue
            
            ast_func = self._get_node(func["_key"])
            if not ast_func:
                continue
            
            # Find parameters node
            func_children = self._get_children(func["_key"])
            params = next((c for c in func_children if c.get("type") == "parameters"), None)
            if not params:
                continue
            
            param_children = self._get_children(params["_key"])
            for param in param_children:
                if param.get("type") in ("identifier", "vararg_expression"):
                    param_node = {
                        "_key": param["_key"],
                        "type": "parameter",
                        "text": param.get("text", ""),
                        "start_byte": param.get("start_byte", 0),
                        "end_byte": param.get("end_byte", 0)
                    }
                    self._insert_knowledge_node(param_node)
                    self._insert_knowledge_edge(func["_key"], param["_key"], "has_parameter")

    def insert_blocks(self):
        """Insert function blocks into knowledge graph"""
        print("Inserting blocks...")
        
        kn = self.gb.get_collection("knowledge_nodes")
        
        for func in kn.all():
            if func.get("type") not in ("function", "local_function", "global_function"):
                continue
            
            ast_func = self._get_node(func["_key"])
            if not ast_func:
                continue
            
            func_children = self._get_children(func["_key"])
            for block in func_children:
                if block.get("type") == "block":
                    block_node = {
                        "_key": block["_key"],
                        "type": "block",
                        "text": block.get("text", ""),
                        "start_byte": block.get("start_byte", 0),
                        "end_byte": block.get("end_byte", 0),
                        "discovered": True,
                        "processed": False
                    }
                    self._insert_knowledge_node(block_node)
                    self._insert_knowledge_edge(func["_key"], block["_key"], "has_block")

    def query_discovered_blocks_without_analysis(self) -> List[str]:
        """Get blocks that are discovered but not yet processed"""
        kn = self.gb.get_collection("knowledge_nodes")
        return [
            n["_key"] for n in kn.all() 
            if n.get("type") == "block" 
            and n.get("discovered") == True 
            and n.get("processed") == False
        ]

    def mark_block_analyzed(self, block_id: str):
        """Mark a block as processed"""
        kn = self.gb.get_collection("knowledge_nodes")
        kn.update(block_id, {"processed": True})

    def insert_block_function_calls(self, block_id: str):
        """Insert function calls within a block"""
        # Traverse to find function calls, stopping at nested blocks
        results = self._traverse_ast(block_id, max_depth=10, stop_at_types={"block"})
        
        for result in results:
            node = result["node"]
            if node.get("type") != "function_call":
                continue
            
            children = self._get_children(node["_key"])
            name_node = next((c for c in children 
                             if c.get("type") in ("identifier", "dot_index_expression")), None)
            
            if not name_node:
                continue
            
            func_name = name_node.get("text", "")
            
            # Try to find existing function in knowledge graph
            kn = self.gb.get_collection("knowledge_nodes")
            existing = None
            for kn_node in kn.all():
                if kn_node.get("text") == func_name and kn_node.get("type") in (
                    "function", "local_function", "global_function", "local_var"
                ):
                    existing = kn_node["_key"]
                    break
            
            if existing:
                self._insert_knowledge_edge(block_id, existing, "calls")
            else:
                # Create function_call node
                call_node = {
                    "_key": node["_key"],
                    "type": "function_call",
                    "text": func_name,
                    "start_byte": node.get("start_byte", 0),
                    "end_byte": node.get("end_byte", 0)
                }
                existing_call = self.gb.get_node("knowledge_nodes", node["_key"])
                if not existing_call:
                    self._insert_knowledge_node(call_node)
                self._insert_knowledge_edge(block_id, node["_key"], "calls")

    def insert_block_var_decls(self, block_id: str):
        """Insert local variable declarations within a block"""
        ast_block = self._get_node(block_id)
        if not ast_block:
            return
        
        block_children = self._get_children(block_id)
        
        for var_decl in block_children:
            if var_decl.get("type") != "variable_declaration":
                continue
            
            vd_children = self._get_children(var_decl["_key"])
            assign = next((c for c in vd_children if c.get("type") == "assignment_statement"), None)
            if not assign:
                continue
            
            assign_children = self._get_children(assign["_key"])
            var_list = next((c for c in assign_children if c.get("type") == "variable_list"), None)
            if not var_list:
                continue
            
            vl_children = self._get_children(var_list["_key"])
            for identifier in vl_children:
                if identifier.get("type") == "identifier":
                    var_node = {
                        "_key": identifier["_key"],
                        "type": "local_var",
                        "text": identifier.get("text", ""),
                        "start_byte": identifier.get("start_byte", 0),
                        "end_byte": identifier.get("end_byte", 0)
                    }
                    self._insert_knowledge_node(var_node)
                    self._insert_knowledge_edge(block_id, identifier["_key"], "declares")

    def insert_local_assignments(self, block_id: str):
        """Insert local assignment statements"""
        block_children = self._get_children(block_id)
        
        for var_decl in block_children:
            if var_decl.get("type") != "variable_declaration":
                continue
            
            vd_children = self._get_children(var_decl["_key"])
            
            for assign in vd_children:
                if assign.get("type") == "assignment_statement":
                    assign_node = {
                        "_key": assign["_key"],
                        "type": "local_assignment",
                        "text": assign.get("text", ""),
                        "start_byte": assign.get("start_byte", 0),
                        "end_byte": assign.get("end_byte", 0)
                    }
                    self._insert_knowledge_node(assign_node)
                    self._insert_knowledge_edge(block_id, assign["_key"], "executes")

    def laststat_return(self, block_id: str):
        """Insert return statements"""
        block_children = self._get_children(block_id)
        
        for stmt in block_children:
            if stmt.get("type") == "return_statement":
                return_node = {
                    "_key": stmt["_key"],
                    "type": "laststat_return",
                    "text": stmt.get("text", ""),
                    "start_byte": stmt.get("start_byte", 0),
                    "end_byte": stmt.get("end_byte", 0)
                }
                self._insert_knowledge_node(return_node)
                self._insert_knowledge_edge(block_id, stmt["_key"], "executes")

    def process_if_statements(self, block_id: str):
        """Process if/elseif/else statements in a block"""
        block_children = self._get_children(block_id)
        
        for if_stmt in block_children:
            if if_stmt.get("type") != "if_statement":
                continue
            
            if_children = self._get_children(if_stmt["_key"])
            
            for child in if_children:
                if child.get("type") in ("else_statement", "elseif_statement"):
                    stmt_node = {
                        "_key": child["_key"],
                        "type": child["type"],
                        "text": child.get("text", ""),
                        "start_byte": child.get("start_byte", 0),
                        "end_byte": child.get("end_byte", 0)
                    }
                    self._insert_knowledge_node(stmt_node)
                    self._insert_knowledge_edge(if_stmt["_key"], child["_key"], "executes")
                    
                    # Find and insert block for else/elseif
                    stmt_children = self._get_children(child["_key"])
                    for block in stmt_children:
                        if block.get("type") == "block":
                            block_node = {
                                "_key": block["_key"],
                                "type": "block",
                                "text": block.get("text", ""),
                                "start_byte": block.get("start_byte", 0),
                                "end_byte": block.get("end_byte", 0),
                                "discovered": True,
                                "processed": False
                            }
                            self._insert_knowledge_node(block_node)
                            self._insert_knowledge_edge(child["_key"], block["_key"], "has_block")

    def query_undiscovered_statements_from_discovered_blocks(self) -> List[Dict[str, Any]]:
        """Find control statements in discovered blocks that haven't been inserted"""
        results = []
        kn = self.gb.get_collection("knowledge_nodes")
        
        for block in kn.all():
            if block.get("type") != "block" or not block.get("discovered"):
                continue
            
            ast_block = self._get_node(block["_key"])
            if not ast_block:
                continue
            
            block_children = self._get_children(block["_key"])
            
            for child in block_children:
                if child.get("type") in self.control_statements:
                    # Check if already exists in knowledge graph
                    existing = self.gb.get_node("knowledge_nodes", child["_key"])
                    if not existing:
                        results.append({
                            "new_node_id": child["_key"],
                            "from_node_id": block["_key"],
                            "type": child["type"],
                            "text": child.get("text", ""),
                            "start_byte": child.get("start_byte", 0),
                            "end_byte": child.get("end_byte", 0)
                        })
        
        return results

    def insert_stmt_blocks(self, statements: List[Dict[str, Any]]):
        """Insert blocks for control statements"""
        if not statements:
            return
        
        for stmt in statements:
            ast_stmt = self._get_node(stmt["new_node_id"])
            if not ast_stmt:
                continue
            
            stmt_children = self._get_children(stmt["new_node_id"])
            
            for block in stmt_children:
                if block.get("type") == "block":
                    block_node = {
                        "_key": block["_key"],
                        "type": "block",
                        "text": block.get("text", ""),
                        "start_byte": block.get("start_byte", 0),
                        "end_byte": block.get("end_byte", 0),
                        "discovered": True,
                        "processed": False
                    }
                    self._insert_knowledge_node(block_node)
                    self._insert_knowledge_edge(stmt["new_node_id"], block["_key"], "has_block")

    def build_recursive_blocks(self):
        """Recursively process all blocks until none remain"""
        iteration = 0
        while True:
            iteration += 1
            new_statements = self.query_undiscovered_statements_from_discovered_blocks()
            
            print(f"Iteration {iteration}: Found {len(new_statements)} undiscovered statements.")
            
            if new_statements:
                for stmt in new_statements:
                    self._insert_nodes_and_edges(
                        node_type=stmt["type"], 
                        edge_relation="executes", 
                        entities=[stmt]
                    )
                self.insert_stmt_blocks(new_statements)
            
            discovered_blocks = self.query_discovered_blocks_without_analysis()
            if not discovered_blocks:
                break
            
            print(f"Processing {len(discovered_blocks)} discovered blocks.")
            
            for block_id in discovered_blocks:
                self.laststat_return(block_id)
                self.insert_block_var_decls(block_id)
                self.insert_local_assignments(block_id)
                self.insert_block_function_calls(block_id)
                self.process_if_statements(block_id)
                self.mark_block_analyzed(block_id)

    def insert_global_var_nodes(self):
        """Insert global variable nodes (simplified)"""
        print("Inserting global variables...")
        # This is a simplified version - full implementation would mirror the AQL query

    def insert_dot_index_nodes(self):
        """Insert dot index expression nodes (simplified)"""
        print("Inserting dot index expressions...")
        # This is a simplified version

    def process_module_nodes(self):
        """Process module relationships (requires/imports)"""
        print("Processing module relationships...")
        # This creates requires and imports edges between modules

    def insert_export_edges(self):
        """Create export edges from modules to functions"""
        print("Creating export edges...")

    # =========================================================================
    # Main entry point
    # =========================================================================
    
    def build_KG(self):
        """Build the complete knowledge graph from AST"""
        print("Building Knowledge Graph...")
        self.get_start_node()
        self.insert_module_nodes()
        self.insert_local_var_nodes()
        self.insert_required_modules()
        self.insert_global_var_nodes()
        self.insert_dot_index_nodes()
        self.process_module_nodes()
        self.insert_functions()
        self.insert_parameters()
        self.insert_blocks()
        self.build_recursive_blocks()
        print("Knowledge Graph build complete!")
