"""
Unit tests for Code Analyzer (AST parsing and metrics).
"""

import os
import sys
import tempfile
import pytest

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from code_analyzer.parse_code import ASTManager
from code_analyzer.ast_metrics.cycl_complexity import calculate_cyclomatic_complexity
from code_analyzer.ast_metrics.halstead_metrics import calculate_halstead_metrics
from code_analyzer.ast_metrics.loc import calculate_loc


# Sample Lua code for testing
SIMPLE_LUA = '''
local x = 10
local y = 20
print(x + y)
'''

FUNCTION_LUA = '''
function add(a, b)
    return a + b
end

function subtract(a, b)
    return a - b
end
'''

CONTROL_FLOW_LUA = '''
function test(x)
    if x > 0 then
        return "positive"
    elseif x < 0 then
        return "negative"
    else
        return "zero"
    end
end

function loop(n)
    local sum = 0
    for i = 1, n do
        sum = sum + i
    end
    while sum > 100 do
        sum = sum / 2
    end
    return sum
end
'''


class TestASTManager:
    """Tests for ASTManager class"""
    
    def test_singleton(self):
        """Test that ASTManager is a singleton"""
        manager1 = ASTManager()
        manager2 = ASTManager()
        assert manager1 is manager2
    
    def test_parse_simple_file(self):
        """Test parsing a simple Lua file"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
            f.write(SIMPLE_LUA)
            f.flush()
            
            manager = ASTManager()
            manager._ast_dict.clear()  # Clear previous state
            
            ast = manager.parse(f.name)
            assert ast is not None
            assert ast.root_node.type == "chunk"
            
            f.close()
            os.unlink(f.name)
    
    def test_parse_function_file(self):
        """Test parsing a file with functions"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
            f.write(FUNCTION_LUA)
            f.flush()
            
            manager = ASTManager()
            manager._ast_dict.clear()
            
            ast = manager.parse(f.name)
            root = ast.root_node
            
            # Should have function_declaration children
            func_decls = [c for c in root.children if c.type == "function_declaration"]
            assert len(func_decls) == 2
            
            f.close()
            os.unlink(f.name)
    
    def test_get_ast(self):
        """Test retrieving a previously parsed AST"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
            f.write(SIMPLE_LUA)
            f.flush()
            
            manager = ASTManager()
            manager._ast_dict.clear()
            
            manager.parse(f.name)
            ast = manager.get_ast(f.name)
            
            assert ast is not None
            assert ast.root_node.type == "chunk"
            
            f.close()
            os.unlink(f.name)
    
    def test_get_ast_not_parsed(self):
        """Test error when getting AST for unparsed file"""
        manager = ASTManager()
        manager._ast_dict.clear()
        
        with pytest.raises(ValueError, match="No ASTs"):
            manager.get_ast("/nonexistent/file.lua")
    
    def test_incremental_parsing(self):
        """Test incremental parsing"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
            f.write(SIMPLE_LUA)
            f.flush()
            
            manager = ASTManager()
            manager._ast_dict.clear()
            
            # First parse
            ast1 = manager.parse(f.name)
            
            # Modify file
            with open(f.name, 'w') as f2:
                f2.write(SIMPLE_LUA + "\nlocal z = 30")
            
            # Incremental parse
            ast2 = manager.parse(f.name, incremental=True)
            
            assert ast2 is not None
            
            f.close()
            os.unlink(f.name)


