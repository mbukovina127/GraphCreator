import os
import sys
import tempfile
import zipfile

import pytest
import ray

from file_system_analyzer import analyze_project_structure
from ray_implementation.csv_graph_exporter import export_to_gephi_csv
from ray_implementation.builders.graph_collector import GraphCollector
from ray_implementation.managers.ray_orchestrator import RayOrchestrator

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from code_analyzer.parse_code import ParallelASTManager
from ray_implementation import CGPWorker
from ray_implementation.managers.graph_manager import GraphManager
from ray_implementation.structures import SymbolTable


# ──────────────────────────────────────────────────────────────────────────────
# Lua fixtures
# ──────────────────────────────────────────────────────────────────────────────

SAMPLE_LUA_SIMPLE = """
local x = 10
local y = 20
local z
w = 10

function add(a, b)
    return a + b
end

local result = add(x, y)
print(result)
"""

SAMPLE_LUA_TWO_FUNCTIONS = """
function add(a, b)
    return a + b
end

function subtract(a, b)
    return a - b
end
"""

SAMPLE_LUA_VARIABLES_ONLY = """
local x = 10
local y = 20
print(x + y)
"""

SAMPLE_LUA_MODULE = """
function addition(a, b)
    return a + b
end

module "math.premium"

function subtract(a, b)
    result = a - b
    return result
end

results = 0
"""

SAMPLE_LUA_REQUIRE = """
local lpeg  = require 'lpeg'
local utils = require("math.utils")

function process(data)
    return utils
end
"""

SAMPLE_LUA_COMPLEX = """
GLOBAL_CONST = 42
local math_utils = require("math.utils")

local x = 10
local y = 20

function add(a, b)
    return a + b
end

local function classify(n)
    if n > 0 then
        return "positive"
    elseif n < 0 then
        return "negative"
    else
        return "zero"
    end
end

function accumulate(limit)
    local sum = 0
    for i = 1, limit do
        sum = sum + i
    end
    while sum > 100 do
        sum = sum / 2
    end
    return sum
end

z = add(x, y)
local classification = classify(z)
"""


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def create_temp_lua(lua_code: str) -> str:
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False)
    f.write(lua_code)
    f.flush()
    f.close()
    return f.name


# ──────────────────────────────────────────────────────────────────────────────
# Ray fixture — one cluster for the entire test session
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def ray_cluster():
    src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src'))
    ray.init(ignore_reinit_error=True, runtime_env={"env_vars": {"PYTHONPATH": src_path}})
    yield
    ray.shutdown()


# ──────────────────────────────────────────────────────────────────────────────
# AST Manager
# ──────────────────────────────────────────────────────────────────────────────

def test_parallel_ast_manager():
    file_path = create_temp_lua(SAMPLE_LUA_SIMPLE)
    try:
        ast_manager = ParallelASTManager(file_path)
        ast = ast_manager.parse(file_path)
        assert ast is not None
        assert ast.root_node is not None
        assert ast.root_node.type == "chunk"
    finally:
        os.unlink(file_path)


# ──────────────────────────────────────────────────────────────────────────────
# GraphManager
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("test_code", [
    SAMPLE_LUA_SIMPLE,
    SAMPLE_LUA_VARIABLES_ONLY,
    SAMPLE_LUA_TWO_FUNCTIONS,
])
def test_graph_manager_result_shape(test_code):
    """get_graphs() must return all expected keys with non-empty graph data."""
    file_path = create_temp_lua(test_code)
    try:
        lst = SymbolTable("1")
        ast = ParallelASTManager(file_path).parse(file_path)
        gm = GraphManager(lst)
        gm.generate_graph(ast, file_path)
        result = gm.get_graphs()

        assert "file" in result
        assert "ast_graph" in result
        assert "knowledge_graph" in result
        assert "unresolved_edges" in result
        assert "exports" in result
        assert "imports" in result

        assert len(result["ast_graph"]["vertices"]) > 0
        assert len(result["knowledge_graph"]["vertices"]) > 0
        assert result["file"] == file_path
    finally:
        os.unlink(file_path)


def test_graph_manager_unresolved_edges_is_dict():
    """unresolved_edges must be a dict (from CPGBuilder), not a list."""
    file_path = create_temp_lua(SAMPLE_LUA_SIMPLE)
    try:
        lst = SymbolTable("1")
        ast = ParallelASTManager(file_path).parse(file_path)
        gm = GraphManager(lst)
        gm.generate_graph(ast, file_path)
        result = gm.get_graphs()
        assert isinstance(result["unresolved_edges"], dict)
    finally:
        os.unlink(file_path)


