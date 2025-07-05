import threading
import unittest
from unittest.mock import MagicMock, patch
from thread_factory.agent.activity.base import BaseActivity
from thread_factory.synchronization.controllers.signal_controller import SignalController
from thread_factory.agent.identity.types.agent import Agent


class TestBaseActivity(unittest.TestCase):
    """Unit tests for BaseActivity class."""

    def setUp(self):
        """Create a fresh SignalController and BaseActivity before each test."""
        self.mock_controller = SignalController()
        self.activity = BaseActivity(signal_controller=self.mock_controller)

    def tearDown(self):
        """Dispose activity and controller after each test."""
        self.activity.dispose()
        self.mock_controller.dispose()

    def test_id_is_set(self):
        """Ensure activity ID is generated and non-empty."""
        self.assertIsNotNone(self.activity.id)
        self.assertIsInstance(self.activity.id, str)

    def test_metadata_is_stored_and_retrievable(self):
        """Test that metadata is properly stored and can be retrieved."""
        custom_activity = BaseActivity(logger=None, signal_controller=None, key1="value1", key2="value2")
        meta = custom_activity.get_metadata()
        self.assertEqual(meta["key1"], "value1")
        self.assertEqual(meta["key2"], "value2")

    def test_dispose_is_idempotent(self):
        """Test that calling dispose multiple times is safe."""
        self.activity.dispose()
        self.activity.dispose()  # Should not raise
        self.assertTrue(self.activity._disposed)

    def test_registered_with_signal_controller(self):
        """Ensure activity registers itself with SignalController."""
        listed = self.mock_controller.list_objects()
        self.assertTrue(any(obj["id"] == self.activity.id for obj in listed))

    def test_unregisters_on_dispose(self):
        """Ensure activity unregisters itself from SignalController on dispose."""
        self.activity.dispose()
        listed = self.mock_controller.list_objects()
        self.assertFalse(any(obj["id"] == self.activity.id for obj in listed))

    def test_dispose_works_without_signal_controller(self):
        activity = BaseActivity(signal_controller=None)
        try:
            activity.dispose()  # Should not raise
        except Exception as e:
            self.fail(f"Disposing without controller raised: {e}")

    def test_get_metadata_returns_copy(self):
        activity = BaseActivity(key1="value1")
        metadata_copy = activity.get_metadata()
        metadata_copy["key1"] = "hacked"
        # Original metadata should not change
        self.assertNotEqual(activity.get_metadata()["key1"], "hacked")

    def test_thread_safe_agent_registration(self):
        import threading

        def register_agent(idx):
            agent = MagicMock(spec=Agent)
            agent.factory_id = f"agent-{idx}"
            self.activity.register_agent(agent)

        threads = [threading.Thread(target=register_agent, args=(i,)) for i in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()

        self.assertEqual(len(self.activity.get_assigned_agents()), 10)

    def test_metadata_supports_primitives(self):
        activity = BaseActivity(user="alice", id=42, debug=True)
        meta = activity.get_metadata()
        self.assertEqual(meta["user"], "alice")
        self.assertEqual(meta["id"], 42)
        self.assertTrue(meta["debug"])



    def test_get_object_details_commands_are_callable(self):
        details = self.activity._get_object_details()
        commands = details["commands"]
        for cmd in commands.values():
            self.assertTrue(callable(cmd))

    def test_methods_after_dispose_are_safe(self):
        self.activity.dispose()
        try:
            self.activity.register_agent(MagicMock(factory_id="ghost"))
        except Exception as e:
            self.assertIsInstance(e, TypeError)  # Expected because _registered_agents is None

    def test_unregister_agent_emits_unassignment_event(self):
        events = []

        def on_event(object_id, event_type, data):
            events.append((event_type, data))

        mock_agent = MagicMock(spec=Agent)
        mock_agent.factory_id = "agent-z"
        self.mock_controller.subscribe(self.activity.id, "AGENT_UNASSIGNED", on_event)

        self.activity.register_agent(mock_agent)
        self.activity.unregister_agent(mock_agent)

        self.assertTrue(any(evt[0] == "AGENT_UNASSIGNED" for evt in events))

    def test_register_agent_emits_assignment_event(self):
        events = []

        def on_event(object_id, event_type, data):
            events.append((event_type, data))

        self.mock_controller.subscribe(self.activity.id, "AGENT_ASSIGNED", on_event)

        mock_agent = MagicMock(spec=Agent)
        mock_agent.factory_id = "agent-y"
        self.activity.register_agent(mock_agent)

        self.assertTrue(any(evt[0] == "AGENT_ASSIGNED" for evt in events))

    def test_get_assigned_agents_initially_empty(self):
        """Ensure no agents are assigned on init."""
        self.assertEqual(len(self.activity.get_assigned_agents()), 0)

    def test_register_and_unregister_agent(self):
        """Test registering and unregistering an agent."""
        mock_agent = MagicMock(spec=Agent)
        mock_agent.factory_id = "agent-001"

        self.activity.register_agent(mock_agent)
        self.assertIn("agent-001", self.activity.get_assigned_agents())

        self.activity.unregister_agent(mock_agent)
        self.assertNotIn("agent-001", self.activity.get_assigned_agents())

    def test_unregistering_nonexistent_agent_is_safe(self):
        mock_agent = MagicMock(spec=Agent)
        mock_agent.factory_id = "ghost"
        try:
            self.activity.unregister_agent(mock_agent)
        except Exception as e:
            self.fail(f"Unregistering a nonexistent agent raised: {e}")


    def test_get_agent_id_returns_none_without_thread_context(self):
        """Ensure _get_agent_id returns None if thread has no factory_id."""
        self.assertIsNone(self.activity._get_agent_id())

    def test_register_agent_twice_does_not_duplicate(self):
        mock_agent = MagicMock(spec=Agent)
        mock_agent.factory_id = "agent-x"
        self.activity.register_agent(mock_agent)
        self.activity.register_agent(mock_agent)
        agents = self.activity.get_assigned_agents()
        self.assertEqual(list(agents).count("agent-x"), 1)


    def test_get_agent_details_returns_agent_with_thread_context(self):
        """Ensure _get_agent_details returns correct agent based on thread-local factory_id."""
        mock_agent = MagicMock(spec=Agent)
        mock_agent.factory_id = "agent-777"
        self.activity.register_agent(mock_agent)

        # Manually inject factory_id into the current thread
        threading.current_thread().factory_id = "agent-777"
        try:
            agent = self.activity._get_agent_details()
            self.assertIs(agent, mock_agent)
        finally:
            # Always clean up to avoid leaking the factory_id into other tests
            del threading.current_thread().factory_id

    def test_get_object_details_returns_expected_contract(self):
        """Ensure _get_object_details() returns expected dictionary."""
        details = self.activity._get_object_details()
        self.assertIn("name", details)
        self.assertIn("commands", details)
        self.assertIn("get_metadata", details["commands"])
        self.assertIn("get_assigned_agents", details["commands"])


if __name__ == "__main__":
    unittest.main()
