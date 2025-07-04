import unittest
from thread_factory.agent.identity.profile_builder import ProfileBuilder
from thread_factory.agent.identity.profiles.general import General


class DummyAgent:
    """Mock agent for testing profile binding."""
    pass


class ProfileBuilderTests(unittest.TestCase):

    def setUp(self):
        self.builder = ProfileBuilder()

    def tearDown(self):
        self.builder.dispose()

    def test_register_and_list_profile(self):
        self.builder.register_profile("tester", lambda p: setattr(p, "name", "Testy"))
        self.assertIn("tester", self.builder.list_profiles())

    def test_has_profile_returns_true(self):
        self.builder.register_profile("foo", lambda p: None)
        self.assertTrue(self.builder.has_profile("foo"))

    def test_unregister_profile_removes_entry(self):
        self.builder.register_profile("temp", lambda p: None)
        removed = self.builder.unregister_profile("temp")
        self.assertTrue(removed)
        self.assertFalse(self.builder.has_profile("temp"))

    def test_create_profile_applies_defaults(self):
        profile = self.builder.create_profile()
        self.assertEqual(profile.name, "UnnamedAgent")
        self.assertEqual(profile.job, "generic")
        self.assertEqual(profile.group, "default")

    def test_apply_custom_profile(self):
        self.builder.register_profile("hero", lambda p: setattr(p, "name", "Heroic"))
        profile = General()
        self.builder.apply_profile("hero", profile)
        self.assertEqual(profile.name, "Heroic")

    def test_apply_unregistered_profile_raises(self):
        profile = General()
        with self.assertRaises(KeyError):
            self.builder.apply_profile("ghost", profile)

    def test_attach_and_detach_profile(self):
        from thread_factory.agent.identity.activator import ActivatedAgent

        thread_stub = type("FakeThread", (), {})()
        agent = ActivatedAgent(thread_stub)
        profile = self.builder.create_profile()

        self.builder.attach_profile(profile, agent)
        self.assertTrue(profile.is_bound)
        self.assertIs(profile._bound_target, agent)

        self.builder.detach_profile(profile)
        self.assertFalse(profile.is_bound)
        self.assertIsNone(profile._bound_target)

    def test_apply_defaults_explicitly(self):
        profile = General()
        self.builder.apply_defaults(profile)
        self.assertEqual(profile.name, "UnnamedAgent")

    def test_register_profile_invalid_input(self):
        with self.assertRaises(ValueError):
            self.builder.register_profile("", None)

    def test_create_and_register_multiple_profiles(self):
        self.builder.register_profile("alpha", lambda p: setattr(p, "group", "AlphaTeam"))
        self.builder.register_profile("beta", lambda p: setattr(p, "group", "BetaSquad"))

        p1 = self.builder.create_profile("alpha")
        p2 = self.builder.create_profile("beta")

        self.assertEqual(p1.group, "AlphaTeam")
        self.assertEqual(p2.group, "BetaSquad")


if __name__ == "__main__":
    unittest.main()
