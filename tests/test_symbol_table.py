import logging
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from csv_graph_exporter import export_from_builder
from parser import ParallelASTManager
from builders import SymbolBuilder, CPGBuilder, LocalOutputBuilder
from structures import SymbolTable

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

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
    sym_builder = SymbolBuilder(local_builder=builder, lst=lst, file_path=file_name)
    cpg_builder = CPGBuilder(builder, lst, file_name)
    return file_name, ast, lst, sym_builder, cpg_builder


def build_symbol_table(lua_code: str):
    """Run SymbolBuilder, return (ast, lst)."""
    _, ast, lst, sym_builder, _ = build_context(lua_code)
    sym_builder.build(ast.root_node)
    return ast, lst


def build_cpg(lua_code: str):
    """Run SymbolBuilder + CPGBuilder, return (file_name, ast, lst, cpg)."""
    file_name, ast, lst, sym_builder, cpg = build_context(lua_code)
    sym_builder.build(ast.root_node)
    cpg.build(ast.root_node, file_name)
    return file_name, ast, lst, cpg


def kg_nodes_of_type(cpg: CPGBuilder, node_type: str):
    return cpg.local_builder.get_nodes_by_type("knowledge_nodes", node_type)


def kg_edges_of_relation(cpg: CPGBuilder, relation: str):
    return [e for e in cpg.local_builder.knowledge_edges if e["relation"] == relation]


# ──────────────────────────────────────────────────────────────────────────────
# Symbol Table — variables, functions, require, module
# ──────────────────────────────────────────────────────────────────────────────

