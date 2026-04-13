import logging
import pytest
import tempfile
import sys
import os

from ray_implementation.bloatedmess import export_to_gephi_csv, export_from_builder

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from code_analyzer.parse_code import ParallelASTManager
from ray_implementation import SymbolBuilder, CPGBuilder, LocalOutputBuilder, SymbolTable
from ray_implementation import bloatedmess

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────/
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
# Symbol Table Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestSymbolCreation:

    # ── Variables ─────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("code, exp_local, exp_global", [
        ("local a = 5\na = 1",   1, 0),
        ("local a\na = 1",       1, 0),
        ("a = 1",                0, 1),
        ("a = 1\na = 2",         0, 1),   # re-assignment, no second symbol
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
        """Re-assigning a variable should not add a second symbol."""
        ast, lst = build_symbol_table("local a = 1\na = 2\na = 3")
        syms = lst.scope_lookup_by_kind(ast.root_node.id, "local_variable")
        assert len(syms) == 1

    # ── Functions ─────────────────────────────────────────────────────────────

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
        assert len(lst.scopes) == 2  # chunk scope + function body scope

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

    # ── Require / module imports ───────────────────────────────────────────────

    def test_require_single(self):
        ast, lst = build_symbol_table('local m = require("math.utils")')
        assert "m" in lst.imports
        assert lst.imports["m"] == "math.utils"

    def test_require_multiple_same_line(self):
        ast, lst = build_symbol_table('local a, b = require "module_a", require "module_b"')
        assert lst.imports.get("a") == "module_a"
        assert lst.imports.get("b") == "module_b"

    def test_require_symbol_kind_is_module_representation(self):
        """Variable bound to require() must be tagged as local_module_representation."""
        ast, lst = build_symbol_table('local m = require("utils")')
        sym = lst.scope_lookup_by_name(ast.root_node.id, "m")
        assert sym is not None
        assert sym.kind == "local_module_representation"

    def test_require_different_quoting_styles(self):
        """require accepts both single-quoted and double-quoted strings."""
        ast, lst = build_symbol_table("local a = require 'mod.a'\nlocal b = require(\"mod.b\")")
        assert lst.imports.get("a") == "mod.a"
        assert lst.imports.get("b") == "mod.b"

    def test_require_two_modules_both_marked(self):
        """Both variables should be module_representation when both sides are require."""
        ast, lst = build_symbol_table('local a, b = require "mod_a", require "mod_b"')
        sym_a = lst.scope_lookup_by_name(ast.root_node.id, "a")
        sym_b = lst.scope_lookup_by_name(ast.root_node.id, "b")
        assert sym_a.kind == "local_module_representation"
        assert sym_b.kind == "local_module_representation"

    # ── Module declaration ─────────────────────────────────────────────────────

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
        """Functions declared after a module statement should still be tracked."""
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
# CPG Builder Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestCPGBuilder:

    # ── Always-present chunk node ──────────────────────────────────────────────

    def test_chunk_node_always_created(self):
        _, ast, lst, cpg = build_cpg("local x = 1")
        assert len(kg_nodes_of_type(cpg, "chunk")) == 1

    # ── Variables ─────────────────────────────────────────────────────────────

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
        """The scope (chunk) node should have a 'declares' edge to the local variable."""
        _, ast, lst, cpg = build_cpg("local a = 5")
        declares_edges = kg_edges_of_relation(cpg, "declares")
        assert len(declares_edges) >= 1

    def test_local_variable_has_name_property(self):
        _, ast, lst, cpg = build_cpg("local x = 42")
        nodes = kg_nodes_of_type(cpg, "local_variable_declaration")
        assert len(nodes) == 1
        assert nodes[0].get("properties", {}).get("name") == "x"

    # ── Functions ─────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("code, exp_type", [
        ("local function add(x,y)\n\treturn x+y\nend", "local_function_definition"),
        ("function add(x,y)\n\treturn x+y\nend",       "global_function_definition"),
    ])
    def test_function_definition_node_created(self, code, exp_type):
        _, ast, lst, cpg = build_cpg(code)
        fns = kg_nodes_of_type(cpg, exp_type)
        assert len(fns) == 1

    def test_function_has_block_edge(self):
        _, ast, lst, cpg = build_cpg("local function add(x,y)\n\treturn x+y\nend")
        fns = kg_nodes_of_type(cpg, "local_function_definition")
        fn_id = fns[0]["_key"]
        has_block = [e for e in kg_edges_of_relation(cpg, "has_block") if e["_from"] == fn_id]
        assert len(has_block) == 1, "Function should have exactly one has_block edge"

    def test_function_with_params_has_parameter_edges(self):
        _, ast, lst, cpg = build_cpg("local function add(x, y)\n\treturn x+y\nend")
        fns = kg_nodes_of_type(cpg, "local_function_definition")
        fn_id = fns[0]["_key"]
        param_edges = [e for e in kg_edges_of_relation(cpg, "has_parameters") if e["_from"] == fn_id]
        assert len(param_edges) == 2

    def test_function_no_params_no_parameter_edges(self):
        _, ast, lst, cpg = build_cpg("local function f()\n\treturn 1\nend")
        fns = kg_nodes_of_type(cpg, "local_function_definition")
        fn_id = fns[0]["_key"]
        param_edges = [e for e in kg_edges_of_relation(cpg, "has_parameters") if e["_from"] == fn_id]
        assert len(param_edges) == 0

    def test_function_has_metrics(self):
        """Each function should have a metrics node attached via has_metrics."""
        _, ast, lst, cpg = build_cpg("function f(a)\n\treturn a\nend")
        fns = kg_nodes_of_type(cpg, "global_function_definition")
        fn_id = fns[0]["_key"]
        metrics_edges = [e for e in kg_edges_of_relation(cpg, "has_metrics") if e["_to"] == fn_id]
        assert len(metrics_edges) == 1

    def test_two_functions_both_have_definition_nodes(self):
        code = "function add(a,b)\n\treturn a+b\nend\nfunction sub(a,b)\n\treturn a-b\nend"
        _, ast, lst, cpg = build_cpg(code)
        assert len(kg_nodes_of_type(cpg, "global_function_definition")) == 2

    def test_function_name_in_node_properties(self):
        _, ast, lst, cpg = build_cpg("function greet(name)\n\treturn name\nend")
        fns = kg_nodes_of_type(cpg, "global_function_definition")
        assert len(fns) == 1
        assert fns[0].get("properties", {}).get("name") == "greet"

    # ── Unresolved edges ──────────────────────────────────────────────────────

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

    # ── Control flow ──────────────────────────────────────────────────────────

    def test_if_statement_node_created(self):
        _, ast, lst, cpg = build_cpg("if 1 == 1 then\n\treturn 1\nend")
        if_stmts = kg_nodes_of_type(cpg, "if_statement")
        assert len(if_stmts) >= 1
        assert if_stmts[0]["properties"]["kind"] == "if_statement"

    def test_if_statement_has_block(self):
        _, ast, lst, cpg = build_cpg("if 1 == 1 then\n\treturn 1\nend")
        ifs = kg_nodes_of_type(cpg, "if_statement")
        if_id = ifs[0]["_key"]
        has_block = [e for e in kg_edges_of_relation(cpg, "has_block") if e["_from"] == if_id]
        assert len(has_block) == 1

    def test_if_has_condition_edge(self):
        _, ast, lst, cpg = build_cpg("if 1 == 1 then\n\treturn 1\nend")
        ifs = kg_nodes_of_type(cpg, "if_statement")
        if_id = ifs[0]["_key"]
        cond_edges = [e for e in kg_edges_of_relation(cpg, "has_condition") if e["_from"] == if_id]
        assert len(cond_edges) >= 1

    def test_nested_if_creates_multiple_nodes(self):
        code = """
local x = 10
if x > 5 then
    if x > 8 then
        x = 0
    end
end
"""
        _, ast, lst, cpg = build_cpg(code)
        assert len(kg_nodes_of_type(cpg, "if_statement")) == 2

    def test_if_elseif_else_all_create_nodes(self):
        code = """
local x = 10
if x == 1 then
    x = 10
elseif x == 2 then
    x = 20
else
    x = 30
end
"""
        _, ast, lst, cpg = build_cpg(code)
        assert len(kg_nodes_of_type(cpg, "if_statement")) >= 1
        assert len(kg_nodes_of_type(cpg, "elseif_statement")) >= 1

    # ── Loops ─────────────────────────────────────────────────────────────────

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

    # ── Module declaration (CPG level) ────────────────────────────────────────

    def test_module_declaration_creates_module_node(self):
        _, ast, lst, cpg = build_cpg("module 'leg.parsing'")
        mod_nodes = kg_nodes_of_type(cpg, "module")
        assert len(mod_nodes) >= 1

    def test_module_node_has_module_name_property(self):
        _, ast, lst, cpg = build_cpg("module 'leg.parsing'")
        mod_nodes = kg_nodes_of_type(cpg, "module")
        assert len(mod_nodes) >= 1
        assert mod_nodes[0].get("properties", {}).get("module_name") == "leg.parsing"

    def test_module_with_functions_creates_both_nodes(self):
        code = """
module 'net.utils'
function send(data)
    return data
end
"""
        _, ast, lst, cpg = build_cpg(code)
        assert len(kg_nodes_of_type(cpg, "module")) >= 1
        assert len(kg_nodes_of_type(cpg, "global_function_definition")) >= 1

    # ── Module importing (require) ────────────────────────────────────────────

    def test_require_call_function_node_type(self):
        """require() is currently processed as a function_call knowledge node."""
        _, ast, lst, cpg = build_cpg('local m = require("math.utils")')
        # The require is treated as a function_call - an unresolved reference to "require"
        assert "require" in cpg.unresolved_edges or \
               len(kg_nodes_of_type(cpg, "function_call")) >= 1

    @pytest.mark.xfail(reason="module_import nodes not yet implemented: see _cpg_declarations._node_variable step 2")
    def test_require_creates_module_import_node(self):
        """After implementing step 2, require() should produce a module_import node."""
        _, ast, lst, cpg = build_cpg('local m = require("math.utils")')
        import_nodes = kg_nodes_of_type(cpg, "module_import")
        assert len(import_nodes) == 1
        assert import_nodes[0].get("properties", {}).get("module_path") == "math.utils"

    @pytest.mark.xfail(reason="require() should not create a function_call node once step 3 is implemented")
    def test_require_does_not_create_function_call_node(self):
        """After step 3, require() in _handle_call should be skipped — no function_call node."""
        _, ast, lst, cpg = build_cpg('local m = require("math.utils")')
        # require() call nodes should not appear in the knowledge graph
        call_nodes = [n for n in cpg.local_builder.knowledge_nodes.values()
                      if n.get("type") == "function_call"
                      and n.get("properties", {}).get("name") == "require"]
        assert len(call_nodes) == 0

