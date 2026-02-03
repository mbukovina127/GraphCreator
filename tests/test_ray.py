
import pytest
import tempfile
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# from ray_implementation.local_graph_queries import LocalGraphQueries
# from ray_implementation.local_output_builder import LocalOuputBuilder
# from ray_implementation.local_symbol_table import LocalSymbolTable
# from ray_implementation.parallel_ast_inserter import ParallelASTInserter
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




with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
    f.write(SAMPLE_LUA_SIMPLE)
    f.flush()

    ast_manager = ASTManager()
    ast_manager.clear()

    ast = ast_manager.parse(f.name)

    print(f"Number of code blocks: {ast.root_node.child_count} ")

    # local_graph_builder = LocalOuputBuilder()
    # lst = LocalSymbolTable(worker_id="worker_1")
    # para_ast_inserter = AST(local_graph_builder, lst, "worker_1", file_path=f.name)

    # para_ast_inserter.insert_nodes(ast.root_node, file=f.name)


    # local_graph_queries = LocalGraphQueries(local_graph_builder)
    # local_graph_queries.build_KG()

    # local_graph_builder.export_cpg_v1