class TestSymbolCreation:

    @pytest.mark.parametrize("code, exp_local, exp_global", [
        ("local a = 5\na = 1",   1, 0),
        ("local a\na = 1",       1, 0),
        ("a = 1",                0, 1),
        ("a = 1\na = 2",         0, 1),
        ("local a\nlocal b",     2, 0),
        ("a = 1\nb = 2",         0, 2),
    ])
    def test_variable_declaration(self, code, exp_local, exp_global):
        ast, lst = build_symbol_table(code)
        assert len(lst.scope_lookup_by_kind(ast.root_node.id, "local_variable")) == exp_local
        assert len(lst.scope_lookup_by_kind(ast.root_node.id, "global_variable")) == exp_global

    def test_variable_name_in_symbol_table(self):
        ast, lst = build_symbol_table("local x = 10")
        sym = lst.scope_lookup_by_name(ast.root_node.id, "x")
        assert sym is not None
        assert sym.name == "x"
        assert sym.kind == "local_variable"

    def test_multiple_declarations_same_name_only_one_symbol(self):
        ast, lst = build_symbol_table("local a = 1\na = 2\na = 3")
        assert len(lst.scope_lookup_by_kind(ast.root_node.id, "local_variable")) == 1

    @pytest.mark.parametrize("code, exp_local, exp_global, exp_params", [
        ("local function add(a, b)\n\treturn a + b\nend", 1, 0, 2),
        ("function add(a, b)\n\treturn a + b\nend",       0, 1, 2),
        ("local function f()\n\treturn 1\nend",           1, 0, 0),
        ("function g(x)\n\treturn x\nend",                0, 1, 1),
    ])
    def test_function_declaration(self, code, exp_local, exp_global, exp_params):
        ast, lst = build_symbol_table(code)
        assert len(lst.scope_lookup_by_kind(ast.root_node.id, "local_function")) == exp_local
        assert len(lst.scope_lookup_by_kind(ast.root_node.id, "global_function")) == exp_global
        assert len([x for x, sym in lst.exports.items() if sym.kind == "parameter"]) == exp_params
        assert len(lst.scopes) == 2

    def test_function_symbol_lookup_by_name(self):
        ast, lst = build_symbol_table("local function greet(name)\n\treturn name\nend")
        sym = lst.scope_lookup_by_name(ast.root_node.id, "greet")
        assert sym is not None
        assert sym.kind == "local_function"

    def test_two_functions_both_in_symbol_table(self):
        code = "function add(a, b)\n\treturn a + b\nend\nfunction sub(a, b)\n\treturn a - b\nend"
        ast, lst = build_symbol_table(code)
        assert lst.scope_lookup_by_name(ast.root_node.id, "add") is not None
        assert lst.scope_lookup_by_name(ast.root_node.id, "sub") is not None
        assert len(lst.scope_lookup_by_kind(ast.root_node.id, "global_function")) == 2

    def test_require_single(self):
        ast, lst = build_symbol_table('local m = require("math.utils")')
        assert "m" in lst.imports
        assert lst.imports["m"] == "math.utils"

    def test_require_multiple_same_line(self):
        ast, lst = build_symbol_table('local a, b = require "module_a", require "module_b"')
        assert lst.imports.get("a") == "module_a"
        assert lst.imports.get("b") == "module_b"

    def test_require_symbol_kind_is_module_representation(self):
        ast, lst = build_symbol_table('local m = require("utils")')
        sym = lst.scope_lookup_by_name(ast.root_node.id, "m")
        assert sym is not None
        assert sym.kind == "local_module_representation"

    def test_require_different_quoting_styles(self):
        ast, lst = build_symbol_table("local a = require 'mod.a'\nlocal b = require(\"mod.b\")")
        assert lst.imports.get("a") == "mod.a"
        assert lst.imports.get("b") == "mod.b"

    def test_require_two_modules_both_marked(self):
        ast, lst = build_symbol_table('local a, b = require "mod_a", require "mod_b"')
        sym_a = lst.scope_lookup_by_name(ast.root_node.id, "a")
        sym_b = lst.scope_lookup_by_name(ast.root_node.id, "b")
        assert sym_a.kind == "local_module_representation"
        assert sym_b.kind == "local_module_representation"

    def test_module_declaration_creates_symbol(self):
        ast, lst = build_symbol_table("module 'leg.parsing'")
        sym = lst.scope_lookup_by_name(ast.root_node.id, "leg.parsing")
        assert sym is not None
        assert sym.kind == "module"

    def test_module_declaration_name_extracted(self):
        ast, lst = build_symbol_table("module 'mypackage.core'")
        sym = lst.scope_lookup_by_name(ast.root_node.id, "mypackage.core")
        assert sym is not None
        assert sym.name == "mypackage.core"

    def test_module_functions_registered_in_symbol_table(self):
        code = "module 'mymod'\nfunction foo(a)\n\treturn a\nend"
        ast, lst = build_symbol_table(code)
        foo = lst.scope_lookup_by_name(ast.root_node.id, "foo")
        assert foo is not None
        assert foo.kind == "global_function"

    def test_module_with_local_and_global_functions(self):
        code = """
module 'net.utils'

local function helper(x)
    return x
end

function public_fn(a, b)
    return helper(a) + b
end
"""
        ast, lst = build_symbol_table(code)
        assert lst.scope_lookup_by_name(ast.root_node.id, "helper") is not None
        assert lst.scope_lookup_by_name(ast.root_node.id, "public_fn") is not None
        assert len(lst.scope_lookup_by_kind(ast.root_node.id, "local_function")) == 1
        assert len(lst.scope_lookup_by_kind(ast.root_node.id, "global_function")) == 1


# ──────────────────────────────────────────────────────────────────────────────
# CPG — variables
# ──────────────────────────────────────────────────────────────────────────────

