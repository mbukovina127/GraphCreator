_TYPE_TO_KEY = {
    "generic_for_statement":    "GenericFor",
    "numeric_for_statement":    "NumericFor",
    "if_statement":             "If",
    "assignment_statement":     "Assign",
    "local_variable_declaration": "LocalAssign",
    "function_call":            "FunctionCall",
    "local_function_definition": "LocalFunction",
    "global_function_definition": "GlobalFunction",
}


def _walk(node, counts: dict):
    key = _TYPE_TO_KEY.get(node.type)
    if key:
        counts[key] = counts.get(key, 0) + 1
    for child in node.children:
        _walk(child, counts)


def calculate_statement_usage(node) -> dict:
    counts = {k: 0 for k in _TYPE_TO_KEY.values()}
    _walk(node, counts)
    return counts


def calculate_statement_usage_agr(node):
    return "statement_usage", calculate_statement_usage(node)
