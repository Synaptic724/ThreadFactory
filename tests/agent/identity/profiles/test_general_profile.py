import unittest
from thread_factory.agent.identity.agent_builder import ProfileBuilder
from thread_factory.agent.identity.types.general import General
from thread_factory.agent.identity.activator import AgentActivator


class ProfileIntegrationTest(unittest.TestCase):

    def setUp(self):
        self.builder = ProfileBuilder()

    def tearDown(self):
        self.builder.dispose()

    def test_profile_creation_and_binding_flow(self):
        """
        Full integration test for:
        - Creating a profile
        - Mutating identity
        - Binding to an agent
        - Detaching and cleanup
        """

        agent = AgentActivator(thread_stub := type("FakeThread", (), {})())
        profile = self.builder.get_profile("default")

        # Verify initial identity
        self.assertEqual(profile.name, "UnnamedAgent")
        self.assertEqual(profile.job, "generic")
        self.assertEqual(profile.group, "default")
        self.assertFalse(profile.is_bound)

        # Modify some identity details
        profile.name = "Scout42"
        profile.job = "Surveyor"
        profile.group = "ExpeditionA"

        # Attach to agent
        self.builder.attach_profile(profile, agent)
        self.assertTrue(profile.is_bound)
        self.assertIs(profile._bound_target, agent)

        # Validate accessors
        self.assertEqual(profile.name, "Scout42")
        self.assertEqual(profile.job, "Surveyor")
        self.assertEqual(profile.group, "ExpeditionA")
        from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict

        self.assertIsInstance(profile.save_points, ConcurrentDict)
        self.assertIsInstance(profile.data_transfer, ConcurrentDict)
        self.assertIsInstance(profile.locations, ConcurrentDict)

        # Detach
        self.builder.detach_profile(profile)
        self.assertFalse(profile.is_bound)
        self.assertIsNone(profile._bound_target)

    def test_multiple_profiles_are_isolated(self):
        """
        Ensure that creating two profiles produces isolated state.
        """
        a = self.builder.create_profile()
        b = self.builder.create_profile()

        a.name = "Alpha"
        b.name = "Beta"
        a.group = "G1"
        b.group = "G2"

        self.assertNotEqual(a.name, b.name)
        self.assertNotEqual(a.group, b.group)
        self.assertNotEqual(id(a), id(b))

    def test_binding_only_works_on_supported_agent(self):
        """
        Ensure that binding fails for unsupported types.
        """
        profile = self.builder.create_profile()
        fake_obj = object()
        with self.assertRaises(TypeError):
            profile.bind_to(fake_obj)


if __name__ == "__main__":
    unittest.main()
