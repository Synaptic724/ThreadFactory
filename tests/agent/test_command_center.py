import unittest, threading, time
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.agent.command_center import CommandCenter, CC
from thread_factory.agent.activator import ActivatedAgent
from thread_factory.agent.thread_pool import HelpRequest


class TestCommandCenter(unittest.TestCase):
    def setUp(self):
        self.center = CC(max_workers=4)

    def tearDown(self):
        self.center.dispose()

    def test_create_agents_registers_correctly(self):
        """
        Validates that agents are correctly created, started, and removed from the registry after execution.
        Ensures `CommandCenter` tracks agents during their lifetime and they auto-dispose cleanly.
        """
        results = []
        joins = []

        def sample_task():
            results.append("ran")
            joins.append(threading.current_thread())  # Capture thread for joining

        agents = self.center.create_agents(3, sample_task, name_prefix="Agent")

        for agent in agents:
            agent.start()

        for thread in joins:
            thread.join()

        self.assertEqual(len(results), 3)

        # Correct method name
        snapshot = self.center.get_active_agents()
        self.assertIsInstance(snapshot, list)
        self.assertEqual(len(snapshot), 0)

    def test_submit_executes_in_threadpool(self):
        called = []

        def job():
            called.append("done")
            return 42

        future = self.center.submit(job)
        result = future.result(timeout=2)
        self.assertEqual(result, 42)
        self.assertEqual(called, ["done"])
        self.assertEqual(len(self.center.get_active_agents()), 0)

    def test_transform_current_thread_success(self):
        result = []

        def inner():
            self.assertFalse(ActivatedAgent.is_agent(threading.current_thread()))
            self.assertTrue(self.center.transform_current_thread("xyz"))
            result.append(True)
            self.assertTrue(ActivatedAgent.is_agent(threading.current_thread()))

        t = threading.Thread(target=inner)
        t.start()
        t.join()

        self.assertTrue(result)
        self.assertEqual(len(self.center.get_active_agents()), 1)

    def test_transform_main_thread_fails(self):
        with self.assertRaises(RuntimeError):
            self.center.transform_current_thread("main-bad")

    def test_activate_agents_bulk(self):
        def dummy(): pass

        threads = [threading.Thread(target=dummy) for _ in range(5)]
        count = self.center.activate_agents(threads)
        self.assertEqual(count, 5)
        self.assertEqual(len(self.center.get_active_agents()), 5)

    def test_dispose_cleans_up_resources(self):
        def dummy(): pass
        self.center.create_agents(2, dummy)
        self.assertGreater(len(self.center.get_active_agents()), 0)
        self.center.dispose()
        self.assertTrue(self.center._disposed)
        self.assertIsNone(self.center._active_agents)
        self.assertIsNone(self.center._offload_pool)

    def test_shutdown_is_alias_for_dispose(self):
        self.assertFalse(self.center._disposed)
        self.center.shutdown()
        self.assertTrue(self.center._disposed)

    def test_submit_registers_agent_temporarily(self):
        agent_ids = []

        def job():
            agent_ids.append(getattr(threading.current_thread(), "factory_id", None))

        self.center.submit(job).result()
        self.assertEqual(len(agent_ids), 1)
        self.assertIsInstance(agent_ids[0], str)
        self.assertEqual(len(self.center.get_active_agents()), 0)

    @unittest.skip("HelpRequest is not implemented in this test suite")
    def test_request_help_raises_runtime_error(self):
        with self.assertRaises(RuntimeError):
            self.center.request_help(HelpRequest())


if __name__ == "__main__":
    unittest.main()
