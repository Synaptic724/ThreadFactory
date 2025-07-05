import unittest
from unittest.mock import MagicMock
from thread_factory.agent.identity.types.general import General
from thread_factory.utils.coordination.package import Pack


class DummyCommandCenter:
    pass


class TestGeneralAgent(unittest.TestCase):
    def setUp(self):
        self.cmd = DummyCommandCenter()
        self.agent = General(
            command_center=self.cmd,
            public_id="test-001",
            public_name="TestAgent",
            job_title="Testing",
            activity_group="UnitTests"
        )

    def tearDown(self):
        self.agent.dispose()

    def test_identity_properties_set(self):
        self.assertEqual(self.agent.public_id, "test-001")
        self.assertEqual(self.agent.public_name, "TestAgent")
        self.assertEqual(self.agent.job_title, "Testing")
        self.assertEqual(self.agent.activity_group, "UnitTests")

    def test_get_name_returns_name(self):
        self.assertEqual(self.agent.get_name(), "TestAgent")

    def test_get_description(self):
        desc = self.agent.get_description()
        self.assertIn("TestAgent", desc)
        self.assertIn("Testing", desc)
        self.assertIn("UnitTests", desc)

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
            self.agent.dispose()
        except Exception as e:
            self.fail(f"Dispose raised error on second call: {e}")

    def test_repr_and_str_consistency(self):
        self.assertIn("TestAgent", repr(self.agent))
        self.assertIn("AgenticProfile", str(self.agent))


if __name__ == "__main__":
    unittest.main()
