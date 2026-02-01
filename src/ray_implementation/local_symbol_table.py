from dataclasses import dataclass
from typing import Dict, List, Literal, Optional


@dataclass(frozen=True)
class SymbolID:
    worker_id: str
    file_path: str
    scope_id: str
    name: str # variable or function name
    kind: Literal[
        "module",
        "function",
        "local_function",
        "global_function",
        "local_var",
        "global_var",
        "parameter"
    ] # declerations
    ast_id: str
    start_byte: Optional[int] = None
    end_byte: Optional[int] = None

@dataclass
class Scope:
    scope_id: str
    parent: Optional[str]
    symbols: Dict[str, SymbolID]

class SymbolTable:
    """
    
    """
    def __init__(self, worker_id: str):
        self.worker_id = worker_id
        self.scopes: Dict[str, Scope] = {}
        """scopes, scope has a tree like structure. You are able to look up symbols from buttom up through its parents"""
        self.exports: Dict[str, SymbolID] = {}
        """symbols"""
        self.imports: Dict[str, str] = {}
        """mappinng of importeted modules to variables i.e. local m = require("math.utils") `m <- math.utils`"""
        self.unresolved: Dict[str, SymbolID] = {}
        """unresolved symbols without an edge. Mostly references to other files or errors"""

    def add_scope(self, scope: Scope):
        self.scopes[scope.scope_id] = scope
    
    def add_export(self, symbol: SymbolID):
        self.exports[symbol.name] = symbol
        
    def add_import(self, var_name: str, module_name: str):
        self.imports[var_name] = module_name
    
    def add_unresolved(self, symbol: SymbolID):
        self.unresolved[symbol.name] = symbol
    
    def scope_lookup(self, scope_id, target:str) -> Optional[SymbolID]:
        """
        Intended purpose is to look up symbols and its node ids to create knowledge edges
        
        @return: symbol if found else None
        """
        scope = self.scopes[scope_id]

        while scope is not None:
            sym = scope.symbols.get(target)
            if sym is not None:
                return sym
          
            scope = self.scopes[scope.parent] if scope.parent is not None else None
        return None

#TODO maybe seperate lst logic from this
class ScopeStack: 
    """
    Structure that maintains context scope and saves its state to local symbol table
    """
    def __init__(self, worker_id, file_path, lst: SymbolTable):
        self.lst = lst
        self.stack: List[Scope] = []
        self._worker_id = worker_id
        self._file_path = file_path
        self._id = 0

    def __current_scope(self):
        return None if len(self.stack) == 0 else self.stack[-1].scope_id
    
    def push_scope(self, scope_id: str):
        id = scope_id
        parent_id = self.__current_scope()
        new = Scope(id, parent_id, {})
        
        self.stack.append(new)
        self.lst.scopes[new.scope_id] = new #FIXME 
        
        return new
    
    def pop_scope(self):
        return self.stack.pop()

    def add_to_scope(self, name: str, id, kind, s_byte, e_byte):
        """
        Adding symbol to scope
        """
        symbol = SymbolID(
            worker_id=self._worker_id,
            file_path=self._file_path,
            scope_id=str(self.__current_scope()),
            name=name,
            kind=kind,
            ast_id=id,
            start_byte=s_byte,
            end_byte=e_byte
        )
        
        self.stack[-1].symbols[symbol.name] = symbol
        self.lst.exports[symbol.name] = symbol
        return