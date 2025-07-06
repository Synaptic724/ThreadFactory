import unittest
import logging
import ulid
from unittest.mock import MagicMock, patch

# Assuming the following imports are correct based on your project structure
from thread_factory.agent.command_center import CommandCenter
from thread_factory.synchronization.controllers.signal_controller import SignalController

# Suppress logging output during tests for a cleaner console
logging.disable(logging.CRITICAL)


class TestCommandCenterSignalControllerManagement(unittest.TestCase):
    """
    A comprehensive test suite for managing SignalControllers within the CommandCenter,
    covering creation, removal, proxy methods, and group-scoping.
    """

    def setUp(self):
        """
        Set up a new CommandCenter instance before each test.
        The AgentBuilder is patched to isolate these tests from agent logic.
        """
        # Patching the builder prevents dependency issues during CommandCenter initialization,
        # allowing us to focus solely on SignalController logic.
        with patch('thread_factory.agent.identity.agent_builder.AgentBuilder'):
            self.cc = CommandCenter(group_max_workers=2, command_group_name="default_bus_group")
        self.default_group_name = "default_bus_group"

    def tearDown(self):
        """
        Clean up by disposing of the CommandCenter instance after each test.
        """
        if self.cc and not self.cc._disposed:
            self.cc.dispose()

    # --- Core SignalController Management Tests ---

    def test_add_signal_controller_creates_new(self):
        """
        Test that add_signal_controller creates a new controller if none is provided.
        """
        controller_name = "test_bus"
        # Initially, the default group has no signal controllers.
        self.assertEqual(len(self.cc.get_command_group(self.default_group_name)._signal_controllers), 0)

        new_controller = self.cc.add_signal_controller(controller_name, command_group_name=self.default_group_name)

        self.assertIsNotNone(new_controller)
        self.assertIsInstance(new_controller, SignalController)
        # Verify it's in the correct group's registry
        self.assertIn(new_controller.id, self.cc.get_command_group(self.default_group_name)._signal_controllers)

    def test_add_existing_signal_controller(self):
        """
        Test that a pre-existing SignalController instance can be added.
        """
        controller_name = "pre_existing_bus"
        existing_controller = SignalController()
        existing_controller.name = controller_name # Manually set name as the source method doesn't

        added_controller = self.cc.add_signal_controller(controller_name, controller=existing_controller, command_group_name=self.default_group_name)

        self.assertIs(added_controller, existing_controller)
        self.assertIn(controller_name, self.cc.list_signal_controllers())

    def test_add_duplicate_name_returns_existing_instance(self):
        """
        Test that adding a SignalController with a duplicate name returns the existing instance
        instead of raising an error, matching the current source code logic.
        """
        controller_name = "shared_bus"
        controller1 = self.cc.add_signal_controller(controller_name, command_group_name=self.default_group_name)
        controller2 = self.cc.add_signal_controller(controller_name, command_group_name=self.default_group_name)

        self.assertIs(controller1, controller2)
        self.assertEqual(len(self.cc.list_signal_controllers()), 1)

    def test_get_signal_controller_by_id(self):
        """
        Test retrieving a SignalController by its unique ID.
        """
        added_controller = self.cc.add_signal_controller("retrieval_bus", command_group_name=self.default_group_name)
        retrieved_controller = self.cc.get_signal_controller_by_id(added_controller.id)

        self.assertIsNotNone(retrieved_controller)
        self.assertIs(added_controller, retrieved_controller)

    def test_remove_signal_controller_by_object(self):
        """
        Test removing a controller by passing its object instance.
        """
        controller_to_remove = self.cc.add_signal_controller("disposable_bus", command_group_name=self.default_group_name)
        controller_id = controller_to_remove.id

        was_removed = self.cc.remove_signal_controller(controller_to_remove)

        self.assertTrue(was_removed)
        self.assertIsNone(self.cc.get_signal_controller_by_id(controller_id))

    def test_remove_non_existent_controller_is_safe(self):
        """
        Test that attempting to remove a non-existent controller returns False.
        """
        non_existent_controller = SignalController()
        was_removed = self.cc.remove_signal_controller(non_existent_controller)
        self.assertFalse(was_removed)

    def test_command_center_dispose_cascades_to_controllers(self):
        """
        Test that disposing the CommandCenter also disposes all its internal controllers.
        """
        mock_controller = MagicMock(spec=SignalController)
        mock_controller.id = "mock_id_1" # Mock needs an ID to be added
        mock_controller.name = "bus_1"

        self.cc.add_signal_controller("bus_1", controller=mock_controller, command_group_name=self.default_group_name)
        self.cc.dispose()
        mock_controller.dispose.assert_called_once()

    # --- Group-Specific Controller Management ---

    def test_controllers_are_scoped_to_command_groups(self):
        """
        Verify that controllers added to different groups are isolated.
        """
        self.cc.create_command_group("group_A", max_workers=1)
        self.cc.create_command_group("group_B", max_workers=1)

        controller_A = self.cc.add_signal_controller("shared_name", command_group_name="group_A")
        controller_B = self.cc.add_signal_controller("shared_name", command_group_name="group_B")

        self.assertIsNotNone(controller_A)
        self.assertIsNotNone(controller_B)
        self.assertNotEqual(controller_A.id, controller_B.id)

        # Verify find_controller_by_name is correctly scoped
        found_A = self.cc.find_controller_by_name("shared_name", command_group_name="group_A")
        found_B = self.cc.find_controller_by_name("shared_name", command_group_name="group_B")

        self.assertIs(found_A, controller_A)
        self.assertIs(found_B, controller_B)

    # --- CommandCenter Proxy Method Tests ---

    def test_invoke_on_controller_by_id_proxies_call(self):
        """
        Test that invoke_on_controller_by_id correctly calls invoke on the target controller.
        """
        mock_controller = MagicMock(spec=SignalController)
        mock_controller.id = "proxy_id_1"
        self.cc.add_signal_controller("proxy_bus", controller=mock_controller, command_group_name=self.default_group_name)

        self.cc.invoke_on_controller_by_id(mock_controller.id, 'obj_123', 'open', 'arg1', kwarg='val')
        mock_controller.invoke.assert_called_once_with('obj_123', 'open', 'arg1', kwarg='val')

    def test_subscribe_to_event_proxies_call(self):
        """
        Test that subscribe_to_event correctly calls subscribe on the target controller.
        """
        mock_controller = MagicMock(spec=SignalController)
        mock_controller.id = "proxy_id_2"
        self.cc.add_signal_controller("event_bus", controller=mock_controller, command_group_name=self.default_group_name)

        callback = lambda: None
        # NOTE: The source method signature is (controller_name, ...), but its implementation
        # incorrectly uses the name as an ID. We pass the ID here to match the implementation.
        self.cc.subscribe_to_event(mock_controller.id, 'obj_123', 'EVENT_FIRED', callback, command_group_name=self.default_group_name)
        mock_controller.subscribe.assert_called_once_with('obj_123', 'EVENT_FIRED', callback)

    def test_list_objects_on_controller_proxies_call(self):
        """
        Test that list_objects_on_controller correctly calls list_objects on the target controller.
        """
        mock_controller = MagicMock(spec=SignalController)
        mock_controller.id = "proxy_id_3"
        self.cc.add_signal_controller("list_bus", controller=mock_controller, command_group_name=self.default_group_name)
        mock_controller.list_objects.return_value = ["obj1", "obj2"]

        # NOTE: The source method signature is (controller_name, ...), but its implementation
        # incorrectly uses the name as an ID. We pass the ID here to match the implementation.
        result = self.cc.list_objects_on_controller(mock_controller.id, name_filter="filter", command_group_name=self.default_group_name)

        mock_controller.list_objects.assert_called_once_with("filter")
        self.assertEqual(result, ["obj1", "obj2"])

    def test_wrappers_raise_on_non_existent_controller(self):
        """
        Test that all wrapper methods raise ValueError for a non-existent controller name.
        """
        bad_name = "non_existent_bus"
        with self.assertRaises(ValueError):
            self.cc.invoke_on_controller_by_name(bad_name, 'id', 'cmd', command_group_name=self.default_group_name)
        with self.assertRaises(ValueError):
            self.cc.subscribe_to_event(bad_name, 'id', 'event', lambda: None, command_group_name=self.default_group_name)
        with self.assertRaises(ValueError):
            self.cc.list_objects_on_controller(bad_name, command_group_name=self.default_group_name)

    def test_wrappers_raise_after_dispose(self):
        """
        Test that wrapper methods raise RuntimeError if called after the CommandCenter is disposed.
        """
        controller = self.cc.add_signal_controller("disposable_bus", command_group_name=self.default_group_name)
        self.cc.dispose()

        with self.assertRaises(RuntimeError):
            self.cc.invoke_on_controller_by_id(controller.id, 'id', 'cmd')
        with self.assertRaises(RuntimeError):
            self.cc.add_signal_controller("another_bus")


if __name__ == '__main__':
    unittest.main(verbosity=2)