# ──────────────────────────────────────────────────────────────────────────────
# CPG: Not-yet-implemented constructs (xfail)
# ──────────────────────────────────────────────────────────────────────────────

_XFAIL_NOT_IMPLEMENTED = "not yet implemented"


class TestCPGNotYetImplemented:

    # ── Dot / field access  (t.field, t.method()) ────────────────────────────

    @pytest.mark.xfail(reason=_XFAIL_NOT_IMPLEMENTED)
    def test_dot_field_access_creates_index_expression_node(self):
        """t.field should produce an index_expression knowledge node."""
        _, ast, lst, cpg = build_cpg("local t = {}\nlocal x = t.field")
        assert len(kg_nodes_of_type(cpg, "index_expression")) >= 1

    @pytest.mark.xfail(reason=_XFAIL_NOT_IMPLEMENTED)
    def test_dot_field_access_has_refers_to_edge(self):
        """The index_expression node for t.field should have a refers_to edge back to t."""
        _, ast, lst, cpg = build_cpg("local t = {}\nlocal x = t.field")
        refers_edges = kg_edges_of_relation(cpg, "refers_to")
        index_nodes = kg_nodes_of_type(cpg, "index_expression")
        assert len(index_nodes) >= 1
        index_ids = {n["_key"] for n in index_nodes}
        assert any(e["_from"] in index_ids for e in refers_edges)

    @pytest.mark.xfail(reason=_XFAIL_NOT_IMPLEMENTED)
    def test_dot_field_access_property_contains_field_name(self):
        """The index_expression node for t.field should record 'field' as the accessed key."""
        _, ast, lst, cpg = build_cpg("local t = {}\nlocal x = t.field")
        nodes = kg_nodes_of_type(cpg, "index_expression")
        assert len(nodes) >= 1
        props = nodes[0].get("properties", {})
        assert props.get("field") == "field" or props.get("key") == "field"

    @pytest.mark.xfail(reason=_XFAIL_NOT_IMPLEMENTED)
    def test_dot_method_call_creates_index_expression_node(self):
        """t.method() — the field access part should produce an index_expression node."""
        _, ast, lst, cpg = build_cpg("local t = {}\nt.method()")
        assert len(kg_nodes_of_type(cpg, "index_expression")) >= 1

    @pytest.mark.xfail(reason=_XFAIL_NOT_IMPLEMENTED)
    def test_chained_dot_access_creates_multiple_nodes(self):
        """t.x.y involves two field accesses; at least two index_expression nodes expected."""
        _, ast, lst, cpg = build_cpg("local a = t.x.y")
        assert len(kg_nodes_of_type(cpg, "index_expression")) >= 2

    # ── Table constructors  ({ ... }) ────────────────────────────────────────

    @pytest.mark.xfail(reason=_XFAIL_NOT_IMPLEMENTED)
    def test_table_constructor_creates_node(self):
        """A table literal should produce a table_constructor knowledge node."""
        _, ast, lst, cpg = build_cpg("local t = {1, 2, 3}")
        assert len(kg_nodes_of_type(cpg, "table_constructor")) == 1

    @pytest.mark.xfail(reason=_XFAIL_NOT_IMPLEMENTED)
    def test_table_constructor_keyed_fields_create_field_nodes(self):
        """Each key=value pair should produce a table_field node."""
        _, ast, lst, cpg = build_cpg("local t = {a=1, b=2}")
        assert len(kg_nodes_of_type(cpg, "table_field")) == 2

    @pytest.mark.xfail(reason=_XFAIL_NOT_IMPLEMENTED)
    def test_table_constructor_field_nodes_linked_via_ast_child(self):
        """The table_constructor node should have ast_child edges to its table_field nodes."""
        _, ast, lst, cpg = build_cpg("local t = {a=1}")
        constructor_nodes = kg_nodes_of_type(cpg, "table_constructor")
        assert len(constructor_nodes) >= 1
        ctor_id = constructor_nodes[0]["_key"]
        ast_child_edges = [e for e in kg_edges_of_relation(cpg, "ast_child")
                           if e["_from"] == ctor_id]
        assert len(ast_child_edges) >= 1

    @pytest.mark.xfail(reason=_XFAIL_NOT_IMPLEMENTED)
    def test_empty_table_constructor_creates_node(self):
        """An empty table literal {} should still produce a table_constructor node."""
        _, ast, lst, cpg = build_cpg("local t = {}")
        assert len(kg_nodes_of_type(cpg, "table_constructor")) == 1

    @pytest.mark.xfail(reason=_XFAIL_NOT_IMPLEMENTED)
    def test_mixed_table_constructor_all_fields_modeled(self):
        """Both positional and keyed entries should each produce a table_field node."""
        _, ast, lst, cpg = build_cpg('local t = {1, key="val"}')
        assert len(kg_nodes_of_type(cpg, "table_field")) == 2

    # ── Bracket indexing  (array[i], array[i][j]) ────────────────────────────

    def test_bracket_index_creates_index_expression_node(self):
        """array[i] should produce an index_expression knowledge node."""
        _, ast, lst, cpg = build_cpg("local t = {}\nlocal x = t[1]")
        assert len(kg_nodes_of_type(cpg, "index_expression")) >= 1

    @pytest.mark.xfail(reason=_XFAIL_NOT_IMPLEMENTED)
    def test_bracket_index_has_refers_to_edge_to_table(self):
        """The index_expression node for t[1] should have a refers_to edge pointing at t."""
        _, ast, lst, cpg = build_cpg("local t = {}\nlocal x = t[1]")
        refers_edges = kg_edges_of_relation(cpg, "refers_to")
        index_nodes = kg_nodes_of_type(cpg, "index_expression")
        assert len(index_nodes) >= 1
        index_ids = {n["_key"] for n in index_nodes}
        assert any(e["_from"] in index_ids for e in refers_edges)

    @pytest.mark.xfail(reason=_XFAIL_NOT_IMPLEMENTED)
    def test_bracket_index_with_variable_key(self):
        """arr[key] — the index_expression node should exist; unknown 'key' goes to unresolved."""
        _, ast, lst, cpg = build_cpg("local x = arr[key]")
        assert len(kg_nodes_of_type(cpg, "index_expression")) >= 1
        assert "key" in cpg.unresolved_edges or "arr" in cpg.unresolved_edges

    @pytest.mark.xfail(reason=_XFAIL_NOT_IMPLEMENTED)
    def test_chained_bracket_index_creates_multiple_nodes(self):
        """mat[i][j] involves two bracket accesses; at least two index_expression nodes expected."""
        _, ast, lst, cpg = build_cpg("local x = mat[i][j]")
        assert len(kg_nodes_of_type(cpg, "index_expression")) >= 2

    @pytest.mark.xfail(reason=_XFAIL_NOT_IMPLEMENTED)
    def test_write_via_bracket_index(self):
        """arr[1] = 42 on the LHS should still produce an index_expression node."""
        _, ast, lst, cpg = build_cpg("arr[1] = 42")
        assert len(kg_nodes_of_type(cpg, "index_expression")) >= 1

    # ── Complex integration ───────────────────────────────────────────────────

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
        """Integration: module declaration + require import + function definitions."""
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
        # lpeg should be tracked in imports
        assert "lpeg" in lst.imports or \
               "lpeg" in cpg.unresolved_edges  # acceptable either way before step 3