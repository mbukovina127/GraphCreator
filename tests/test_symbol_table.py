import logging

import pytest
import tempfile
import sys
import os

from code_analyzer.parse_code import ParallelASTManager
from src.ray_implementation import bloatedmess

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from code_analyzer import ASTManager
from ray_implementation import SymbolBuilder, CPGBuilder, LocalOutputBuilder, SymbolTable

SAMPLE_LUA_VAR_VERY_SIMPLE = """
local a = 5
a = 1
"""

# 3 symbols, 2 scope, 2 contains, 4 referes_to edges, 2 has_argument edges.... a lot is going on
SAMPLE_LUA_FUN_VERY_SIMPLE = """
local function add(a,b)
    print(a)
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

SAMPLE_LUA_CONTROL_FLOW = """
"""

SAMPLE_LUA_BASIC = """
-- 
local x = 10
local y = 5
local z = 3 + (10 + 2) 

y = x

-- function that adds two numbers
local function add(a,b)
    local result
    result = a + b
    return result
    
local return_value = add(1,2)
print(add(x,y))
"""
SAMPLE_LUA_MODULE = """
module 'leg.parsing'
            
--this should not be in module
local function add(x,y)
    return x + y
end

--this should be in module
function parse(file)
    local output
    tree-sitting(file, output)
    return output 
end

"""
SAMPLE_LUA_COMPLEX = """
local assert  = assert
local pairs   = pairs
local type    = type

-- imported modules
local lpeg = require 'lpeg'

-- imported functions
local P, V = lpeg.P, lpeg.V

-- module declaration
module 'leg.grammar'

