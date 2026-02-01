import pytest
import tempfile
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from code_analyzer import ASTManager
from ray_implementation import SymbolBuilder, CPGBuilder, LocalOuputBuilder, SymbolTable

SAMPLE_LUA_VERY_SIMPLE = """
local a = 5
a = 1
"""

with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
    f.write(SAMPLE_LUA_VERY_SIMPLE)
    f.flush()
    
    ast = ASTManager().parse(f.name)
    
    localBuilder = LocalOuputBuilder()
    lst = SymbolTable("1")


    symbolmanager = SymbolBuilder(local_builder=localBuilder, lst=lst, file_path=f.name)

    symbolmanager.walk(ast.root_node)

    knowledge_graph_creator = CPGBuilder(localBuilder, lst)
    knowledge_graph_creator.build_cpg(ast.root_node, f.name)
    print()


