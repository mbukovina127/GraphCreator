from typing import Dict, Any, List


def compute_dependency_metrics(
    knowledge_nodes: Dict[str, Any],
    knowledge_edges: List[Dict],
) -> Dict[str, Dict]:
    """
    For each function definition node, compute:
      - depends_on: list of function node IDs this function calls
      - depended_by: list of function node IDs that call this function

    Call chain: function_definition -HAS_BLOCK-> block -CALLS-> function_call -REFERS_TO-> function_definition

    Returns {fn_node_id: {"depends_on": [...], "depended_by": [...]}}
    """
    fn_types = {"local_function_definition", "global_function_definition"}

    # index edges by relation for fast lookup
    edges_from: Dict[str, List[Dict]] = {}
    for edge in knowledge_edges:
        edges_from.setdefault(edge["_from"], []).append(edge)

    def _follow(from_id: str, relation: str) -> List[str]:
        return [e["_to"] for e in edges_from.get(from_id, []) if e["relation"] == relation]

    result: Dict[str, Dict] = {}

    for fn_id, fn_node in knowledge_nodes.items():
        if fn_node.get("type") not in fn_types:
            continue

        depends_on = set()
        # fn -HAS_BLOCK-> block(s)
        for block_id in _follow(fn_id, "has_block"):
            # block -CALLS-> function_call
            for call_id in _follow(block_id, "calls"):
                # function_call -REFERS_TO-> function_definition
                for target_id in _follow(call_id, "refers_to"):
                    if knowledge_nodes.get(target_id, {}).get("type") in fn_types:
                        depends_on.add(target_id)

        result[fn_id] = {"depends_on": sorted(depends_on), "depended_by": []}

    # build depended_by as reverse of depends_on
    for fn_id, data in result.items():
        for callee_id in data["depends_on"]:
            if callee_id in result:
                result[callee_id]["depended_by"].append(fn_id)

    return result
