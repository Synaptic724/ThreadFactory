import unittest
from unittest.mock import Mock
from thread_factory.agent.identity.agent_builder import AgentBuilder
from thread_factory.agent.identity.types.agent import Agent
from thread_factory.agent.identity.types.general import General
from thread_factory.utils.coordination.package import Pack


class TestAgentBuilder(unittest.TestCase):

    def setUp(self):
        self.builder = AgentBuilder()
        self.mock_cc = Mock()

    def tearDown(self):
        self.builder.dispose()

    def test_default_template_exists(self):
        self.assertTrue(self.builder.has_template("default"))

    def test_list_templates_contains_default(self):
        self.assertIn("default", self.builder.list_templates())

    def test_create_agent_from_default(self):
        agent = self.builder.create_agent("default", command_center=self.mock_cc)
        self.assertIsInstance(agent, Agent)
        agent.dispose()

    def test_create_agent_runs_callable(self):
        result = []

        def factory(cc):
            result.append(cc)
            return General(command_center=cc)

        self.builder.register_template("test", Pack(factory))
        agent = self.builder.create_agent("test", self.mock_cc)
        self.assertEqual(result[0], self.mock_cc)
        agent.dispose()

    def test_register_duplicate_name_raises(self):
        with self.assertRaises(ValueError):
            self.builder.register_template("default", Pack(lambda x: General(x)))

    def test_register_template_invalid_name(self):
        with self.assertRaises(ValueError):
            self.builder.register_template("", Pack(lambda x: General(x)))

    def test_register_template_invalid_callable(self):
        with self.assertRaises(ValueError):
            self.builder.register_template("x", "not_callable")

    def test_unregister_template_success(self):
        self.builder.register_template("alpha", Pack(lambda x: General(x)))
        removed = self.builder.unregister_template("alpha")
        self.assertTrue(removed)

    def test_unregister_template_missing(self):
        self.assertFalse(self.builder.unregister_template("zzz"))

    def test_has_template_false_for_missing(self):
        self.assertFalse(self.builder.has_template("nope"))

    def test_list_templates_empty_after_dispose(self):
        self.builder.dispose()
        self.assertEqual(self.builder._registry, None)

    def test_dispose_idempotent(self):
        self.builder.dispose()
        self.builder.dispose()  # Should not crash

    def test_create_agent_missing_template(self):
        with self.assertRaises(KeyError):
            self.builder.create_agent("unknown", command_center=self.mock_cc)

    def test_create_agent_returns_thread_and_agent(self):
        agent = self.builder.create_agent("default", command_center=self.mock_cc)
        self.assertTrue(isinstance(agent, Agent))
        self.assertTrue(agent.is_alive() is False or isinstance(agent.name, str))
        agent.dispose()

    def test_create_agent_with_arg_override(self):
        self.builder.register_template("greet", Pack(lambda command_center, public_name: General(command_center, public_name=public_name)))
        agent = self.builder.create_agent("greet", command_center=self.mock_cc, public_name="Override")
        self.assertEqual(agent.get_name(), "Override")
        agent.dispose()

    def test_template_remains_unchanged_after_override(self):
        def factory(command_center, public_name="Base"):
            return General(command_center, public_name=public_name)

        self.builder.register_template("preserve_test", Pack(factory))
        _ = self.builder.create_agent("preserve_test", command_center=self.mock_cc, public_name="Override")
        # Create again and verify the original default remains
        agent2 = self.builder.create_agent("preserve_test", command_center=self.mock_cc)
        self.assertEqual(agent2.get_name(), "Base")
        agent2.dispose()

    def test_create_agent_accepts_valid_agent_thread(self):
        class MockAgent(Agent):
            def __init__(self, **kwargs): super().__init__(command_center=kwargs["command_center"])

        self.builder.register_template("mock_thread", Pack(lambda **kwargs: MockAgent(**kwargs)))
        agent = self.builder.create_agent("mock_thread", command_center=self.mock_cc)
        self.assertIsInstance(agent, Agent)
        agent.dispose()

    def test_register_after_dispose_silent_fail(self):
        self.builder.dispose()
        try:
            self.builder.register_template("ghost", Pack(lambda **kwargs: General(**kwargs)))
        except TypeError:
            pass  # acceptable, we allow hard crash here
        except Exception as e:
            self.fail(f"Should not crash with unexpected exception: {e}")

    def test_frozen_pack_raises_on_mutation(self):
        def factory(cc, role="Base"): return General(cc, job_title=role)

        pack = Pack(factory, role="Unchangeable")
        pack.freeze()
        self.builder.register_template("frozen", pack)
        with self.assertRaises(RuntimeError):
            # simulate override attempt by curry, which does not mutate but just to simulate locking
            frozen_pack = pack.bind(role="Hack")  # Should raise

    def test_override_with_invalid_kwargs_fails_cleanly(self):
        def factory(cc): return General(cc)

        self.builder.register_template("bad_override", Pack(factory))
        with self.assertRaises(TypeError):
            self.builder.create_agent("bad_override", command_center=self.mock_cc, not_a_real_arg="wat")

    def test_register_after_dispose_does_nothing(self):
        self.builder.dispose()
        with self.assertRaises(TypeError):
            self.builder.register_template("ghost", Pack(lambda **kwargs: General(**kwargs)))

    def test_registry_isolated_between_instances(self):
        other = AgentBuilder()
        other.register_template("isolated", Pack(lambda x: General(x)))
        self.assertFalse(self.builder.has_template("isolated"))
        other.dispose()

    def test_register_template_stores_pack(self):
        self.builder.register_template("check", Pack(lambda x: General(x)))
        self.assertIn("check", self.builder._registry)

    def test_create_agent_type_check_fails(self):
        class BadObject:
            def __call__(self): return "not an agent"
        self.builder.register_template("bad", Pack(lambda x: "not an agent"))
        with self.assertRaises(TypeError):
            self.builder.create_agent("bad", command_center=self.mock_cc)

    def test_override_args_functionality(self):
        def factory(command_center, public_name=None):
            return General(command_center, public_name=public_name)

        self.builder.register_template("override_test", Pack(factory, public_name="Base"))
        agent = self.builder.create_agent("override_test", command_center=self.mock_cc, public_name="New")
        self.assertEqual(agent.get_name(), "New")
        agent.dispose()


if __name__ == "__main__":
    unittest.main()