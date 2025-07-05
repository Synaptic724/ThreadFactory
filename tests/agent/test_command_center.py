import unittest
import time
from thread_factory.agent.command_center import CommandCenter
from thread_factory.agent.identity.types.agent import Agent


class DummyAgent(Agent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._disposed = False

    # def dispose(self):
    #     #self._disposed = True
    #     pass

class TestCommandCenter(unittest.TestCase):

    def setUp(self):
        self.cc = CommandCenter(max_workers=3)

    def tearDown(self):
        self.cc.dispose()

    def test_register_and_list_templates(self):
        self.cc.register_template("test", lambda **kwargs: DummyAgent(**kwargs))
        self.assertIn("test", self.cc.list_templates())

    def test_unregister_template_success(self):
        self.cc.register_template("remove_me", lambda **kwargs: DummyAgent(**kwargs))
        result = self.cc.unregister_template("remove_me")
        self.assertTrue(result)
        self.assertNotIn("remove_me", self.cc.list_templates())

    def test_create_agent_and_dispose(self):
        self.cc.register_template("one", lambda **kwargs: DummyAgent(**kwargs))
        agent = self.cc.create_agent("one")
        self.assertIsInstance(agent, DummyAgent)
        self.assertIn(agent, self.cc.get_active_agents())
        agent.dispose()

    def test_create_agents_batch(self):
        self.cc.register_template("multi", lambda **kwargs: DummyAgent(**kwargs))
        agents = self.cc.create_agents(3, "multi")
        self.assertEqual(len(agents), 3)
        for agent in agents:
            self.assertIn(agent, self.cc.get_active_agents())

    def test_worker_cap_enforced(self):
        self.cc.register_template("limited", lambda **kwargs: DummyAgent(**kwargs))
        self.cc.create_agents(3, "limited")
        with self.assertRaises(RuntimeError):
            self.cc.create_agent("limited")

    def test_double_register_raises(self):
        self.cc.register_template("dupe", lambda **kw: DummyAgent(**kw))
        with self.assertRaises(ValueError):
            self.cc.register_template("dupe", lambda **kw: DummyAgent(**kw))

    def test_submit_after_dispose_raises(self):
        self.cc.register_template("submit_late", lambda **kw: DummyAgent(**kw))
        self.cc.dispose()
        with self.assertRaises(RuntimeError):
            self.cc.submit(lambda: None, template_name="submit_late")

    def test_unregister_nonexistent_template(self):
        result = self.cc.unregister_template("ghost")
        self.assertFalse(result)

    def test_dispose_multiple_times_is_safe(self):
        self.cc.dispose()
        self.cc.dispose()
        self.assertTrue(True)  # If it doesn't crash, it's good

    def test_dispose_frees_worker_slot(self):
        self.cc.register_template("slot", lambda **kw: DummyAgent(**kw))
        agent1 = self.cc.create_agent("slot")
        agent2 = self.cc.create_agent("slot")
        agent3 = self.cc.create_agent("slot")

        with self.assertRaises(RuntimeError):
            self.cc.create_agent("slot")  # should fail

        agent1.dispose()
        self.cc._unregister_agent(agent1)  # manually unregister to free slot

        new_agent = self.cc.create_agent("slot")  # should now succeed
        self.assertIn(new_agent, self.cc.get_active_agents())

    @unittest.expectedFailure
    def test_register_template_with_invalid_callable(self):
        with self.assertRaises(TypeError):
            self.cc.register_template("bad", "not a function")

    def test_agent_construction_failure(self):
        def bad_factory(**kw):
            raise ValueError("boom")

        self.cc.register_template("fail_build", bad_factory)
        with self.assertRaises(RuntimeError) as ctx:
            self.cc.create_agent("fail_build")
        self.assertIn("boom", str(ctx.exception))

    def test_template_without_kwargs_fails(self):
        def bad_template():
            return DummyAgent()

        self.cc.register_template("bad", bad_template)
        with self.assertRaises(RuntimeError):
            self.cc.create_agent("bad")

    def test_submit_task_with_exception(self):
        self.cc.register_template("explode", lambda **kw: DummyAgent(**kw))

        def task():
            raise RuntimeError("kaboom")

        self.cc.submit(task, template_name="explode")
        time.sleep(1.5)  # give thread a chance
        self.assertEqual(len(self.cc.get_active_agents()), 0)


    def test_submit_runs_and_disposes_agent(self):
        called = []

        def task():
            called.append("ran")

        self.cc.register_template("submit_test", lambda **kwargs: DummyAgent(**kwargs))
        self.cc.submit(task, template_name="submit_test")
        time.sleep(0.05)
        self.assertIn("ran", called)

    def test_dispose_unregisters_agents(self):
        self.cc.register_template("clean", lambda **kwargs: DummyAgent(**kwargs))
        agent = self.cc.create_agent("clean")
        agent_id = agent.factory_id
        self.cc.dispose()
        self.assertIsNone(self.cc.get_agent_by_id(agent_id))

    def test_register_after_dispose_raises(self):
        self.cc.dispose()
        with self.assertRaises(RuntimeError):
            self.cc.register_template("fail", lambda **kwargs: DummyAgent(**kwargs))

    def test_get_agent_by_id_returns_correct_agent(self):
        self.cc.register_template("lookup", lambda **kwargs: DummyAgent(**kwargs))
        agent = self.cc.create_agent("lookup")
        found = self.cc.get_agent_by_id(agent.factory_id)
        self.assertIs(agent, found)

    def test_create_agent_after_dispose_raises(self):
        self.cc.register_template("fail_late", lambda **kwargs: DummyAgent(**kwargs))
        self.cc.dispose()
        with self.assertRaises(RuntimeError):
            self.cc.create_agent("fail_late")


if __name__ == "__main__":
    unittest.main()