class TestCPGVariables:

    def test_chunk_node_always_created(self):
        _, ast, lst, cpg = build_cpg("local x = 1")
        assert len(kg_nodes_of_type(cpg, "chunk")) == 1

    @pytest.mark.parametrize("code, exp_local, exp_global", [
        ("local a = 5\na = 1",   1, 0),
        ("local a\na = 1",       1, 0),
        ("a = 1",                0, 1),
        ("a = 1\na = 2",         0, 1),
    ])
    def test_variable_declaration_nodes(self, code, exp_local, exp_global):
        _, ast, lst, cpg = build_cpg(code)
        assert len(kg_nodes_of_type(cpg, "local_variable_declaration")) == exp_local
        assert len(kg_nodes_of_type(cpg, "global_variable_declaration")) == exp_global

    def test_multiple_local_variables_each_get_a_node(self):
        _, ast, lst, cpg = build_cpg("local x = 10\nlocal y = 20\nlocal z = 30")
        assert len(kg_nodes_of_type(cpg, "local_variable_declaration")) == 3

    def test_variable_declares_edge_exists(self):
        _, ast, lst, cpg = build_cpg("local a = 5")
        assert len(kg_edges_of_relation(cpg, "declares")) >= 1

    def test_variable_declaration_refers_to_edge(self):
        _, ast, lst, cpg = build_cpg("local a = 5\nlocal b = a")
        assert len(kg_nodes_of_type(cpg, "local_variable_declaration")) == 2
        assert len(kg_edges_of_relation(cpg, "refers_to")) == 1

    def test_local_variable_has_name_property(self):
        _, ast, lst, cpg = build_cpg("local x = 42")
        nodes = kg_nodes_of_type(cpg, "local_variable_declaration")
        assert len(nodes) == 1
        assert nodes[0].get("properties", {}).get("name") == "x"

    def test_table_variable_has_is_table_property(self):
        """A variable initialized with {} should have is_table=True on its declaration node."""
        _, ast, lst, cpg = build_cpg("local t = {}")
        nodes = kg_nodes_of_type(cpg, "local_variable_declaration")
        assert len(nodes) == 1
        assert nodes[0].get("properties", {}).get("is_table") == "True"


# ──────────────────────────────────────────────────────────────────────────────
# CPG — functions
# ──────────────────────────────────────────────────────────────────────────────

class TestCPGFunctions:

    @pytest.mark.parametrize("code, exp_type", [
        ("local function add(x,y)\n\treturn x+y\nend", "local_function_definition"),
        ("function add(x,y)\n\treturn x+y\nend",       "global_function_definition"),
    ])
    def test_function_definition_node_created(self, code, exp_type):
        _, ast, lst, cpg = build_cpg(code)
        assert len(kg_nodes_of_type(cpg, exp_type)) == 1

    def test_function_has_block_edge(self):
        _, ast, lst, cpg = build_cpg("local function add(x,y)\n\treturn x+y\nend")
        fn_id = kg_nodes_of_type(cpg, "local_function_definition")[0]["_key"]
        has_block = [e for e in kg_edges_of_relation(cpg, "has_block") if e["_from"] == fn_id]
        assert len(has_block) == 1

    def test_function_with_params_has_parameter_edges(self):
        _, ast, lst, cpg = build_cpg("local function add(x, y)\n\treturn x+y\nend")
        fn_id = kg_nodes_of_type(cpg, "local_function_definition")[0]["_key"]
        param_edges = [e for e in kg_edges_of_relation(cpg, "has_parameters") if e["_from"] == fn_id]
        assert len(param_edges) == 2
        assert len(kg_edges_of_relation(cpg, "refers_to")) == 2

    def test_function_no_params_no_parameter_edges(self):
        _, ast, lst, cpg = build_cpg("local function f()\n\treturn 1\nend")
        fn_id = kg_nodes_of_type(cpg, "local_function_definition")[0]["_key"]
        param_edges = [e for e in kg_edges_of_relation(cpg, "has_parameters") if e["_from"] == fn_id]
        assert len(param_edges) == 0

    def test_function_has_metrics(self):
        _, ast, lst, cpg = build_cpg("function f(a)\n\treturn a\nend")
        fn_id = kg_nodes_of_type(cpg, "global_function_definition")[0]["_key"]
        metrics_edges = [e for e in kg_edges_of_relation(cpg, "has_metrics") if e["_to"] == fn_id]
        assert len(metrics_edges) == 1

    def test_two_functions_both_have_definition_nodes(self):
        code = "function add(a,b)\n\treturn a+b\nend\nfunction sub(a,b)\n\treturn a-b\nend"
        _, ast, lst, cpg = build_cpg(code)
        assert len(kg_nodes_of_type(cpg, "global_function_definition")) == 2

    def test_function_name_in_node_properties(self):
        _, ast, lst, cpg = build_cpg("function greet(name)\n\treturn name\nend")
        fns = kg_nodes_of_type(cpg, "global_function_definition")
        assert fns[0].get("properties", {}).get("name") == "greet"

    def test_function_return_inside_control_statement(self):
        _, ast, lst, cpg = build_cpg("function greet(name,x)\n\tif x == 1 then\n\t\treturn name\n\tend\nend")
        rts = kg_nodes_of_type(cpg, "return_statement")
        rtes = kg_edges_of_relation(cpg, "returns")
        assert len(rts) == 1
        assert len(rtes) == 1
        export_from_builder(cpg)


