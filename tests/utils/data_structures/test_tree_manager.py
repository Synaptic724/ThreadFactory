import unittest
from thread_factory.utils.data_structures.tree_manager import TreeNode, TreeManager

class TestTreeNode(unittest.TestCase):
    def test_tree_node_creation(self):
        node = TreeNode(name="TestNode", type="category", metadata={"description": "A test node"})
        self.assertEqual(node.name, "TestNode")
        self.assertEqual(node.type, "category")
        self.assertEqual(node.metadata["description"], "A test node")
        self.assertEqual(node.children, [])

    def test_tree_node_add_child(self):
        parent = TreeNode(name="Parent", type="category")
        child = TreeNode(name="Child", type="category")
        parent.add_child(child)
        self.assertEqual(len(parent.children), 1)
        self.assertEqual(parent.children[0].name, "Child")

class TestTreeManager(unittest.TestCase):
    def test_tree_manager_initialization(self):
        manager = TreeManager(name="Root")
        self.assertEqual(manager.root.name, "Root")
        self.assertEqual(manager.root.type, "category")
        self.assertEqual(manager.root.children, [])

    def test_tree_manager_add_node(self):
        manager = TreeManager(name="Root")
        manager.add_node(name="Category1", type="category", parent_name="Root")
        self.assertEqual(len(manager.root.children), 1)
        self.assertEqual(manager.root.children[0].name, "Category1")

        manager.add_node(name="Category2", type="category", parent_name="Category1")
        category1_node = manager.find_node("Category1")
        self.assertEqual(len(category1_node.children), 1)
        self.assertEqual(category1_node.children[0].name, "Category2")

        manager.add_node(name="Category3", type="category", parent_name="Root")
        self.assertEqual(len(manager.root.children), 2)
        self.assertEqual(manager.root.children[1].name, "Category3")

    def test_invalid_operations(self):
        manager = TreeManager(name="Root")
        with self.assertRaises(ValueError) as cm:
            manager.add_node(name="Category4", type="category", parent_name="NonExistent")
        self.assertIn("Parent node 'NonExistent' not found.", str(cm.exception))

    def test_find_node(self):
        manager = TreeManager(name="Root")
        manager.add_node(name="Category1", type="category", parent_name="Root")
        manager.add_node(name="Category2", type="category", parent_name="Category1")

        node = manager.find_node("Category2")
        self.assertIsNotNone(node)
        self.assertEqual(node.name, "Category2")

        node = manager.find_node("NonExistent")
        self.assertIsNone(node)

    def test_detailed_find_node(self):
        manager = TreeManager(name="Root")
        manager.add_node(name="Category1", type="category", parent_name="Root")
        manager.add_node(name="Category2", type="category", parent_name="Category1")
        manager.add_node(name="Category3", type="category", parent_name="Category2")
        manager.add_node(name="Category4", type="category", parent_name="Category3")
        manager.add_node(name="Category5", type="category", parent_name="Category4")
        manager.add_node(name="Category6", type="category", parent_name="Category5")
        manager.add_node(name="Category6_item", type="item", parent_name="Root")  # Separate item to not clash

        node = manager.detailed_find_node("Category6_item", "Root")
        self.assertIsNotNone(node)
        self.assertEqual(node.name, "Category6_item")

        node = manager.find_node("NonExistent")
        self.assertIsNone(node)

if __name__ == "__main__":
    unittest.main()
