import unittest
from unittest.mock import MagicMock
from thread_factory.agent.identity.types.general import General
from thread_factory.utils.coordination.package import Pack
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict


class TestGeneralAgent(unittest.TestCase):
    def setUp(self):
        """
        Set up the test case.

        FIX: Replaced the inadequate `DummyCommandCenter` with `MagicMock`.
        `MagicMock` can dynamically respond to any method call, including the
        `_unregister_agent` call that happens during the agent's dispose cycle,
        which was the source of the errors.
        """
        self.cmd = MagicMock()
        self.agent = General(
            command_center=self.cmd,
            public_id="test-001",
            public_name="TestAgent",
            job_title="Testing",
            activity_group="UnitTests"
        )

    def tearDown(self):
        """
        Clean up after each test.
        This will now execute without error because the mocked command center
        can handle the dispose call chain.
        """
        if self.agent and not self.agent._disposed:
            self.agent.dispose()

    def test_identity_properties_set(self):
        self.assertEqual(self.agent.public_id, "test-001")
        self.assertEqual(self.agent.public_name, "TestAgent")
        self.assertEqual(self.agent.job_title, "Testing")

    def test_get_name_returns_name(self):
        self.assertEqual(self.agent.get_name(), "TestAgent")

    def test_get_description(self):
        desc = self.agent.get_description()
        self.assertIn("TestAgent", desc)
        self.assertIn("Testing", desc)

    def test_register_data_transfer_executes(self):
        self.agent.register_data_transfer("hello", lambda: "world")
        result = self.agent.execute_transfer("hello")
        self.assertEqual(result, "world")

    def test_register_data_transfer_with_pack(self):
        self.agent.register_data_transfer("greet", Pack.bundle(lambda: "yo"))
        result = self.agent.execute_transfer("greet")
        self.assertEqual(result, "yo")

    def test_get_data_transfer_dict_returns_copy(self):
        self.agent.register_data_transfer("x", lambda: 123)
        copy_dict = self.agent.get_data_transfer_dict()
        self.assertIn("x", copy_dict)
        self.assertIsNot(copy_dict, self.agent.data_transfer)

    def test_register_save_point_and_retrieve(self):
        called = {"hit": False}
        self.agent.register_save_point("checkpoint", lambda: called.update(hit=True))
        self.agent.save_points["checkpoint"]()
        self.assertTrue(called["hit"])

    def test_get_save_points_dict_returns_copy(self):
        self.agent.register_save_point("x", lambda: None)
        copy_dict = self.agent.get_save_points_dict()
        self.assertIn("x", copy_dict)
        self.assertIsNot(copy_dict, self.agent.save_points)

    def test_register_location_and_invoke(self):
        flag = {"ok": False}
        self.agent.register_location("zoneA", lambda: flag.update(ok=True))
        self.agent.locations["zoneA"]()
        self.assertTrue(flag["ok"])

    def test_get_locations_dict_returns_copy(self):
        self.agent.register_location("y", lambda: None)
        copy_dict = self.agent.get_locations_dict()
        self.assertIn("y", copy_dict)
        self.assertIsNot(copy_dict, self.agent.locations)

    def test_dispose_nullifies_and_doesnt_crash(self):
        self.agent.dispose()
        self.assertIsNone(self.agent.save_points)
        self.assertIsNone(self.agent.locations)
        self.assertIsNone(self.agent.data_transfer)

    def test_dispose_is_idempotent(self):
        self.agent.dispose()
        try:
            self.agent.dispose()  # Call a second time
        except Exception as e:
            self.fail(f"Dispose raised error on second call: {e}")

    def test_repr_and_str_consistency(self):
        self.assertIn("TestAgent", repr(self.agent))
        self.assertIn("AgenticProfile", str(self.agent))


