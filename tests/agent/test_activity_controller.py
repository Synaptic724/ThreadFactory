import unittest
from thread_factory.agent.activity_controller import ActivityController
from thread_factory import ConcurrentDict


class TestActivityController(unittest.TestCase):

    def setUp(self):
        self.controller = ActivityController(job="unit_test", priority=1)

    def tearDown(self):
        if self.controller and not self.controller._disposed:
            self.controller.dispose()

    def test_ulid_is_generated(self):
        self.assertTrue(hasattr(self.controller, "_ulid"))
        self.assertIsInstance(self.controller._ulid, str)
        self.assertGreater(len(self.controller._ulid), 0)

    def test_metadata_fields_set_correctly(self):
        meta = self.controller.metadata
        self.assertEqual(meta["job"], "unit_test")
        self.assertEqual(meta["user_metadata"]["priority"], 1)

        meta["user_metadata"]["priority"] = 999
        self.assertNotEqual(self.controller.user_metadata["priority"], 1)

    def test_task_job_group_setters_work(self):
        self.controller.task = "download"
        self.controller.job = "B123"
        self.controller.group = "group_alpha"
        self.assertEqual(self.controller.task, "download")
        self.assertEqual(self.controller.job, "B123")
        self.assertEqual(self.controller.group, "group_alpha")

    def test_bind_propagates_to_activity_token(self):
        self.controller.bind("cancel_requested", True)
        self.controller.bind("compute_value", lambda: 99)
        token = self.controller.activity
        self.assertIn("cancel_requested", token)
        self.assertTrue(token["cancel_requested"])
        self.assertEqual(token["compute_value"](), 99)

    def test_register_and_run_callback_executes(self):
        calls = []

        def on_trigger():
            calls.append("ran")

        self.controller.register_callback("my_cb", on_trigger)
        result = self.controller.run_callback("my_cb")
        self.assertTrue(result)
        self.assertIn("ran", calls)

    def test_run_callback_returns_false_if_missing(self):
        result = self.controller.run_callback("not_there")
        self.assertFalse(result)

    def test_run_callback_returns_false_on_exception(self):
        def broken():
            raise RuntimeError("fail")

        self.controller.register_callback("boom", broken)
        result = self.controller.run_callback("boom")
        self.assertFalse(result)

    def test_user_metadata_access(self):
        c = ActivityController(task="extract", user_label="custom")
        self.assertEqual(c.user_metadata["user_label"], "custom")
        c.dispose()

    def test_dispose_clears_internal_references(self):
        self.controller.bind("flag", True)
        self.controller.register_callback("noop", lambda: None)
        self.controller.dispose()
        self.assertTrue(self.controller._disposed)
        self.assertIsNone(self.controller._metadata)
        self.assertIsNone(self.controller._actions)
        self.assertIsNone(self.controller._callbacks)
        self.assertIsNone(self.controller._activity)


if __name__ == "__main__":
    unittest.main()
