import unittest
import logging
import time
import sys
from threading import Event
from typing import Optional, Dict

from thread_factory.synchronization import SignalController
from thread_factory.agent.identity.types.general import General
from thread_factory.utils.coordination.package import Pack
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.concurrency.concurrent_queue import ConcurrentQueue
from thread_factory.concurrency.concurrent_list import ConcurrentList


# --- Mocked CommandCenter ---
class MockCommandCenter:
    def __init__(self):
        self._agents = ConcurrentDict()

    def _unregister_agent(self, agent):
        if agent.factory_id in self._agents:
            self._agents.pop(agent.factory_id)

    def get_agent_by_id(self, factory_id: str):
        return self._agents.get(factory_id)

    def register_agent(self, agent):
        self._agents[agent.factory_id] = agent


# --- Core TestCase ---
class TestGeneralAgentSignalControllerIntegration(unittest.TestCase):

    def setUp(self):
        """Prepare full integration environment with agent, controller, mocks, and test tracking."""
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger("TestGeneralAgent")

        self.command_center = MockCommandCenter()
        self.signal_controller = SignalController(logger=self.logger)
        self.work_queue = ConcurrentQueue()

        self.agent = General(
            command_center=self.command_center,
            public_id="agent-001",
            public_name="Test General Agent",
            job_title="Integration Tester",
            activity_group="Testing Team",
            signal_controller=self.signal_controller,
            work_queue=self.work_queue,
            logger=self.logger
        )
        self.command_center.register_agent(self.agent)

        self.received_events = ConcurrentList()
        self.event_received_flag = Event()

        def event_callback(object_id: str, event_type: str, data: Optional[Dict]):
            self.received_events.append({"object_id": object_id, "event_type": event_type, "data": data})
            self.event_received_flag.set()
            if not getattr(sys, "is_finalizing", lambda: False)():
                self.logger.info(f"Event received: {event_type} for {object_id} | Data: {data}")

        self.event_callback = event_callback

        self.agent.set_home(lambda: time.sleep(0.2))
        self.agent.start()

    def tearDown(self):
        """Dispose all test resources gracefully, ensuring thread join and controller flush."""
        try:
            if self.agent and not self.agent.is_disposed:
                self.agent.dispose()
            if self.agent:
                self.agent.join(timeout=2)
        except Exception:
            pass

        try:
            if self.signal_controller and not self.signal_controller._disposed:
                self.signal_controller.dispose()
        except Exception:
            pass

        try:
            self.work_queue.dispose()
            self.received_events.dispose()
        except Exception:
            pass

        if not getattr(sys, 'is_finalizing', lambda: False)():
            self.logger.info("Test teardown complete.")


    # --- TESTS ---

    def test_agent_registration_and_basic_commands(self):
        """Agent should appear in controller, expose commands, and respond properly."""
        registered = self.signal_controller.list_objects()
        self.assertIn(self.agent.id, [o["id"] for o in registered])
        self.assertEqual(len(registered), 1)

        agent_data = next(obj for obj in registered if obj["id"] == self.agent.id)
        self.assertEqual(agent_data["name"], "General")
        self.assertIn("get_public_name", agent_data["commands"])

        name = self.signal_controller.invoke(self.agent.id, "get_public_name")
        self.assertEqual(name, "Test General Agent")

        job = self.signal_controller.invoke(self.agent.id, "get_job_title")
        self.assertEqual(job, "Integration Tester")

    def test_agent_event_subscription_and_notification(self):
        """SignalController should deliver custom events to subscribed callbacks."""
        self.signal_controller.subscribe(self.agent.id, "CUSTOM_EVENT", self.event_callback)

        payload = {"key": "value", "status": "completed"}
        self.signal_controller.notify(self.agent.id, "CUSTOM_EVENT", payload)

        self.event_received_flag.wait(timeout=2)
        self.assertTrue(self.event_received_flag.is_set())
        self.assertEqual(len(self.received_events), 1)

        event = self.received_events[0]
        self.assertEqual(event["object_id"], self.agent.id)
        self.assertEqual(event["event_type"], "CUSTOM_EVENT")
        self.assertEqual(event["data"], payload)
    def test_double_dispose_is_idempotent(self):
        """Disposing the agent more than once should not raise or break anything."""
        self.agent.dispose()
        try:
            self.agent.dispose()  # Should silently succeed
        except Exception as e:
            self.fail(f"Second dispose raised an unexpected exception: {e}")

    def test_unsubscribe_event_stops_callback(self):
        """After unsubscribing, the callback should no longer receive events."""
        self.signal_controller.subscribe(self.agent.id, "TEST_EVENT", self.event_callback)
        self.signal_controller.unsubscribe(self.agent.id, "TEST_EVENT", self.event_callback)

        self.signal_controller.notify(self.agent.id, "TEST_EVENT", {"data": 123})
        triggered = self.event_received_flag.wait(timeout=1)
        self.assertFalse(triggered, "Callback was triggered after unsubscribing.")

    def test_re_registration_of_same_agent_id_overwrites(self):
        """If an agent with the same ID is registered again, it should replace the previous one."""
        new_agent = General(
            command_center=self.command_center,
            public_id="agent-001",  # Same ID
            public_name="New Name",
            job_title="New Job",
            activity_group="New Group",
            signal_controller=self.signal_controller,
            work_queue=ConcurrentQueue(),
            logger=self.logger
        )
        self.command_center.register_agent(new_agent)

        # Should return the new one
        result = self.command_center.get_agent_by_id("agent-001")
        self.assertIs(result, new_agent)

        # Clean up new agent
        new_agent.dispose()
        new_agent.join(timeout=1)

    def test_unknown_command_raises(self):
        """SignalController should raise KeyError if a command doesn't exist."""
        with self.assertRaises(KeyError):
            self.signal_controller.invoke(self.agent.id, "nonexistent_command")

    def test_register_duplicate_behavior_overwrites(self):
        """Registering a behavior with the same name should overwrite the previous one."""
        first = {"result": "first"}
        second = {"result": "second"}

        self.signal_controller.invoke(self.agent.id, "register_data_transfer", name="Dup", fn=Pack(lambda: first))
        self.signal_controller.invoke(self.agent.id, "register_data_transfer", name="Dup", fn=Pack(lambda: second))

        result = self.signal_controller.invoke(self.agent.id, "execute_transfer", name="Dup")
        self.assertEqual(result, second)

    def test_signal_after_dispose_does_not_fire(self):
        """No callbacks should be triggered if the agent is disposed before signal."""
        self.signal_controller.subscribe(self.agent.id, "POST_DEATH", self.event_callback)
        self.agent.dispose()
        self.agent.join(timeout=1)

        self.signal_controller.notify(self.agent.id, "POST_DEATH", {"ghost": True})
        received = self.event_received_flag.wait(timeout=1)
        self.assertFalse(received, "Event callback triggered on disposed agent.")

    def test_command_after_agent_thread_ends_raises(self):
        """Invoking commands after disposal should fail with KeyError due to deregistration."""
        self.agent.dispose()
        self.agent.join(timeout=1)

        with self.assertRaises(KeyError):
            self.signal_controller.invoke(self.agent.id, "get_job_title")

    def test_agent_dynamic_behavior_registration_and_invocation(self):
        """Agent should register dynamic behaviors and expose them through controller commands."""
        mock_location = {"x": 1, "y": 2}
        mock_save = {"progress": 0.75}
        mock_transfer = {"packet": "data"}

        self.signal_controller.invoke(self.agent.id, "register_location", name="MockLoc", fn=Pack(lambda: mock_location))
        self.signal_controller.invoke(self.agent.id, "register_save_point", name="MockSave", fn=Pack(lambda: mock_save))
        self.signal_controller.invoke(self.agent.id, "register_data_transfer", name="MockXfer", fn=Pack(lambda: mock_transfer))

        locations = self.signal_controller.invoke(self.agent.id, "get_locations_dict")
        self.assertIn("MockLoc", locations)

        save_points = self.signal_controller.invoke(self.agent.id, "get_save_points_dict")
        self.assertIn("MockSave", save_points)

        result = self.signal_controller.invoke(self.agent.id, "execute_transfer", name="MockXfer")
        self.assertEqual(result, mock_transfer)

    def test_agent_lifecycle_and_disposal(self):
        """Agent should clean up properly and unregister from SignalController."""
        self.assertTrue(self.agent.is_alive())
        self.assertIn(self.agent.get_state().name, ["STARTING", "IDLE", "ACTIVE"])

        self.agent.dispose()
        self.agent.join(timeout=2)

        self.assertFalse(self.agent.is_alive())
        self.assertTrue(self.agent.is_disposed)

        objects = self.signal_controller.list_objects()
        self.assertNotIn(self.agent.id, [obj["id"] for obj in objects])

        with self.assertRaises(KeyError):
            self.signal_controller.invoke(self.agent.id, "get_public_name")


if __name__ == "__main__":
    unittest.main(argv=["first-arg-is-ignored"], exit=False)
