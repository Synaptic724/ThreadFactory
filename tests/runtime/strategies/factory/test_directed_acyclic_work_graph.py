import unittest
import time
from thread_factory.runtime.strategies.factory.directed_acyclic_work_graph import Node, Edge, DirectedAcyclicWorkGraph, StateObject, ExecutionContext

# Assuming you have all your DAG code in a module named 'dag_module'
# For example:
# from dag_module import Node, Edge, DAG, StateObject, ExecutionContext
#
# But since you pasted all classes in the same file, you might just
# import them directly if they are in the global namespace.
#
# Adjust imports as needed:

class TestDAGSystem(unittest.TestCase):

    def test_node_basic_tasks(self):
        """
        Test that tasks added to a Node are executed in order.
        """
        node = Node("TestNode")
        call_list = []

        def task1():
            call_list.append("task1")

        def task2():
            call_list.append("task2")

        node.add_task(task1)
        node.add_task(task2)
        node.execute_tasks()  # Should run task1, then task2

        self.assertEqual(call_list, ["task1", "task2"], "Node tasks did not execute in the correct order.")

    def test_node_execution_context(self):
        """
        Test that a Node's ExecutionContext is called after the tasks.
        """
        node = Node("ContextNode")
        call_list = []

        class MyExecutionContext(ExecutionContext):
            def execute(self):
                call_list.append("context_execute")

        def task():
            call_list.append("task")

        node.add_task(task)

        # Create a dummy DAG for the state object, though it won't be used heavily.
        dummy_dag = DirectedAcyclicWorkGraph()
        state = StateObject(dummy_dag)

        ctx = MyExecutionContext(state)
        node.set_execution_context(ctx)

        node.execute_tasks()
        self.assertEqual(call_list, ["task", "context_execute"], "Execution context did not run after tasks.")

    def test_edge_creation_and_removal(self):
        """
        Test adding and removing edges from nodes.
        """
        node_a = Node("A")
        node_b = Node("B")
        edge_ab = Edge(node_a, node_b)

        dag = DirectedAcyclicWorkGraph()
        dag.add_node(node_a)
        dag.add_node(node_b)
        dag.add_edge(edge_ab)

        # Check that node_a -> node_b is present
        self.assertIn(edge_ab, dag.get_edges(), "Edge not found in DAG after adding.")
        self.assertIn(edge_ab, node_a.get_outgoing_edges(), "Edge not found in node A's outgoing edges.")
        self.assertIn(edge_ab, node_b.get_incoming_edges(), "Edge not found in node B's incoming edges.")

        # Remove edge and verify
        dag.remove_edge(edge_ab)
        self.assertNotIn(edge_ab, dag.get_edges(), "Edge still found in DAG after removal.")
        self.assertNotIn(edge_ab, node_a.get_outgoing_edges(), "Edge still found in node A's outgoing edges.")
        self.assertNotIn(edge_ab, node_b.get_incoming_edges(), "Edge still found in node B's incoming edges.")

    def test_dag_add_remove_node(self):
        """
        Test adding and removing a node in the DAG.
        """
        dag = DirectedAcyclicWorkGraph()
        node_a = Node("A")
        node_b = Node("B")
        dag.add_node(node_a)
        dag.add_node(node_b)

        self.assertEqual(len(dag.get_nodes()), 2, "DAG should have 2 nodes after adding them.")

        dag.remove_node(node_a)
        self.assertEqual(len(dag.get_nodes()), 1, "DAG should have 1 node after removing A.")
        self.assertNotIn(node_a, dag.get_nodes(), "Node A was not removed properly.")

    def test_topological_sort_simple_chain(self):
        """
        Test a simple chain A->B->C topological sort order.
        """
        dag = DirectedAcyclicWorkGraph()
        a = Node("A")
        b = Node("B")
        c = Node("C")

        dag.add_node(a)
        dag.add_node(b)
        dag.add_node(c)

        dag.add_edge(Edge(a, b))  # A->B
        dag.add_edge(Edge(b, c))  # B->C

        result = dag.topological_sort()
        sorted_ids = [node.id for node in result]
        self.assertEqual(sorted_ids, ["A", "B", "C"], f"Topological sort incorrect. Got {sorted_ids}")

    def test_topological_sort_branching(self):
        """
        Test a branching DAG:
            A -> C
            B -> C
        The valid topological sorts could be A,B,C or B,A,C
        We'll just check that C is always last.
        """
        dag = DirectedAcyclicWorkGraph()
        a = Node("A")
        b = Node("B")
        c = Node("C")
        dag.add_node(a)
        dag.add_node(b)
        dag.add_node(c)

        dag.add_edge(Edge(a, c))  # A->C
        dag.add_edge(Edge(b, c))  # B->C

        result = dag.topological_sort()
        sorted_ids = [node.id for node in result]

        # 'C' should be last
        self.assertEqual(sorted_ids[-1], "C", "Node C should be last in topological order.")
        # A or B can appear in any order, but both must precede C

    def test_topological_sort_cycle(self):
        """
        Test that a cycle detection raises an exception.
        We'll create A->B, B->A.
        """
        dag = DirectedAcyclicWorkGraph()
        a = Node("A")
        b = Node("B")
        dag.add_node(a)
        dag.add_node(b)
        dag.add_edge(Edge(a, b))  # A->B
        dag.add_edge(Edge(b, a))  # B->A (forms a cycle)

        with self.assertRaises(ValueError):
            dag.topological_sort()

    def test_sequential_execute(self):
        """
        Test DAG.execute() for sequential run.
        We'll do A->C, B->C.
        We'll verify tasks are run in a topological order.
        """
        dag = DirectedAcyclicWorkGraph()
        node_a = Node("A")
        node_b = Node("B")
        node_c = Node("C")

        dag.add_node(node_a)
        dag.add_node(node_b)
        dag.add_node(node_c)

        dag.add_edge(Edge(node_a, node_c))
        dag.add_edge(Edge(node_b, node_c))

        call_list = []
        node_a.add_task(lambda: call_list.append("[A]"))
        node_b.add_task(lambda: call_list.append("[B]"))
        node_c.add_task(lambda: call_list.append("[C]"))

        dag.execute()
        # The exact order might be A->B->C or B->A->C if A, B have no dependencies.
        # But C should always be last. We'll just check that C is last.
        self.assertTrue(call_list[-1] == "[C]", f"C should be last, got {call_list}")

    def test_parallel_bfs_layered_simple(self):
        """
        Test DAG.execute_layered() with a small DAG and check partial concurrency.
        Example: A->C, B->C. A, B can run in parallel, then C.
        We'll add artificial sleep to see concurrency.
        """
        dag = DirectedAcyclicWorkGraph()
        a = Node("A")
        b = Node("B")
        c = Node("C")
        dag.add_node(a)
        dag.add_node(b)
        dag.add_node(c)

        dag.add_edge(Edge(a, c))
        dag.add_edge(Edge(b, c))

        call_list = []
        def taskA():
            time.sleep(0.1)
            call_list.append("A")
        def taskB():
            time.sleep(0.1)
            call_list.append("B")
        def taskC():
            call_list.append("C")

        a.add_task(taskA)
        b.add_task(taskB)
        c.add_task(taskC)

        dag.execute_layered(max_workers=2)

        # A and B can be in any order, but C must be last.
        self.assertEqual(call_list[-1], "C", "C must be last in BFS layering.")
        self.assertIn("A", call_list)
        self.assertIn("B", call_list)

    def test_parallel_bfs_layered_complex(self):
        """
        Test the bigger DAG from the example in 'more_complex_usage'.
        Just ensure no crash and that all tasks are executed exactly once.
        """
        dag = DirectedAcyclicWorkGraph()
        node_a = Node("A")
        node_b = Node("B")
        node_c = Node("C")
        node_d = Node("D")
        node_e = Node("E")
        node_f = Node("F")

        dag.add_node(node_a)
        dag.add_node(node_b)
        dag.add_node(node_c)
        dag.add_node(node_d)
        dag.add_node(node_e)
        dag.add_node(node_f)

        dag.add_edge(Edge(node_a, node_c))  # A->C
        dag.add_edge(Edge(node_b, node_c))  # B->C
        dag.add_edge(Edge(node_c, node_d))  # C->D
        dag.add_edge(Edge(node_b, node_e))  # B->E
        dag.add_edge(Edge(node_d, node_f))  # D->F
        dag.add_edge(Edge(node_e, node_f))  # E->F

        call_list = []

        node_a.add_task(lambda: call_list.append("A"))
        node_b.add_task(lambda: call_list.append("B"))
        node_c.add_task(lambda: call_list.append("C"))
        node_d.add_task(lambda: call_list.append("D"))
        node_e.add_task(lambda: call_list.append("E"))
        node_f.add_task(lambda: call_list.append("F"))

        dag.execute_layered(max_workers=3)

        # Check that each node executed exactly once
        self.assertCountEqual(call_list, ["A","B","C","D","E","F"],
                              f"Did not see exactly one execution of each node, got {call_list}")

    def test_state_object_removal(self):
        """
        Test that the StateObject can remove a failing node from the DAG.
        """
        dag = DirectedAcyclicWorkGraph()
        state = StateObject(dag)

        node_a = Node("A")
        node_b = Node("B")  # We'll fail B
        dag.add_node(node_a)
        dag.add_node(node_b)

        dag.add_edge(Edge(node_a, node_b))  # A->B

        state.register_node_result("A", success=True)
        # B is "failing", so register_node_result("B", success=False)
        state.register_node_result("B", success=False)

        # B should be removed from the DAG
        remaining_nodes = dag.get_nodes()
        self.assertEqual(len(remaining_nodes), 1, "Node B should have been removed by the StateObject.")
        self.assertEqual(remaining_nodes[0].id, "A", "Only node A should remain.")

    def test_disposal_dag(self):
        """
        Ensure disposing the DAG disposes all nodes and edges.
        """
        dag = DirectedAcyclicWorkGraph()
        a = Node("A")
        b = Node("B")
        edge_ab = Edge(a, b)
        dag.add_node(a)
        dag.add_node(b)
        dag.add_edge(edge_ab)

        dag.dispose()
        # Once disposed, the internal structures should be cleared
        self.assertEqual(len(dag.get_nodes()), 0, "Nodes not cleared after DAG disposal.")
        self.assertEqual(len(dag.get_edges()), 0, "Edges not cleared after DAG disposal.")

    def test_disposal_node(self):
        """
        Test disposing a single Node object, ensuring edges and tasks are cleared.
        """
        node = Node("TestNode")
        node.add_task(lambda: None)
        node.dispose()
        self.assertEqual(node.get_incoming_edges(), [], "Incoming edges not cleared on dispose.")
        self.assertEqual(node.get_outgoing_edges(), [], "Outgoing edges not cleared on dispose.")
        # We can't directly inspect the tasks, but we can rely on get_incoming_edges and get_outgoing_edges

    def test_execution_context_dispose(self):
        """
        Test that disposing an ExecutionContext clears its reference to the state.
        """
        dag = DirectedAcyclicWorkGraph()
        state = StateObject(dag)
        class MyContext(ExecutionContext):
            def execute(self):
                pass

        ctx = MyContext(state)
        self.assertIsNotNone(ctx.state, "State should be set initially.")
        ctx.dispose()
        self.assertIsNone(ctx.state, "State should be cleared after dispose.")

    def test_state_object_dispose(self):
        """
        Test that disposing the StateObject clears its references.
        """
        dag = DirectedAcyclicWorkGraph()
        state = StateObject(dag)
        state.dispose()
        # the 'dag' reference is set to None in _dispose_internal
        self.assertIsNone(state._dag, "StateObject's DAG reference should be cleared after dispose.")
        self.assertEqual(state.get_all_statuses(), {}, "Execution data should be cleared after dispose.")


if __name__ == "__main__":
    # This allows you to run the tests from this file via: python test_dag_system.py
    unittest.main()
