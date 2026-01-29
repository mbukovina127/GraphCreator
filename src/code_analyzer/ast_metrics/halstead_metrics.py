import math

def get_operands_operators(node, not_leaves=None, operands=None, operators=None, operator_count=0, operand_count=0):
    # initialize sets
    if operators is None:
        operators = set()  # will store unique operator strings
    if operands is None:
        operands = set()   # will store unique operand values/names

    # skip comment nodes entirely and string content subtree count as one token
    if node.type == "comment" or node.type == "string_content":
        if node.type == "string_content":
            operands.add(node.type)
            operand_count += 1

    operator_symbols = {
        # logical / relational / bitwise / arithmetic symbols
        # symbols "]", ")", "}", "]]", "\"", "'" are missing because the pair counts as one operator
        "#", "%", "&", "(", "*", "+", ",", "-", ".", "..",
        "/", "//", ":", "::", ";", "<", "<<", "<=", "=", "==", ">", ">=", ">>",
        "[", "[[", "^", "{", "|", "~", "~=",
        # control-flow / keywords 
        "and", "do", "else", "elseif", "for", "function", "goto", "if", "in",
        "local", "not", "or", "repeat", "return", "then", "until", "while", "end",
    }

    # recursively process AST
    if node.child_count > 0:
        for child in node.children:
            operators, operands, operator_count, operand_count = get_operands_operators(
                child, not_leaves, operands, operators, operator_count, operand_count
            )
    else:
        # leaf token - get the actual text content
        # safer if the type name was different than the text if represents
        token_text = node.text.decode('utf-8')
        # check if this is an operator
        if token_text in operator_symbols or node.type in operator_symbols:
            operators.add(token_text)
            operator_count += 1
        elif token_text in [")", "]", "}"]:
            # these operators come in pairs but are counted as one operator
            # if the code has f.e. only one bracket,
            # the parser creates both nodes and set attribute is_missing=True of representing missing node 
            # in that case we dont have to count the other pair of these operators
            pass
        elif token_text in  ["\"", "\'"]:
            operators.add(token_text)
            # adds 0.5 because they always come in pair, function add will add only one qoute/doublequote
            operator_count += 0.5
        else:
            operands.add(token_text)
            operand_count += 1

    return operators, operands, operator_count, operand_count

# function calculates halstead metrics for a subtree
def calculate_halstead_metrics(node):
    # get operands, operators and their quantity
    operators, operands, operator_count, operand_count = get_operands_operators(node)

    # after recursion, calculate Halstead metrics
    n1 = len(operators)        # number of distinct operators
    n2 = len(operands)         # number of distinct operands
    N1 = operator_count        # total operator occurrences
    N2 = operand_count         # total operand occurrences

    n = n1 + n2                # vocabulary
    N = N1 + N2                # length

    if n == 0:
        volume = 0
    else:
        volume = N * math.log2(n)

    if n2 == 0:
        difficulty = 0
    else:
        difficulty = (n1 / 2.0) * (N2 / n2)

    effort = volume * difficulty
    time_ = effort / 18.0 if effort > 0 else 0.0
    bugs = (effort ** (2.0/3.0) / 3000.0) if effort > 0 else 0.0

    return {
        "n1": n1,
        "n2": n2,
        "N1": N1,
        "N2": N2,
        "n": n,
        "N": N,
        "V": round(volume, 4),
        "D": round(difficulty, 4),
        "E": round(effort, 4),
        "T": round(time_, 4),
        "B": round(bugs, 4)
    }
