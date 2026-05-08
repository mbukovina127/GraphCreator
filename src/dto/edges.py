from enum import Enum


class Edges(Enum):
    # Structural / scope
    DEFINES = "defines"
    DECLARES = "declares"
    CONTAINS = "contains"
    IMPORTS = "imports"
    # Function structure
    HAS_BLOCK = "has_block"
    HAS_PARAMETERS = "has_parameters"
    HAS_FIELD = "has_field"
    HAS_ARGUMENT = "has_argument"
    HAS_CONDITION = "has_condition"
    # Data flow
    REFERS_TO = "refers_to"
    CALLS = "calls"
    RETURNS = "returns"
    FLOWS_TO = "flows_to"
    INITIALIZES = "initializes"
    ASSIGNS_TO = "assigns_to"
    INSIDE_OF = "inside_of"
    EXECUTES = "executes"
    # Graph connectivity
    IS = "is"
    CHILD_OF = "child_of"
    # Metrics
    HAS_METRICS = "has_metrics"
    # CPG v1 standard (uppercase by convention)
    AST_CHILD = "AST_CHILD"
    HAS_PARAMETER = "has_parameter"
    DOCUMENTS = "documents"
    HAS_SCOPE = "has_scope"
    NESTED = "nested"
    CAPTURES = "captures"
    REACHES = "reaches"
