import unittest
from thread_factory.agent.activity import Activity
from thread_factory import ConcurrentDict


class TestActivity(unittest.TestCase):

    def setUp(self):
        self.metadata = ConcurrentDict({
            "job_name": "unit_test",
            "priority": 3
        })
        self.activity = Activity(metadata=self.metadata)

    def tearDown(self):
        self.activity.dispose()

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

        self.assertTrue("cancel_requested" in self.activity)
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

    def test_activity_knows_its_controller(self):
        from thread_factory.agent.activity_controller import ActivityController
        controller = ActivityController(task="foo", use_default_profiles=False)
        self.assertIs(controller.activity._controller, controller)
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
        original = {"nested": {"x": 1}}
        self.activity._metadata["deep"] = original

        copied = self.activity.metadata
        copied["deep"]["nested"]["x"] = 99

        # Since it's a shallow copy, this should reflect in the original too
        self.assertEqual(self.activity.metadata["deep"]["nested"]["x"], 99)


if __name__ == "__main__":
    unittest.main()
