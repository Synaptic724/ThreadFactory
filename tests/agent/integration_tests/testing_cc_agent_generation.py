import unittest
from thread_factory.agent.command_center import CommandCenter
from thread_factory.agent.identity.types.agent import Agent


class TestAgentCreationIntegration(unittest.TestCase):
    """Integration tests for agent creation via CommandCenter using naming and identity configurations."""

    def setUp(self):
        self.center = CommandCenter()
        self.center.name = "CreateTestCenter"

    def tearDown(self):
        self.center.dispose()

    def test_create_agent_with_name_sets_identity_fields(self):
        agent = self.center.create_agent(public_name="TestUnit", define_home=lambda: None)
        self.assertIsInstance(agent, Agent)
        self.assertEqual(agent.public_name, "TestUnit")

    def test_create_multiple_named_agents_have_unique_ids(self):
        a1 = self.center.create_agent(public_name="Clone", define_home=lambda: None)
        a2 = self.center.create_agent(public_name="Clone", define_home=lambda: None)
        self.assertNotEqual(a1.factory_id, a2.factory_id)
        self.assertEqual(a1.public_name, "Clone")
        self.assertEqual(a2.public_name, "Clone")

    def test_create_agent_without_name_assigns_default(self):
        agent = self.center.create_agent(define_home=lambda: None)
        self.assertTrue(agent.public_name.startswith("Agent") or agent.public_name.startswith("UnnamedAgent"))

if __name__ == "__main__":
    unittest.main(verbosity=2)
