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
        if self.activity and not self.activity._disposed:
            self.activity.dispose()

    def test_ulid_is_unique_string(self):
        ulid = self.activity.ulid
        self.assertIsInstance(ulid, str)
        self.assertGreater(len(ulid), 0)

    def test_shallow_metadata_copy(self):
        shallow_copy = self.activity.metadata
        self.assertEqual(shallow_copy["job_name"], "unit_test")
        self.assertEqual(shallow_copy["priority"], 3)
        shallow_copy["job_name"] = "modified"
        self.assertNotEqual(self.activity.metadata["job_name"], "modified")

    def test_deep_metadata_copy_isolated(self):
        self.activity._metadata["deep"] = {"nested": {"x": 1}}
        deep_copy = self.activity.deep_metadata()
        deep_copy["deep"]["nested"]["x"] = 99
        self.assertEqual(self.activity._metadata["deep"]["nested"]["x"], 1)

    def test_add_and_get_activity(self):
        self.activity.add_activity("cancel_requested", True)
        self.activity.add_activity("compute_fn", lambda: 42)

        self.assertIn("cancel_requested", self.activity)
        self.assertEqual(self.activity["cancel_requested"], True)
        self.assertEqual(self.activity["compute_fn"](), 42)

    def test_overwrite_activity_value(self):
        self.activity.add_activity("flag", False)
        self.assertFalse(self.activity["flag"])
        self.activity.add_activity("flag", True)
        self.assertTrue(self.activity["flag"])

    def test_get_activity_missing_returns_none(self):
        self.assertIsNone(self.activity.get_activity("ghost_flag"))

    def test_callable_activity_can_be_updated(self):
        self.activity.add_activity("calc", lambda: 1)
        self.assertEqual(self.activity["calc"](), 1)
        self.activity.add_activity("calc", lambda: 99)
        self.assertEqual(self.activity["calc"](), 99)

    def test_many_activities_can_be_bound_and_retrieved(self):
        for i in range(1000):
            self.activity.add_activity(f"task_{i}", i)
        for i in range(1000):
            self.assertEqual(self.activity[f"task_{i}"], i)

    def test_dispose_releases_internal_references(self):
        self.activity.add_activity("cancel_requested", True)
        self.activity.dispose()
        self.assertTrue(self.activity._disposed)
        self.assertIsNone(self.activity._metadata)
        self.assertIsNone(self.activity._actions)

    def test_dispose_twice_does_not_crash(self):
        self.activity.dispose()
        try:
            self.activity.dispose()
        except Exception as e:
            self.fail(f"Second dispose() raised an exception: {e}")


if __name__ == "__main__":
    unittest.main()
