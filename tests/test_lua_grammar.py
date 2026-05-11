"""
Tests derived from tests/resources/grammar.lua.

Each class covers one logical chunk of the file:
  - Header     : local aliases, require, module declaration
  - AnyOf      : function anyOf(list)
  - ListOf     : function listOf(patt, sep)
  - Captures   : function C(...) / Ct(...)
  - Copy       : function copy(grammar)
  - Complete   : function complete(dest, orig)
  - Pipe       : function pipe(dest, orig)
  - Apply      : function apply(grammar, rules, captures)

Plus one end-to-end integration test that parses the full file and exports to Gephi.
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from parser import ParallelASTManager
from builders import SymbolBuilder, CPGBuilder, LocalOutputBuilder
from structures import SymbolTable
from managers.graph_manager import GraphManager
from csv_graph_exporter import export_to_gephi_csv

GRAMMAR_LUA = os.path.join(os.path.dirname(__file__), 'resources', 'grammar.lua')


# ──────────────────────────────────────────────────────────────────────────────
# Helpers  (same pattern as test_symbol_table.py)
# ──────────────────────────────────────────────────────────────────────────────

def create_temp_lua(lua_code: str) -> str:
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False)
    f.write(lua_code)
    f.flush()
    f.close()
    return f.name


def build_context(lua_code: str):
    file_name = create_temp_lua(lua_code)
    parser    = ParallelASTManager("1")
    builder   = LocalOutputBuilder()
    lst       = SymbolTable("1")
    ast       = parser.parse(file_name)
    sym_builder = SymbolBuilder(local_builder=builder, lst=lst, file_path=file_name)
    cpg_builder = CPGBuilder(builder, lst, file_name)
    return file_name, ast, lst, sym_builder, cpg_builder


def build_symbol_table(lua_code: str):
    _, ast, lst, sym_builder, _ = build_context(lua_code)
    sym_builder.build(ast.root_node)
    return ast, lst


def build_cpg(lua_code: str):
    file_name, ast, lst, sym_builder, cpg = build_context(lua_code)
    sym_builder.build(ast.root_node)
    cpg.build(ast.root_node, file_name)
    return file_name, ast, lst, cpg


def kg_nodes_of_type(cpg: CPGBuilder, node_type: str):
    return cpg.local_builder.get_nodes_by_type("knowledge_nodes", node_type)


def kg_edges_of_relation(cpg: CPGBuilder, relation: str):
    return [e for e in cpg.local_builder.knowledge_edges if e["relation"] == relation]


# ──────────────────────────────────────────────────────────────────────────────
# Code chunks extracted from grammar.lua
# ──────────────────────────────────────────────────────────────────────────────

HEADER = """\
local assert  = assert
local pairs   = pairs
local type    = type

local lpeg = require 'lpeg'

local P, V = lpeg.P, lpeg.V

module 'leg.grammar'
"""

ANY_OF = """\
function anyOf(list)
  local patt = P(false)

  for i = 1, #list, 1 do
    patt = P(list[i]) + patt
  end

  return patt
end
"""

LIST_OF = """\
function listOf(patt, sep)
  patt, sep = P(patt), P(sep)

  return patt * (sep * patt)^0
end
"""

CAPTURES = """\
function C(...) return ... end

function Ct(...) return { ... } end
"""

COPY = """\
function copy(grammar)
    local newt = {}

    for k, v in pairs(grammar) do
        newt[k] = v
    end

    return newt
end
"""

COMPLETE = """\
function complete(dest, orig)
    for rule, patt in pairs(orig) do
        if not dest[rule] then
            dest[rule] = patt
        end
    end

    return dest
end
"""

PIPE = """\
function pipe(dest, orig)
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
"""

APPLY = """\
function apply(grammar, rules, captures)
  if rules == nil then
    rules = {}
  elseif type(rules) ~= 'table' then
    rules = { rules }
  end

  if type(grammar[1]) == 'string' then
    rules[1] = grammar[1]
  end

  if captures ~= nil then
    for rule, cap in pairs(captures) do
        rules[rule] = cap
    end
  end

  return rules
