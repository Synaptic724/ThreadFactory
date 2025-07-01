import unittest
from thread_factory.agent.activity.activity_controller import ActivityController
from thread_factory.agent.activity.activity_builder import ActivityBuilder


class TestActivityBuilder(unittest.TestCase):

    def setUp(self):
        self.builder = ActivityBuilder()
        self.controller = ActivityController(task="test", priority=5)

    def tearDown(self):
        if getattr(self.builder, "_registry", None):
            self.builder.dispose()
        if getattr(self.controller, "_metadata", None):
            self.controller.dispose()

    def test_register_and_apply_custom_profile(self):
        def sample_profile(ctrl):
            ctrl.bind("ready", True)
            ctrl.register_callback("poke", lambda: ctrl.bind("poked", True))

        self.builder.register_profile("custom", sample_profile)
        self.builder.apply_profile("custom", self.controller)

        self.assertTrue("ready" in self.controller.activity)
        self.assertEqual(self.controller.activity["ready"], True)

        self.assertFalse("poked" in self.controller.activity)
        self.controller.run_callback("poke")
        self.assertEqual(self.controller.activity["poked"], True)

    def test_apply_default_profiles_adds_cancel(self):
        self.builder.apply_defaults(self.controller)
        self.assertIn("cancel_requested", self.controller.activity)

        cancel_status = self.controller.activity["cancel_requested"]
        self.assertFalse(cancel_status())

        self.controller.run_callback("cancel")
        self.assertTrue(self.controller.activity["cancel_requested"]())

    def test_register_profile_overwrites_existing(self):
        called = []

        def first_profile(ctrl):
            called.append("first")

        def second_profile(ctrl):
            called.append("second")

        self.builder.register_profile("overwrite", first_profile)
        self.builder.register_profile("overwrite", second_profile)
        self.builder.apply_profile("overwrite", self.controller)

        self.assertIn("second", called)
        self.assertNotIn("first", called)

    def test_dispose_clears_registry(self):
        self.builder.register_profile("test", lambda c: c.bind("x", 1))
        self.assertIn("test", self.builder._registry)
        self.builder.dispose()
        self.assertIsNone(self.builder._registry)
        self.assertFalse(self.builder._registered)


if __name__ == "__main__":
    unittest.main()
