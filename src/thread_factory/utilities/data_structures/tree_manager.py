import abc
from typing import List, Optional
import uuid
from thread_factory.utilities.interfaces.disposable import IDisposable


# TODO 1: Rename "Tree" to "Synaptic" or "Pulse Storage" later.

class TreeNode(IDisposable):
    """
    Represents a node in a hierarchy (with categories and items).
    Categories group items and other categories. Items hold actual content.
    """

    def __init__(self,
                 name: str,
                 type: str,
                 metadata: Optional[dict] = None,
                 unique_id: Optional[str] = None):
        super().__init__()
        if type not in {"category", "item"}:
            raise ValueError("Type must be 'category' or 'item'.")

        self.name: str = name
        self.type: str = type
        self.metadata: dict = metadata or {}
        self.children: List["TreeNode"] = []
        self.unique_id: str = unique_id or str(uuid.uuid4())

    def add_child(self, child: "TreeNode") -> None:
        if self.type != "category":
            raise ValueError("Only category nodes can have children (items cannot have children).")
        self.children.append(child)

    def dispose(self):
        """
        Dispose of this node and all its children recursively.
        """
        if self._disposed:
            return

        for child in self.children:
            child.dispose()

        # Here you would release any resources held by this node.
        self._disposed = True
        if isinstance(self.metadata, dict):
            self.metadata.clear()
        self.children.clear()

    @staticmethod
    def find_all_abc_names_for_class(cls):
        """
        Iteratively finds the names of all ABCs in the inheritance hierarchy
        of a given class using a loop. Accepts a class reference as input.
        Returns a list of unique ABC names.
        """
        queue = list(cls.__bases__)
        visited = {cls}
        abc_names = set()

        while queue:
            base = queue.pop(0)
            if base in visited:
                continue
            visited.add(base)

            if isinstance(base, abc.ABCMeta):
                abc_names.add(base.__name__)

            queue.extend(base.__bases__)

        return list(abc_names)



class TreeManager(IDisposable):
    """
    Manages a hierarchy of TreeNode objects (categories and items).
    """

    def __init__(self, name: str):
        super().__init__()
        self.root: TreeNode = TreeNode(name=name, type="category")

    def add_node(self, name: str, type: str, parent_name: str, metadata: Optional[dict] = None) -> None:
        parent_node = self.find_node(parent_name)
        if not parent_node:
            raise ValueError(f"Parent node '{parent_name}' not found.")
        if parent_node.type != "category":
            raise ValueError(f"Parent node '{parent_name}' must be a category.")

        new_node = TreeNode(name=name, type=type, metadata=metadata)
        parent_node.add_child(new_node)

    def find_node(self, name: str) -> Optional[TreeNode]:
        """
        Finds a node by name using breadth-first search.
        """
        queue = [self.root]
        while queue:
            current = queue.pop(0)
            if current.name == name:
                return current
            queue.extend(current.children)
        return None

    def detailed_find_node(self, name: str, parent_name: str) -> Optional[TreeNode]:
        """
        Finds a node by name under the specified parent.
        """
        parent_node = self.find_node(parent_name)
        if not parent_node:
            raise ValueError(f"Parent node '{parent_name}' not found.")

        for child in parent_node.children:
            if child.name == name:
                return child
        return None

    def get_parent_node(self, name: str) -> Optional[TreeNode]:
        """
        Finds the parent of a node by name using breadth-first search.
        """
        queue = [self.root]
        while queue:
            current = queue.pop(0)
            for child in current.children:
                if child.name == name:
                    return current
            queue.extend(current.children)
        return None

    def remove_node(self, name: str) -> None:
        """
        Removes a node by name and all its descendants.
        """
        if self.root.name == name:
            raise ValueError("Cannot remove the root node.")

        parent_node = None
        node_to_remove = None

        queue = [self.root]
        while queue:
            current = queue.pop(0)
            for child in current.children:
                if child.name == name:
                    parent_node = current
                    node_to_remove = child
                    break
            if node_to_remove:
                break
            queue.extend(current.children)

        if not node_to_remove:
            raise ValueError(f"Node '{name}' not found.")

        parent_node.children.remove(node_to_remove)
        print(f"Node '{name}' and its descendants removed.")

    def dispose(self):
        """
        Disposes of the entire tree structure.
        """
        if self._disposed:
            return
        self.root.dispose()
        self.root = None
        self._disposed = True