def test_graph_manager_imports_populated_for_require():
    """Files with require() calls must have populated imports dict."""
    file_path = create_temp_lua(SAMPLE_LUA_REQUIRE)
    try:
        lst = SymbolTable("1")
        ast = ParallelASTManager(file_path).parse(file_path)
        gm = GraphManager(lst)
        gm.generate_graph(ast, file_path)
        result = gm.get_graphs()

        assert isinstance(result["imports"], dict)
        assert "lpeg" in result["imports"]
        assert result["imports"]["lpeg"] == "lpeg"
        assert "utils" in result["imports"]
        assert result["imports"]["utils"] == "math.utils"
    finally:
        os.unlink(file_path)


def test_graph_manager_module_creates_knowledge_node():
    """Files with a module declaration should have a 'module' knowledge node."""
    file_path = create_temp_lua(SAMPLE_LUA_MODULE)
    try:
        lst = SymbolTable("1")
        ast = ParallelASTManager(file_path).parse(file_path)
        gm = GraphManager(lst)
        gm.generate_graph(ast, file_path)
        result = gm.get_graphs()

        kg_vertices = result["knowledge_graph"]["vertices"]
        module_nodes = [n for n in kg_vertices if n.get("type") == "module"]
        assert len(module_nodes) >= 1
        assert module_nodes[0].get("properties", {}).get("module_name") == "math.premium"
    finally:
        os.unlink(file_path)


def test_graph_manager_raises_if_not_run():
    """get_graphs() before generate_graph() should raise RuntimeError."""
    lst = SymbolTable("1")
    gm = GraphManager(lst)
    with pytest.raises(RuntimeError):
        gm.get_graphs()


def test_graph_manager_clear_resets_state():
    """After clear(), get_graphs() should raise again."""
    file_path = create_temp_lua(SAMPLE_LUA_SIMPLE)
    try:
        lst = SymbolTable("1")
        ast = ParallelASTManager(file_path).parse(file_path)
        gm = GraphManager(lst)
        gm.generate_graph(ast, file_path)
        gm.clear()
        with pytest.raises(RuntimeError):
            gm.get_graphs()
    finally:
        os.unlink(file_path)


# ──────────────────────────────────────────────────────────────────────────────
# CGPWorker (Ray Actor)
# ──────────────────────────────────────────────────────────────────────────────

def test_cpg_worker_result_shape():
    file_path = create_temp_lua(SAMPLE_LUA_SIMPLE)
    try:
        worker = CGPWorker.remote("test_worker_1")
        result = ray.get(worker.analyze_file.remote(file_path))

        assert result is not None
        assert "ast_graph" in result
        assert "knowledge_graph" in result
        assert "unresolved_edges" in result
        assert "imports" in result
        assert "exports" in result

        assert len(result["ast_graph"]["vertices"]) > 0
        assert len(result["knowledge_graph"]["vertices"]) > 0
    finally:
        os.unlink(file_path)


def test_cpg_worker_is_stateless_between_calls():
    """Each analyze_file() call should produce independent results for the same file."""
    file_path = create_temp_lua(SAMPLE_LUA_SIMPLE)
    try:
        worker = CGPWorker.remote("test_worker_2")
        r1 = ray.get(worker.analyze_file.remote(file_path))
        r2 = ray.get(worker.analyze_file.remote(file_path))
        assert len(r1["knowledge_graph"]["vertices"]) == len(r2["knowledge_graph"]["vertices"])
    finally:
        os.unlink(file_path)


@pytest.mark.parametrize("test_code", [
    SAMPLE_LUA_SIMPLE,
    SAMPLE_LUA_TWO_FUNCTIONS,
    SAMPLE_LUA_MODULE,
])
def test_cpg_worker_various_inputs(test_code):
    file_path = create_temp_lua(test_code)
    try:
        worker = CGPWorker.remote("test_worker_3")
        result = ray.get(worker.analyze_file.remote(file_path))
        assert result is not None
        assert len(result["knowledge_graph"]["vertices"]) > 0
    finally:
        os.unlink(file_path)


# ──────────────────────────────────────────────────────────────────────────────
# RayOrchestrator
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("test_code", [
    SAMPLE_LUA_SIMPLE,
    SAMPLE_LUA_VARIABLES_ONLY,
    SAMPLE_LUA_TWO_FUNCTIONS,
    SAMPLE_LUA_MODULE,
])
def test_orchestrator_result_shape(test_code):
    file_path = create_temp_lua(test_code)
    try:
        orchestrator = RayOrchestrator()
        orchestrator.create_workers(1)
        futures = orchestrator.distribute_work([{"path": file_path}])
        results = ray.get(futures)

        assert len(results) == 1
        result = results[0]
        assert result is not None
        assert len(result["ast_graph"]["vertices"]) > 0
        assert len(result["knowledge_graph"]["vertices"]) > 0
    finally:
        os.unlink(file_path)
        orchestrator.workers = []  # clear workers without shutting down Ray


