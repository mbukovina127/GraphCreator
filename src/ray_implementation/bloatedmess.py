import csv
from typing import List, Dict, Any


def _strip_collection(handle: str) -> str:
    """
    Converts 'collection/key' -> 'key'
    If already plain, returns unchanged.
    """
    if "/" in handle:
        return handle.split("/", 1)[1]
    return handle


def _flatten_properties(node: Dict[str, Any]) -> Dict[str, Any]:
    """
    Flattens the 'properties' field into top-level attributes.
    """
    flat = {}

    # Copy known top-level fields except special ones
    for k, v in node.items():
        if k not in {"_key", "properties"}:
            flat[k] = v

    # Flatten nested properties if present
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
    """

    # ---- Prepare Nodes ----
    processed_nodes = []
    all_node_fields = set()

    for node in nodes:
        node_id = node["_key"]
        flattened = _flatten_properties(node)

        row = {
            "Id": node_id,
            "Label": flattened.get("type", node_id),
        }

        # Add all other attributes
        for k, v in flattened.items():
            if k != "type":
                row[k] = v

        processed_nodes.append(row)
        all_node_fields.update(row.keys())

    # Ensure Id and Label are first
    node_fieldnames = ["Id", "Label"] + sorted(
        f for f in all_node_fields if f not in {"Id", "Label"}
    )

    with open(nodes_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=node_fieldnames)
        writer.writeheader()
        for row in processed_nodes:
            writer.writerow(row)

    # ---- Prepare Edges ----
    processed_edges = []
    all_edge_fields = {"Source", "Target", "Type"}

    for edge in edges:
        row = {
            "Id": edge.get("_key"),
            "Source": _strip_collection(edge["_from"]),
            "Target": _strip_collection(edge["_to"]),
            "Type": "Directed",
            "relation": edge.get("relation"),
        }

        # Preserve any extra edge attributes
        for k, v in edge.items():
            if k not in {"_key", "_from", "_to", "relation"}:
                row[k] = v

        processed_edges.append(row)
        all_edge_fields.update(row.keys())

    edge_fieldnames = ["Id", "Source", "Target", "Type"] + sorted(
        f for f in all_edge_fields if f not in {"Id", "Source", "Target", "Type"}
    )

    with open(edges_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=edge_fieldnames)
        writer.writeheader()
        for row in processed_edges:
            writer.writerow(row)