from typing import Dict, Any, List


def _build_metrics_index(nodes: Dict, edges: List) -> Dict[str, dict]:
    """Returns {target_node_id -> metric properties} from HAS_METRICS edges."""
    index = {}
    metric_ids = {nid for nid, n in nodes.items() if n.get("type") == "metric"}
    for edge in edges:
        if edge["relation"] == "has_metrics" and edge["_from"] in metric_ids:
            index[edge["_to"]] = nodes[edge["_from"]].get("properties", {})
    return index


def compute_project_metrics(
    knowledge_nodes: Dict[str, Any],
    knowledge_edges: List[Dict],
) -> Dict[str, Any]:
    """
    Aggregate project-level metrics from the complete knowledge graph.
    Returns a flat properties dict suitable for a project_metric node.
    """
    metrics_index = _build_metrics_index(knowledge_nodes, knowledge_edges)

    num_files = sum(1 for n in knowledge_nodes.values() if n.get("type") == "file")
    num_modules = sum(1 for n in knowledge_nodes.values() if n.get("type") == "module")

    # collect per-chunk and per-function stats
    fn_types = {"local_function_definition", "global_function_definition"}
    chunk_fn_counts = []
    fn_loc_totals = []
    comment_pcts = []

    for node_id, node in knowledge_nodes.items():
        node_type = node.get("type")
        m = metrics_index.get(node_id, {})

        if node_type == "chunk":
            fc = m.get("function_counts", {})
            if fc:
                chunk_fn_counts.append(fc.get("total", 0))
            loc = m.get("loc", {})
            if isinstance(loc, dict) and loc.get("comment_pct") is not None:
                comment_pcts.append(loc["comment_pct"])

        elif node_type in fn_types:
            loc = m.get("loc", {})
            if isinstance(loc, dict) and loc.get("total") is not None:
                fn_loc_totals.append(loc["total"])

    def _avg(lst):
        return round(sum(lst) / len(lst), 2) if lst else 0.0

    return {
        "num_files": num_files,
        "num_modules": num_modules,
        "avg_functions_per_file": _avg(chunk_fn_counts),
        "max_functions_in_file": max(chunk_fn_counts, default=0),
        "min_functions_in_file": min(chunk_fn_counts, default=0),
        "avg_lines_per_function": _avg(fn_loc_totals),
        "avg_comment_pct": _avg(comment_pcts),
    }
