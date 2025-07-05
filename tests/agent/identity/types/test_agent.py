import unittest
import threading
from thread_factory.agent.identity.types.agent import Agent
from thread_factory.runtime.factory.operations.work.work import Work
from thread_factory.agent.thread_pool.help_request import HelpRequest
from thread_factory.runtime.orchestrator.monitoring.records.records import WorkStatus, Record
from thread_factory.utils.coordination.package import Pack
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict

class DummyCommandCenter:
    def __init__(self):
        self._agents = {}

    def _unregister_agent(self, agent):
        if agent.factory_id in self._agents:
            del self._agents[agent.factory_id]

    def add_agent(self, agent):
        self._agents[agent.factory_id] = agent

    def get_agent_by_id(self, factory_id: str):
        return self._agents.get(factory_id, None)


class TestAgent(unittest.TestCase):
    def setUp(self):
        self.command_center = DummyCommandCenter()
        self.agent = Agent(command_center=self.command_center)
        self.command_center.add_agent(self.agent)

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
        work = HelpRequest(work_callable=lambda: "done")
        self.agent._set_value_work(work)
        self.assertIs(self.agent._get_value_work(), work)

    def test_mark_work_states(self):
        work = HelpRequest(work_callable=lambda: "done")
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
        work = HelpRequest(work_callable=lambda: "done")
        self.agent._set_value_work(work)
        self.assertIsInstance(self.agent._get_work_record(), Record)

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

    def test_run_executes_home_loop(self):
        called = {"flag": False}
        self.agent.set_home(lambda: called.update(flag=True))
        self.agent._pool_agent = True
        self.agent.run()
        self.assertTrue(called["flag"])

    def test_bind_to_inventory_by_id(self):
        agent2 = Agent(command_center=self.command_center)
        self.command_center.add_agent(agent2)
        self.agent.bind_to_inventory_by_id(agent2.factory_id, "key1", 123)
        self.assertEqual(agent2.public_inventory["key1"], 123)

    def test_get_from_inventory_by_id(self):
        agent2 = Agent(command_center=self.command_center)
        self.command_center.add_agent(agent2)
        self.agent.bind_to_inventory_by_id(agent2.factory_id, "key2", 456)
        self.assertEqual(self.agent.get_from_inventory_by_id(agent2.factory_id, "key2"), 456)

    def test_invalid_agent_id_in_inventory_bind(self):
        with self.assertRaises(ValueError):
            self.agent.bind_to_inventory_by_id("invalid_factory_id", "key", 123)

    def test_inventory_clear_after_dispose(self):
        self.agent.public_inventory["test"] = "value"
        self.agent.dispose()

        # After disposing, check that the public_inventory is None
        self.assertIsNone(self.agent.public_inventory)

    def test_public_inventory_key_management(self):
        self.agent.public_inventory["test_key"] = "test_value"
        self.assertEqual(self.agent.public_inventory["test_key"], "test_value")

    def test_run_without_home_raises(self):
        # Before running, check that the agent is not disposed
        self.assertFalse(self.agent._disposed)

        # Run the agent without setting a home loop, which should dispose of it
        self.agent.run()

        # After running, check that the agent is disposed
        self.assertTrue(self.agent._disposed)


if __name__ == "__main__":
    unittest.main()