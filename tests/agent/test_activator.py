import threading
import time
import unittest
from thread_factory.agent.activator import ActivatedAgent


# A mock class to simulate a thread pool or factory that can track workers by ID.
class MockFactory:
    def __init__(self):
        self.workers = {}

    def add_worker(self, worker):
        self.workers[worker.factory_id] = worker

    def get_worker_by_id(self, factory_id):
        return self.workers.get(factory_id)

class TestActivatedAgent(unittest.TestCase):
    """Test suite for the ActivatedAgent class."""


    def setUp(self):
        """Set up a new thread for each test."""
        self.results = {}
        self.event = threading.Event()
        self.thread = threading.Thread(target=self._test_target)

    def test_idempotent_activation(self):
        """Ensure re-activating an already agentic thread does not break."""
        ActivatedAgent(self.thread)
        ActivatedAgent(self.thread)  # Should not double-patch or crash

        self.assertTrue(ActivatedAgent.is_agent(self.thread))

    def test_inter_agent_communication_via_shared_inventory(self):
        """Verify one agent can receive data placed in its shared inventory."""

        # Agent B's target function will check if it received the message
        def agent_b_target():
            # It checks its own shared inventory
            received_message = threading.current_thread().get_shared_inventory_item("message")
            self.results['received_message'] = received_message

        # Create the thread with the target correctly assigned
        agent_b_thread = threading.Thread(target=agent_b_target)

        # Activate the thread as an agent BEFORE starting
        activator_b = ActivatedAgent(agent_b_thread, factory_id="agent_B")

        # Place a value into the shared inventory (before thread starts)
        activator_b.set_shared_inventory_item("message", "hello_from_outside")

        # Start and join the thread
        agent_b_thread.start()
        agent_b_thread.join()

        # Assert that the message was received properly
        self.assertEqual(self.results.get('received_message'), "hello_from_outside")

    def test_private_inventory_isolation(self):
        """Verify that private inventories of two agents do not interfere."""
        event_a = threading.Event()
        event_b = threading.Event()

        def target_a():
            agent = threading.current_thread()
            try:
                agent.set_shared_inventory_item("secret", "for_A_only")
                time.sleep(0.05)  # Give B time to write
                # Agent A asserts its own data is unchanged
                self.assertEqual(agent.get_shared_inventory_item("secret"), "for_A_only")
                self.results['a_passed'] = True
            except AssertionError:
                self.results['a_passed'] = False
            finally:
                event_a.set()

        def target_b():
            agent = threading.current_thread()
            try:
                agent.set_shared_inventory_item("secret", "for_B_only")
                time.sleep(0.05)  # Give A time to write
                # Agent B asserts its own data is unchanged
                self.assertEqual(agent.get_shared_inventory_item("secret"), "for_B_only")
                self.results['b_passed'] = True
            except AssertionError:
                self.results['b_passed'] = False
            finally:
                event_b.set()

        thread_a = threading.Thread(target=target_a)
        thread_b = threading.Thread(target=target_b)

        ActivatedAgent(thread_a)
        ActivatedAgent(thread_b)

        thread_a.start()
        thread_b.start()
        thread_a.join()
        thread_b.join()

        self.assertTrue(self.results.get('a_passed'), "Agent A's private inventory was corrupted.")
        self.assertTrue(self.results.get('b_passed'), "Agent B's private inventory was corrupted.")

    def test_shared_inventory_concurrency(self):
        """Test for race conditions when multiple threads write to one agent's shared inventory."""
        main_agent_thread = threading.Thread()
        ActivatedAgent(main_agent_thread)

        writer_threads = []
        num_writers = 10
        writes_per_thread = 100

        def writer_task(writer_id):
            for i in range(writes_per_thread):
                # All writers hammer the same key in the shared inventory
                main_agent_thread.set_shared_inventory_item('counter', f"writer_{writer_id}_{i}")

        for i in range(num_writers):
            thread = threading.Thread(target=writer_task, args=(i,))
            writer_threads.append(thread)
            thread.start()

        for thread in writer_threads:
            thread.join()

        # The primary goal is to ensure this completes without a deadlock or exception.
        # We can also check that the shared inventory has a value.
        self.assertIsNotNone(main_agent_thread.get_shared_inventory_item('counter'))
        self.assertTrue(main_agent_thread.get_shared_inventory_item('counter').startswith('writer_'))

    def test_cross_agent_inventory_via_factory_id(self):
        """Test bind_to_inventory_by_id and get_from_inventory_by_id with factory lookup."""
        factory = MockFactory()

        thread_a = threading.Thread()
        thread_b = threading.Thread()

        activator_a = ActivatedAgent(thread_a, factory_id="A")
        activator_b = ActivatedAgent(thread_b, factory_id="B")

        activator_a.factory = factory
        activator_b.factory = factory

        factory.add_worker(thread_a)
        factory.add_worker(thread_b)

        activator_a.bind_to_inventory_by_id("B", "shared_key", "hello_from_A")

        result = activator_a.get_from_inventory_by_id("B", "shared_key")
        self.assertEqual(result, "hello_from_A")

    def test_recursive_inventory_access(self):
        """Ensure reentrant inventory access doesn't deadlock or fail."""
        ActivatedAgent(self.thread)

        def recursive_fn(depth=3):
            if depth == 0:
                return self.thread.get_from_inventory("recurse")
            self.thread.bind_to_inventory("recurse", f"depth_{depth}")
            return recursive_fn(depth - 1)

        self.assertEqual(recursive_fn(), "depth_1")

    def test_transfer_function_error_propagation(self):
        """Ensure exceptions inside transfer functions bubble up."""
        ActivatedAgent(self.thread)

        def broken_fn():
            raise RuntimeError("Boom")

        self.thread.register_data_transfer("explode", broken_fn)

        with self.assertRaises(RuntimeError):
            self.thread.execute_transfer("explode")

    def test_true_thread_local_isolation(self):
        """Make sure thread-local inventory is not shared across threads."""
        thread_a = threading.Thread()
        thread_b = threading.Thread()
        ActivatedAgent(thread_a)
        ActivatedAgent(thread_b)

        thread_a.bind_to_inventory("x", "a_value")
        self.assertIsNone(thread_b.get_from_inventory("x"))

    def test_all_expected_methods_patched(self):
        """Ensure all expected methods are present on the thread after activation."""
        expected = {
            'bind_to_inventory', 'get_from_inventory',
            'set_shared_inventory_item', 'get_shared_inventory_item',
            'get_shared_inventory', 'register_data_transfer',
            'get_data_transfer_dict', 'execute_transfer',
            'register_save_point', 'get_save_points_dict',
            'register_location', 'get_locations_dict',
            'get_factory_id', 'bind_to_inventory_by_id',
            'get_from_inventory_by_id', 'dispose'
        }

        ActivatedAgent(self.thread)
        missing = [m for m in expected if not hasattr(self.thread, m)]

        self.assertEqual(missing, [], f"Missing patched methods: {missing}")

    def test_shared_inventory_copy_isolation(self):
        """Ensure get_shared_inventory() returns a copy, not the original."""
        ActivatedAgent(self.thread)

        self.thread.set_shared_inventory_item("key", 123)
        shared = self.thread.get_shared_inventory()
        shared["key"] = 999

        # Original should not be affected
        self.assertEqual(self.thread.get_shared_inventory_item("key"), 123)

    def test_massive_shared_inventory_concurrency(self):
        """Hammer shared inventory with high concurrency to flush out race issues."""
        thread = threading.Thread()
        ActivatedAgent(thread)

        def hammer():
            for i in range(1000):
                thread.set_shared_inventory_item("x", i)

        threads = [threading.Thread(target=hammer) for _ in range(20)]
        for t in threads: t.start()
        for t in threads: t.join()

        val = thread.get_shared_inventory_item("x")
        self.assertIsInstance(val, int)

    def _test_target(self):
        """A simple target function for the test thread."""
        # This is where code inside the agent thread would run.
        # We use an event to signal that the thread has started and is ready.
        self.event.set()
        time.sleep(0.1)  # Give main thread time to run its assertions

    def test_activation_and_is_agent(self):
        """Verify that a thread is correctly identified as an agent after activation."""
        self.assertFalse(ActivatedAgent.is_agent(self.thread), "Thread should not be an agent initially.")

        activator = ActivatedAgent(self.thread, factory_id="test_agent_01")

        self.assertTrue(ActivatedAgent.is_agent(self.thread), "Thread should be an agent after activation.")
        self.assertEqual(self.thread.factory_id, "test_agent_01")
        self.assertEqual(self.thread._worker_type, "agentic")

    def test_inventory_management(self):
        """Test that a thread can bind to and retrieve from its own private inventory."""
        ActivatedAgent(self.thread)

        def target_with_internal_assertion():
            agent = threading.current_thread()
            try:
                # 1. The thread binds a value to its own inventory.
                agent.bind_to_inventory("private_key", "private_value")

                # 2. The same thread retrieves the value.
                retrieved_value = agent.get_from_inventory("private_key")

                # 3. The assertion is made directly within the thread, as requested.
                self.assertEqual(retrieved_value, "private_value")

            except AssertionError as e:
                # If the assertion fails, store the error for the main thread.
                self.results['assertion_error'] = e
            finally:
                # Signal that the test logic in the thread is complete.
                self.event.set()

        self.thread.target = target_with_internal_assertion
        self.thread.start()
        self.thread.join()

        # This final check ensures the test fails correctly in the test runner.
        if 'assertion_error' in self.results:
            raise self.results['assertion_error']

    def test_behavior_routing(self):
        """Test registration and retrieval of locations and save points."""
        ActivatedAgent(self.thread)

        def my_location():
            self.results['location_called'] = True

        def my_save_point():
            self.results['save_point_called'] = True

        self.thread.register_location("home", my_location)
        self.thread.register_save_point("checkpoint1", my_save_point)

        locations = self.thread.get_locations_dict()
        save_points = self.thread.get_save_points_dict()

        self.assertIn("home", locations)
        self.assertIn("checkpoint1", save_points)

        # Execute the retrieved function
        locations["home"]()
        save_points["checkpoint1"]()

        self.assertTrue(self.results.get('location_called'))
        self.assertTrue(self.results.get('save_point_called'))

    def test_data_transfer(self):
        """Test registration and execution of data transfer functions."""
        ActivatedAgent(self.thread)

        def get_status():
            return "system_ok"

        self.thread.register_data_transfer("check_status", get_status)

        status = self.thread.execute_transfer("check_status")
        self.assertEqual(status, "system_ok")

        with self.assertRaises(KeyError):
            self.thread.execute_transfer("non_existent_transfer")

    def test_disposal(self):
        """Verify that dispose() cleans up the agent and unpatches the thread."""
        activator = ActivatedAgent(self.thread)
        self.assertTrue(ActivatedAgent.is_agent(self.thread))
        self.assertTrue(hasattr(self.thread, 'bind_to_inventory'))

        # Add some data to ensure it gets cleared
        self.thread.register_location("temp_loc", lambda: None)
        self.thread.set_shared_inventory_item("temp_item", 123)
        self.assertEqual(len(activator._locations), 1)
        self.assertEqual(len(activator._shared_inventory), 1)

        self.thread.dispose()

        self.assertFalse(ActivatedAgent.is_agent(self.thread), "Thread should not be an agent after disposal.")
        self.assertFalse(hasattr(self.thread, 'bind_to_inventory'), "Patched methods should be removed after disposal.")
        self.assertFalse(hasattr(self.thread, 'factory_id'), "Patched attributes should be removed.")

        # Check that internal collections are cleared
        self.assertEqual(len(activator._locations), 0)
        self.assertEqual(len(activator._shared_inventory), 0)
        self.assertTrue(activator._disposed)

    def test_id_generation(self):
        """Test automatic and manual factory_id assignment."""
        # Automatic ID
        activator1 = ActivatedAgent(threading.Thread())
        self.assertIsInstance(activator1.factory_id, str)
        self.assertTrue(len(activator1.factory_id) > 0)

        # Manual ID
        activator2 = ActivatedAgent(threading.Thread(), factory_id="custom-id-123")
        self.assertEqual(activator2.factory_id, "custom-id-123")

    def test_async_function_rejection(self):
        """Ensure async functions cannot be registered."""
        ActivatedAgent(self.thread)

        async def my_async_func():
            pass

        with self.assertRaises(TypeError):
            self.thread.register_location("async_loc", my_async_func)

        with self.assertRaises(TypeError):
            self.thread.register_save_point("async_sp", my_async_func)

        with self.assertRaises(TypeError):
            self.thread.register_data_transfer("async_dt", my_async_func)


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
