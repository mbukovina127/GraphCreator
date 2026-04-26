def calculate_function_counts(lst) -> dict:
    """Count function symbols across all scopes in a SymbolTable."""
    global_count = 0
    local_count = 0
    for scope in lst.scopes.values():
        for sym in scope.symbols.values():
            if sym.kind == "global_function":
                global_count += 1
            elif sym.kind == "local_function":
                local_count += 1
    return {
        "total": global_count + local_count,
        "global": global_count,
        "local": local_count,
    }


def calculate_function_counts_agr(lst):
    return "function_counts", calculate_function_counts(lst)