# ──────────────────────────────────────────────────────────────────────────────
# CPG — unresolved edges
# ──────────────────────────────────────────────────────────────────────────────

class TestCPGUnresolvedEdges:

    def test_call_to_unknown_function_creates_unresolved_edge(self):
        _, ast, lst, cpg = build_cpg("unknown_fn(1, 2)")
        assert "unknown_fn" in cpg.unresolved_edges
        pending = cpg.unresolved_edges["unknown_fn"]
        assert len(pending) >= 1
        assert pending[0]["edge_type"] == "defines"

    def test_reference_to_unknown_variable_creates_unresolved_edge(self):
        _, ast, lst, cpg = build_cpg("x = undefined_var")
        assert "undefined_var" in cpg.unresolved_edges

    def test_known_function_call_has_no_unresolved_edge(self):
        code = "local function f()\n\treturn 1\nend\nf()"
        _, ast, lst, cpg = build_cpg(code)
        assert "f" not in cpg.unresolved_edges


# ──────────────────────────────────────────────────────────────────────────────
# CPG — control flow (if / elseif / else)
# ──────────────────────────────────────────────────────────────────────────────

class TestCPGControlFlow:

    def test_if_statement_node_created(self):
        _, ast, lst, cpg = build_cpg("if 1 == 1 then\n\treturn 1\nend")
        if_stmts = kg_nodes_of_type(cpg, "if_statement")
        assert len(if_stmts) >= 1
        assert if_stmts[0]["properties"]["kind"] == "if_statement"

    def test_if_statement_has_block(self):
        _, ast, lst, cpg = build_cpg("if 1 == 1 then\n\treturn 1\nend")
        if_id = kg_nodes_of_type(cpg, "if_statement")[0]["_key"]
        has_block = [e for e in kg_edges_of_relation(cpg, "has_block") if e["_from"] == if_id]
        assert len(has_block) == 1

    def test_if_has_condition_edge(self):
        _, ast, lst, cpg = build_cpg("if 1 == 1 then\n\treturn 1\nend")
        if_id = kg_nodes_of_type(cpg, "if_statement")[0]["_key"]
        cond_edges = [e for e in kg_edges_of_relation(cpg, "has_condition") if e["_from"] == if_id]
        assert len(cond_edges) >= 1

    def test_nested_if_creates_multiple_nodes(self):
        code = "local x = 10\nif x > 5 then\n    if x > 8 then\n        x = 0\n    end\nend"
        _, ast, lst, cpg = build_cpg(code)
        assert len(kg_nodes_of_type(cpg, "if_statement")) == 2

    def test_if_elseif_else_all_create_nodes(self):
        code = "local x = 10\nif x == 1 then\n    x = 10\nelseif x == 2 then\n    x = 20\nelse\n    x = 30\nend"
        _, ast, lst, cpg = build_cpg(code)
        assert len(kg_nodes_of_type(cpg, "if_statement")) >= 1
        assert len(kg_nodes_of_type(cpg, "elseif_statement")) >= 1


