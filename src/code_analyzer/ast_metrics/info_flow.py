_PUNCTUATION = {"(", ")", ","}


def _count_parameters(node) -> int:
    params_node = next(
        (c for c in node.children if c.type == "parameters"), None
    )
    if params_node is None:
        return 0
    return sum(
        1 for c in params_node.children
        if c.type not in _PUNCTUATION and c.type != "self"
    )


def _count_returns(node) -> int:
    count = 0
    for child in node.children:
        if child.type == "return_statement":
            # a bare `return` has no value children beyond the keyword
            has_value = any(c.type not in ("return",) for c in child.children)
            if has_value:
                count += 1
        else:
            count += _count_returns(child)
    return count


def calculate_info_flow(node) -> dict:
    args_in = _count_parameters(node)
    args_out = _count_returns(node)
    return {
        "args_in": args_in,
        "args_out": args_out,
        "interface_complexity": (args_in + args_out) ** 2,
    }


def calculate_info_flow_agr(node):
    return "info_flow", calculate_info_flow(node)
