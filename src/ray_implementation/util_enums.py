from enum import Enum, auto

class Context(Enum):
    GLOBAL = auto()
    VAR_DECL = auto()
    EXPRESSION = auto()
    ARGUMENTS = auto() #function calls
    ASSIGNMENT = auto()
    RETURN = auto()
    PARAMETERS = auto()
    BLOCK = auto()
    FUN_DECL = auto()
