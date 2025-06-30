import logging
import threading
import unittest
import ulid
from unittest.mock import Mock, MagicMock
from thread_factory.primitives.controller import Controller
from thread_factory.concurrency import ConcurrentDict
from thread_factory.utils.interfaces.disposable import IDisposable


# A helper class that fulfills the contract required by the Controller
class MockControllable(IDisposable):
    """A mock object that can be registered with the Controller."""

    def __init__(self, name="mock_object"):
        super().__init__()
        self.id = str(ulid.ULID())
        self.name = name
        # Use mock objects for commands to track calls and set return values
        self.mock_command_a = Mock(return_value="A")
        self.mock_command_b = Mock(return_value="B")
        self.mock_dispose = Mock()

    def _get_object_details(self):
        return {
            'name': self.name,
            'commands': {
                'command_a': self.mock_command_a,
                'command_b': self.mock_command_b,
                'dispose': self.mock_dispose
            }
        }

    def dispose(self):
        # Allow the object's own dispose to be called.
        super().dispose()
        self.mock_dispose()


class TestController(unittest.TestCase):

    def setUp(self):
        """Create a new Controller instance for each test."""
        self.mock_logger = MagicMock(spec=logging.Logger)
        self.controller = Controller(logger=self.mock_logger)

    def tearDown(self):
        """Ensure the controller is disposed after each test."""
        if not self.controller._disposed:
            self.controller.dispose()

    def test_initialization(self):
        """Test the controller's initial state."""
        self.assertIsInstance(self.controller._registry, ConcurrentDict)
        self.assertFalse(self.controller._disposed)
        self.assertEqual(self.controller._logger, self.mock_logger)
        # Test initialization without a logger
        no_logger_controller = Controller()
        self.assertIsNone(no_logger_controller._logger)

    def test_registration_success(self):
        """Test successful registration of a compliant object."""
        mock_obj = MockControllable()
        self.controller.register(mock_obj)

        self.mock_logger.debug.assert_called_with(f"Registered object: ID='{mock_obj.id}', Name='{mock_obj.name}'")
        self.assertIn(mock_obj.id, self.controller._registry)
        details = self.controller.list_objects()
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]['id'], mock_obj.id)
        self.assertEqual(details[0]['name'], mock_obj.name)

    def test_registration_failures(self):
        """Test various registration failure scenarios."""
        # Failure: Object doesn't have the required method
        with self.assertRaisesRegex(TypeError, "must have 'id' and '_get_object_details'"):
            self.controller.register(object())

        # Failure: Object already registered
        mock_obj = MockControllable()
        self.controller.register(mock_obj)
        with self.assertRaisesRegex(ValueError, "already registered"):
            self.controller.register(mock_obj)

    def test_unregister(self):
        """Test unregistering an object."""
        mock_obj = MockControllable()
        self.controller.register(mock_obj)
        self.assertIn(mock_obj.id, self.controller._registry)

        self.controller.unregister(mock_obj.id)
        self.mock_logger.debug.assert_called_with(f"Unregistered object: {mock_obj.id}")
        self.assertNotIn(mock_obj.id, self.controller._registry)
        mock_obj.mock_dispose.assert_called_once()

    def test_unregister_without_dispose(self):
        """Test unregistering without disposing the object."""
        mock_obj = MockControllable()
        self.controller.register(mock_obj)
        self.controller.unregister(mock_obj.id, dispose_object=False)
        self.assertNotIn(mock_obj.id, self.controller._registry)
        mock_obj.mock_dispose.assert_not_called()

    def test_invoke_success(self):
        """Test successfully invoking a command."""
        mock_obj = MockControllable()
        self.controller.register(mock_obj)
        result = self.controller.invoke(mock_obj.id, 'command_a', 1, 2, key='val')

        self.assertEqual(result, "A")
        mock_obj.mock_command_a.assert_called_once_with(1, 2, key='val')

    def test_invoke_failures(self):
        """Test various command invocation failures."""
        mock_obj = MockControllable()
        self.controller.register(mock_obj)

        with self.assertRaisesRegex(KeyError, "No object registered"):
            self.controller.invoke("nonexistent-id", 'command_a')

        with self.assertRaisesRegex(KeyError, "has no command"):
            self.controller.invoke(mock_obj.id, 'nonexistent_command')

        # Test when the command itself raises an error
        mock_obj.mock_command_b.side_effect = ValueError("Command Failed")
        with self.assertRaisesRegex(ValueError, "Command Failed"):
            self.controller.invoke(mock_obj.id, 'command_b')
        self.mock_logger.error.assert_called()

    def test_invoke_on_all(self):
        """Test invoking a command on multiple objects."""
        obj1 = MockControllable(name="type1")
        obj2 = MockControllable(name="type1")
        obj3 = MockControllable(name="type2")
        self.controller.register(obj1)
        self.controller.register(obj2)
        self.controller.register(obj3)

        # Invoke on all
        self.controller.invoke_on_all('command_a')
        obj1.mock_command_a.assert_called_once()
        obj2.mock_command_a.assert_called_once()
        obj3.mock_command_a.assert_called_once()

        # Invoke with name filter
        self.controller.invoke_on_all('command_b', name_filter="type1")
        obj1.mock_command_b.assert_called_once()
        obj2.mock_command_b.assert_called_once()
        obj3.mock_command_b.assert_not_called()

    def test_event_and_state_tracking(self):
        """Test the notify method and state tracking for waiting objects."""
        mock_obj = MockControllable()
        self.controller.register(mock_obj)

        self.assertEqual(self.controller.get_waiting_objects(), [])

        # Use the adapter to simulate a wait signal
        self.controller.on_wait_starting(mock_obj.id)
        self.mock_logger.info.assert_called_with(f"Controller Event: ID='{mock_obj.id}', Event='WAIT_STARTING'")
        self.assertEqual(self.controller.get_waiting_objects(), [mock_obj.id])

        # Simulate the object being opened by the controller
        self.controller.invoke(mock_obj.id, 'dispose')
        self.assertEqual(self.controller.get_waiting_objects(), [])

    def test_subscribe_and_notify(self):
        """Test the Pub/Sub system."""
        mock_obj = MockControllable()
        self.controller.register(mock_obj)
        mock_callback = Mock()

        self.controller.subscribe(mock_obj.id, "WAIT_STARTING", mock_callback)
        self.mock_logger.debug.assert_called()

        # This notification should trigger the callback
        self.controller.notify(mock_obj.id, "WAIT_STARTING", data={'info': 'test'})
        mock_callback.assert_called_once_with(mock_obj.id, "WAIT_STARTING", {'info': 'test'})

        # This notification should NOT trigger the callback
        self.controller.notify(mock_obj.id, "SOMETHING_ELSE")
        mock_callback.assert_called_once()  # Still called only once

    def test_hook_system(self):
        """Test the pre- and post-invocation hook system."""
        mock_obj = MockControllable()
        self.controller.register(mock_obj)
        pre_hook = Mock()
        post_hook = Mock()

        self.controller.add_pre_invoke_hook(pre_hook)
        self.controller.add_post_invoke_hook(post_hook)

        # Test success case
        result = self.controller.invoke(mock_obj.id, 'command_a')
        pre_hook.assert_called_once_with(mock_obj.id, 'command_a')
        post_hook.assert_called_once_with(mock_obj.id, 'command_a', result, None)

        # Test failure case
        pre_hook.reset_mock()
        post_hook.reset_mock()
        mock_obj.mock_command_b.side_effect = RuntimeError("Hook Test Fail")

        with self.assertRaises(RuntimeError):
            self.controller.invoke(mock_obj.id, 'command_b')

        pre_hook.assert_called_once_with(mock_obj.id, 'command_b')
        # Check that the exception object was passed to the post-hook
        post_hook.assert_called_once()
        args, _ = post_hook.call_args
        self.assertEqual(args[0], mock_obj.id)
        self.assertEqual(args[1], 'command_b')
        self.assertIsNone(args[2])  # result
        self.assertIsInstance(args[3], RuntimeError)  # exception

    def test_dispose(self):
        """Test the controller's dispose method."""
        mock_obj = MockControllable()
        self.controller.register(mock_obj)

        self.controller.dispose()

        # Check that the object's dispose was called via invoke_on_all
        mock_obj.mock_dispose.assert_called_once()
        self.assertTrue(self.controller._disposed)
        # Check that internal dicts were disposed
        self.assertTrue(self.controller._registry._disposed)
        self.assertTrue(self.controller._active_waits._disposed)
        self.assertTrue(self.controller._subscribers._disposed)


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)