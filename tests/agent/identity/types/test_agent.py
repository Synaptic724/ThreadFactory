import unittest
from unittest.mock import MagicMock
from thread_factory.agent.identity.types.agent import Agent
from thread_factory.agent.thread_pool.help_request import HelpRequest
from thread_factory.runtime.orchestrator.monitoring.records.records import WorkStatus, Record
from thread_factory.utils.coordination.package import Pack


def dummy_callable():
    return "done"


class DummyAgent:
    def __init__(self):
        self.inventory = {}
    def bind_to_inventory(self, key, value): self.inventory[key] = value
    def get_from_inventory(self, key, default=None): return self.inventory.get(key, default)


class DummyCommandCenter:
    def __init__(self):
        self._agents = {"some_id": DummyAgent()}

    def get_agent_by_id(self, factory_id: str):
        return self._agents.get(factory_id)


class TestAgent(unittest.TestCase):
    def setUp(self):
        self.command_center = DummyCommandCenter()
        self.agent = Agent(command_center=self.command_center)

    def tearDown(self):
        self.agent.dispose()

    def test_factory_id_is_unique_string(self):
        self.assertIsInstance(self.agent.factory_id, str)
        another = Agent(command_center=self.command_center)
        self.assertNotEqual(self.agent.factory_id, another.factory_id)
        another.dispose()

    def test_should_return_home_toggle(self):
        self.assertFalse(self.agent.should_return_home())
        self.agent.set_return_home(True)
        self.assertTrue(self.agent.should_return_home())

    def test_set_home_executes(self):
        state = {"called": False}
        def fake_home(): state["called"] = True
        self.agent.set_home(fake_home)
        self.agent._event_loop()
        self.assertTrue(state["called"])

    def test_invalid_target_raises(self):
        with self.assertRaises(TypeError):
            Agent(command_center=self.command_center, target="not_a_callable")

    def test_set_target_valid(self):
        def task(): pass
        self.agent.set_target(task)
        self.assertIsInstance(self.agent._target, Pack)

    def test_bind_and_get_work(self):
        work = HelpRequest(work_callable=dummy_callable)
        self.agent._set_value_work(work)
        self.assertIs(self.agent._get_value_work(), work)

    def test_mark_work_states(self):
        work = HelpRequest(work_callable=dummy_callable)
        self.agent._set_value_work(work)
        self.agent._mark_work_in_progress()
        self.assertEqual(work.get_state(), WorkStatus.IN_PROGRESS)
        self.agent._mark_work_completed()
        self.assertEqual(work.get_state(), WorkStatus.COMPLETED)
        self.agent._mark_work_failed()
        self.assertEqual(work.get_state(), WorkStatus.FAILED)
        self.agent._mark_work_cancelled()
        self.assertEqual(work.get_state(), WorkStatus.CANCELLED)
        self.agent._reset_work()
        self.assertEqual(work.get_state(), WorkStatus.PENDING)

    def test_work_record_retrieval(self):
        work = HelpRequest(work_callable=dummy_callable)
        self.agent._set_value_work(work)
        self.assertIsInstance(self.agent._get_work_record(), Record)

    def test_bind_to_inventory_by_id(self):
        self.agent.bind_to_inventory_by_id("some_id", "x", 42)
        agent = self.command_center.get_agent_by_id("some_id")
        self.assertEqual(agent.inventory["x"], 42)

    def test_get_from_inventory_by_id(self):
        agent = self.command_center.get_agent_by_id("some_id")
        agent.bind_to_inventory("magic", 123)
        value = self.agent.get_from_inventory_by_id("some_id", "magic")
        self.assertEqual(value, 123)

    def test_dispose_is_idempotent(self):
        self.agent.dispose()
        try:
            self.agent.dispose()
        except Exception as e:
            self.fail(f"Dispose raised unexpectedly: {e}")

    def test_validate_caller_accepts_and_rejects(self):
        import threading
        setattr(threading.current_thread(), "factory_id", self.agent.factory_id)
        self.agent._validate_caller()
        setattr(threading.current_thread(), "factory_id", "bad_id")
        with self.assertRaises(PermissionError):
            self.agent._validate_caller()

    def test_run_without_home_raises(self):
        self.agent._pool_agent = True
        self.agent._event_loop = None
        with self.assertRaises(RuntimeError):
            self.agent.run()

    def test_run_executes_home_loop(self):
        called = {"flag": False}
        self.agent.set_home(lambda: called.update(flag=True))
        self.agent._pool_agent = True
        self.agent.run()
        self.assertTrue(called["flag"])


if __name__ == "__main__":
    unittest.main()