# ──────────────────────────────────────────────────────────────────────────────
# CPG — loops (for / while / repeat)
# ──────────────────────────────────────────────────────────────────────────────

class TestCPGLoops:

    def test_generic_for_creates_loop_node(self):
        code = "function copy(t)\n\tfor k, v in pairs(t) do\n\t\tt[k] = v\n\tend\nend"
        _, ast, lst, cpg = build_cpg(code)
        assert len(kg_nodes_of_type(cpg, "for_statement")) >= 1

    def test_while_loop_creates_node(self):
        code = "local a = 10\nwhile a > 0 do\n\ta = a - 1\nend"
        _, ast, lst, cpg = build_cpg(code)
        assert len(kg_nodes_of_type(cpg, "while_statement")) >= 1

    def test_repeat_until_creates_node(self):
        code = "local i = 0\nrepeat\n\ti = i + 1\nuntil i >= 10"
        _, ast, lst, cpg = build_cpg(code)
        assert len(kg_nodes_of_type(cpg, "repeat_statement")) >= 1


# ──────────────────────────────────────────────────────────────────────────────
# CPG — modules (declaration + require)
# ──────────────────────────────────────────────────────────────────────────────

class TestCPGModules:

    def test_module_declaration_creates_module_node(self):
        _, ast, lst, cpg = build_cpg("module 'leg.parsing'")
        assert len(kg_nodes_of_type(cpg, "module")) >= 1

    def test_module_node_has_module_name_property(self):
        _, ast, lst, cpg = build_cpg("module 'leg.parsing'")
        mod_nodes = kg_nodes_of_type(cpg, "module")
        assert len(mod_nodes) >= 1
        assert mod_nodes[0].get("properties", {}).get("module_name") == "leg.parsing"

    def test_module_with_functions_creates_both_nodes(self):
        code = "module 'net.utils'\nfunction send(data)\n    return data\nend"
        _, ast, lst, cpg = build_cpg(code)
        assert len(kg_nodes_of_type(cpg, "module")) >= 1
        assert len(kg_nodes_of_type(cpg, "global_function_definition")) >= 1

    def test_require_creates_module_import_node(self):
        _, ast, lst, cpg = build_cpg('local m = require("math.utils")')
        import_nodes = kg_nodes_of_type(cpg, "module_import")
        assert len(import_nodes) == 1
        assert import_nodes[0].get("properties", {}).get("module_path") == "math.utils"

    def test_require_does_not_create_function_call_node(self):
        _, ast, lst, cpg = build_cpg('local m = require("math.utils")')
        call_nodes = [n for n in cpg.local_builder.knowledge_nodes.values()
                      if n.get("type") == "function_call"
                      and n.get("properties", {}).get("name") == "require"]
        assert len(call_nodes) == 0


# ──────────────────────────────────────────────────────────────────────────────
# CPG — dot / field access  (t.field, t.method(), t.x.y)
# ──────────────────────────────────────────────────────────────────────────────

