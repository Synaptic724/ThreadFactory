import unittest
from thread_factory.agent.activity_controller import ActivityController
from thread_factory import ConcurrentDict


class TestAgentController(unittest.TestCase):

    def setUp(self):
        self.controller = ActivityController(job_name="unit_test", priority=1)

    def tearDown(self):
        self.controller.dispose()

    def test_ulid_exists(self):
        self.assertTrue(hasattr(self.controller, "_ulid"))
        self.assertIsInstance(self.controller._ulid, str)
        self.assertGreater(len(self.controller._ulid), 0)

    def test_metadata_copy(self):
        meta = self.controller.metadata
        self.assertEqual(meta["job_name"], "unit_test")
        self.assertEqual(meta["priority"], 1)

        meta["job_name"] = "modified"
        self.assertNotEqual(self.controller.metadata["job_name"], "modified")

    def test_bind_and_activity_propagation(self):
        self.controller.bind("cancel_requested", True)
        self.controller.bind("compute", lambda: 123)

        act = self.controller.activity
        self.assertTrue("cancel_requested" in act)
        self.assertEqual(act["cancel_requested"], True)
        self.assertEqual(act["compute"](), 123)

    def test_register_and_run_callback_success(self):
        called = []

        def my_callback():
            called.append("ok")

        self.controller.register_callback("on_shutdown", my_callback)
        result = self.controller.run_callback("on_shutdown")

        self.assertTrue(result)
        self.assertIn("ok", called)

    def test_run_callback_not_found(self):
        self.assertFalse(self.controller.run_callback("does_not_exist"))

    def test_run_callback_raises(self):
        def bad_callback():
            raise RuntimeError("fail")

        self.controller.register_callback("fail", bad_callback)
        self.assertFalse(self.controller.run_callback("fail"))  # should not raise

    def test_dispose_clears_everything(self):
        self.controller.bind("cancel_requested", True)
        self.controller.register_callback("on_shutdown", lambda: None)

        self.controller.dispose()
        self.assertTrue(self.controller._disposed)
        self.assertIsNone(self.controller._metadata)
        self.assertIsNone(self.controller._actions)
        self.assertIsNone(self.controller._callbacks)
        self.assertIsNone(self.controller._activity)

if __name__ == "__main__":
    unittest.main()