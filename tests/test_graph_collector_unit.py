"""Unit tests for GraphCollectorBase and GraphCollector (no Ray, no ZIP files)."""
import os
import pytest

from ray_implementation.builders.graph_collector import GraphCollectorBase, GraphCollector
from ray_implementation.dto.edges import Edges
from ray_implementation.structures import SymbolTable


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def base():
    return GraphCollectorBase()


@pytest.fixture
def gc():
    return GraphCollector()


def _make_result(file_path: str, *, imports=None, unresolved_edges=None, kg_vertices=None, kg_edges=None, ast_vertices=None, ast_edges=None) -> dict:
    """Build a synthetic per-file result dict matching the format from Ray workers."""
    fp = str(file_path)
    return {
        "file": fp,
        "imports": imports or {},
        "unresolved_edges": unresolved_edges or {},
        "knowledge_graph": {
            "vertices": kg_vertices if kg_vertices is not None else [
                {"_key": f"kg:chunk:{fp}", "type": "chunk", "file_path": fp, "properties": {}}
            ],
            "edges": kg_edges or [],
        },
        "ast_graph": {
            "vertices": ast_vertices if ast_vertices is not None else [
                {"_key": f"ast:chunk:{fp}", "type": "chunk"}
            ],
            "edges": ast_edges or [],
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# Section 1 — GraphCollectorBase: ID generators
# ──────────────────────────────────────────────────────────────────────────────

def test_gen_next_ast_id_starts_at_one(base):
    assert base._gen_next_ast_id() == 1


def test_gen_next_ast_id_increments_sequentially(base):
    assert base._gen_next_ast_id() == 1
    assert base._gen_next_ast_id() == 2
    assert base._gen_next_ast_id() == 3


def test_gen_next_ast_id_mutates_counter(base):
    base._gen_next_ast_id()
    assert base.ast_id == 1


def test_gen_next_knowledge_id_starts_at_one(base):
    assert base._gen_next_knowledge_id() == 1


def test_gen_next_knowledge_id_increments_independently_from_ast(base):
    base._gen_next_ast_id()
    base._gen_next_ast_id()
    assert base._gen_next_knowledge_id() == 1


def test_gen_next_knowledge_id_mutates_counter(base):
    base._gen_next_knowledge_id()
    base._gen_next_knowledge_id()
    assert base.knowledge_id == 2


# ──────────────────────────────────────────────────────────────────────────────
# Section 2 — GraphCollectorBase: AST node/edge storage
# ──────────────────────────────────────────────────────────────────────────────

def test_add_ast_node_stores_by_key(base):
    node = {"_key": "n1", "type": "file"}
    base._add_ast_node(node)
    assert base._ast_nodes["n1"] is node


def test_add_ast_node_overwrites_same_key(base):
    base._add_ast_node({"_key": "n1", "type": "file"})
    base._add_ast_node({"_key": "n1", "type": "directory"})
    assert base._ast_nodes["n1"]["type"] == "directory"


def test_add_ast_nodes_stores_all(base):
    nodes = [{"_key": f"n{i}"} for i in range(3)]
    base._add_ast_nodes(nodes)
    assert all(f"n{i}" in base._ast_nodes for i in range(3))


def test_add_ast_nodes_empty_list(base):
    base._add_ast_nodes([])
    assert base._ast_nodes == {}


def test_add_ast_edge_appends(base):
    edge = {"_from": "a", "_to": "b"}
    base._add_ast_edge(edge)
    assert len(base._ast_edges) == 1
    assert base._ast_edges[0] is edge


def test_add_ast_edges_extends_preserving_order(base):
    base._add_ast_edge({"_from": "a", "_to": "b"})
    base._add_ast_edges([{"_from": "c", "_to": "d"}, {"_from": "e", "_to": "f"}])
    assert len(base._ast_edges) == 3
    assert base._ast_edges[0]["_from"] == "a"


def test_add_ast_edges_empty_list(base):
    base._add_ast_edges([])
    assert base._ast_edges == []


# ──────────────────────────────────────────────────────────────────────────────
# Section 3 — GraphCollectorBase: knowledge node/edge storage
# ──────────────────────────────────────────────────────────────────────────────

def test_add_knowledge_node_stores_by_key(base):
    node = {"_key": "kg1", "type": "chunk"}
    base._add_knowledge_node(node)
    assert base._knowledge_nodes["kg1"] is node


def test_add_knowledge_node_overwrites_same_key(base):
    base._add_knowledge_node({"_key": "kg1", "type": "chunk"})
    base._add_knowledge_node({"_key": "kg1", "type": "module"})
    assert base._knowledge_nodes["kg1"]["type"] == "module"


def test_add_knowledge_nodes_stores_all(base):
    nodes = [{"_key": f"kg{i}"} for i in range(3)]
    base._add_knowledge_nodes(nodes)
    assert all(f"kg{i}" in base._knowledge_nodes for i in range(3))


def test_add_knowledge_nodes_empty_list(base):
    base._add_knowledge_nodes([])
    assert base._knowledge_nodes == {}


def test_add_knowledge_edge_appends(base):
    edge = {"_from": "x", "_to": "y", "relation": "contains"}
    base._add_knowledge_edge(edge)
    assert len(base._knowledge_edges) == 1
    assert base._knowledge_edges[0] is edge


def test_add_knowledge_edges_extends_preserving_order(base):
    base._add_knowledge_edge({"_from": "a", "_to": "b", "relation": "is"})
    base._add_knowledge_edges([{"_from": "c", "_to": "d"}, {"_from": "e", "_to": "f"}])
    assert len(base._knowledge_edges) == 3
    assert base._knowledge_edges[0]["_from"] == "a"


def test_add_knowledge_edges_empty_list(base):
    base._add_knowledge_edges([])
    assert base._knowledge_edges == []


# ──────────────────────────────────────────────────────────────────────────────
# Section 4 — _create_ast_node factory
# ──────────────────────────────────────────────────────────────────────────────

def test_create_ast_node_all_fields_present(base):
    node = base._create_ast_node("nid", "aid", "function", 10, 50, "fn body")
    assert set(node.keys()) == {"_key", "ast_id", "type", "start_byte", "end_byte", "text"}


def test_create_ast_node_values_correct(base):
    node = base._create_ast_node("nid", "aid", "function", 10, 50, "fn body")
    assert node["_key"] == "nid"
    assert node["ast_id"] == "aid"
    assert node["type"] == "function"
    assert node["start_byte"] == 10
    assert node["end_byte"] == 50
    assert node["text"] == "fn body"


def test_create_ast_node_ast_id_none_allowed(base):
    node = base._create_ast_node("nid", None, "file", 0, 0, "")
    assert node["ast_id"] is None


# ──────────────────────────────────────────────────────────────────────────────
# Section 5 — _create_ast_edge factory
# ──────────────────────────────────────────────────────────────────────────────

def test_create_ast_edge_default_relation(base):
    edge = base._create_ast_edge("parent", "child")
    assert edge["relation"] == "child_of"


def test_create_ast_edge_custom_relation(base):
    edge = base._create_ast_edge("p", "c", relation="is")
    assert edge["relation"] == "is"


def test_create_ast_edge_from_and_to(base):
    edge = base._create_ast_edge("parent", "child")
    assert edge["_from"] == "parent"
    assert edge["_to"] == "child"


def test_create_ast_edge_no_extra_keys(base):
    edge = base._create_ast_edge("p", "c")
    assert set(edge.keys()) == {"_from", "_to", "relation"}


# ──────────────────────────────────────────────────────────────────────────────
# Section 6 — _create_knowledge_node factory
# ──────────────────────────────────────────────────────────────────────────────

def test_create_knowledge_node_required_key_field(base):
    node = base._create_knowledge_node("k1")
    assert node["_key"] == "k1"


def test_create_knowledge_node_all_fields_present(base):
    node = base._create_knowledge_node("k1")
    assert set(node.keys()) == {"_key", "symbol_id", "type", "text", "start_byte", "end_byte", "file_path", "properties"}


def test_create_knowledge_node_defaults_none_for_optional_scalars(base):
    node = base._create_knowledge_node("k1")
    for field in ("symbol_id", "type", "text", "start_byte", "end_byte", "file_path"):
        assert node[field] is None, f"Expected {field} to default to None"


def test_create_knowledge_node_properties_defaults_to_empty_dict(base):
    node = base._create_knowledge_node("k1")
    assert node["properties"] == {}


def test_create_knowledge_node_properties_none_becomes_empty_dict(base):
    node = base._create_knowledge_node("k1", properties=None)
    assert node["properties"] == {}


def test_create_knowledge_node_properties_dict_preserved(base):
    props = {"name": "add", "loc": 5}
    node = base._create_knowledge_node("k1", properties=props)
    assert node["properties"] == props


def test_create_knowledge_node_all_fields_populated(base):
    node = base._create_knowledge_node(
        "k1", symbol_id="s1", type="chunk", text="hello",
        start_byte=0, end_byte=100, file_path="/a.lua", properties={"x": 1}
    )
    assert node["symbol_id"] == "s1"
    assert node["type"] == "chunk"
    assert node["text"] == "hello"
    assert node["start_byte"] == 0
    assert node["end_byte"] == 100
    assert node["file_path"] == "/a.lua"
    assert node["properties"] == {"x": 1}


# ──────────────────────────────────────────────────────────────────────────────
# Section 7 — _create_knowledge_edge factory
# ──────────────────────────────────────────────────────────────────────────────

def test_create_knowledge_edge_uses_enum_value(base):
    edge = base._create_knowledge_edge("a", "b", Edges.IMPORTS)
    assert edge["relation"] == "imports"


def test_create_knowledge_edge_contains_relation(base):
    edge = base._create_knowledge_edge("a", "b", Edges.CONTAINS)
    assert edge["relation"] == "contains"


def test_create_knowledge_edge_from_and_to(base):
    edge = base._create_knowledge_edge("from_node", "to_node", Edges.IS)
    assert edge["_from"] == "from_node"
    assert edge["_to"] == "to_node"


def test_create_knowledge_edge_has_metrics_relation(base):
    edge = base._create_knowledge_edge("m", "f", Edges.HAS_METRICS)
    assert edge["relation"] == "has_metrics"


def test_create_knowledge_edge_no_extra_keys(base):
    edge = base._create_knowledge_edge("a", "b", Edges.IS)
    assert set(edge.keys()) == {"_from", "_to", "relation"}


# ──────────────────────────────────────────────────────────────────────────────
# Section 8 — GraphCollector.__init__
# ──────────────────────────────────────────────────────────────────────────────

def test_graph_collector_initial_ast_state(gc):
    assert gc._ast_nodes == {}
    assert gc._ast_edges == []


def test_graph_collector_initial_knowledge_state(gc):
    assert gc._knowledge_nodes == {}
    assert gc._knowledge_edges == []


def test_graph_collector_initial_indexes_empty(gc):
    assert gc._module_index == {}
    assert gc._chunk_index == {}
    assert gc._export_index == {}


def test_graph_collector_initial_results_empty(gc):
    assert gc.results == {}


def test_graph_collector_initial_symbol_table_type(gc):
    assert isinstance(gc.global_symbol_table, SymbolTable)


# ──────────────────────────────────────────────────────────────────────────────
# Section 9 — _collect_local_results
# ──────────────────────────────────────────────────────────────────────────────

def test_collect_local_results_indexes_by_file(gc):
    res_a = _make_result("/a.lua")
    res_b = _make_result("/b.lua")
    gc._collect_local_results([res_a, res_b])
    assert gc.results["/a.lua"] is res_a
    assert gc.results["/b.lua"] is res_b


def test_collect_local_results_empty_list(gc):
    gc._collect_local_results([])
    assert gc.results == {}


def test_collect_local_results_single_item(gc):
    gc._collect_local_results([_make_result("/a.lua")])
    assert len(gc.results) == 1


def test_collect_local_results_duplicate_file_key_last_wins(gc):
    res1 = _make_result("/a.lua", imports={"x": "m1"})
    res2 = _make_result("/a.lua", imports={"y": "m2"})
    gc._collect_local_results([res1, res2])
    assert gc.results["/a.lua"] is res2


# ──────────────────────────────────────────────────────────────────────────────
# Section 10 — _store_local_graph
# ──────────────────────────────────────────────────────────────────────────────

def test_store_local_graph_missing_file_logs_warning_and_returns(gc, caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        gc._store_local_graph("ast:p", "kg:p", "/missing.lua")
    assert gc._ast_nodes == {}
    assert gc._knowledge_nodes == {}


def test_store_local_graph_malformed_no_knowledge_graph_key(gc, caplog):
    import logging
    gc.results["/f.lua"] = {"ast_graph": {"vertices": [{"_key": "a1"}], "edges": []}}
    with caplog.at_level(logging.ERROR):
        gc._store_local_graph("ap", "kp", "/f.lua")
    assert gc._knowledge_nodes == {}


def test_store_local_graph_malformed_empty_vertices(gc, caplog):
    import logging
    gc.results["/f.lua"] = {
        "knowledge_graph": {"vertices": [], "edges": []},
        "ast_graph": {"vertices": [], "edges": []},
    }
    with caplog.at_level(logging.ERROR):
        gc._store_local_graph("ap", "kp", "/f.lua")
    assert gc._knowledge_nodes == {}


def test_store_local_graph_adds_ast_edge_to_parent(gc):
    fp = "/f.lua"
    gc.results[fp] = _make_result(fp)
    gc._store_local_graph("ast:parent", "kg:parent", fp)
    ast_parent_edges = [e for e in gc._ast_edges if e["_from"] == "ast:parent"]
    assert len(ast_parent_edges) == 1
    assert ast_parent_edges[0]["_to"] == f"ast:chunk:{fp}"
    assert ast_parent_edges[0]["relation"] == "is"


def test_store_local_graph_adds_kg_edge_to_parent(gc):
    fp = "/f.lua"
    gc.results[fp] = _make_result(fp)
    gc._store_local_graph("ast:parent", "kg:parent", fp)
    kg_parent_edges = [e for e in gc._knowledge_edges if e["_from"] == "kg:parent"]
    assert len(kg_parent_edges) == 1
    assert kg_parent_edges[0]["_to"] == f"kg:chunk:{fp}"
    assert kg_parent_edges[0]["relation"] == "is"


def test_store_local_graph_merges_all_ast_vertices(gc):
    fp = "/f.lua"
    gc.results[fp] = _make_result(fp, ast_vertices=[
        {"_key": "a1"}, {"_key": "a2"}, {"_key": "a3"}
    ])
    gc._store_local_graph("ap", "kp", fp)
    assert all(k in gc._ast_nodes for k in ("a1", "a2", "a3"))


def test_store_local_graph_merges_all_ast_edges(gc):
    fp = "/f.lua"
    gc.results[fp] = _make_result(fp, ast_edges=[
        {"_from": "a1", "_to": "a2"}, {"_from": "a2", "_to": "a3"}
    ])
    gc._store_local_graph("ap", "kp", fp)
    # 1 parent IS-edge + 2 from result
    assert len(gc._ast_edges) == 3


def test_store_local_graph_merges_all_kg_vertices(gc):
    fp = "/f.lua"
    gc.results[fp] = _make_result(fp, kg_vertices=[
        {"_key": "kg1", "type": "chunk", "file_path": fp, "properties": {}},
        {"_key": "kg2", "type": "module", "file_path": fp, "properties": {}},
    ])
    gc._store_local_graph("ap", "kp", fp)
    assert "kg1" in gc._knowledge_nodes
    assert "kg2" in gc._knowledge_nodes


def test_store_local_graph_merges_all_kg_edges(gc):
    fp = "/f.lua"
    gc.results[fp] = _make_result(fp, kg_edges=[{"_from": "kg1", "_to": "kg2", "relation": "contains"}])
    gc._store_local_graph("ap", "kp", fp)
    # 1 parent IS-edge + 1 from result
    assert len(gc._knowledge_edges) == 2


# ──────────────────────────────────────────────────────────────────────────────
# Section 11 — _create_indexes
# ──────────────────────────────────────────────────────────────────────────────

def test_create_indexes_module_node_added_to_module_index(gc):
    gc._knowledge_nodes["m1"] = {"_key": "m1", "type": "module", "properties": {"module_name": "math.utils"}}
    gc._create_indexes()
    assert gc._module_index["math.utils"] == "m1"


def test_create_indexes_module_without_module_name_not_indexed(gc):
    gc._knowledge_nodes["m1"] = {"_key": "m1", "type": "module", "properties": {}}
    gc._create_indexes()
    assert gc._module_index == {}


def test_create_indexes_chunk_node_added_to_chunk_index(gc):
    gc._knowledge_nodes["c1"] = {"_key": "c1", "type": "chunk", "file_path": "/src/a.lua"}
    gc._create_indexes()
    assert gc._chunk_index["/src/a.lua"] == "c1"


def test_create_indexes_chunk_none_file_path_stored(gc):
    gc._knowledge_nodes["c1"] = {"_key": "c1", "type": "chunk", "file_path": None}
    gc._create_indexes()
    assert None in gc._chunk_index


def test_create_indexes_export_index_from_declares_edge(gc):
    gc._knowledge_nodes["m1"] = {"_key": "m1", "type": "module", "properties": {"module_name": "mymod"}}
    gc._knowledge_nodes["fn1"] = {"_key": "fn1", "type": "local_function_definition", "properties": {"name": "add"}}
    gc._knowledge_edges.append({"_from": "m1", "_to": "fn1", "relation": Edges.DECLARES.value})
    gc._create_indexes()
    assert gc._export_index["mymod"]["add"] == "fn1"


def test_create_indexes_export_index_from_defines_edge(gc):
    gc._knowledge_nodes["m1"] = {"_key": "m1", "type": "module", "properties": {"module_name": "mymod"}}
    gc._knowledge_nodes["fn1"] = {"_key": "fn1", "type": "local_function_definition", "properties": {"name": "sqrt"}}
    gc._knowledge_edges.append({"_from": "m1", "_to": "fn1", "relation": Edges.DEFINES.value})
    gc._create_indexes()
    assert gc._export_index["mymod"]["sqrt"] == "fn1"


def test_create_indexes_export_index_edge_with_missing_from_node(gc):
    gc._knowledge_nodes["fn1"] = {"_key": "fn1", "type": "local_function_definition", "properties": {"name": "add"}}
    gc._knowledge_edges.append({"_from": "ghost", "_to": "fn1", "relation": Edges.DECLARES.value})
    gc._create_indexes()
    assert gc._export_index == {}


def test_create_indexes_export_index_edge_with_missing_to_node(gc):
    gc._knowledge_nodes["m1"] = {"_key": "m1", "type": "module", "properties": {"module_name": "mymod"}}
    gc._knowledge_edges.append({"_from": "m1", "_to": "ghost", "relation": Edges.DECLARES.value})
    gc._create_indexes()
    assert gc._export_index == {}


def test_create_indexes_ignores_other_edge_relations(gc):
    gc._knowledge_nodes["m1"] = {"_key": "m1", "type": "module", "properties": {"module_name": "mymod"}}
    gc._knowledge_nodes["fn1"] = {"_key": "fn1", "type": "local_function_definition", "properties": {"name": "add"}}
    gc._knowledge_edges.append({"_from": "m1", "_to": "fn1", "relation": Edges.CONTAINS.value})
    gc._create_indexes()
    assert gc._export_index == {}


def test_create_indexes_multiple_modules_and_functions(gc):
    gc._knowledge_nodes["m1"] = {"_key": "m1", "type": "module", "properties": {"module_name": "modA"}}
    gc._knowledge_nodes["m2"] = {"_key": "m2", "type": "module", "properties": {"module_name": "modB"}}
    gc._knowledge_nodes["fn1"] = {"_key": "fn1", "type": "local_function_definition", "properties": {"name": "foo"}}
    gc._knowledge_nodes["fn2"] = {"_key": "fn2", "type": "local_function_definition", "properties": {"name": "bar"}}
    gc._knowledge_nodes["fn3"] = {"_key": "fn3", "type": "local_function_definition", "properties": {"name": "baz"}}
    gc._knowledge_edges += [
        {"_from": "m1", "_to": "fn1", "relation": Edges.DECLARES.value},
        {"_from": "m2", "_to": "fn2", "relation": Edges.DECLARES.value},
        {"_from": "m2", "_to": "fn3", "relation": Edges.DECLARES.value},
    ]
    gc._create_indexes()
    assert "modA" in gc._module_index and "modB" in gc._module_index
    assert gc._export_index["modA"] == {"foo": "fn1"}
    assert gc._export_index["modB"] == {"bar": "fn2", "baz": "fn3"}


# ──────────────────────────────────────────────────────────────────────────────
# Section 12 — _find_declaration_node
# ──────────────────────────────────────────────────────────────────────────────

def test_find_declaration_node_returns_key_when_found(gc):
    gc._knowledge_nodes["fn:1"] = {"_key": "fn:1", "file_path": "/a.lua", "properties": {"name": "process"}}
    assert gc._find_declaration_node("/a.lua", "process") == "fn:1"


def test_find_declaration_node_returns_none_wrong_file(gc):
    gc._knowledge_nodes["fn:1"] = {"_key": "fn:1", "file_path": "/a.lua", "properties": {"name": "process"}}
    assert gc._find_declaration_node("/b.lua", "process") is None


def test_find_declaration_node_returns_none_wrong_name(gc):
    gc._knowledge_nodes["fn:1"] = {"_key": "fn:1", "file_path": "/a.lua", "properties": {"name": "process"}}
    assert gc._find_declaration_node("/a.lua", "parse") is None


def test_find_declaration_node_returns_none_empty_graph(gc):
    assert gc._find_declaration_node("/a.lua", "anything") is None


def test_find_declaration_node_node_without_properties_does_not_crash(gc):
    gc._knowledge_nodes["n1"] = {"_key": "n1", "file_path": "/a.lua"}
    assert gc._find_declaration_node("/a.lua", "anything") is None


def test_find_declaration_node_node_with_empty_properties_does_not_crash(gc):
    gc._knowledge_nodes["n1"] = {"_key": "n1", "file_path": "/a.lua", "properties": {}}
    assert gc._find_declaration_node("/a.lua", "anything") is None


# ──────────────────────────────────────────────────────────────────────────────
# Section 13 — _resolve_symbol
# ──────────────────────────────────────────────────────────────────────────────

def test_resolve_symbol_via_imports_map(gc):
    gc._export_index = {"math.utils": {"sqrt": "fn:sqrt:1"}}
    result = gc._resolve_symbol("sqrt", "/a.lua", imports={"sqrt": "math.utils"})
    assert result == "fn:sqrt:1"


def test_resolve_symbol_via_global_fallback(gc):
    gc._export_index = {"other.mod": {"helper": "fn:helper:1"}}
    result = gc._resolve_symbol("helper", "/a.lua", imports={})
    assert result == "fn:helper:1"


def test_resolve_symbol_returns_none_when_not_found(gc):
    gc._export_index = {}
    assert gc._resolve_symbol("unknown", "/a.lua", imports={}) is None


def test_resolve_symbol_imports_map_takes_priority_over_global(gc):
    gc._export_index = {
        "mod_a": {"add": "fn:add:modA"},
        "mod_b": {"add": "fn:add:modB"},
    }
    result = gc._resolve_symbol("add", "/a.lua", imports={"add": "mod_a"})
    assert result == "fn:add:modA"


def test_resolve_symbol_import_path_exists_but_symbol_not_in_module_exports(gc):
    gc._export_index = {"math.utils": {"otherFn": "fn:1"}}
    # "utils" is the var name mapped to "math.utils", but "utils" isn't exported by it
    result = gc._resolve_symbol("utils", "/a.lua", imports={"utils": "math.utils"})
    # falls through to global fallback — "utils" not in any module exports → None
    assert result is None


def test_resolve_symbol_empty_imports_uses_global(gc):
    gc._export_index = {"some.mod": {"calc": "fn:calc:1"}}
    assert gc._resolve_symbol("calc", "/a.lua", imports={}) == "fn:calc:1"


# ──────────────────────────────────────────────────────────────────────────────
# Section 14 — _resolve_cross_file_edges
# ──────────────────────────────────────────────────────────────────────────────

def test_resolve_cross_file_edges_empty_results(gc):
    gc._resolve_cross_file_edges()
    assert gc._knowledge_edges == []


def test_resolve_cross_file_edges_no_imports_no_unresolved(gc):
    gc.results["/a.lua"] = {"imports": {}, "unresolved_edges": {}}
    gc._resolve_cross_file_edges()
    assert gc._knowledge_edges == []


def test_resolve_cross_file_edges_creates_imports_edge(gc):
    fp = "/a.lua"
    # set up module in index
    gc._module_index["math.utils"] = "mod:math.utils"
    # set up declaration node for "localUtils" in file
    gc._knowledge_nodes["decl:localUtils"] = {
        "_key": "decl:localUtils",
        "file_path": fp,
        "properties": {"name": "localUtils"},
    }
    gc.results[fp] = {"imports": {"localUtils": "math.utils"}, "unresolved_edges": {}}
    gc._resolve_cross_file_edges()
    import_edges = [e for e in gc._knowledge_edges if e["relation"] == "imports"]
    assert len(import_edges) == 1
    assert import_edges[0]["_from"] == "decl:localUtils"
    assert import_edges[0]["_to"] == "mod:math.utils"


def test_resolve_cross_file_edges_unresolved_import_module_logs_error(gc, caplog):
    import logging
    gc.results["/a.lua"] = {"imports": {"x": "missing.module"}, "unresolved_edges": {}}
    with caplog.at_level(logging.ERROR):
        gc._resolve_cross_file_edges()
    assert gc._knowledge_edges == []
    assert any("missing.module" in r.message for r in caplog.records)


def test_resolve_cross_file_edges_unresolved_import_declaration_logs_error(gc, caplog):
    import logging
    gc._module_index["math.utils"] = "mod:1"
    gc.results["/a.lua"] = {"imports": {"utils": "math.utils"}, "unresolved_edges": {}}
    # no declaration node for "utils" exists
    with caplog.at_level(logging.ERROR):
        gc._resolve_cross_file_edges()
    assert gc._knowledge_edges == []


def test_resolve_cross_file_edges_resolves_unresolved_edge(gc):
    gc._export_index = {"mymod": {"sqrt": "fn:sqrt"}}
    gc.results["/a.lua"] = {
        "imports": {},
        "unresolved_edges": {
            "sqrt": [{"node_id": "call:1", "edge_type": "calls"}]
        },
    }
    gc._resolve_cross_file_edges()
    resolved = [e for e in gc._knowledge_edges if e["relation"] == "calls"]
    assert len(resolved) == 1
    assert resolved[0]["_from"] == "call:1"
    assert resolved[0]["_to"] == "fn:sqrt"


def test_resolve_cross_file_edges_unresolved_symbol_not_found_logs_error(gc, caplog):
    import logging
    gc.results["/a.lua"] = {
        "imports": {},
        "unresolved_edges": {"unknownFn": [{"node_id": "call:x", "edge_type": "calls"}]},
    }
    with caplog.at_level(logging.ERROR):
        gc._resolve_cross_file_edges()
    assert gc._knowledge_edges == []


def test_resolve_cross_file_edges_multiple_files(gc):
    for fp, mod, var in [("/a.lua", "mod.a", "aUtil"), ("/b.lua", "mod.b", "bUtil")]:
        mod_key = f"mod:{mod}"
        decl_key = f"decl:{var}"
        gc._module_index[mod] = mod_key
        gc._knowledge_nodes[decl_key] = {"_key": decl_key, "file_path": fp, "properties": {"name": var}}
        gc.results[fp] = {"imports": {var: mod}, "unresolved_edges": {}}
    gc._resolve_cross_file_edges()
    import_edges = [e for e in gc._knowledge_edges if e["relation"] == "imports"]
    assert len(import_edges) == 2


# ──────────────────────────────────────────────────────────────────────────────
# Section 15 — _compute_graph_metrics
# ──────────────────────────────────────────────────────────────────────────────

def test_compute_graph_metrics_creates_project_metric_node(gc):
    gc._compute_graph_metrics()
    assert "metric:project:1" in gc._knowledge_nodes


def test_compute_graph_metrics_project_node_type(gc):
    gc._compute_graph_metrics()
    assert gc._knowledge_nodes["metric:project:1"]["type"] == "metric"


def test_compute_graph_metrics_project_node_kind(gc):
    gc._compute_graph_metrics()
    assert gc._knowledge_nodes["metric:project:1"]["properties"]["kind"] == "project"


def test_compute_graph_metrics_project_node_has_expected_keys(gc):
    gc._compute_graph_metrics()
    props = gc._knowledge_nodes["metric:project:1"]["properties"]
    for key in ("num_files", "num_modules", "avg_functions_per_file", "avg_lines_per_function", "avg_comment_pct"):
        assert key in props, f"Missing key: {key}"


def test_compute_graph_metrics_no_functions_only_project_node(gc):
    gc._compute_graph_metrics()
    metric_nodes = [n for n in gc._knowledge_nodes.values() if n.get("type") == "metric"]
    assert len(metric_nodes) == 1


def test_compute_graph_metrics_new_function_metric_node_created(gc):
    gc._knowledge_nodes["fn:1"] = {
        "_key": "fn:1", "type": "local_function_definition",
        "file_path": "/a.lua", "start_byte": 0, "end_byte": 100, "properties": {}
    }
    gc._compute_graph_metrics()
    assert "metric:fn:1" in gc._knowledge_nodes


def test_compute_graph_metrics_new_function_metric_node_type(gc):
    gc._knowledge_nodes["fn:1"] = {
        "_key": "fn:1", "type": "local_function_definition",
        "file_path": "/a.lua", "start_byte": 0, "end_byte": 100, "properties": {}
    }
    gc._compute_graph_metrics()
    assert gc._knowledge_nodes["metric:fn:1"]["type"] == "metric"


def test_compute_graph_metrics_new_function_metric_node_kind(gc):
    gc._knowledge_nodes["fn:1"] = {
        "_key": "fn:1", "type": "local_function_definition",
        "file_path": "/a.lua", "start_byte": 0, "end_byte": 100, "properties": {}
    }
    gc._compute_graph_metrics()
    assert gc._knowledge_nodes["metric:fn:1"]["properties"]["kind"] == "function"


def test_compute_graph_metrics_has_metrics_edge_created_for_new_function(gc):
    gc._knowledge_nodes["fn:1"] = {
        "_key": "fn:1", "type": "local_function_definition",
        "file_path": "/a.lua", "start_byte": 0, "end_byte": 100, "properties": {}
    }
    gc._compute_graph_metrics()
    has_metrics_edges = [
        e for e in gc._knowledge_edges
        if e["relation"] == "has_metrics" and e["_to"] == "fn:1"
    ]
    assert len(has_metrics_edges) == 1
    assert has_metrics_edges[0]["_from"] == "metric:fn:1"


def test_compute_graph_metrics_updates_existing_metric_node_not_create_new(gc):
    gc._knowledge_nodes["fn:1"] = {
        "_key": "fn:1", "type": "local_function_definition",
        "file_path": "/a.lua", "start_byte": 0, "end_byte": 100, "properties": {}
    }
    existing_metric = {"_key": "m:existing", "type": "metric", "properties": {}}
    gc._knowledge_nodes["m:existing"] = existing_metric
    gc._knowledge_edges.append({"_from": "m:existing", "_to": "fn:1", "relation": "has_metrics"})
    gc._compute_graph_metrics()
    assert "metric:fn:1" not in gc._knowledge_nodes
    assert "dependency" in gc._knowledge_nodes["m:existing"]["properties"]


def test_compute_graph_metrics_existing_metric_edge_not_duplicated(gc):
    gc._knowledge_nodes["fn:1"] = {
        "_key": "fn:1", "type": "local_function_definition",
        "file_path": "/a.lua", "start_byte": 0, "end_byte": 100, "properties": {}
    }
    gc._knowledge_nodes["m:existing"] = {"_key": "m:existing", "type": "metric", "properties": {}}
    gc._knowledge_edges.append({"_from": "m:existing", "_to": "fn:1", "relation": "has_metrics"})
    before = len(gc._knowledge_edges)
    gc._compute_graph_metrics()
    new_has_metrics = [
        e for e in gc._knowledge_edges[before:]
        if e["relation"] == "has_metrics" and e["_to"] == "fn:1"
    ]
    assert new_has_metrics == []


# ──────────────────────────────────────────────────────────────────────────────
# Section 16 — _create_spine (needs real filesystem via tmp_path)
# ──────────────────────────────────────────────────────────────────────────────

def test_create_spine_directory_creates_directory_node(gc, tmp_path):
    gc._create_spine(str(tmp_path))
    types = {n.get("type") for n in gc._knowledge_nodes.values()}
    assert "directory" in types


def test_create_spine_single_file_creates_file_node(gc, tmp_path):
    (tmp_path / "a.lua").write_text("-- code")
    gc._create_spine(str(tmp_path))
    types = {n.get("type") for n in gc._knowledge_nodes.values()}
    assert "file" in types


def test_create_spine_nested_dir_creates_contains_edge(gc, tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "a.lua").write_text("-- code")
    gc._create_spine(str(tmp_path))
    contains_edges = [e for e in gc._knowledge_edges if e["relation"] == "contains"]
    assert len(contains_edges) >= 1


def test_create_spine_file_in_results_creates_is_edge(gc, tmp_path):
    fp = str(tmp_path / "a.lua")
    (tmp_path / "a.lua").write_text("-- code")
    gc.results[fp] = _make_result(fp)
    gc._create_spine(str(tmp_path))
    is_edges = [e for e in gc._knowledge_edges if e["relation"] == "is"]
    assert len(is_edges) >= 1


def test_create_spine_file_not_in_results_no_crash(gc, tmp_path):
    (tmp_path / "orphan.lua").write_text("-- code")
    gc._create_spine(str(tmp_path))  # should not raise
    types = {n.get("type") for n in gc._knowledge_nodes.values()}
    assert "directory" in types or "file" in types


def test_create_spine_id_counter_advances(gc, tmp_path):
    (tmp_path / "a.lua").write_text("-- code")
    gc._create_spine(str(tmp_path))
    assert gc.ast_id >= 2
    assert gc.knowledge_id >= 2


# ──────────────────────────────────────────────────────────────────────────────
# Section 17 — collect() integration without Ray
# ──────────────────────────────────────────────────────────────────────────────

def test_collect_empty_results_empty_directory(gc, tmp_path):
    gc.collect([], str(tmp_path))
    types = {n.get("type") for n in gc._knowledge_nodes.values()}
    assert "directory" in types


def test_collect_populates_results_dict(gc, tmp_path):
    fp = str(tmp_path / "a.lua")
    (tmp_path / "a.lua").write_text("-- code")
    gc.collect([_make_result(fp)], str(tmp_path))
    assert fp in gc.results


def test_collect_builds_module_index(gc, tmp_path):
    fp = str(tmp_path / "a.lua")
    (tmp_path / "a.lua").write_text("-- code")
    result = _make_result(fp, kg_vertices=[
        {"_key": "kg:chunk", "type": "chunk", "file_path": fp, "properties": {}},
        {"_key": "kg:mod", "type": "module", "properties": {"module_name": "my.mod"}},
    ])
    gc.collect([result], str(tmp_path))
    assert "my.mod" in gc._module_index


def test_collect_creates_project_metric_node(gc, tmp_path):
    fp = str(tmp_path / "a.lua")
    (tmp_path / "a.lua").write_text("-- code")
    gc.collect([_make_result(fp)], str(tmp_path))
    assert "metric:project:1" in gc._knowledge_nodes