class TestCPGDotAccess:

    def test_dot_field_access_creates_index_expression_node(self):
        _, ast, lst, cpg = build_cpg("local t = {}\nlocal x = t.field")
        assert len(kg_nodes_of_type(cpg, "index_expression")) >= 1

    def test_dot_field_access_has_accesses_member_of_edge(self):
        _, ast, lst, cpg = build_cpg("local t = {}\nlocal x = t.field")
        index_ids = {n["_key"] for n in kg_nodes_of_type(cpg, "index_expression")}
        assert len(index_ids) >= 1
        assert any(e["_from"] in index_ids for e in kg_edges_of_relation(cpg, "accesses_member_of"))

    def test_dot_field_access_property_contains_field_name(self):
        _, ast, lst, cpg = build_cpg("local t = {}\nlocal x = t.field")
        nodes = kg_nodes_of_type(cpg, "index_expression")
        assert len(nodes) >= 1
        props = nodes[0].get("properties", {})
        assert props.get("field") == "field" or props.get("key") == "field"

    def test_dot_method_call_creates_index_expression_node(self):
        _, ast, lst, cpg = build_cpg("local t = {}\nt.method()")
        assert len(kg_nodes_of_type(cpg, "index_expression")) >= 1
        export_from_builder(cpg)

    def test_chained_dot_access_creates_multiple_nodes(self):
        _, ast, lst, cpg = build_cpg("local a = t.x.y")
        assert len(kg_nodes_of_type(cpg, "index_expression")) >= 2

    def test_dot_access_on_imported_module_records_name_and_field(self):
        code = 'local m = require("math.utils")\nlocal x = m.sqrt'
        _, ast, lst, cpg = build_cpg(code)
        nodes = kg_nodes_of_type(cpg, "index_expression")
        assert len(nodes) >= 1
        props = nodes[0].get("properties", {})
        assert props.get("name") == "m"
        assert props.get("field") == "sqrt"


# ──────────────────────────────────────────────────────────────────────────────
# CPG — table constructors  ({ ... })
# ──────────────────────────────────────────────────────────────────────────────

class TestCPGTableConstructors:

    def test_table_constructor_creates_node(self):
        _, ast, lst, cpg = build_cpg("local t = {1, 2, 3}")
        assert len(kg_nodes_of_type(cpg, "table_constructor")) == 1

    def test_empty_table_constructor_creates_node(self):
        _, ast, lst, cpg = build_cpg("local t = {}")
        assert len(kg_nodes_of_type(cpg, "table_constructor")) == 1

    def test_keyed_fields_recorded_in_table_keys_property(self):
        _, ast, lst, cpg = build_cpg("local t = {a=1, b=2}")
        nodes = kg_nodes_of_type(cpg, "table_constructor")
        assert len(nodes) == 1
        fi = nodes[0].get("properties", {}).get("table_keys", "")
        assert "a" in fi and "b" in fi

    def test_table_constructor_has_field_edges_to_value_nodes(self):
        _, ast, lst, cpg = build_cpg("local x = 1\nlocal t = {a=x}")
        ctor_nodes = kg_nodes_of_type(cpg, "table_constructor")
        assert len(ctor_nodes) >= 1
        ctor_id = ctor_nodes[0]["_key"]
        has_field_edges = [e for e in kg_edges_of_relation(cpg, "has_field") if e["_from"] == ctor_id]
        assert len(has_field_edges) >= 1

    def test_mixed_table_keys_cover_positional_and_keyed(self):
        _, ast, lst, cpg = build_cpg('local t = {1, key="val"}')
        nodes = kg_nodes_of_type(cpg, "table_constructor")
        assert len(nodes) == 1
        fi = nodes[0].get("properties", {}).get("table_keys", "")
        assert len(fi.split(",")) == 2

    def test_positional_keys_are_1_indexed(self):
        _, ast, lst, cpg = build_cpg("local t = {10, 20, 30}")
        nodes = kg_nodes_of_type(cpg, "table_constructor")
        fi = nodes[0].get("properties", {}).get("table_keys", "")
        assert fi == "1,2,3"


# ──────────────────────────────────────────────────────────────────────────────
# CPG — literals  (number, string, true, false, nil)
# ──────────────────────────────────────────────────────────────────────────────

