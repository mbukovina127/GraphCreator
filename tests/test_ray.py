
import pytest
import tempfile
import sys
import os

import ray

from ray_implementation.ray_orchestrator import RayOrchestrator

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


from code_analyzer.parse_code import ParallelASTManager
from ray_implementation import GraphManager, SymbolTable, CGPWorker

from code_analyzer import ASTManager


SAMPLE_LUA_SIMPLE = '''
-- Simple Lua file for testing
local x = 10
local y = 20
local z
w = 10

function add(a, b)
    return a + b
end

local result = add(x, y)
print(result)
'''

SAMPLE_LUA_COMPLEX = """
-- Comprehensive Lua test file
-- Exercises AST parsing, graph building, and knowledge graph logic

-- Global variable
GLOBAL_CONST = 42

-- Required module
local math_utils = require("math_utils")

-- Local variables
local x = 10
local y = 20
local z

-- Global function
function add(a, b)
    return a + b
end

-- Local function with parameters and control flow
local function classify(n)
    if n > 0 then
        return "positive"
    elseif n < 0 then
        return "negative"
    else
        return "zero"
    end
end

-- Function with loop constructs
function accumulate(limit)
    local sum = 0

    for i = 1, limit do
        sum = sum + i
    end

    while sum > 100 do
        sum = sum / 2
    end

    repeat
        sum = sum + 1
    until sum >= 50

    return sum
end

-- Function using varargs
local function log_all(...)
    local args = {...}
    for i = 1, #args do
        print(args[i])
    end
end

-- Nested function calls and assignments
z = add(x, y)
local classification = classify(z)

-- Dot index expression and function call
local sqrt_value = math_utils.sqrt(z)

-- Block with mixed statements
do
    local inner = accumulate(10)

    if inner > GLOBAL_CONST then
        log_all(inner, classification, sqrt_value)
    else
        print("Value is small")
    end
end

-- Final return-like statement (top-level laststat)
print("Done")
"""



def create_temp_lua(lua_code: str) -> str:
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False)
    f.write(lua_code)
    f.flush()
    f.close()
    return f.name

def test_parallel_ast_manager():
    file_path = create_temp_lua(SAMPLE_LUA_SIMPLE)
    try:
        ast_manager = ParallelASTManager(file_path)
        ast = ast_manager.parse(file_path)
    finally:
        os.unlink(file_path)

def test_graph_manager():
    file_path = create_temp_lua(SAMPLE_LUA_SIMPLE)

    try:
        lst = SymbolTable("1")
        ast = ParallelASTManager(file_path).parse(file_path)

        graph_manager = GraphManager(lst)

        graph_manager.generate_graph(ast, file_path)

        result = graph_manager.get_graphs()

        assert result.__len__() > 0

    finally:
        os.unlink(file_path)

def test_cpg_worker():
    file_path = create_temp_lua(SAMPLE_LUA_SIMPLE)

    ray.init()

    worker = CGPWorker.remote("1")

    future = worker.analyze_file.remote(file_path)

    result = ray.get(future)

    assert result['ast_graph'].__len__() > 0
    assert result['cpg_graph'].__len__() > 0

def test_orchestrator():
    file_path = create_temp_lua(SAMPLE_LUA_SIMPLE)

    ray_orchestrator = RayOrchestrator()
    ray_orchestrator.create_workers(1)
    futures = ray_orchestrator.distribute_work([file_path])
    result = ray.get(futures)

    assert result[0]['ast_graph'].__len__() > 0
    assert result[0]['cpg_graph'].__len__() > 0