end
"""


# ──────────────────────────────────────────────────────────────────────────────
# Header: local aliases + require + module declaration
# ──────────────────────────────────────────────────────────────────────────────

class TestGrammarHeader:
    """grammar.lua header: local aliases, require 'lpeg', module 'leg.grammar'."""

    def test_require_lpeg_is_tracked_as_import(self):
        ast, lst = build_symbol_table(HEADER)
        assert "lpeg" in lst.imports
        assert lst.imports["lpeg"] == "lpeg"

    def test_lpeg_variable_is_module_representation(self):
        ast, lst = build_symbol_table(HEADER)
        sym = lst.scope_lookup_by_name(ast.root_node.id, "lpeg")
        assert sym is not None
        assert sym.kind == "local_module_representation"

    def test_module_declaration_tracked_in_symbol_table(self):
        ast, lst = build_symbol_table(HEADER)
        sym = lst.scope_lookup_by_name(ast.root_node.id, "leg.grammar")
        assert sym is not None
        assert sym.kind == "module"

    def test_module_declaration_creates_cpg_node(self):
        _, ast, lst, cpg = build_cpg(HEADER)
        mod_nodes = kg_nodes_of_type(cpg, "module")
        assert len(mod_nodes) >= 1

    def test_module_node_has_correct_name_property(self):
        _, ast, lst, cpg = build_cpg(HEADER)
        mod_nodes = kg_nodes_of_type(cpg, "module")
        assert mod_nodes[0].get("properties", {}).get("module_name") == "leg.grammar"

    def test_local_alias_variables_are_declared(self):
        ast, lst = build_symbol_table(HEADER)
        for name in ("assert", "pairs", "type"):
            sym = lst.scope_lookup_by_name(ast.root_node.id, name)
            assert sym is not None, f"Expected '{name}' in symbol table"
            assert sym.kind == "local_variable"

    def test_export_to_gephi(self):
        _, ast, lst, cpg = build_cpg(HEADER)
        nodes = cpg.local_builder.knowledge_nodes.values()
        edges = cpg.local_builder.knowledge_edges
        export_to_gephi_csv(nodes, edges, "k_nodes.csv", "k_edges.csv")


# ──────────────────────────────────────────────────────────────────────────────
# anyOf — numeric for loop inside a global function
# ──────────────────────────────────────────────────────────────────────────────

class TestAnyOf:
    """grammar.lua – function anyOf(list): numeric for, local var patt."""

    def test_anyof_is_global_function(self):
        ast, lst = build_symbol_table(ANY_OF)
        assert lst.scope_lookup_by_name(ast.root_node.id, "anyOf") is not None
        fns = lst.scope_lookup_by_kind(ast.root_node.id, "global_function")
        assert len(fns) == 1

    def test_anyof_has_one_parameter(self):
        ast, lst = build_symbol_table(ANY_OF)
        params = [sym for sym in lst.exports.values() if sym.kind == "parameter"]
        assert len(params) == 1
        assert params[0].name == "list"

    def test_anyof_local_patt_declared_inside_body(self):
        _, ast, lst, cpg = build_cpg(ANY_OF)
        local_vars = kg_nodes_of_type(cpg, "local_variable_declaration")
        names = [n.get("properties", {}).get("name") for n in local_vars]
        assert "patt" in names

    def test_anyof_numeric_for_loop_creates_node(self):
        _, ast, lst, cpg = build_cpg(ANY_OF)
        assert len(kg_nodes_of_type(cpg, "for_statement")) >= 1

    def test_anyof_function_definition_node_exists(self):
        _, ast, lst, cpg = build_cpg(ANY_OF)
        fns = kg_nodes_of_type(cpg, "global_function_definition")
        assert len(fns) == 1
        assert fns[0].get("properties", {}).get("name") == "anyOf"

    def test_anyof_function_has_block_edge(self):
        _, ast, lst, cpg = build_cpg(ANY_OF)
        fns = kg_nodes_of_type(cpg, "global_function_definition")
        fn_id = fns[0]["_key"]
        has_block = [e for e in kg_edges_of_relation(cpg, "has_block") if e["_from"] == fn_id]
        assert len(has_block) == 1

    def test_export_to_gephi(self):
        _, ast, lst, cpg = build_cpg(ANY_OF)
        export_to_gephi_csv(cpg.local_builder.knowledge_nodes.values(), cpg.local_builder.knowledge_edges, "k_nodes.csv", "k_edges.csv")


# ──────────────────────────────────────────────────────────────────────────────
# listOf — two parameters, no local declarations
# ──────────────────────────────────────────────────────────────────────────────

class TestListOf:
    """grammar.lua – function listOf(patt, sep): two params, no new local vars."""

    def test_listof_is_global_function(self):
        ast, lst = build_symbol_table(LIST_OF)
        assert lst.scope_lookup_by_name(ast.root_node.id, "listOf") is not None

    def test_listof_has_two_parameters(self):
        ast, lst = build_symbol_table(LIST_OF)
        params = [sym for sym in lst.exports.values() if sym.kind == "parameter"]
        assert len(params) == 2
        param_names = {s.name for s in params}
        assert param_names == {"patt", "sep"}

    def test_listof_cpg_function_definition_exists(self):
        _, ast, lst, cpg = build_cpg(LIST_OF)
        fns = kg_nodes_of_type(cpg, "global_function_definition")
        assert len(fns) == 1
        assert fns[0].get("properties", {}).get("name") == "listOf"

    def test_listof_has_parameter_edges(self):
        _, ast, lst, cpg = build_cpg(LIST_OF)
        fns = kg_nodes_of_type(cpg, "global_function_definition")
        fn_id = fns[0]["_key"]
        param_edges = [e for e in kg_edges_of_relation(cpg, "has_parameters") if e["_from"] == fn_id]
        assert len(param_edges) == 2

    def test_listof_no_local_variable_nodes(self):
        _, ast, lst, cpg = build_cpg(LIST_OF)
        assert len(kg_nodes_of_type(cpg, "local_variable_declaration")) == 0

    def test_export_to_gephi(self):
        _, ast, lst, cpg = build_cpg(LIST_OF)
        export_to_gephi_csv(cpg.local_builder.knowledge_nodes.values(), cpg.local_builder.knowledge_edges, "k_nodes.csv", "k_edges.csv")


# ──────────────────────────────────────────────────────────────────────────────
# C / Ct — variadic capture helpers
# ──────────────────────────────────────────────────────────────────────────────

class TestCaptureFunctions:
    """grammar.lua – function C(...) and function Ct(...): variadic, no params in table."""

    def test_both_functions_in_symbol_table(self):
        ast, lst = build_symbol_table(CAPTURES)
        assert lst.scope_lookup_by_name(ast.root_node.id, "C") is not None
        assert lst.scope_lookup_by_name(ast.root_node.id, "Ct") is not None

    def test_both_are_global_functions(self):
        ast, lst = build_symbol_table(CAPTURES)
        fns = lst.scope_lookup_by_kind(ast.root_node.id, "global_function")
        assert len(fns) == 2

    def test_two_function_definition_cpg_nodes(self):
        _, ast, lst, cpg = build_cpg(CAPTURES)
        fns = kg_nodes_of_type(cpg, "global_function_definition")
        assert len(fns) == 2

    def test_no_local_variable_nodes(self):
        _, ast, lst, cpg = build_cpg(CAPTURES)
        assert len(kg_nodes_of_type(cpg, "local_variable_declaration")) == 0

    def test_export_to_gephi(self):
        _, ast, lst, cpg = build_cpg(CAPTURES)
        export_to_gephi_csv(cpg.local_builder.knowledge_nodes.values(), cpg.local_builder.knowledge_edges, "k_nodes.csv", "k_edges.csv")


# ──────────────────────────────────────────────────────────────────────────────
# copy — generic for loop, one local var
# ──────────────────────────────────────────────────────────────────────────────

class TestCopy:
    """grammar.lua – function copy(grammar): generic for-in, local newt."""

    def test_copy_is_global_function(self):
        ast, lst = build_symbol_table(COPY)
        assert lst.scope_lookup_by_name(ast.root_node.id, "copy") is not None

    def test_copy_has_one_parameter(self):
        ast, lst = build_symbol_table(COPY)
        params = [sym for sym in lst.exports.values() if sym.kind == "parameter"]
        assert len(params) == 1
        assert params[0].name == "grammar"

    def test_copy_local_newt_declared(self):
        _, ast, lst, cpg = build_cpg(COPY)
        local_vars = kg_nodes_of_type(cpg, "local_variable_declaration")
        names = [n.get("properties", {}).get("name") for n in local_vars]
        assert "newt" in names

    def test_copy_generic_for_loop_created(self):
        _, ast, lst, cpg = build_cpg(COPY)
        assert len(kg_nodes_of_type(cpg, "for_statement")) >= 1

    def test_copy_function_definition_name(self):
        _, ast, lst, cpg = build_cpg(COPY)
        fns = kg_nodes_of_type(cpg, "global_function_definition")
        assert fns[0].get("properties", {}).get("name") == "copy"

    def test_export_to_gephi(self):
        _, ast, lst, cpg = build_cpg(COPY)
        export_to_gephi_csv(cpg.local_builder.knowledge_nodes.values(), cpg.local_builder.knowledge_edges, "k_nodes.csv", "k_edges.csv")


# ──────────────────────────────────────────────────────────────────────────────
# complete — for loop + if statement
# ──────────────────────────────────────────────────────────────────────────────

class TestComplete:
    """grammar.lua – function complete(dest, orig): for-in with nested if."""

    def test_complete_is_global_function(self):
        ast, lst = build_symbol_table(COMPLETE)
        assert lst.scope_lookup_by_name(ast.root_node.id, "complete") is not None

    def test_complete_has_two_parameters(self):
        ast, lst = build_symbol_table(COMPLETE)
        params = [sym for sym in lst.exports.values() if sym.kind == "parameter"]
        assert len(params) == 2
        assert {s.name for s in params} == {"dest", "orig"}

    def test_complete_for_loop_created(self):
        _, ast, lst, cpg = build_cpg(COMPLETE)
        assert len(kg_nodes_of_type(cpg, "for_statement")) >= 1

    def test_complete_if_statement_inside_loop(self):
        _, ast, lst, cpg = build_cpg(COMPLETE)
        assert len(kg_nodes_of_type(cpg, "if_statement")) >= 1

    def test_complete_no_local_vars(self):
        _, ast, lst, cpg = build_cpg(COMPLETE)
        assert len(kg_nodes_of_type(cpg, "local_variable_declaration")) == 0

    def test_export_to_gephi(self):
        _, ast, lst, cpg = build_cpg(COMPLETE)
        export_to_gephi_csv(cpg.local_builder.knowledge_nodes.values(), cpg.local_builder.knowledge_edges, "k_nodes.csv", "k_edges.csv")


# ──────────────────────────────────────────────────────────────────────────────
# pipe — for loop + local var inside + if/else + nested anonymous function
# ──────────────────────────────────────────────────────────────────────────────

class TestPipe:
    """grammar.lua – function pipe(dest, orig): local vdest, if/else, nested closure."""

    def test_pipe_is_global_function(self):
        ast, lst = build_symbol_table(PIPE)
        assert lst.scope_lookup_by_name(ast.root_node.id, "pipe") is not None

    def test_pipe_has_two_parameters(self):
        ast, lst = build_symbol_table(PIPE)
        params = [sym for sym in lst.exports.values() if sym.kind == "parameter"]
        assert len(params) == 2
        assert {s.name for s in params} == {"dest", "orig"}

    def test_pipe_generic_for_loop_created(self):
        _, ast, lst, cpg = build_cpg(PIPE)
        assert len(kg_nodes_of_type(cpg, "for_statement")) >= 1

    def test_pipe_local_vdest_declared_inside_loop(self):
        _, ast, lst, cpg = build_cpg(PIPE)
        local_vars = kg_nodes_of_type(cpg, "local_variable_declaration")
        names = [n.get("properties", {}).get("name") for n in local_vars]
        assert "vdest" in names

    def test_pipe_if_statement_inside_loop(self):
        _, ast, lst, cpg = build_cpg(PIPE)
        assert len(kg_nodes_of_type(cpg, "if_statement")) >= 1

    def test_pipe_function_definition_name(self):
        _, ast, lst, cpg = build_cpg(PIPE)
        fns = kg_nodes_of_type(cpg, "global_function_definition")
        outer = [f for f in fns if f.get("properties", {}).get("name") == "pipe"]
        assert len(outer) == 1

    def test_export_to_gephi(self):
        _, ast, lst, cpg = build_cpg(PIPE)
        export_to_gephi_csv(cpg.local_builder.knowledge_nodes.values(), cpg.local_builder.knowledge_edges, "k_nodes.csv", "k_edges.csv")


# ──────────────────────────────────────────────────────────────────────────────
# apply — three params, two if blocks, elseif, for loop
# ──────────────────────────────────────────────────────────────────────────────

class TestApply:
    """grammar.lua – function apply(grammar, rules, captures): complex control flow."""

    def test_apply_is_global_function(self):
        ast, lst = build_symbol_table(APPLY)
        assert lst.scope_lookup_by_name(ast.root_node.id, "apply") is not None

    def test_apply_has_three_parameters(self):
        ast, lst = build_symbol_table(APPLY)
        params = [sym for sym in lst.exports.values() if sym.kind == "parameter"]
        assert len(params) == 3
        assert {s.name for s in params} == {"grammar", "rules", "captures"}

    def test_apply_if_statements_created(self):
        _, ast, lst, cpg = build_cpg(APPLY)
        assert len(kg_nodes_of_type(cpg, "if_statement")) >= 2

    def test_apply_elseif_created(self):
        _, ast, lst, cpg = build_cpg(APPLY)
        assert len(kg_nodes_of_type(cpg, "elseif_statement")) >= 1

    def test_apply_for_loop_inside_captures_block(self):
        _, ast, lst, cpg = build_cpg(APPLY)
        assert len(kg_nodes_of_type(cpg, "for_statement")) >= 1

    def test_apply_function_definition_node_exists(self):
        _, ast, lst, cpg = build_cpg(APPLY)
        fns = kg_nodes_of_type(cpg, "global_function_definition")
        assert len(fns) == 1
        assert fns[0].get("properties", {}).get("name") == "apply"

    def test_apply_has_block_edge(self):
        _, ast, lst, cpg = build_cpg(APPLY)
        fns = kg_nodes_of_type(cpg, "global_function_definition")
        fn_id = fns[0]["_key"]
        has_block = [e for e in kg_edges_of_relation(cpg, "has_block") if e["_from"] == fn_id]
        assert len(has_block) == 1

    def test_export_to_gephi(self):
        _, ast, lst, cpg = build_cpg(APPLY)
        export_to_gephi_csv(cpg.local_builder.knowledge_nodes.values(), cpg.local_builder.knowledge_edges, "k_nodes.csv", "k_edges.csv")


# ──────────────────────────────────────────────────────────────────────────────
# Integration — full grammar.lua → CPG → Gephi export
# ──────────────────────────────────────────────────────────────────────────────

def test_full_grammar_lua_gephi_export():
    """Parse the full grammar.lua, build CPG, export knowledge graph to Gephi CSVs."""
    ast = ParallelASTManager(GRAMMAR_LUA).parse(GRAMMAR_LUA)
    assert ast is not None and ast.root_node.type == "chunk"

    gm = GraphManager(SymbolTable("grammar_integration"))
    gm.generate_graph(ast, GRAMMAR_LUA)
    result = gm.get_graphs()

    assert len(result["ast_graph"]["vertices"]) > 0
    assert len(result["knowledge_graph"]["vertices"]) > 0

    export_to_gephi_csv(result["knowledge_graph"]["vertices"], result["knowledge_graph"]["edges"], "k_nodes.csv", "k_edges.csv")
