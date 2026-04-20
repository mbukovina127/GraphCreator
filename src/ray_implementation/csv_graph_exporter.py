import csv
from collections import Counter
from typing import List, Dict, Any

from ray_implementation import CPGBuilder
from ray_implementation.dto.edges import Edges

# ForceAtlas 2 edge weights: structural edges pull harder, data-flow edges are softer.
_EDGE_WEIGHTS: Dict[str, float] = {
    Edges.DEFINES.value:        3.0,
    Edges.DECLARES.value:       3.0,
    Edges.IMPORTS.value:        2.5,
    Edges.HAS_BLOCK.value:      2.5,
    Edges.HAS_PARAMETERS.value: 2.0,
    Edges.CALLS.value:          2.0,
    Edges.RETURNS.value:        2.0,
    Edges.REFERS_TO.value:      1.5,
    Edges.HAS_ARGUMENT.value:   1.5,
    Edges.HAS_CONDITION.value:  1.5,
    Edges.HAS_FIELD.value:      1.5,
    Edges.INITIALIZES.value:    1.5,
    Edges.ASSIGNS_TO.value:     1.5,
    Edges.EXECUTES.value:       1.2,
    Edges.CONTAINS.value:       1.0,
    Edges.FLOWS_TO.value:       1.0,
    Edges.INSIDE_OF.value:      1.0,
    Edges.HAS_METRICS.value:    0.5,
}

# Base node size per type: high-level constructs are larger hubs.
_NODE_BASE_SIZE: Dict[str, float] = {
    "module":                      20.0,
    "chunk":                       18.0,
    "global_function_definition":  15.0,
    "local_function_definition":   15.0,
    "global_variable_declaration": 10.0,
    "local_variable_declaration":  10.0,
    "module_import":               10.0,
    "if_statement":                 8.0,
    "for_statement":                8.0,
    "while_statement":              8.0,
    "repeat_statement":             8.0,
    "table_constructor":            8.0,
    "block":                        6.0,
    "function_call":                6.0,
    "index_expression":             5.0,
    "identifier":                   4.0,
    "expression_list":              3.0,
    "binary_expression":            3.0,
    "return_statement":             3.0,
    "literal":                      2.0,
    "metric":                       1.0,
}
_DEFAULT_NODE_SIZE = 4.0


def _strip_collection(handle: str) -> str:
    if "/" in handle:
        return handle.split("/", 1)[1]
    return handle


def _flatten_properties(node: Dict[str, Any]) -> Dict[str, Any]:
    flat = {}
    for k, v in node.items():
        if k not in {"_key", "properties"}:
            flat[k] = v
    props = node.get("properties", {})
    if isinstance(props, dict):
        for k, v in props.items():
            flat[f"prop_{k}"] = v
    return flat


def export_to_gephi_csv(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    nodes_csv_path: str = "nodes.csv",
    edges_csv_path: str = "edges.csv",
) -> None:
    """
    Exports nodes and edges into two CSV files compatible with Gephi.

    Adds:
    - Weight on each edge (relation-type based) for ForceAtlas 2 spring strength
    - Size on each node (base size + degree bonus) for repulsion radius
    """
    nodes = list(nodes)

    # Compute degree for each node id (in + out edges)
    degree: Counter = Counter()
    for edge in edges:
        degree[_strip_collection(edge["_from"])] += 1
        degree[_strip_collection(edge["_to"])] += 1

    # ---- Prepare Nodes ----
    processed_nodes = []
    all_node_fields = set()

    for node in nodes:
        node_id = node["_key"]
        flattened = _flatten_properties(node)
        node_type = flattened.get("type", "")

        base_size = _NODE_BASE_SIZE.get(node_type, _DEFAULT_NODE_SIZE)
        size = round(base_size + degree[node_id] * 0.5, 2)

        row = {
            "Id":    node_id,
            "Label": node_type or node_id,
            "Size":  size,
        }
        for k, v in flattened.items():
            if k != "type":
                row[k] = v

        processed_nodes.append(row)
        all_node_fields.update(row.keys())

    node_fieldnames = ["Id", "Label", "Size"] + sorted(
        f for f in all_node_fields if f not in {"Id", "Label", "Size"}
    )

    with open(nodes_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=node_fieldnames)
        writer.writeheader()
        for row in processed_nodes:
            writer.writerow(row)

    # ---- Prepare Edges ----
    processed_edges = []
    all_edge_fields = {"Source", "Target", "Type", "Weight"}

    for edge in edges:
        relation = edge.get("relation", "")
        row = {
            "Id":     edge.get("_key"),
            "Source": _strip_collection(edge["_from"]),
            "Target": _strip_collection(edge["_to"]),
            "Type":   "Directed",
            "Label":  relation,
            "Weight": _EDGE_WEIGHTS.get(relation, 1.0),
        }
        for k, v in edge.items():
            if k not in {"_key", "_from", "_to", "relation"}:
                row[k] = v
        processed_edges.append(row)
        all_edge_fields.update(row.keys())

    edge_fieldnames = ["Id", "Source", "Target", "Type", "Weight"] + sorted(
        f for f in all_edge_fields if f not in {"Id", "Source", "Target", "Type", "Weight"}
    )

    with open(edges_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=edge_fieldnames)
        writer.writeheader()
        for row in processed_edges:
            writer.writerow(row)


def export_from_builder(builder):
    if isinstance(builder, CPGBuilder):
        builder = builder.local_builder
    nodes = builder.knowledge_nodes.values()
    edges = builder.knowledge_edges
    export_to_gephi_csv(nodes, edges, "k_nodes.csv", "k_edges.csv")
