import unittest
import logging
from unittest.mock import MagicMock, patch, ANY
from typing import Optional

# Assuming the classes are in a reachable path.
# These imports reflect the final architecture.
from thread_factory.agent.command_center import CommandCenter, CommandGroup
from thread_factory.agent.activity.base import BaseActivity
from thread_factory.agent.identity.types.agent import Agent
from thread_factory.synchronization import SignalController

# Suppress logging for cleaner test output
logging.disable(logging.CRITICAL)


class TestCommandGroupManagement(unittest.TestCase):
    """Tests the CommandCenter's ability to create and manage CommandGroups."""

    def setUp(self):
        self.agent_builder_patcher = patch('thread_factory.agent.identity.agent_builder.AgentBuilder')
        self.activity_builder_patcher = patch('thread_factory.agent.activity.builder.ActivityBuilder')

        self.mock_agent_builder_class = self.agent_builder_patcher.start()
        self.mock_activity_builder_class = self.activity_builder_patcher.start()

        self.mock_agent_builder_instance = self.mock_agent_builder_class.return_value
        self.mock_activity_builder_instance = self.mock_activity_builder_class.return_value

        self.addCleanup(self.agent_builder_patcher.stop)
        self.addCleanup(self.activity_builder_patcher.stop)

        self.cc = CommandCenter(total_max_workers=10)
        self.cc.create_command_group("etl_group", max_workers=5)

    def tearDown(self):
        if self.cc and not self.cc._disposed:
            self.cc.dispose()

    def test_01_initialization_creates_default_group(self):
        """Test that a 'default' CommandGroup is created on initialization."""
        self.assertIn("default", self.cc._command_groups)
        default_group = self.cc.get_command_group("default")
        self.assertIsInstance(default_group, CommandGroup)
        self.assertEqual(default_group.name, "default")

    def test_02_create_custom_command_group_succeeds(self):
        """Test creating a new, custom command group."""
        self.cc.create_command_group("data_team", max_workers=5)
        self.assertIn("data_team", self.cc._command_groups)
        data_team_group = self.cc.get_command_group("data_team")
        self.assertEqual(data_team_group.name, "data_team")
        self.assertEqual(data_team_group._max_workers, 5)

    def test_03_create_duplicate_group_name_raises_error(self):
        """Test that creating a group with a duplicate name raises a ValueError."""
        with self.assertRaises(ValueError):
            self.cc.create_command_group("default", max_workers=2)

    def test_05_get_command_group_retrieves_correctly(self):
        """Test retrieving a command group by its name."""
        group = self.cc.get_command_group("default")
        self.assertIsNotNone(group)
        self.assertEqual(group.name, "default")
        with self.assertRaises(KeyError):
            self.cc.get_command_group("non_existent_group")

    def test_06_dispose_cascades_to_all_groups(self):
        """Test that disposing the CommandCenter also disposes its CommandGroups."""
        mock_group = MagicMock(spec=CommandGroup)
        self.cc._command_groups["mock_group"] = mock_group
        self.cc.dispose()
        mock_group.dispose.assert_called_once()


