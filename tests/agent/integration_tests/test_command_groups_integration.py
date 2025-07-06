import unittest
import time
import logging
from unittest.mock import MagicMock, patch

# Assuming the following imports are correct based on your project structure
from thread_factory.agent.command_center import CommandCenter
from thread_factory.agent.activity.base import BaseActivity, ActivityStatus
from thread_factory.agent.identity.types.agent import Agent

# Suppress all logging below CRITICAL for cleaner test output
logging.disable(logging.CRITICAL)


# --- Test Helper Classes ---

class MockAgent(Agent):
    """A mock Agent for testing that doesn't require a full CommandCenter."""

    def __init__(self, *args, **kwargs):
        if 'command_center' not in kwargs:
            kwargs['command_center'] = MagicMock()
        super().__init__(*args, **kwargs)
        self._is_alive = False

    def deploy(self):
        self._is_alive = True

    def is_alive(self):
        return self._is_alive

    def dispose(self):
        if not self._disposed:
            self._unregister()
            self._disposed = True


class MockActivity(BaseActivity):
    """A mock Activity for testing with controllable status."""

    def perform_activity(self):
        pass  # No-op for testing


# --- Test Suite ---

class TestCommandGroupOperations(unittest.TestCase):
    """
    Test suite for the internal operations of the CommandGroup class,
    including member management, bulk lifecycle control, and reporting.
    """

    def setUp(self):
        """Set up a CommandCenter and a dedicated CommandGroup for each test."""
        self.cc = CommandCenter(total_max_workers=20)
        self.cc.register_template("mock_agent", lambda **kwargs: MockAgent(**kwargs))
        self.cc.register_activity_template("mock_activity", MockActivity)

        self.group_name = "operations_group"
        self.cc.create_command_group(self.group_name, max_workers=10)
        self.group = self.cc.get_command_group(self.group_name)

    def tearDown(self):
        """Clean up the CommandCenter instance."""
        self.cc.dispose()

    # --- Member Management Tests ---

    def test_add_agent_to_group(self):
        """Verify an agent can be created and added directly to a group."""
        self.assertEqual(len(self.group.list_agents()), 0)
        agent = self.group.add_agent(template_name="mock_agent", target=lambda: None)
        self.assertIsNotNone(agent)
        self.assertIn(agent.factory_id, self.group.list_agents())
        self.assertEqual(self.group._worker_count, 1)

    def test_add_agent_respects_group_worker_limit(self):
        """Ensure add_agent fails if the group is full."""
        self.group._max_workers = 1
        self.group.add_agent(template_name="mock_agent", target=lambda: None)

        # Adding a second agent should fail
        agent2 = self.group.add_agent(template_name="mock_agent", target=lambda: None)
        self.assertIsNone(agent2)
        self.assertEqual(len(self.group.list_agents()), 1)

    def test_add_and_remove_activity(self):
        """Verify activities can be added and removed from a group."""
        activity = self.group.add_activity(name="mock_activity")
        self.assertIn(activity.id, self.group.list_activities())

        was_removed = self.group.remove_activity(activity.id, dispose=False)
        self.assertTrue(was_removed)
        self.assertNotIn(activity.id, self.group.list_activities())

    def test_remove_agent_decrements_worker_count(self):
        """Check that removing an agent correctly decrements the worker count."""
        agent = self.group.add_agent(template_name="mock_agent", target=lambda: None)
        self.assertEqual(self.group._worker_count, 1)

        self.group.remove_agent(agent.factory_id, dispose=False)
        self.assertEqual(self.group._worker_count, 0)
        self.assertNotIn(agent.factory_id, self.group.list_agents())

    # --- Bulk Lifecycle Control Tests ---

    def test_start_all_activities(self):
        """Test starting all PENDING activities in a group."""
        act1 = self.group.add_activity("mock_activity")
        act2 = self.group.add_activity("mock_activity")
        act3 = self.group.add_activity("mock_activity")
        act3.set_status("RUNNING")  # This one should not be started again

        self.group.start_all_activities()

        self.assertEqual(act1.get_status(), ActivityStatus.RUNNING)
        self.assertEqual(act2.get_status(), ActivityStatus.RUNNING)
        self.assertEqual(act3.get_status(), ActivityStatus.RUNNING)  # Still running

    def test_deploy_all_agents(self):
        """Test deploying all agents in a group."""
        agent1 = self.group.add_agent("mock_agent", target=lambda: None)
        agent2 = self.group.add_agent("mock_agent", target=lambda: None)

        agent1.deploy = MagicMock()
        agent2.deploy = MagicMock()

        self.group.deploy_all_agents()

        agent1.deploy.assert_called_once()
        agent2.deploy.assert_called_once()

    def test_pause_all_activities(self):
        """Test pausing all RUNNING activities in a group."""
        act1 = self.group.add_activity("mock_activity")
        act2 = self.group.add_activity("mock_activity")
        act1.start()
        act2.start()

        self.group.pause_all_activities()

        self.assertEqual(act1.get_status(), ActivityStatus.PAUSED)
        self.assertEqual(act2.get_status(), ActivityStatus.PAUSED)

    def test_cancel_all_activities(self):
        """Test cancelling all non-terminal activities."""
        act_pending = self.group.add_activity("mock_activity")
        act_running = self.group.add_activity("mock_activity")
        act_completed = self.group.add_activity("mock_activity")
        act_running.start()
        act_completed.set_status("COMPLETED")

        self.group.cancel_all_activities()

        self.assertEqual(act_pending.get_status(), ActivityStatus.CANCELLED)
        self.assertEqual(act_running.get_status(), ActivityStatus.CANCELLED)
        self.assertEqual(act_completed.get_status(), ActivityStatus.COMPLETED)  # Should not change

    def test_shutdown_all_members_disposes_all(self):
        """Verify shutdown_all_members disposes all agents and activities."""
        agent = self.group.add_agent("mock_agent", target=lambda: None)
        activity = self.group.add_activity("mock_activity")

        agent.dispose = MagicMock()
        activity.dispose = MagicMock()

        self.group.shutdown_all_members(dispose=True)

        agent.dispose.assert_called_once()
        activity.dispose.assert_called_once()
        self.assertEqual(len(self.group.list_agents()), 0)
        self.assertEqual(len(self.group.list_activities()), 0)

    # --- Introspection and Reporting Tests ---

    def test_get_status_summary_counts_correctly(self):
        """Test the activity status summary report."""
        self.group.add_activity("mock_activity").set_status("RUNNING")
        self.group.add_activity("mock_activity").set_status("RUNNING")
        self.group.add_activity("mock_activity").set_status("PENDING")
        self.group.add_activity("mock_activity").set_status("COMPLETED")

        summary = self.group.get_status_summary()

        self.assertEqual(summary['RUNNING'], 2)
        self.assertEqual(summary['PENDING'], 1)
        self.assertEqual(summary['COMPLETED'], 1)
        self.assertEqual(summary['FAILED'], 0)

    def test_get_worker_utilization(self):
        """Test the worker utilization report."""
        self.group.add_agent("mock_agent", target=lambda: None)
        self.group.add_agent("mock_agent", target=lambda: None)
        self.group.add_agent("mock_agent", target=lambda: None)
        # 3 active agents out of 10 max workers

        report = self.group.get_worker_utilization()

        self.assertEqual(report['active'], 3)
        self.assertEqual(report['max'], 10)
        self.assertEqual(report['utilization'], 30.0)

    def test_list_agents_and_activities(self):
        """Test that list methods return correct IDs."""
        agent1 = self.group.add_agent("mock_agent", target=lambda: None)
        agent2 = self.group.add_agent("mock_agent", target=lambda: None)
        act1 = self.group.add_activity("mock_activity")
        act2 = self.group.add_activity("mock_activity")

        agent_ids = self.group.list_agents()
        activity_ids = self.group.list_activities()

        self.assertCountEqual(agent_ids, [agent1.factory_id, agent2.factory_id])
        self.assertCountEqual(activity_ids, [act1.id, act2.id])


if __name__ == '__main__':
    unittest.main(verbosity=2)