class TestCPGLiterals:

    def test_number_literal_creates_node(self):
        _, ast, lst, cpg = build_cpg("local x = 42")
        nodes = kg_nodes_of_type(cpg, "literal")
        assert any(n.get("properties", {}).get("kind") == "number" for n in nodes)

    def test_string_literal_creates_node(self):
        _, ast, lst, cpg = build_cpg('local x = "hello"')
        nodes = kg_nodes_of_type(cpg, "literal")
        assert any(n.get("properties", {}).get("kind") == "string" for n in nodes)

    def test_boolean_literals_create_nodes(self):
        _, ast, lst, cpg = build_cpg("local a = true\nlocal b = false")
        kinds = {n.get("properties", {}).get("kind") for n in kg_nodes_of_type(cpg, "literal")}
        assert "true" in kinds and "false" in kinds

    def test_nil_literal_creates_node(self):
        _, ast, lst, cpg = build_cpg("local x = nil")
        nodes = kg_nodes_of_type(cpg, "literal")
        assert any(n.get("properties", {}).get("kind") == "nil" for n in nodes)

    def test_literal_value_property_is_correct(self):
        _, ast, lst, cpg = build_cpg("local x = 99")
        nodes = kg_nodes_of_type(cpg, "literal")
        assert any(n.get("properties", {}).get("value") == "99" for n in nodes)

    def test_literal_as_function_argument_has_argument_edge(self):
        _, ast, lst, cpg = build_cpg('print(1, "ok")')
        literal_ids = {n["_key"] for n in kg_nodes_of_type(cpg, "literal")}
        assert any(e["_to"] in literal_ids for e in kg_edges_of_relation(cpg, "has_argument"))

    def test_positional_literals_in_table_have_has_field_edges(self):
        _, ast, lst, cpg = build_cpg("local t = {1, 2, 3}")
        ctor_id = kg_nodes_of_type(cpg, "table_constructor")[0]["_key"]
        has_field_edges = [e for e in kg_edges_of_relation(cpg, "has_field") if e["_from"] == ctor_id]
        assert len(has_field_edges) == 3

    def test_keyed_literal_in_table_has_field_edge(self):
        _, ast, lst, cpg = build_cpg("local t = {a=1}")
        ctor_id = kg_nodes_of_type(cpg, "table_constructor")[0]["_key"]
        has_field_edges = [e for e in kg_edges_of_relation(cpg, "has_field") if e["_from"] == ctor_id]
        assert len(has_field_edges) == 1

    def test_literal_return_creates_literal_node_and_returns_edge(self):
        _, ast, lst, cpg = build_cpg("local function f() return 42 end")
        assert len(kg_nodes_of_type(cpg, "literal")) >= 1
        assert len(kg_edges_of_relation(cpg, "returns")) >= 1


# ──────────────────────────────────────────────────────────────────────────────
# CPG — bracket indexing  (t[i], t[i][j])
# ──────────────────────────────────────────────────────────────────────────────

class TestCPGBracketIndex:

    def test_bracket_index_creates_index_expression_node(self):
        _, ast, lst, cpg = build_cpg("local t = {}\nlocal x = t[1]")
        assert len(kg_nodes_of_type(cpg, "index_expression")) >= 1

    @pytest.mark.xfail(reason="not yet implemented")
    def test_bracket_index_has_accesses_member_of_edge_to_table(self):
        _, ast, lst, cpg = build_cpg("local t = {}\nlocal x = t[1]")
        index_ids = {n["_key"] for n in kg_nodes_of_type(cpg, "index_expression")}
        assert len(index_ids) >= 1
        assert any(e["_from"] in index_ids for e in kg_edges_of_relation(cpg, "accesses_member_of"))

    def test_bracket_index_with_variable_key(self):
        _, ast, lst, cpg = build_cpg("local x = arr[key]")
        assert len(kg_nodes_of_type(cpg, "index_expression")) >= 1
        assert "key" in cpg.unresolved_edges or "arr" in cpg.unresolved_edges

    @pytest.mark.xfail(reason="tree-sitter parses mat[i][j] as a single bracket_index_expression; nested nodes not yet supported")
    def test_chained_bracket_index_creates_multiple_nodes(self):
        _, ast, lst, cpg = build_cpg("local x = mat[i][j]")
        assert len(kg_nodes_of_type(cpg, "index_expression")) >= 2

    @pytest.mark.xfail(reason="not yet implemented")
    def test_write_via_bracket_index(self):
        _, ast, lst, cpg = build_cpg("arr[1] = 42")
        assert len(kg_nodes_of_type(cpg, "index_expression")) >= 1


