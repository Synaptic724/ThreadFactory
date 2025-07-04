import unittest
import threading
from thread_factory.agent.command_center import CommandCenter
from thread_factory.agent.identity.profiles.general import General


class TestCommandCenterProfileIntegration(unittest.TestCase):

    def setUp(self):
        self.cc = CommandCenter()

    def tearDown(self):
        self.cc.shutdown()

    def test_default_profile_is_available(self):
        self.assertIn("default", self.cc.list_profiles())

    def test_register_new_profile(self):
        self.cc.register_profile("archer", lambda p: setattr(p, "job", "Archer"))
        self.assertIn("archer", self.cc.list_profiles())

    def test_unregister_profile(self):
        self.cc.register_profile("to_remove", lambda p: None)
        self.assertTrue(self.cc.unregister_profile("to_remove"))
        self.assertNotIn("to_remove", self.cc.list_profiles())

    def test_set_default_profile_key(self):
        self.cc.register_profile("scout", lambda p: setattr(p, "name", "Scouty"))
        self.cc.set_default_profile_key("scout")
        self.assertEqual(self.cc._default_profile_key, "scout")

    def test_set_invalid_profile_key_raises(self):
        with self.assertRaises(KeyError):
            self.cc.set_default_profile_key("nonexistent")

    def test_create_agent_uses_default_profile(self):
        agent = self.cc.create_agents(1, lambda: None)[0]
        self.assertIsInstance(agent.profile, General)

    def test_create_agent_with_custom_profile(self):
        self.cc.register_profile("sniper", lambda p: setattr(p, "job", "Sniper"))
        self.cc.set_default_profile_key("sniper")
        agent = self.cc.create_agents(1, lambda: None)[0]
        self.assertEqual(agent.profile.job, "Sniper")

    def test_profile_objects_are_unique(self):
        agents = self.cc.create_agents(2, lambda: None)
        agents[0].profile.name = "AgentA"
        agents[1].profile.name = "AgentB"
        self.assertNotEqual(agents[0].profile.name, agents[1].profile.name)

    def test_submit_uses_profile(self):
        result = []

        def task():
            thread = threading.current_thread()
            result.append(thread.profile.name)

        future = self.cc.submit(task)
        future.result(timeout=1)
        self.assertEqual(result[0], "UnnamedAgent")

    def test_transform_current_thread_profile_binding(self):
        def fn():
            self.assertTrue(hasattr(threading.current_thread(), "profile"))
            self.assertIsInstance(threading.current_thread().profile, General)

        t = threading.Thread(target=lambda: (self.cc.transform_current_thread(), fn()))
        t.start()
        t.join()

    def test_profile_data_transfer_defaults_empty(self):
        agent = self.cc.create_agents(1, lambda: None)[0]
        self.assertEqual(len(agent.profile.data_transfer), 0)

    def test_profile_save_points_defaults_empty(self):
        agent = self.cc.create_agents(1, lambda: None)[0]
        self.assertEqual(len(agent.profile.save_points), 0)

    def test_profile_locations_defaults_empty(self):
        agent = self.cc.create_agents(1, lambda: None)[0]
        self.assertEqual(len(agent.profile.locations), 0)

    def test_profile_group_assignment(self):
        self.cc.register_profile("medic", lambda p: setattr(p, "group", "medical"))
        self.cc.set_default_profile_key("medic")
        agent = self.cc.create_agents(1, lambda: None)[0]
        self.assertEqual(agent.profile.group, "medical")

    def test_create_profile_directly(self):
        profile = self.cc._profile_builder.create_profile("default")
        self.assertIsInstance(profile, General)
        self.assertEqual(profile.name, "UnnamedAgent")
