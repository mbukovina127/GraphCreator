from typing import Dict, Any, List


def compute_global_var_metrics(
    knowledge_nodes: Dict[str, Any],
    knowledge_edges: List[Dict],
) -> Dict[str, Dict]:
    """
    For each function definition node, count global variable accesses:
      - global_vars_read:    identifiers referring to global_variable_declaration without write property
      - global_vars_written: identifiers referring to global_variable_declaration with write==True

    Strategy: an identifier is "inside" a function if it shares the same file_path and its
    byte range falls within the function's byte range.

    Returns {fn_node_id: {"global_vars_read": N, "global_vars_written": N}}
    """
    fn_types = {"local_function_definition", "global_function_definition"}

    # index REFERS_TO targets for each identifier node
    refers_to: Dict[str, str] = {}  # identifier_id -> target_id
    for edge in knowledge_edges:
        if edge["relation"] == "refers_to":
            refers_to[edge["_from"]] = edge["_to"]

    global_decl_ids = {
        nid for nid, n in knowledge_nodes.items()
        if n.get("type") == "global_variable_declaration"
    }

    # collect all identifiers that refer to a global variable
    global_refs = []  # (identifier_node, is_write)
    for nid, node in knowledge_nodes.items():
        if node.get("type") != "identifier":
            continue
        target = refers_to.get(nid)
        if target in global_decl_ids:
            is_write = node.get("properties", {}).get("write") == "True"
            global_refs.append((node, is_write))

    # collect function definitions with their byte ranges per file
    functions = [
        (nid, node)
        for nid, node in knowledge_nodes.items()
        if node.get("type") in fn_types
    ]

    result: Dict[str, Dict] = {
        fn_id: {"global_vars_read": 0, "global_vars_written": 0}
        for fn_id, _ in functions
    }

    for ident_node, is_write in global_refs:
        ident_file = ident_node.get("file_path")
        ident_start = ident_node.get("start_byte", -1)
        ident_end = ident_node.get("end_byte", -1)

        for fn_id, fn_node in functions:
            if fn_node.get("file_path") != ident_file:
                continue
            fn_start = fn_node.get("start_byte", 0)
            fn_end = fn_node.get("end_byte", 0)
            if fn_start <= ident_start and ident_end <= fn_end:
                key = "global_vars_written" if is_write else "global_vars_read"
                result[fn_id][key] += 1
                break  # assign to innermost match — first match is sufficient here

    return result
