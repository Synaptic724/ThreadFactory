import unittest
from thread_factory.agent.activity import Activity
from thread_factory.agent.activity.activity_controller import ActivityController
from thread_factory.agent.activity.activity_builder import ActivityBuilder
from thread_factory import ConcurrentDict


class TestActivitySystem(unittest.TestCase):

    def setUp(self):
        self.metadata = ConcurrentDict({
            "job_name": "unit_test",
            "priority": 3
        })
        self.activity = Activity(metadata=self.metadata)
        self.controller = ActivityController(task="test_task", job="unit_job", group="test_group")

    def tearDown(self):
        self.activity.dispose()
        self.controller.dispose()

    def test_ulid_is_generated(self):
        self.assertIsInstance(self.activity.ulid, str)
        self.assertGreater(len(self.activity.ulid), 0)

    def test_metadata_is_copied(self):
        copied = self.activity.metadata
        self.assertEqual(copied["job_name"], "unit_test")
        self.assertEqual(copied["priority"], 3)
        copied["job_name"] = "changed"
        self.assertNotEqual(self.activity.metadata["job_name"], "changed")

    def test_add_and_get_activity(self):
        self.activity.add_activity("cancel_requested", True)
        self.activity.add_activity("compute_fn", lambda: 42)
        self.assertIn("cancel_requested", self.activity)
        self.assertEqual(self.activity["cancel_requested"], True)
        self.assertEqual(self.activity["compute_fn"](), 42)

    def test_get_activity_missing(self):
        self.assertIsNone(self.activity.get_activity("not_there"))

    def test_dispose_releases_resources(self):
        self.activity.add_activity("cancel_requested", True)
        self.activity.dispose()
        self.assertTrue(self.activity._disposed)
        self.assertIsNone(self.activity._metadata)
        self.assertIsNone(self.activity._actions)

    def test_double_dispose_is_idempotent(self):
        self.activity.dispose()
        try:
            self.activity.dispose()
        except Exception as e:
            self.fail(f"Second dispose() raised an error: {e}")

    def test_overwrite_activity_value(self):
        self.activity.add_activity("flag", False)
        self.assertFalse(self.activity["flag"])
        self.activity.add_activity("flag", True)
        self.assertTrue(self.activity["flag"])

    def test_callable_activity_can_be_updated(self):
        self.activity.add_activity("calc", lambda: 1)
        self.assertEqual(self.activity["calc"](), 1)
        self.activity.add_activity("calc", lambda: 99)
        self.assertEqual(self.activity["calc"](), 99)

    def test_many_activities_can_be_bound(self):
        for i in range(1000):
            self.activity.add_activity(f"task_{i}", i)
        for i in range(1000):
            self.assertEqual(self.activity[f"task_{i}"], i)

    def test_metadata_copy_is_shallow(self):
        self.activity._metadata["deep"] = {"x": 1}
        shallow = self.activity.metadata
        shallow["deep"]["x"] = 42
        self.assertEqual(self.activity.metadata["deep"]["x"], 42)

    def test_activity_metadata_deep_copy_isolated(self):
        self.activity._metadata["deep"] = {"x": 1}
        deep = self.activity.deep_metadata()
        deep["deep"]["x"] = 999
        self.assertNotEqual(self.activity.metadata["deep"]["x"], 999)

    def test_controller_sets_default_fields(self):
        self.assertEqual(self.controller.task, "test_task")
        self.assertEqual(self.controller.job, "unit_job")
        self.assertEqual(self.controller.group, "test_group")
        self.assertIsInstance(self.controller.user_metadata, ConcurrentDict)

    def test_bind_and_callback_execution(self):
        flag = {"triggered": False}

        def cb():
            flag["triggered"] = True

        self.controller.register_callback("on_test", cb)
        result = self.controller.run_callback("on_test")

        self.assertTrue(result)
        self.assertTrue(flag["triggered"])

    def test_cancellation_profile_behavior(self):
        activity = self.controller.activity
        self.assertIn("cancel_requested", activity)
        self.assertFalse(activity["cancel_requested"]())
        self.controller.run_callback("cancel")
        self.assertTrue(activity["cancel_requested"]())

    def test_manual_profile_application(self):
        ctrl = ActivityController(use_default_profiles=False)
        builder = ActivityBuilder()
        builder.apply_profile("cancellation", ctrl)
        self.assertIn("cancel_requested", ctrl.activity)
        self.assertFalse(ctrl.activity["cancel_requested"]())
        ctrl.run_callback("cancel")
        self.assertTrue(ctrl.activity["cancel_requested"]())


if __name__ == "__main__":
    unittest.main()
