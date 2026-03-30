from enum import Enum, auto

class Context(Enum):
    CHUNK = auto()
    MODULE = auto()
    VAR_DECL = auto()
    EXPRESSION = auto()
    ARGUMENTS = auto() #function calls
    ASSIGNMENT = auto()
    RETURN = auto()
    PARAMETERS = auto()
    BLOCK = auto()
    FUN_DECL = auto()
    IF_STATEMENT = auto() # control statement
    CONTROL_STATEMENT = auto()
    LOOP = auto()
    FOR_CLAUSE = auto()