class TestAgentManagementInGroups(unittest.TestCase):
    """Tests creating and managing agents within specific CommandGroups."""

    def setUp(self):
        with patch('thread_factory.agent.identity.agent_builder.AgentBuilder'), \
                patch('thread_factory.agent.activity.builder.ActivityBuilder'):
            self.cc = CommandCenter(total_max_workers=10)
            self.cc.create_command_group("team_a", max_workers=4)

    def tearDown(self):
        if self.cc and not self.cc._disposed:
            self.cc.dispose()

    @patch('thread_factory.agent.identity.agent_builder.AgentBuilder.create_agent')
    def test_07_create_agent_in_default_group(self, mock_create_agent):
        """Test creating an agent successfully in the default group."""
        mock_agent = MagicMock(spec=Agent)
        mock_agent.factory_id = "agent_1"
        mock_create_agent.return_value = mock_agent

        agent = self.cc.create_agent(command_group_name="default", target=lambda: None)

        self.assertIsNotNone(agent)
        default_group = self.cc.get_command_group("default")
        self.assertIn(agent.factory_id, default_group._active_agents)
        self.assertEqual(default_group._worker_count, 1)
        self.assertEqual(agent._group_name, "default")

    @patch('thread_factory.agent.identity.agent_builder.AgentBuilder.create_agent')
    def test_08_create_agent_in_custom_group(self, mock_create_agent):
        """Test creating an agent successfully in a custom group."""
        mock_agent = MagicMock(spec=Agent)
        mock_agent.factory_id = "agent_2"
        mock_create_agent.return_value = mock_agent

        agent = self.cc.create_agent(command_group_name="team_a", target=lambda: None)

        team_a_group = self.cc.get_command_group("team_a")
        self.assertIn(agent.factory_id, team_a_group._active_agents)
        self.assertEqual(team_a_group._worker_count, 1)
        self.assertEqual(agent._group_name, "team_a")

    @patch('thread_factory.agent.identity.agent_builder.AgentBuilder.create_agent')
    def test_09_group_worker_limit_is_enforced(self, mock_create_agent):
        """Test that a group's local max_workers limit is enforced."""
        mock_create_agent.return_value = MagicMock(spec=Agent, factory_id="temp_id")

        team_a = self.cc.get_command_group("team_a")
        team_a._max_workers = 1

        self.cc.create_agent(command_group_name="team_a", target=lambda: None)

        with self.assertRaises(RuntimeError):
            self.cc.create_agent(command_group_name="team_a", target=lambda: None)

    @patch('thread_factory.agent.identity.agent_builder.AgentBuilder.create_agent')
    def test_10_global_worker_limit_is_enforced(self, mock_create_agent):
        """Test that the CommandCenter's global worker limit is enforced."""
        mock_create_agent.return_value = MagicMock(spec=Agent, factory_id="temp_id")
        with self.assertRaises(ValueError):
            self.cc.adjust_global_limit(1)


    @patch('thread_factory.agent.identity.agent_builder.AgentBuilder.create_agent')
    def test_11_get_command_group_of_agent(self, mock_create_agent):
        """Test finding which group an agent belongs to."""
        mock_agent = MagicMock(spec=Agent)
        mock_agent.factory_id = "agent_3"
        mock_create_agent.return_value = mock_agent

        agent = self.cc.create_agent(command_group_name="team_a", target=lambda: None)

        found_group = self.cc.get_command_group_of_agent(agent.factory_id)
        self.assertIsNotNone(found_group)
        self.assertEqual(found_group.name, "team_a")

    @patch('thread_factory.agent.identity.agent_builder.AgentBuilder.create_agent')
    def test_12_unregister_agent_decrements_count(self, mock_create_agent):
        """Test that _unregister_agent correctly removes an agent and decrements the group count."""
        mock_agent = MagicMock(spec=Agent)
        mock_agent.factory_id = "agent_4"
        mock_create_agent.return_value = mock_agent

        agent = self.cc.create_agent(command_group_name="team_a", target=lambda: None)
        team_a_group = self.cc.get_command_group("team_a")
        self.assertEqual(team_a_group._worker_count, 1)

        self.cc._unregister_agent(agent)

        self.assertEqual(team_a_group._worker_count, 0)
        self.assertNotIn(agent.factory_id, team_a_group._active_agents)

    def test_13_adjust_global_limit_increase(self):
        """Test increasing the global worker limit."""
        initial_limit = self.cc._total_max_workers
        self.cc.adjust_global_limit(initial_limit + 5)
        self.assertEqual(self.cc._total_max_workers, initial_limit + 5)

        with self.assertRaises(ValueError):
            self.cc.adjust_global_limit(initial_limit)


class TestActivityManagementAndDeployment(unittest.TestCase):
    """Tests creating, managing, and deploying activities within groups."""

    def setUp(self):
        with patch('thread_factory.agent.identity.agent_builder.AgentBuilder') as self.mock_agent_builder, \
                patch('thread_factory.agent.activity.builder.ActivityBuilder') as self.mock_activity_builder:
            self.mock_activity_builder_instance = self.mock_activity_builder
            self.cc = CommandCenter(total_max_workers=10)
            self.cc.create_command_group("etl_group", max_workers=5)

    def tearDown(self):
        if self.cc and not self.cc._disposed:
            self.cc.dispose()


    def test_20_find_agent_by_id_searches_all_groups(self):
        """Test that find_agent_by_id can find an agent without specifying the group."""
        with patch('thread_factory.agent.identity.agent_builder.AgentBuilder.create_agent') as mock_create:
            mock_agent = MagicMock(spec=Agent)
            mock_agent.factory_id = "universal_agent"
            mock_create.return_value = mock_agent

            agent = self.cc.create_agent(command_group_name="etl_group", target=lambda: None)

            # Find it without knowing its group by searching the default group first
            found_agent = self.cc.find_agent_by_id("universal_agent")

            self.assertIsNotNone(found_agent)
            self.assertIs(agent, found_agent)


if __name__ == '__main__':
    unittest.main(verbosity=2)
