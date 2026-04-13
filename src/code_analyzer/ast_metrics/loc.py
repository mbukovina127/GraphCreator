# function calculates a sum of lines of code in a subtree
from typing import Dict


def calculate_loc(node):
    loc = len(node.text.split(b'\n'))
    return loc
def calculate_loc_agr(node):
    return "loc", calculate_loc(node)