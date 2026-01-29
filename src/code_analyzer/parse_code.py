from typing import ClassVar, Dict, Optional
from tree_sitter import Language, Parser, Tree
import tree_sitter_lua as tslua

# ASTManager is a singleton class
# because we want to have only one instance of the parser and language
# and we dont want to use them as global variables
class ASTManager:
    _instance: ClassVar[Optional["ASTManager"]] = None
    
    # Instance variables (initialized in __new__)
    _ast_dict: Dict[str, Tree]
    _parser: Parser
    _language: Language
    _project_name: Optional[str]
    _project_path: Optional[str]

    # singleton pattern -> only one instance of ASTManager 
    # so that the parser and language are not re-initialized
    def __new__(cls) -> "ASTManager":
        if cls._instance is None:
            # if the class is not initialized yet, create new instance
            instance = super(ASTManager, cls).__new__(cls)
            instance._language = Language(tslua.language())
            instance._parser = Parser()
            instance._parser.language = instance._language
            instance._ast_dict = {}
            instance._project_name = None
            instance._project_path = None
            cls._instance = instance
        return cls._instance

    # method that creates AST and add it to the _ast_dict with path to the file
    def parse(self, file_path: str, incremental: bool = False) -> Tree:
        # read source code
        with open(file_path, "rb") as f:
            lua_code = f.read()
        if incremental and file_path in self._ast_dict:
            # if the file was already parsed and we want to use Tree-sitters incremental parsing
            self._ast_dict[file_path] = self._parser.parse(lua_code, self._ast_dict[file_path])
        else:
            self._ast_dict[file_path] = self._parser.parse(lua_code)
            
        return self._ast_dict[file_path]

    # method returns AST of a certain file from _ast_dict
    def get_ast(self, file_path: str) -> Tree:
        if not self._ast_dict:
            raise ValueError("No ASTs have been parsed yet. Call parse() first.")
            
        if file_path not in self._ast_dict:
            raise ValueError(f"No AST found for {file_path}. Parse this file first.")
            
        return self._ast_dict[file_path]
    
    def clear(self) -> None:
        """Clear all stored ASTs - useful for processing new projects"""
        self._ast_dict.clear()
        self._project_name = None
        self._project_path = None