# ──────────────────────────────────────────────────────────────────────────────
# CPG — integration tests
# ──────────────────────────────────────────────────────────────────────────────

class TestCPGIntegration:

    def test_complex_function_with_control_flow(self):
        code = """
local function classify(n)
    if n > 0 then
        return "positive"
    elseif n < 0 then
        return "negative"
    else
        return "zero"
    end
end
"""
        _, ast, lst, cpg = build_cpg(code)
        assert len(kg_nodes_of_type(cpg, "local_function_definition")) == 1
        assert len(kg_nodes_of_type(cpg, "if_statement")) >= 1

    def test_function_with_loop_and_local_vars(self):
        code = """
function accumulate(limit)
    local sum = 0
    for i = 1, limit do
        sum = sum + i
    end
    return sum
end
"""
        _, ast, lst, cpg = build_cpg(code)
        assert len(kg_nodes_of_type(cpg, "global_function_definition")) == 1
        assert len(kg_nodes_of_type(cpg, "for_statement")) >= 1
        assert len(kg_nodes_of_type(cpg, "local_variable_declaration")) >= 1

    def test_module_with_require_and_functions(self):
        code = """
local lpeg = require 'lpeg'

module 'leg.grammar'

function anyOf(list)
    local patt = lpeg
    return patt
end
"""
        _, ast, lst, cpg = build_cpg(code)
        assert len(kg_nodes_of_type(cpg, "module")) >= 1
        assert len(kg_nodes_of_type(cpg, "global_function_definition")) >= 1
        assert "lpeg" in lst.imports or "lpeg" in cpg.unresolved_edges

    def test_complex_program_export_to_gephi(self):
        """Full-feature Lua program: exercises tables, dot access, loops, conditionals,
        literals, function calls, and return values. Exports to k_nodes.csv / k_edges.csv."""
        code = """
local utils = require 'utils'

local THRESHOLD = 10
local STATUS = {
    ok      = true,
    failed  = false,
    code    = 42,
    message = "nominal",
}

local function clamp(value, min_val, max_val)
    if value < min_val then
        return min_val
    elseif value > max_val then
        return max_val
    else
        return value
    end
end

local function process(items)
    local result = {}
    local count  = 0

    for i = 1, #items do
        local item  = items[i]
        local score = item.score

        if score > THRESHOLD then
            result[count] = item.name
            count = count + 1
        end
    end

    return result
end

function run(config)
    local limit  = config.limit
    local data   = config.data
    local output = process(data)

    if STATUS.ok then
        local clamped = clamp(limit, 0, 100)
        return clamped
    end

    return nil
end
"""
        _, ast, lst, cpg = build_cpg(code)

        assert len(kg_nodes_of_type(cpg, "global_function_definition")) >= 1
        assert len(kg_nodes_of_type(cpg, "local_function_definition")) >= 2
        assert len(kg_nodes_of_type(cpg, "table_constructor")) >= 1
        assert len(kg_nodes_of_type(cpg, "if_statement")) >= 1
        assert len(kg_nodes_of_type(cpg, "for_statement")) >= 1
        assert len(kg_nodes_of_type(cpg, "literal")) >= 1
        assert len(kg_nodes_of_type(cpg, "index_expression")) >= 1

        export_from_builder(cpg)
    def test_complex_program_export_for_thesis(self):
        """Full-feature Lua program: exercises tables, dot access, loops, conditionals,
        literals, function calls, and return values. Exports to k_nodes.csv / k_edges.csv."""
#         code = """
# local utils = require("math.utils")
#
# function process(data)
#     return utils.sqrt(data)
# end
# """

        code = """
local count = 0

local function add(a, b)
    count = count + 1
    return a + b
end

add(1, 2)

local function sum_list(list)
    local total = 0
    for i = 1, #list do
        total = add(total, list[i])
    end
    return total
end
"""
        _, ast, lst, cpg = build_cpg(code)

        export_from_builder(cpg)
