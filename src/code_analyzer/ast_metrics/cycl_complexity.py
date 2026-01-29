# function calculates cyclomatic complexity recursively
# starts with cc=1 as a base of every function
def calculate_cyclomatic_complexity(node, cc=1):
    # if this node is a decision point, increment the counter
    if node.type in [      
        "if_statement", 
        "elseif_statement", 
        "while_statement",
        "for_statement", 
        "repeat_statement"
    ]:
        cc += 1
    # recursively process all children
    for child in node.children:
        cc = calculate_cyclomatic_complexity(child, cc)

    return cc
