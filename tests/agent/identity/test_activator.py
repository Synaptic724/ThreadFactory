import threading
import time
import unittest
from thread_factory.agent.identity.activator import ActivatedAgent
from thread_factory.agent.identity.profiles.general import General  # Import General
from thread_factory.agent.identity.profile_builder import ProfileBuilder  # Import ProfileBuilder


class MockFactory:
    def __init__(self):
        self.workers = {}

    def add_worker(self, worker_thread):  # Accept the patched thread
        self.workers[worker_thread.factory_id] = worker_thread

    def get_worker_by_id(self, factory_id):
        # In MockFactory, ensure you return the actual patched thread
        return self.workers.get(factory_id)


class TestActivatedAgent(unittest.TestCase):
    def setUp(self):
        self.results = {}
        self.event = threading.Event()
        # Initialize a fresh thread for each test
        self.raw_thread = threading.Thread(target=self._test_target)
        # self.agent will hold the ActivatedAgent instance
        self.agent = ActivatedAgent(self.raw_thread)
        # Initialize profile builder for tests that use it
        self.profile_builder = ProfileBuilder()
        # Create and bind a profile immediately for agentic features
        self.agent.profile = self.profile_builder.create_profile()
        self.agent.profile.bind_to(self.agent)  # Bind the profile to the ActivatedAgent instance

    def tearDown(self):
        # Ensure proper disposal after each test
        if self.agent and not self.agent._disposed:
            self.agent.dispose()
        if self.profile_builder and not self.profile_builder._disposed:
            self.profile_builder.dispose()
        self.results.clear()
        self.event.clear()
        self.raw_thread = None
        self.agent = None

    def test_idempotent_activation(self):
        # A new ActivatedAgent instance is created in setUp, so we don't need to do it here
        # Test idempotency by creating another ActivatedAgent with the same raw_thread
        another_agent_instance = ActivatedAgent(self.raw_thread)
        self.assertTrue(ActivatedAgent.is_agent(self.raw_thread))
        # Dispose the temporary agent instance
        another_agent_instance.dispose()

    def test_inter_agent_communication_via_shared_inventory(self):
        def agent_b_target(agent_instance_b):  # Pass the agent instance
            received_message = agent_instance_b.get_shared_inventory_item("message")
            self.results['received_message'] = received_message

        # Create a new raw thread for agent B
        raw_thread_b = threading.Thread(target=agent_b_target, args=(self.agent,))  # Pass self.agent
        # OR:
        # raw_thread_b = threading.Thread(target=agent_b_target, args=(activator_b,)) # Pass activator_b if it's the one setting it

        activator_b = ActivatedAgent(raw_thread_b, factory_id="agent_B")

        # Now, ensure that the activator_b being created here and the one
        # used inside the thread are the same for setting/getting shared state.
        # It's cleaner if the agent's target *is* the agent itself, or a method on it.

        # Let's adjust the test to make it clearer what's being shared.
        # The _shared_inventory is an instance attribute of ActivatedAgent.
        # If you want inter-agent communication via *shared* inventory,
        # all participating agents need to point to the *same* ConcurrentDict instance.

        # For this test, it's about an agent setting something and then reading it.
        # The key is that `threading.current_thread()` returns the patched thread.
        # The patched methods *on that thread* are the ones that access the *original*
        # ActivatedAgent's shared inventory.

        # Let's re-examine your _patch_thread logic carefully.
        # When you do:
        # setattr(self._thread_target, 'set_shared_inventory_item', getattr(self, 'set_shared_inventory_item'))
        # This means that when thread.set_shared_inventory_item() is called, it's actually
        # calling the `set_shared_inventory_item` method of the *original ActivatedAgent instance* that patched it.
        # So, the problem is likely still in `agent_b_target`:

        def agent_b_target():
            # The current thread *is* the patched thread. Its methods directly access
            # the _shared_inventory of the ActivatedAgent that patched it.
            received_message = threading.current_thread().get_shared_inventory_item("message")
            self.results['received_message'] = received_message

        raw_thread_b = threading.Thread(target=agent_b_target)
        activator_b = ActivatedAgent(raw_thread_b, factory_id="agent_B")

        # Set the shared inventory item on the *activator_b* instance
        activator_b.set_shared_inventory_item("message", "hello_from_outside")

        raw_thread_b.start()
        raw_thread_b.join()

        self.assertEqual(self.results.get('received_message'), "hello_from_outside")
        activator_b.dispose()  # Clean up
    def test_private_inventory_isolation(self):
        event_a = threading.Event()
        event_b = threading.Event()

        def target_a():
            # Get the ActivatedAgent instance for the current thread
            agent = ActivatedAgent(threading.current_thread())
            try:
                agent.bind_to_inventory("secret", "for_A_only")
                time.sleep(0.05)
                self.assertEqual(agent.get_from_inventory("secret"), "for_A_only")
                self.results['a_passed'] = True
            except AssertionError:
                self.results['a_passed'] = False
            finally:
                event_a.set()

        def target_b():
            # Get the ActivatedAgent instance for the current thread
            agent = ActivatedAgent(threading.current_thread())
            try:
                agent.bind_to_inventory("secret", "for_B_only")
                time.sleep(0.05)
                self.assertEqual(agent.get_from_inventory("secret"), "for_B_only")
                self.results['b_passed'] = True
            except AssertionError:
                self.results['b_passed'] = False
            finally:
                event_b.set()

        thread_a_raw = threading.Thread(target=target_a)
        thread_b_raw = threading.Thread(target=target_b)

        # Activators are created here. They automatically patch the threads.
        activator_a = ActivatedAgent(thread_a_raw)
        activator_b = ActivatedAgent(thread_b_raw)

        thread_a_raw.start()
        thread_b_raw.start()
        thread_a_raw.join()
        thread_b_raw.join()

        self.assertTrue(self.results.get('a_passed'))
        self.assertTrue(self.results.get('b_passed'))
        activator_a.dispose()
        activator_b.dispose()

    def test_shared_inventory_concurrency(self):
        # The main_agent_thread is self.raw_thread, and self.agent wraps it
        writer_threads = []
        num_writers = 10
        writes_per_thread = 100

        def writer_task(writer_id):
            # This task directly interacts with the patched thread object
            for i in range(writes_per_thread):
                self.agent.set_shared_inventory_item('counter', f"writer_{writer_id}_{i}")

        for i in range(num_writers):
            thread = threading.Thread(target=writer_task, args=(i,))
            writer_threads.append(thread)
            thread.start()

        for thread in writer_threads:
            thread.join()

        self.assertIsNotNone(self.agent.get_shared_inventory_item('counter'))
        self.assertTrue(self.agent.get_shared_inventory_item('counter').startswith('writer_'))

    def test_cross_agent_inventory_via_factory_id(self):
        factory = MockFactory()

        # Create raw threads
        thread_a_raw = threading.Thread()
        thread_b_raw = threading.Thread()

        # Create ActivatedAgent instances
        activator_a = ActivatedAgent(thread_a_raw, factory_id="A")
        activator_b = ActivatedAgent(thread_b_raw, factory_id="B")

        # Set the factory attribute on the ActivatedAgent instances
        # This assumes your ActivatedAgent has a 'factory' attribute or you pass it during init
        # Based on your _resolve_worker_by_id, it implicitly expects `self.factory` to be set
        # You need to expose a way to set the factory on the ActivatedAgent
        # For this test, let's directly set it if it's not handled in __init__
        activator_a.factory = factory
        activator_b.factory = factory

        # Add the patched threads to the mock factory
        factory.add_worker(thread_a_raw)
        factory.add_worker(thread_b_raw)

        activator_a.bind_to_inventory_by_id("B", "shared_key", "hello_from_A")
        result = activator_a.get_from_inventory_by_id("B", "shared_key")
        self.assertEqual(result, "hello_from_A")

        activator_a.dispose()
        activator_b.dispose()

    def test_recursive_inventory_access(self):
        # self.agent is already set up in setUp
        def recursive_fn(depth=3):
            if depth == 0:
                return self.agent.get_from_inventory("recurse")
            self.agent.bind_to_inventory("recurse", f"depth_{depth}")
            return recursive_fn(depth - 1)

        self.assertEqual(recursive_fn(), "depth_1")

    def test_true_thread_local_isolation(self):
        thread_a_raw = threading.Thread()
        thread_b_raw = threading.Thread()

        activator_a = ActivatedAgent(thread_a_raw)
        activator_b = ActivatedAgent(thread_b_raw)

        activator_a.bind_to_inventory("x", "a_value")
        self.assertIsNone(activator_b.get_from_inventory("x"))

        activator_a.dispose()
        activator_b.dispose()

    def test_all_expected_methods_patched(self):
        expected = {
            'bind_to_inventory', 'get_from_inventory',
            'set_shared_inventory_item', 'get_shared_inventory_item',
            'get_shared_inventory', 'get_factory_id',
            'bind_to_inventory_by_id', 'get_from_inventory_by_id', 'dispose'
        }

        # self.raw_thread is the thread object patched by self.agent
        missing = [m for m in expected if not hasattr(self.raw_thread, m)]

        self.assertEqual(missing, [], f"Missing patched methods: {missing}")

    def test_shared_inventory_copy_isolation(self):
        # self.agent is already set up
        self.agent.set_shared_inventory_item("key", 123)
        shared = self.agent.get_shared_inventory()
        shared["key"] = 999
        self.assertEqual(self.agent.get_shared_inventory_item("key"), 123)

    def test_massive_shared_inventory_concurrency(self):
        # self.agent is already set up
        def hammer():
            for i in range(1000):
                self.agent.set_shared_inventory_item("x", i)

        threads = [threading.Thread(target=hammer) for _ in range(20)]
        for t in threads: t.start()
        for t in threads: t.join()

        val = self.agent.get_shared_inventory_item("x")
        self.assertIsInstance(val, int)

    def _test_target(self):
        # This target is for the raw_thread, which is wrapped by self.agent
        self.event.set()
        time.sleep(0.1)

    def test_activation_and_is_agent(self):
        # In setUp, self.raw_thread is created and wrapped by self.agent.
        # Before setUp, the raw_thread would not be an agent.
        # After setUp, it should be.
        self.assertTrue(ActivatedAgent.is_agent(self.raw_thread))
        self.assertEqual(self.agent.factory_id, self.raw_thread.factory_id)  # factory_id is patched onto the thread
        self.assertEqual(self.raw_thread._worker_type, "agentic")

    def test_inventory_management(self):
        # self.agent is already set up
        def target_with_internal_assertion():
            # Get the ActivatedAgent instance for the current thread
            agent_in_thread = ActivatedAgent(threading.current_thread())
            try:
                agent_in_thread.bind_to_inventory("private_key", "private_value")
                retrieved_value = agent_in_thread.get_from_inventory("private_key")
                self.assertEqual(retrieved_value, "private_value")
            except AssertionError as e:
                self.results['assertion_error'] = e
            finally:
                self.event.set()

        # Update the target of the raw thread, which is wrapped by self.agent
        self.raw_thread._target = target_with_internal_assertion
        self.raw_thread.start()
        self.raw_thread.join()

        if 'assertion_error' in self.results:
            raise self.results['assertion_error']

    def test_behavior_routing(self):
        # self.agent is already set up, and its profile too
        def my_location():
            self.results['location_called'] = True

        def my_save_point():
            self.results['save_point_called'] = True

        self.agent.profile.register_location("home", my_location)
        self.agent.profile.register_save_point("checkpoint1", my_save_point)

        locations = self.agent.profile.get_locations_dict()
        save_points = self.agent.profile.get_save_points_dict()

        self.assertIn("home", locations)
        self.assertIn("checkpoint1", save_points)

        locations["home"]()
        save_points["checkpoint1"]()

        self.assertTrue(self.results.get('location_called'))
        self.assertTrue(self.results.get('save_point_called'))

    def test_data_transfer(self):
        # self.agent is already set up, and its profile too
        def get_status():
            return "system_ok"

        self.agent.profile.register_data_transfer("check_status", get_status)
        status = self.agent.profile.execute_transfer("check_status")
        self.assertEqual(status, "system_ok")

        with self.assertRaises(KeyError):
            self.agent.profile.execute_transfer("non_existent_transfer")

    def test_disposal(self):
        # self.agent is set up in setUp. We test its disposal here.
        # We need a new agent for this test to dispose of, as self.agent is disposed in tearDown.
        temp_raw_thread = threading.Thread()
        temp_agent = ActivatedAgent(temp_raw_thread)
        temp_agent.profile = self.profile_builder.create_profile()  # create a profile for temp_agent
        temp_agent.profile.bind_to(temp_agent)

        self.assertTrue(ActivatedAgent.is_agent(temp_raw_thread))
        self.assertTrue(hasattr(temp_raw_thread, 'bind_to_inventory'))

        temp_agent.profile.register_location("temp_loc", lambda: None)
        temp_agent.set_shared_inventory_item("temp_item", 123)
        self.assertEqual(len(temp_agent.profile.get_locations_dict()), 1)
        self.assertEqual(len(temp_agent._shared_inventory), 1)  # Directly access internal state for assertion

        temp_agent.dispose()  # Call dispose on the ActivatedAgent instance

        self.assertFalse(ActivatedAgent.is_agent(temp_raw_thread))
        self.assertFalse(hasattr(temp_raw_thread, 'bind_to_inventory'))
        self.assertFalse(hasattr(temp_raw_thread, 'factory_id'))
        self.assertEqual(len(temp_agent._shared_inventory), 0)
        self.assertTrue(temp_agent._disposed)

    def test_id_generation(self):
        # Test creation of a new agent instance
        activator1 = ActivatedAgent(threading.Thread())
        self.assertIsInstance(activator1.factory_id, str)
        self.assertTrue(len(activator1.factory_id) > 0)
        activator1.dispose()

        # Test with custom ID
        activator2 = ActivatedAgent(threading.Thread(), factory_id="custom-id-123")
        self.assertEqual(activator2.factory_id, "custom-id-123")
        activator2.dispose()

    def test_async_function_rejection(self):
        # self.agent is already set up, and its profile too
        async def my_async_func():
            pass

        with self.assertRaises(TypeError):
            self.agent.profile.register_location("async_loc", my_async_func)

        with self.assertRaises(TypeError):
            self.agent.profile.register_save_point("async_sp", my_async_func)

        with self.assertRaises(TypeError):
            self.agent.profile.register_data_transfer("async_dt", my_async_func)


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)