import unittest
import logging
from unittest.mock import MagicMock, patch
from thread_factory.agent.command_center import CommandCenter
from thread_factory.synchronization.controllers.signal_controller import SignalController

# Suppress logging output during tests for a cleaner console
logging.disable(logging.CRITICAL)


class TestCommandCenterSignalManagement(unittest.TestCase):
    """
    Test suite for managing internal SignalControllers within the CommandCenter.
    """

    def setUp(self):
        """
        Set up a new CommandCenter instance before each test.
        """
        # We patch the AgentBuilder to avoid dependency issues during CC initialization
        with patch('thread_factory.agent.identity.agent_builder.AgentBuilder'):
            self.cc = CommandCenter()

    def tearDown(self):
        """
        Clean up by disposing of the CommandCenter instance after each test.
        """
        if self.cc and not self.cc._disposed:
            self.cc.dispose()

    def test_add_signal_controller_creates_new(self):
        """
        Test that add_signal_controller creates a new controller if none is provided.
        """
        controller_name = "test_bus"
        self.assertEqual(len(self.cc.list_signal_controllers()), 0)

        new_controller = self.cc.add_signal_controller(controller_name)

        self.assertIsNotNone(new_controller)
        self.assertIsInstance(new_controller, SignalController)
        self.assertIn(controller_name, self.cc.list_signal_controllers())
        self.assertEqual(len(self.cc.list_signal_controllers()), 1)

    def test_add_existing_signal_controller(self):
        """
        Test that an existing SignalController instance can be added.
        """
        controller_name = "pre_existing_bus"
        existing_controller = SignalController()

        added_controller = self.cc.add_signal_controller(controller_name, controller=existing_controller)

        self.assertIs(added_controller, existing_controller)
        self.assertIn(controller_name, self.cc.list_signal_controllers())

    def test_add_duplicate_name_raises_error(self):
        """
        Test that adding a SignalController with a duplicate name raises a ValueError.
        """
        controller_name = "duplicate_bus"
        self.cc.add_signal_controller(controller_name)

        with self.assertRaises(ValueError):
            self.cc.add_signal_controller(controller_name)

    def test_get_signal_controller(self):
        """
        Test retrieving a SignalController by its name.
        """
        controller_name = "retrieval_bus"
        # Test getting a non-existent controller
        self.assertIsNone(self.cc.get_signal_controller(controller_name))

        # Add a controller and then get it
        added_controller = self.cc.add_signal_controller(controller_name)
        retrieved_controller = self.cc.get_signal_controller(controller_name)

        self.assertIsNotNone(retrieved_controller)
        self.assertIs(added_controller, retrieved_controller)

    def test_list_signal_controllers(self):
        """
        Test that list_signal_controllers returns the correct names.
        """
        self.assertEqual(self.cc.list_signal_controllers(), [])

        names = ["bus_alpha", "bus_beta", "bus_gamma"]
        for name in names:
            self.cc.add_signal_controller(name)

        listed_names = self.cc.list_signal_controllers()
        self.assertCountEqual(listed_names, names)

    def test_remove_signal_controller_with_dispose(self):
        """
        Test removing a controller and ensuring its dispose method is called by default.
        """
        controller_name = "disposable_bus"
        mock_controller = MagicMock(spec=SignalController)

        self.cc.add_signal_controller(controller_name, controller=mock_controller)
        self.assertIn(controller_name, self.cc.list_signal_controllers())

        was_removed = self.cc.remove_signal_controller(controller_name)

        self.assertTrue(was_removed)
        self.assertNotIn(controller_name, self.cc.list_signal_controllers())
        mock_controller.dispose.assert_called_once()

    def test_remove_signal_controller_without_dispose(self):
        """
        Test removing a controller with dispose=False.
        """
        controller_name = "non_disposable_bus"
        mock_controller = MagicMock(spec=SignalController)

        self.cc.add_signal_controller(controller_name, controller=mock_controller)

        was_removed = self.cc.remove_signal_controller(controller_name, dispose=False)

        self.assertTrue(was_removed)
        self.assertNotIn(controller_name, self.cc.list_signal_controllers())
        mock_controller.dispose.assert_not_called()

    def test_remove_non_existent_controller(self):
        """
        Test that attempting to remove a non-existent controller returns False.
        """
        was_removed = self.cc.remove_signal_controller("non_existent_bus")
        self.assertFalse(was_removed)

    def test_command_center_dispose_cascades_to_controllers(self):
        """
        Test that disposing the CommandCenter also disposes all its internal controllers.
        """
        mock_controller_1 = MagicMock(spec=SignalController)
        mock_controller_2 = MagicMock(spec=SignalController)

        self.cc.add_signal_controller("bus_1", controller=mock_controller_1)
        self.cc.add_signal_controller("bus_2", controller=mock_controller_2)

        # Dispose the main command center
        self.cc.dispose()

        # Check that each internal controller's dispose method was called
        mock_controller_1.dispose.assert_called_once()
        mock_controller_2.dispose.assert_called_once()


if __name__ == '__main__':
    unittest.main(verbosity=2)
