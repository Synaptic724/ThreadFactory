import unittest
from unittest.mock import Mock
from typing import Callable, Union, Any, Optional
from thread_factory.agent.identity.types.agent import Agent
from thread_factory.agent.identity.types.general import General
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.utils.coordination.package import Pack


# Mock CommandCenter since it's a required dependency for Agent's __init__
class MockCommandCenter:
    """A mock CommandCenter to satisfy the constructor of the Agent class."""
    pass


class TestGeneralAgent(unittest.TestCase):
    """Unit tests for the General agent class."""

    def setUp(self):
        """Set up a new General agent instance before each test."""
        self.mock_command_center = MockCommandCenter()
        self.agent = General(
            command_center=self.mock_command_center,
            public_id="test-001",
            name="TestAgent",
            job="Testing",
            group="UnitTests"
        )
        self.unnamed_agent = General(command_center=self.mock_command_center)

    def tearDown(self):
        """Clean up the agent instance after each test."""
        self.agent.dispose()
        self.unnamed_agent.dispose()

    def test_initialization(self):
        """Test that the agent initializes with the correct attributes."""
        self.assertEqual(self.agent.public_id, "test-001")
        self.assertEqual(self.agent.name, "TestAgent")
        self.assertEqual(self.agent.job, "Testing")
        self.assertEqual(self.agent.group, "UnitTests")
        self.assertIsNone(self.agent.save_points)
        self.assertIsNone(self.agent.locations)
        self.assertIsNone(self.agent.data_transfer)
        self.assertIsInstance(self.agent, Agent)

    def test_get_name(self):
        """Test the get_name method with and without a name set."""
        self.assertEqual(self.agent.get_name(), "TestAgent")
        self.assertEqual(self.unnamed_agent.get_name(), "UnnamedAgent")

    def test_get_description(self):
        """Test that the description is formatted correctly."""
        expected_description = "Agent TestAgent with job 'Testing' in group 'UnitTests'"
        self.assertEqual(self.agent.get_description(), expected_description)

    def test_register_and_get_location(self):
        """Test registering a location and retrieving the locations dictionary."""
        self.assertIsNone(self.agent.locations)  # Verify lazy initialization

        def my_location():
            pass

        self.agent.register_location("home_base", my_location)
        self.assertIsInstance(self.agent.locations, ConcurrentDict)

        locations_dict = self.agent.get_locations_dict()
        self.assertIn("home_base", locations_dict)
        self.assertIsInstance(locations_dict["home_base"], Pack)

        # Verify it's a copy
        locations_dict["intruder"] = lambda: None
        self.assertNotIn("intruder", self.agent.locations)

    def test_register_and_get_save_point(self):
        """Test registering a save point and retrieving the save points dictionary."""
        self.assertIsNone(self.agent.save_points)  # Verify lazy initialization

        def my_save_point():
            pass

        self.agent.register_save_point("checkpoint_alpha", my_save_point)
        self.assertIsInstance(self.agent.save_points, ConcurrentDict)

        save_points_dict = self.agent.get_save_points_dict()
        self.assertIn("checkpoint_alpha", save_points_dict)
        self.assertIsInstance(save_points_dict["checkpoint_alpha"], Pack)

    def test_register_and_execute_data_transfer(self):
        """Test registering and executing a data transfer function."""
        self.assertIsNone(self.agent.data_transfer)  # Verify lazy initialization

        def get_status():
            return "All systems nominal"

        self.agent.register_data_transfer("system_status", get_status)
        self.assertIsInstance(self.agent.data_transfer, ConcurrentDict)

        result = self.agent.execute_transfer("system_status")
        self.assertEqual(result, "All systems nominal")

    def test_execute_nonexistent_data_transfer(self):
        """Test that executing a non-existent data transfer raises a KeyError."""
        with self.assertRaises(KeyError):
            self.agent.execute_transfer("nonexistent_transfer")

    def test_dispose(self):
        """Test that the dispose method cleans up resources correctly."""
        # Register something to ensure there's something to dispose
        self.agent.register_location("temp_loc", lambda: None)
        self.agent.register_save_point("temp_sp", lambda: None)
        self.agent.register_data_transfer("temp_dt", lambda: None)

        self.assertFalse(self.agent._disposed)
        self.assertIsNotNone(self.agent.locations)
        self.assertIsNotNone(self.agent.save_points)
        self.assertIsNotNone(self.agent.data_transfer)

        # First dispose call
        self.agent.dispose()

        self.assertTrue(self.agent._disposed)
        self.assertIsNone(self.agent.locations)
        self.assertIsNone(self.agent.save_points)
        self.assertIsNone(self.agent.data_transfer)

        # Test idempotency (calling dispose again should not raise an error)
        try:
            self.agent.dispose()
        except Exception as e:
            self.fail(f"dispose() raised {type(e).__name__} unexpectedly on second call")

    def test_get_empty_dictionaries(self):
        """Test that getting dicts before registration returns empty dicts."""
        self.assertEqual(len(self.agent.get_locations_dict()), 0)
        self.assertIsInstance(self.agent.get_locations_dict(), ConcurrentDict)

        self.assertEqual(len(self.agent.get_save_points_dict()), 0)
        self.assertIsInstance(self.agent.get_save_points_dict(), ConcurrentDict)

        self.assertEqual(len(self.agent.get_data_transfer_dict()), 0)
        self.assertIsInstance(self.agent.get_data_transfer_dict(), ConcurrentDict)


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