def test_orchestrator_distributes_to_multiple_workers():
    """Work should be spread across workers round-robin."""
    files = [create_temp_lua(SAMPLE_LUA_SIMPLE) for _ in range(4)]
    try:
        orchestrator = RayOrchestrator()
        orchestrator.create_workers(2)
        futures = orchestrator.distribute_work([{"path": f} for f in files])
        assert len(futures) == 4
        results = ray.get(futures)
        assert all(r is not None for r in results)
        assert all(len(r["knowledge_graph"]["vertices"]) > 0 for r in results)
    finally:
        for f in files:
            os.unlink(f)
        orchestrator.workers = []


def test_orchestrator_raises_without_workers():
    orchestrator = RayOrchestrator()
    with pytest.raises(IndexError):
        orchestrator.distribute_work([{"path": "dummy.lua"}])


# ──────────────────────────────────────────────────────────────────────────────
# GraphCollector
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_zip():
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
        zip_path = f.name
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr("src/main.lua", SAMPLE_LUA_SIMPLE)
            zf.writestr("src/utils.lua", SAMPLE_LUA_TWO_FUNCTIONS)
            zf.writestr("src/premium/math.lua", SAMPLE_LUA_MODULE)
    yield zip_path
    os.unlink(zip_path)


@pytest.fixture
def module_zip():
    """ZIP with a module that another file requires."""
    provider = """
module "math.utils"
function sqrt(x)
    return x
end
"""
    consumer = """
local utils = require("math.utils")
function process(data)
    return utils.sqrt(data)
end
"""
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
        zip_path = f.name
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr("src/provider.lua", provider)
            zf.writestr("src/consumer.lua", consumer)
    yield zip_path
    os.unlink(zip_path)


def _extract_and_collect(zip_path: str) -> tuple[GraphCollector, list]:
    temp_dir = tempfile.mkdtemp(prefix="test_gc_")
    extract_dir = os.path.join(temp_dir, "extract")
    os.makedirs(extract_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_dir)

    project_structure = analyze_project_structure(extract_dir)
    files = [x for x in project_structure if x["type"] == "file"]

    orchestrator = RayOrchestrator()
    orchestrator.create_workers(2)
    futures = orchestrator.distribute_work(files)
    results = ray.get(futures)
    orchestrator.workers = []

    gc = GraphCollector()
    gc.collect(results, extract_dir)
    return gc, results


def test_graph_collector_collects_all_files(sample_zip):
    gc, results = _extract_and_collect(sample_zip)
    assert len(results) == 3
    assert len(gc._knowledge_nodes) > 0
    assert len(gc._knowledge_edges) > 0


def test_graph_collector_spine_has_directory_and_file_nodes(sample_zip):
    gc, _ = _extract_and_collect(sample_zip)
    types = {n.get("type") for n in gc._knowledge_nodes.values()}
    assert "directory" in types or "file" in types


def test_graph_collector_module_index_populated(sample_zip):
    gc, _ = _extract_and_collect(sample_zip)
    # SAMPLE_LUA_MODULE declares module "math.premium"
    assert "math.premium" in gc._module_index


def test_graph_collector_export_to_gephi(sample_zip):
    """export_to_gephi_csv should not raise."""
    gc, _ = _extract_and_collect(sample_zip)
    nodes = gc._knowledge_nodes.values()
    edges = gc._knowledge_edges
    export_to_gephi_csv(nodes, edges, "k_nodes.csv", "k_edges.csv")


def test_graph_collector_cross_file_module_resolved(module_zip):
    """
    consumer.lua requires math.utils from provider.lua.
    After collection, an 'imports' edge should link them.
    """
    gc, _ = _extract_and_collect(module_zip)
    import_edges = [e for e in gc._knowledge_edges if e.get("relation") == "imports"]
    nodes = gc._knowledge_nodes.values()
    edges = gc._knowledge_edges
    export_to_gephi_csv(nodes, edges, "k_nodes.csv", "k_edges.csv")
    assert len(import_edges) >= 1, (
        "Expected at least one 'imports' edge after cross-file resolution"
    )
def test_big_repository():
    zip_path = os.path.join(os.path.dirname(__file__), "resources", "test_lua.zip")
    gc, _ = _extract_and_collect(zip_path)
    import_edges = [e for e in gc._knowledge_edges if e.get("relation") == "imports"]
    nodes = gc._knowledge_nodes.values()
    edges = gc._knowledge_edges
    export_to_gephi_csv(nodes, edges, "k_nodes.csv", "k_edges.csv")