--[[ 
Returns a pattern which matches any of the patterns received.

**Example:**
``
local g, s, m = require 'leg.grammar', require 'leg.scanner', require 'lpeg'

-- -- match numbers or operators, capture the numbers
print( (g.anyOf { '+', '-', '%*', '/', m.C(s.NUMBER) }):match '34.5@23 %* 56 / 45 - 45' )
-- --> prints 34.5
``

**Parameters:**
* `list`: a list of zero or more LPeg patterns or values which can be fed to [http://www.inf.puc-rio.br/~roberto/lpeg.html#lpeg lpeg.P].

**Returns:**
* a pattern which matches any of the patterns received.
--]]
function anyOf(list)
  local patt = P(false)
  
  for i = 1, #list, 1 do
    patt = P(list[i]) + patt
  end
  
  return patt
end

--[=[
Returns a pattern which matches a list of `patt`s, separated by `sep`.

local assert  = assert
local pairs   = pairs
local type    = ty
**Example:** matching comma-separated values:
``
local g, m = require 'leg.grammar', require 'lpeg'

-- -- separator
local sep = m.P',' + m.P'\n'

-- -- element: anything but sep, capture it
local elem = m.C((1 - sep)^0)

-- -- pattern
local patt = g.listOf(elem, sep)

-- -- matching
print( patt:match %[%[a, b, 'christmas eve'
  d, evening; mate!
  f%]%])
-- --> prints out "a        b       'christmas eve'  d        evening; mate! f"
``

**Parameters:**
* `patt`: a LPeg pattern.
* `sep`: a LPeg pattern.

**Returns:**
* the following pattern: ``patt %* (sep %* patt)^0``
--]=]
function listOf(patt, sep)
  patt, sep = P(patt), P(sep)
  
  return patt * (sep * patt)^0
end


--[[ 
A capture function, made so that `patt / C` is equivalent to `m.C(patt)`. It's intended to be used in capture tables, such as those required by [#function_pipe pipe] and [#function_apply apply].
--]]
function C(...) return ... end

--[[ 
A capture function, made so that `patt / Ct` is equivalent to `m.Ct(patt)`. It's intended to be used in capture tables, such as those required by [#function_pipe pipe] and [#function_apply apply].
--]]
function Ct(...) return { ... } end

--[[
Creates a shallow copy of `grammar`.

**Parameters:**
* `grammar`: a regular table.

**Returns:**
* a newly created table, with `grammar`'s keys and values.
--]]
function copy(grammar)
	local newt = {}
  
	for k, v in pairs(grammar) do
		newt[k] = v
	end
  
	return newt
end

--[[
[#section_Completing Completes] `dest` with `orig`.

**Parameters:**
* `dest`: the new grammar. Must be a table.
* `orig`: the original grammar. Must be a table.

**Returns:**
* `dest`, with new rules inherited from `orig`.
--]]
function complete (dest, orig)
	for rule, patt in pairs(orig) do
		if not dest[rule] then
			dest[rule] = patt
		end
	end
  
	return dest
end

--[[
[#section_Piping Pipes] the captures in `orig` to the ones in `dest`.

`dest` and `orig` should be tables, with each key storing a capture function. Each capture in `dest` will be altered to use the results for the matching one in `orig` as input, using function composition. Should `orig` possess keys not in `dest`, `dest` will copy them.

**Parameters:**
* `dest`: a capture table.
* `orig`: a capture table.

**Returns:**
* `dest`, suitably modified.
--]]
function pipe (dest, orig)
	for k, vorig in pairs(orig) do
		local vdest = dest[k]
		if vdest then
			dest[k] = function(...) return vdest(vorig(...)) end
		else
			dest[k] = vorig
		end
	end
	
	return dest
end

--[[
[#section_Completing Completes] `rules` with `grammar` and then [#Applying applies] `captures`.     

`rules` can either be:
* a single pattern, which is taken to be the new initial rule, 
* a possibly incomplete LPeg grammar, as per [#function_complete complete], or 
* `nil`, which means no new rules are added.

`captures` can either be:
* a capture table, as per [#function_pipe pipe], or
* `nil`, which means no captures are applied.

**Parameters:**
* `grammar`: the old grammar. It stays unmodified.
* `rules`: optional, the new rules. 
* `captures`: optional, the final capture table.

**Returns:**
* `rules`, suitably augmented by `grammar` and `captures`.
--]]
function apply (grammar, rules, captures)
  if rules == nil then
    rules = {}
  elseif type(rules) ~= 'table' then
    rules = { rules }
  end
  
  complete(rules, grammar)
  
  if type(grammar[1]) == 'string' then
    rules[1] = lpeg.V(grammar[1])
  end
	
	if captures ~= nil then
		assert(type(captures) == 'table', 'captures must be a table')
    
		for rule, cap in pairs(captures) do
			rules[rule] = rules[rule] / cap
		end
	end
  
	return rules
end
"""
def create_temp_lua(lua_code: str) -> str:
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False)
    f.write(lua_code)
    f.flush()
    f.close()
    return f.name

def build_context(lua_code: str):
    file_name = create_temp_lua(lua_code)
    parser = ParallelASTManager("1")
    builder = LocalOutputBuilder()
    lst = SymbolTable("1")

    ast = parser.parse(file_name)

    sym_builder = SymbolBuilder(
        local_builder=builder,
        lst=lst,
        file_path=file_name
    )
    cpg_builder = CPGBuilder(builder, lst, file_name)

    return file_name, ast, lst, sym_builder, cpg_builder


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TestSymbolCreation:

    @pytest.mark.parametrize('test_file,exp_local,exp_global', [
        ("""local a = 5\na = 1""",1,0),
        ("""local a\na = 1""",1,0),
        ("""a = 1""",0,1),
        ("""a = 1\na = 2""",0,1)
    ])
    def test_simple_variable_declaration(self, test_file, exp_local, exp_global):
        file_name, ast, lst, symbol_builder, cpg_builder = build_context(test_file)
        symbol_builder.build(ast.root_node)

        assert len(lst.scope_lookup_by_kind(ast.root_node.id, "local_variable")) == exp_local
        assert len(lst.scope_lookup_by_kind(ast.root_node.id, "global_variable")) == exp_global

    @pytest.mark.parametrize("test_file,exp_local,exp_global", [
        ("""local function add(a,b)\n\treturn a + b\nend""",1,0),
        ("""function add(a,b)\n\treturn a + b\nend""",0,1)
    ])
    def test_simple_function_definition(self, test_file,exp_local,exp_global):
        file_name, ast, lst, symbol_builder, cpg_builder = build_context(test_file)
        symbol_builder.build(ast.root_node)

        assert lst.exports.__len__() == 3  # 3 symbols
        assert lst.scopes.__len__() == 2
        assert len(lst.scope_lookup_by_kind(ast.root_node.id, "local_function")) == exp_local
        assert len(lst.scope_lookup_by_kind(ast.root_node.id, "global_function")) == exp_global

    @pytest.mark.parametrize("test_file", [
        """
        local a, b = require "module", require "second_module"
        """
    ])
    def test_require_modules(self, test_file):
        file_name, ast, lst, symbol_builder, cpg_builder = build_context(test_file)
        symbol_builder.build(ast.root_node)

        assert lst.imports["a"] == 'module'
        assert lst.imports["b"] == 'second_module'

class TestCPGBuilder:

    @pytest.mark.parametrize("test_file,exp_local,exp_global", [
        ("""local a = 5\na = 1""",1,0), # file
        ("""local a\na = 1""",1,0),
        ("""a = 1""",0,1),
        ("""a = 1\na = 2""",0,1)
    ])

    def test_simple_variable(self, test_file, exp_local, exp_global):
        file_name, ast, lst, symbol_builder, cpg_builder = build_context(test_file)
        symbol_builder.build(ast.root_node)
        cpg_builder.build(ast.root_node, file_name)

        assert cpg_builder.local_builder.get_nodes_by_type("knowledge_nodes", "local_variable_declaration").__len__() == exp_local # chunk and variable declaration + 2 identifiers
        assert cpg_builder.local_builder.get_nodes_by_type("knowledge_nodes", "global_variable_declaration").__len__() == exp_global # chunk contains variable, variable declared, variable assigned

    def test_less_simple_variable(self):
        file_name, ast, lst, symbol_builder, cpg_builder = build_context(SAMPLE_LUA_VAR_SIMPLE)
        symbol_builder.build(ast.root_node)
        cpg_builder.build(ast.root_node, file_name)

        bloatedmess.export_from_builder(cpg_builder.local_builder)

        print()

    @pytest.mark.parametrize("test_file", [
        (
            """
            local function add(x,y)
                return x + y
            end
            """
        ),
        (
            """
            function add(x,y)
                return x + y
            end
            """
        ),
        (
            """
            function add(x,y)
                local a = x
                b = x + y
                return b
            end
            """
        ),
        (
            """
            function add(x,y)
                print("adding numbers")
                return x + y
            end
            """
        )
    ])
    def test_simple_function(self, test_file):
        file_name, ast, lst, symbol_builder, cpg_builder = build_context(test_file)
        symbol_builder.build(ast.root_node)
        cpg_builder.build(ast.root_node, file_name)

        print()
        print(f"knowledge_nodes:{cpg_builder.local_builder.knowledge_nodes.__len__()} and knowledge_edges:{cpg_builder.local_builder.knowledge_edges.__len__()}")

    @pytest.mark.dependency(depends=["test_simple_variable" "test_simple_function"])
    @pytest.mark.parametrize("test_file", [
        (
            """
            module 'leg.parsing'
            
            --this should not be in module
            local function add(x,y)
                return x + y
            end
            
            --this should be in module
            function parse(file)
                local output
                tree-sitting(file, output)
                return output 
            end
            """
        )
    ])
    def test_modules(self, test_file):
        file_name, ast, lst, symbol_builder, cpg_builder = build_context(test_file)
        symbol_builder.build(ast.root_node)
        cpg_builder.build(ast.root_node, file_name)

    @pytest.mark.parametrize("test_file", [
        (
        """
        if 1 == 1 then
            return 1
        else
            return 2
        end
        """
    ),
        ("""
        local x = 10
        if x == 10 then
            x = 10 * 2
            if x == 20 then
                x = x - 2
            else 
                x = 0
            end
        elseif x == 11 then
            x = 0
        else
            x = 1
        end
        """)
    ])
    def test_if_statement(self, test_file):
        file_name, ast, lst, symbol_builder, cpg_builder = build_context(test_file)
        symbol_builder.build(ast.root_node)
        cpg_builder.build(ast.root_node, file_name)

        bloatedmess.export_from_builder(cpg_builder.local_builder)


    @pytest.mark.parametrize("test_file", [
        # (
        #     """
        #         local patt = P(false)
        #
        #         for x = 1, 19 do
        #             print(x)
        #         end
        #
        #         for i = 1, #list, 1 do
        #             local patt = P(list[i])
        #         end
        #     """
        # ),
        # (
        #     """
        #     function copy(grammar)
        #         local newt = {}
        #
        #         for k, v in pairs(grammar) do
        #             newt = v
        #         end
        #
        #         return newt
        #     end"""
        # ),
        # (
        #     """
        #     a = 10
        #
        #     while( a < 20 )
        #     do
        #        print("value of a:", a)
        #        a = a+1
        #     end"""
        # ),
        (
            """
            i = 10
            repeat
               print("value of i:",i)
               i = i + 1
            until i > 20"""
        )
    ])
    def test_loops(self, test_file):
        file_name, ast, lst, symbol_builder, cpg_builder = build_context(test_file)
        symbol_builder.build(ast.root_node)
        cpg_builder.build(ast.root_node, file_name)

        bloatedmess.export_from_builder(cpg_builder.local_builder)