class TestCyclomaticComplexity:
    """Tests for cyclomatic complexity calculation"""
    
    def test_simple_code(self):
        """Test CC of simple code without control flow"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
            f.write(SIMPLE_LUA)
            f.flush()
            
            manager = ASTManager()
            manager._ast_dict.clear()
            ast = manager.parse(f.name)
            
            cc = calculate_cyclomatic_complexity(ast.root_node)
            assert cc == 1  # Base complexity
            
            f.close()
            os.unlink(f.name)
    
    def test_function_with_control_flow(self):
        """Test CC of code with control flow"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
            f.write(CONTROL_FLOW_LUA)
            f.flush()
            
            manager = ASTManager()
            manager._ast_dict.clear()
            ast = manager.parse(f.name)
            
            cc = calculate_cyclomatic_complexity(ast.root_node)
            # if + elseif + for + while = 4 decision points + 1 base = 5
            assert cc == 5
            
            f.close()
            os.unlink(f.name)
    
    def test_single_if(self):
        """Test CC with single if statement"""
        code = '''
        function test(x)
            if x then
                return true
            end
            return false
        end
        '''
        with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
            f.write(code)
            f.flush()
            
            manager = ASTManager()
            manager._ast_dict.clear()
            ast = manager.parse(f.name)
            
            cc = calculate_cyclomatic_complexity(ast.root_node)
            assert cc == 2  # 1 base + 1 if
            
            f.close()
            os.unlink(f.name)


class TestHalsteadMetrics:
    """Tests for Halstead metrics calculation"""
    
    def test_simple_code(self):
        """Test Halstead metrics of simple code"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
            f.write(SIMPLE_LUA)
            f.flush()
            
            manager = ASTManager()
            manager._ast_dict.clear()
            ast = manager.parse(f.name)
            
            metrics = calculate_halstead_metrics(ast.root_node)
            
            assert "n1" in metrics  # distinct operators
            assert "n2" in metrics  # distinct operands
            assert "N1" in metrics  # total operators
            assert "N2" in metrics  # total operands
            assert "V" in metrics   # volume
            assert "D" in metrics   # difficulty
            assert "E" in metrics   # effort
            assert "T" in metrics   # time
            assert "B" in metrics   # bugs
            
            assert metrics["n1"] > 0
            assert metrics["n2"] > 0
            
            f.close()
            os.unlink(f.name)
    
    def test_function_code(self):
        """Test Halstead metrics of function code"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
            f.write(FUNCTION_LUA)
            f.flush()
            
            manager = ASTManager()
            manager._ast_dict.clear()
            ast = manager.parse(f.name)
            
            metrics = calculate_halstead_metrics(ast.root_node)
            
            # Functions should have more operators (function, return, end, etc.)
            assert metrics["n1"] >= 3  # At least function, return, end
            
            f.close()
            os.unlink(f.name)
    
    def test_empty_node(self):
        """Test Halstead metrics with minimal code"""
        code = "-- just a comment"
        with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
            f.write(code)
            f.flush()
            
            manager = ASTManager()
            manager._ast_dict.clear()
            ast = manager.parse(f.name)
            
            metrics = calculate_halstead_metrics(ast.root_node)
            
            # Should handle empty/minimal code gracefully
            assert metrics["V"] >= 0
            assert metrics["E"] >= 0
            
            f.close()
            os.unlink(f.name)


class TestLOC:
    """Tests for lines of code calculation"""
    
    def test_simple_code(self):
        """Test LOC of simple code"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
            f.write(SIMPLE_LUA)
            f.flush()
            
            manager = ASTManager()
            manager._ast_dict.clear()
            ast = manager.parse(f.name)
            
            loc = calculate_loc(ast.root_node)
            
            # LOC counts non-empty lines in the AST
            # SIMPLE_LUA has 4 lines total (including empty first line from triple-quote)
            assert loc >= 3  # At least 3 non-empty lines
            
            f.close()
            os.unlink(f.name)
    
    def test_function_code(self):
        """Test LOC of function code"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False) as f:
            f.write(FUNCTION_LUA)
            f.flush()
            
            manager = ASTManager()
            manager._ast_dict.clear()
            ast = manager.parse(f.name)
            
            loc = calculate_loc(ast.root_node)
            
            # LOC counts lines in the AST (includes all lines)
            assert loc >= 6  # At least 6 lines of actual code
            
            f.close()
            os.unlink(f.name)
