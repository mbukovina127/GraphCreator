# function calculates a sum of lines of code in a subtree
def calculate_loc(node):
    loc = len(node.text.split(b'\n'))
    return loc