class TestGeneralAdditional(unittest.TestCase):

    def setUp(self):
        """
        Set up the test case.

        FIX: The original used `Mock()`, which was correct. Switched to
        `MagicMock()` for consistency with the other test class.
        """
        self.mock_command_center = MagicMock()
        self.agent = General(
            command_center=self.mock_command_center,
            public_id="id-001",
            public_name="TestAgent",
            job_title="Testing",
            activity_group="UnitTests"
        )

    def tearDown(self):
        if self.agent and not self.agent._disposed:
            self.agent.dispose()

    def test_double_dispose(self):
        self.agent.dispose()
        self.agent.dispose()  # Should not raise an error
        self.assertTrue(self.agent._disposed)

    def test_register_save_point_after_dispose_raises(self):
        self.agent.dispose()
        with self.assertRaises(RuntimeError):
            self.agent.register_save_point("save", lambda: None)

    def test_register_location_after_dispose_raises(self):
        self.agent.dispose()
        with self.assertRaises(RuntimeError):
            self.agent.register_location("loc", lambda: None)

    def test_register_data_transfer_after_dispose_raises(self):
        self.agent.dispose()
        with self.assertRaises(RuntimeError):
            self.agent.register_data_transfer("transfer", lambda: None)

    def test_save_points_copy_empty_if_none(self):
        self.agent.save_points = None
        copy = self.agent.get_save_points_dict()
        self.assertIsInstance(copy, ConcurrentDict)
        self.assertEqual(len(copy), 0)

    def test_locations_copy_empty_if_none(self):
        self.agent.locations = None
        copy = self.agent.get_locations_dict()
        self.assertIsInstance(copy, ConcurrentDict)
        self.assertEqual(len(copy), 0)

    def test_data_transfer_copy_empty_if_none(self):
        self.agent.data_transfer = None
        copy = self.agent.get_data_transfer_dict()
        self.assertIsInstance(copy, ConcurrentDict)
        self.assertEqual(len(copy), 0)

    def test_register_and_copy_all(self):
        self.agent.register_save_point("sp", lambda: None)
        self.agent.register_location("loc", lambda: None)
        self.agent.register_data_transfer("dt", lambda: 123)
        self.assertIn("sp", self.agent.get_save_points_dict())
        self.assertIn("loc", self.agent.get_locations_dict())
        self.assertIn("dt", self.agent.get_data_transfer_dict())

    def test_execute_transfer_success(self):
        self.agent.register_data_transfer("echo", lambda: "pong")
        result = self.agent.execute_transfer("echo")
        self.assertEqual(result, "pong")

    def test_execute_transfer_missing_raises(self):
        with self.assertRaises(KeyError):
            self.agent.execute_transfer("missing")

    def test_register_callable_vs_pack(self):
        self.agent.register_location("raw", lambda: "a")
        self.agent.register_location("pack", Pack.bundle(lambda: "b"))
        locs = self.agent.get_locations_dict()
        self.assertIn("raw", locs)
        self.assertIn("pack", locs)
        self.assertTrue(callable(locs["raw"]))
        self.assertTrue(callable(locs["pack"]))

    def test_multiple_registrations_survive(self):
        self.agent.register_save_point("a", lambda: 1)
        self.agent.register_save_point("b", lambda: 2)
        self.agent.register_location("a", lambda: 3)
        self.agent.register_location("b", lambda: 4)
        self.agent.register_data_transfer("a", lambda: 5)
        self.agent.register_data_transfer("b", lambda: 6)
        self.assertEqual(len(self.agent.get_save_points_dict()), 2)
        self.assertEqual(len(self.agent.get_locations_dict()), 2)
        self.assertEqual(len(self.agent.get_data_transfer_dict()), 2)

    def test_dispose_and_safe_dict_return(self):
        self.agent.register_location("loc", lambda: 1)
        self.agent.dispose()
        locs = self.agent.get_locations_dict()
        self.assertIsInstance(locs, ConcurrentDict)
        self.assertEqual(len(locs), 0)

    def test_repr_contains_name(self):
        text = repr(self.agent)
        self.assertIn("TestAgent", text)

    def test_get_name_returns_default(self):
        agent = General(command_center=self.mock_command_center)
        agent.name = "UnnamedAgent"
        self.assertEqual(agent.get_name(), "UnnamedAgent")
        agent.dispose()


if __name__ == "__main__":
    unittest.main(argv=['first-arg-is-ignored'], exit=False)