import pytest
import tempfile
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from code_analyzer import ASTManager
from ray_implementation import SymbolBuilder, CPGBuilder, LocalOuputBuilder, SymbolTable

SAMPLE_LUA_VAR_VERY_SIMPLE = """
local a = 5
a = 1
"""

# 3 symbols, 2 scope, 2 contains, 4 referes_to edges, 2 has_argument edges.... a lot is going on
SAMPLE_LUA_FUN_VERY_SIMPLE = """
local function add(a,b)
    return a + b
add(a,b)
"""

SAMPLE_LUA_VAR_SIMPLE = """
local x = 10
local y = 1 + 1
local z = y + 5
local w

GLOBAL = 100

x = 1
y = 2
w = 10

-- undefined
a = x
"""

SAMPLE_LUA_BASIC = """
-- 
local x = 10
local y = 5

-- function that adds two numbers
local function add(a,b)
    local result
    result = a + b
    return result

print(add(x,y))
"""

with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
    f.write(SAMPLE_LUA_BASIC)
    f.flush()
    
    ast = ASTManager().parse(f.name)
    
    localBuilder = LocalOuputBuilder()
    lst = SymbolTable("1")


    symbolmanager = SymbolBuilder(local_builder=localBuilder, lst=lst, file_path=f.name)

    symbolmanager.walk(ast.root_node)

    knowledge_graph_creator = CPGBuilder(localBuilder, lst)
    knowledge_graph_creator.build_cpg(ast.root_node, f.name)

    print(lst.exports.__len__())


class TestSymbolCreation:

    def test_simple_variable_declaration(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
            f.write(SAMPLE_LUA_VAR_VERY_SIMPLE)
            f.flush()
            parser = ASTManager()
            builder = LocalOuputBuilder()
            lst = SymbolTable("1")
            ast = parser.parse(f.name)

            symbolmanager = SymbolBuilder(local_builder=builder, lst=lst, file_path=f.name)

            symbolmanager.walk(ast.root_node)

            assert lst.exports.__len__() == 1  # 'a' declared and assigned
            assert lst.scopes.__len__() == 1


    def test_simple_function_definition(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
            f.write(SAMPLE_LUA_FUN_VERY_SIMPLE)
            f.flush()
            parser = ASTManager()
            builder = LocalOuputBuilder()
            lst = SymbolTable("1")
            ast = parser.parse(f.name)

            symbolmanager = SymbolBuilder(local_builder=builder, lst=lst, file_path=f.name)

            symbolmanager.walk(ast.root_node)

            assert lst.exports.__len__() == 3  # 3 symbols
            assert lst.scopes.__len__() == 2

class TestCPGBuilder:

    def test_simple_variable(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
            f.write(SAMPLE_LUA_VAR_VERY_SIMPLE)
            f.flush()
            parser = ASTManager()
            builder = LocalOuputBuilder()
            lst = SymbolTable("1")
            ast = parser.parse(f.name)
            cpg_builder = CPGBuilder(builder, lst)

            symbolmanager = SymbolBuilder(local_builder=builder, lst=lst, file_path=f.name)

            symbolmanager.walk(ast.root_node)

            cpg_builder.build_cpg(ast.root_node, f.name)

            assert builder._knowledge_nodes.__len__() == 4 # chunk and variable declaration + 2 identifiers
            assert builder._knowledge_edges.__len__() == 3 # chunk contains variable, variable declared, variable assigned

    #TODO add block processing return statement, parameter relation, unresolved edges
    def test_simple_function(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
            f.write(SAMPLE_LUA_FUN_VERY_SIMPLE)
            f.flush()
            parser = ASTManager()
            builder = LocalOuputBuilder()
            lst = SymbolTable("1")
            ast = parser.parse(f.name)
            cpg_builder = CPGBuilder(builder, lst)

            symbolmanager = SymbolBuilder(local_builder=builder, lst=lst, file_path=f.name)

            symbolmanager.walk(ast.root_node)

            cpg_builder.build_cpg(ast.root_node, f.name)

            print(builder._knowledge_nodes.__len__())
            print(builder._knowledge_edges.__len__())
