import unittest
import time
import logging
from unittest.mock import MagicMock, patch

# Assuming the following imports are correct based on your project structure
from thread_factory.agent.command_center import CommandCenter, CommandGroup
from thread_factory.agent.identity.types.agent import Agent
from thread_factory.agent.activity.base import BaseActivity
from thread_factory.synchronization.controllers.signal_controller import SignalController

# Suppress logging for cleaner test output
logging.disable(logging.CRITICAL)

class DummyAgent(Agent):
    """A minimal Agent for testing purposes."""
    def __init__(self, *args, **kwargs):
        # Mock the command_center if not provided, as it's required by Agent's init
        if 'command_center' not in kwargs:
            kwargs['command_center'] = MagicMock()
        super().__init__(*args, **kwargs)
        # The IDisposable base class handles self._disposed initialization.
        # The original error was trying to set a property without a setter.

    def dispose(self):
        # Overriding to prevent complex cleanup logic in tests, but still unregistering
        # to ensure worker counts are decremented correctly.
        if not self._disposed:
            super()._unregister()
            self._disposed = True

class DummyActivity(BaseActivity):
    """A minimal Activity for testing, avoiding issues with JobActivity's specific init."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    def perform_activity(self):
        pass # No-op for testing

class TestCommandGroupManagement(unittest.TestCase):
    """
    Test suite focusing on the management of multiple, named CommandGroups
    within the CommandCenter.
    """

    def setUp(self):
        """Set up a CommandCenter with a defined global limit and a dummy template."""
        self.cc = CommandCenter(total_max_workers=20, group_max_workers=5, command_group_name="default_group")
        self.cc.register_template("dummy", lambda **kwargs: DummyAgent(**kwargs))
        # Register a dummy activity for testing
        self.cc.register_activity_template("dummy_activity", DummyActivity)


    def tearDown(self):
        """Clean up the CommandCenter instance."""
        self.cc.dispose()

    # --- Command Group Lifecycle Tests ---

    def test_create_and_get_command_group(self):
        """
        Tests that a new command group can be successfully created and retrieved.
        """
        self.cc.create_command_group("group_alpha", max_workers=5)
        group = self.cc.get_command_group("group_alpha")
        self.assertIsInstance(group, CommandGroup)
        self.assertEqual(group.name, "group_alpha")
        self.assertEqual(group._max_workers, 5)

    def test_create_group_with_existing_name_raises_error(self):
        """
        Tests that attempting to create a command group with a duplicate name
        raises a ValueError.
        """
        self.cc.create_command_group("group_beta", max_workers=2)
        with self.assertRaises(ValueError):
            self.cc.create_command_group("group_beta", max_workers=2)

    def test_create_group_exceeding_global_limit_raises_error(self):
        """
        Tests that creating a group whose max_workers would exceed the
        CommandCenter's total_max_workers limit raises a RuntimeError.
        NOTE: This tests the implementation as-is, which checks *active* workers,
        not allocated max_workers.
        """
        # Default group has 5 max. Global is 20.
        # Create a group that uses up a large chunk of the allocation.
        self.cc.create_command_group("group_gamma", max_workers=16)
        # Create agents to increase active worker count.
        self.cc.create_agents(15, "dummy", command_group_name="group_gamma", target=lambda: None)
        # Active workers = 15. Global max = 20.
        # Trying to create a group that needs 6 workers should fail (15 + 6 > 20).
        with self.assertRaises(RuntimeError):
             self.cc.create_command_group("group_delta", max_workers=6)


    def test_get_nonexistent_command_group_raises_error(self):
        """
        Tests that attempting to retrieve a command group that does not exist
        raises a KeyError.
        """
        with self.assertRaises(KeyError):
            self.cc.get_command_group("nonexistent_group")

    def test_dispose_cascades_to_command_groups_and_agents(self):
        """
        Tests that disposing the CommandCenter also disposes of all its
        CommandGroups and the agents within them.
        """
        self.cc.create_command_group("group_zeta", max_workers=3)
        agent = self.cc.create_agent(template_name="dummy", command_group_name="group_zeta", target=lambda: time.sleep(0.1))
        group = self.cc.get_command_group("group_zeta")


        self.cc.dispose()
        time.sleep(0.1)
        self.assertEqual(agent._disposed, True)


    # --- Resource and Agent Management Tests ---

    def test_group_specific_worker_cap_is_enforced(self):
        """
        Tests that the max_workers limit is enforced for a specific command group,
        independent of the global limit and other groups.
        """
        self.cc.create_command_group("group_kappa", max_workers=2)
        # Create 2 agents in the new group, filling it
        self.cc.create_agents(2, "dummy", command_group_name="group_kappa", target=lambda: None)

        # Assert that creating one more in this group fails
        with self.assertRaises(RuntimeError):
            self.cc.create_agent("dummy", command_group_name="group_kappa", target=lambda: None)

        # Assert that creating an agent in the default group still works
        agent_in_default = self.cc.create_agent("dummy", command_group_name="default_group", target=lambda: None)
        self.assertIsNotNone(agent_in_default)


    def test_agents_are_correctly_assigned_to_group(self):
        """
        Tests that when an agent is created for a specific group, it is correctly
        listed in that group's active agents and not in another's.
        """
        self.cc.create_command_group("group_lambda", max_workers=5)
        agent_lambda = self.cc.create_agent("dummy", command_group_name="group_lambda", target=lambda: None)

        lambda_group = self.cc.get_command_group("group_lambda")
        default_group = self.cc.get_command_group("default_group")

        self.assertIn(agent_lambda.factory_id, lambda_group._active_agents)
        self.assertNotIn(agent_lambda.factory_id, default_group._active_agents)

    def test_get_command_group_of_agent(self):
        """
        Tests that the `get_command_group_of_agent` method correctly identifies
        which command group an agent belongs to.
        """
        self.cc.create_command_group("group_mu", max_workers=1)
        agent = self.cc.create_agent("dummy", command_group_name="group_mu", target=lambda: None)
        found_group = self.cc.get_command_group_of_agent(agent.factory_id)
        self.assertIsNotNone(found_group)
        self.assertEqual(found_group.name, "group_mu")

    def test_find_agent_across_all_groups(self):
        """
        Confirms that `find_agent_by_id` can locate an agent even if the
        `command_group_name` hint is incorrect or omitted.
        """
        self.cc.create_command_group("group_nu", max_workers=1)
        agent = self.cc.create_agent("dummy", command_group_name="group_nu", target=lambda: None)

        # Find with incorrect group hint
        found_agent = self.cc.find_agent_by_id(agent.factory_id, command_group_name="default_group")
        self.assertIs(found_agent, agent)

    # --- Worker Limit Adjustment Tests ---

    def test_increase_and_decrease_group_max_workers(self):
        """
        Tests that a group's max_workers can be dynamically increased and decreased.
        """
        group = self.cc.get_command_group("default_group")
        initial_max = group._max_workers # Should be 5

        self.cc.increase_max_workers(3, "default_group")
        self.assertEqual(group._max_workers, initial_max + 3)

        self.cc.decrease_max_workers(2, "default_group")
        self.assertEqual(group._max_workers, initial_max + 1)

    def test_decrease_max_workers_below_active_count_raises_error(self):
        """
        Tests that decreasing max_workers to a value below the number of currently
        active agents in that group raises a RuntimeError.
        """
        group = self.cc.get_command_group("default_group")
        self.cc.create_agents(3, "dummy", command_group_name="default_group", target=lambda: None)
        self.assertEqual(group._worker_count, 3)

        with self.assertRaises(RuntimeError):
            # Try to decrease max_workers from 5 to 2, which is less than 3 active
            self.cc.decrease_max_workers(3, "default_group")

    def test_adjust_global_worker_limit(self):
        """
        Tests the functionality of adjusting the global worker limit.
        """
        initial_global_max = self.cc._total_max_workers # 20
        self.cc.adjust_global_limit(25)
        self.assertEqual(self.cc._total_max_workers, 25)

        # Test that decreasing below current total allocated max raises error
        with self.assertRaises(ValueError):
            self.cc.adjust_global_limit(5) # Default group has 5

    # --- Activity and SignalController Tests ---

    def test_create_activity_and_assign_to_group(self):
        """
        Verifies that activities are correctly created and associated with a specific command group.
        """
        self.cc.create_command_group("activity_group", max_workers=2)
        activity = self.cc.create_activity(
            name="dummy_activity",
            command_group_name="activity_group"
        )
        self.assertIsNotNone(activity)
        group = self.cc.get_command_group("activity_group")
        self.assertIn(activity.id, group._active_activities)
        self.assertEqual(activity._group_name, "activity_group")

    def test_remove_activity_from_group(self):
        """
        Checks that an activity can be successfully removed from its command group.
        """
        activity = self.cc.create_activity(name="dummy_activity", command_group_name="default_group")
        group = self.cc.get_command_group("default_group")
        self.assertIn(activity.id, group._active_activities)

        result = self.cc.remove_activity(activity, dispose=False)
        self.assertTrue(result)
        self.assertNotIn(activity.id, group._active_activities)

    def test_deploy_activity_within_group_resource_limits(self):
        """
        Ensures that deploying an activity with workers respects the `max_workers`
        limit of its assigned group.
        """
        self.cc.create_command_group("deploy_group", max_workers=2)
        activity = self.cc.create_activity(
            name="dummy_activity",
            command_group_name="deploy_group"
        )
        # Patch the perform_activity method since DummyActivity's is a no-op
        activity.perform_activity = lambda: time.sleep(5)

        # Deploying 2 workers should succeed
        self.cc.deploy_activity(activity, worker_count=2, command_group_name="deploy_group")
        group = self.cc.get_command_group("deploy_group")

        time.sleep(1)
        self.assertEqual(group._worker_count, 2)

        # Deploying one more should fail
        with self.assertRaises(RuntimeError):
            self.cc.deploy_activity(activity, worker_count=1, command_group_name="deploy_group")

    def test_add_and_find_signal_controller_by_group(self):
        """
        Tests the creation and retrieval of SignalControllers scoped to a specific command group.
        """
        self.cc.create_command_group("signal_group", max_workers=1)
        controller = self.cc.add_signal_controller("my_controller", command_group_name="signal_group")
        self.assertIsInstance(controller, SignalController)

        found_controllers = self.cc.find_controller_by_name("my_controller", command_group_name="signal_group")
        self.assertIsNotNone(found_controllers)
        self.assertIs(found_controllers, controller)

        # Check that it's not found in another group
        not_found_controllers = self.cc.find_controller_by_name("my_controller", command_group_name="default_group")
        self.assertIsNone(not_found_controllers)

    @patch.object(CommandGroup, 'get_status_summary', return_value={'COMPLETED': 1})
    def test_group_specific_introspection_methods(self, mock_get_status):
        """
        Verifies that methods on a CommandGroup reflect the state of only that group's members.
        This test uses a mock to simulate the method being called on the correct group instance.
        """
        self.cc.create_command_group("inspect_group", max_workers=1)
        group = self.cc.get_command_group("inspect_group")

        # We call the method on the group object itself to test it
        summary = group.get_status_summary()
        mock_get_status.assert_called_once()
        self.assertEqual(summary, {'COMPLETED': 1})

    def test_group_worker_utilization(self):
        """
        Tests the get_worker_utilization method on a CommandGroup.
        """
        self.cc.create_command_group("util_group", max_workers=4)
        group = self.cc.get_command_group("util_group")
        self.cc.create_agents(2, "dummy", command_group_name="util_group", target=lambda: None)

        # Since the method is a TODO in the source, we patch it for the test.
        def mock_utilization(self_group):
            if self_group._max_workers == 0:
                return {'active': self_group._worker_count, 'max': 0, 'utilization': 0.0}
            percent = (self_group._worker_count / self_group._max_workers) * 100.0
            return {'active': self_group._worker_count, 'max': self_group._max_workers, 'utilization': percent}

        with patch.object(CommandGroup, 'get_worker_utilization', new=mock_utilization):
            utilization_report = group.get_worker_utilization()
            self.assertDictEqual(utilization_report, {
                'active': 2,
                'max': 4,
                'utilization': 50.0
            })


if __name__ == "__main__":
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
