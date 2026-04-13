"""
Data structure keeping track of a scope while parsing AST to a graph
"""
from typing import List, Optional

from ray_implementation.dto.context import Context


class ContextStack:
    def __init__(self):
        self.context_stack: List[Context] = []
        self.context_relevant_node_ids: List[str] = []

    def __eq__(self, other):
        if isinstance(other, Context):
            return self.context_stack[-1] == other
        return False

    def __ne__(self, other: Context):
        if isinstance(other, Context):
            return self.context_stack[-1] != other
        return False

    def push_context(self, ids, context: Context):
        """Push the context from the Context enum onto the stack
        :param ids: the ids of the context
        :param context: the context to be pushed"""
        self.context_stack.append(context)
        self.context_relevant_node_ids.append(ids)

    def pop_context(self) -> tuple[Context, str]:
        """Pops the stack and @returns: context_type and a list of relevant_node_ids"""
        return self.context_stack.pop(), self.context_relevant_node_ids.pop()

    def peek_context(self, offset: int = -1) -> Optional[Context]:
        try:
            result = self.context_stack[offset]
        except IndexError:
            result = None
        return result

    def get_context(self, offset: int = -1) -> tuple[Context, str]:
        """@returns: context_type and a list of relevant_node_ids"""
        try:
            context = self.context_stack[offset]
            ids = self.context_relevant_node_ids[offset]
        except IndexError:
            raise IndexError("Index out of range")
        return context, ids

    def find_in_wider_context(self, target: List[Context]) -> Optional[str]:
        """Finds the relevant id of the deeper most target context if it was found else None"""
        for i in reversed(range(len(self.context_stack))):
            if self.context_stack[i] in target:
                return self.context_relevant_node_ids[i]
        return None
