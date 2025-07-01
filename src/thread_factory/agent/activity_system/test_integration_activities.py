import unittest
from thread_factory.agent.activity import Activity
from thread_factory.agent.activity_builder import ActivityBuilder
from thread_factory.agent.activity_controller import ActivityController


class TestActivitySystem(unittest.TestCase):

    def test_activity_controller_creates_ulid(self):
        controller = ActivityController(task="test")
        self.assertIsInstance(controller.activity.ulid, str)

    def test_user_metadata_roundtrip(self):
        controller = ActivityController(task="a", group="g", spam="eggs", foo="bar")
        meta = controller.user_metadata
        self.assertEqual(meta["foo"], "bar")
        self.assertEqual(meta["spam"], "eggs")

        meta["foo"] = "updated"
        self.assertEqual(controller.user_metadata["foo"], "updated")

    def test_cancellation_profile_behavior(self):
        controller = ActivityController(task="shutdown_test")
        activity = controller.activity

        # Confirm flag exists
        self.assertIn("cancel_requested", controller.metadata)
        self.assertFalse(activity["cancel_requested"])

        # Trigger cancellation
        result = controller.run_callback("cancel")
        self.assertTrue(result)
        self.assertTrue(activity["cancel_requested"])

    def test_can_skip_default_profiles(self):
        controller = ActivityController(use_default_profiles=False)
        self.assertNotIn("cancel_requested", controller.metadata)
        self.assertNotIn("cancel_requested", controller.activity)

    def test_binding_controller_behavior(self):
        controller = ActivityController(task="bind_test")
        controller.bind("should_exit", lambda: True)

        self.assertIn("should_exit", controller.activity)
        self.assertTrue(controller.activity["should_exit"]())

    def test_activity_metadata_shallow_vs_deep(self):
        controller = ActivityController(task="profile_test")
        activity = controller.activity

        controller.user_metadata["deep"] = {"x": 1}

        shallow = activity.metadata
        shallow["deep"]["x"] = 42
        self.assertEqual(activity.metadata["deep"]["x"], 42)

        deep = activity.deep_metadata()
        deep["deep"]["x"] = 999
        self.assertNotEqual(activity.metadata["deep"]["x"], 999)

    def test_callback_execution_and_fallback(self):
        controller = ActivityController()

        called = []
        controller.register_callback("record", lambda: called.append("ok"))

        ran = controller.run_callback("record")
        self.assertTrue(ran)
        self.assertEqual(called, ["ok"])

        self.assertFalse(controller.run_callback("nonexistent"))

    def test_activity_overwrite_and_get(self):
        controller = ActivityController()
        controller.bind("flag", False)
        self.assertFalse(controller.activity["flag"])

        controller.bind("flag", True)
        self.assertTrue(controller.activity["flag"])

    def test_profile_registry_addition(self):
        builder = ActivityBuilder()

        def dummy_profile(controller):
            controller.bind("dummy", lambda: 123)

        builder.register_profile("dummy", dummy_profile)

        controller = ActivityController(use_default_profiles=False)
        builder.apply_profile("dummy", controller)

        self.assertEqual(controller.activity["dummy"](), 123)


if __name__ == "__main__":
    unittest.main()