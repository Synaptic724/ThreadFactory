import logging
import threading
import time
import unittest
from typing import List
from unittest.mock import MagicMock

# Assuming your classes are in these locations
from thread_factory import SignalController, SignalFork


# --- Test Utilities ---

def dummy_func_factory(name: str, log: List[str]):
    """A simple function factory for logging task execution."""

    def _fn():
        log.append(name)

    return _fn


def thread_use_fork(fork: SignalFork):
    """Target function for threads; ignores the expected error on exhaustion."""
    try:
        fork.use_fork()
    except RuntimeError:
        # Expected when fork is exhausted, can be ignored for these tests.
        pass


# --- Test Suite ---

class TestControllerWithSignalFork(unittest.TestCase):
    """
    Tests the integration between SignalController and the non-blocking SignalFork,
    verifying registration, command invocation, and event notifications.
    """

    def setUp(self):
        self.log: List[str] = []
        self.mock_logger = MagicMock(spec=logging.Logger)
        self.controller = SignalController(logger=self.mock_logger)

    def tearDown(self):
        if self.controller and not self.controller._disposed:
            self.controller.dispose()

    def _make_signal_fork(self, slots: int, callback: callable = None):
        """Helper to create a SignalFork instance registered with the controller."""
        return SignalFork(
            number_of_forks=1,
            callables=[(slots, dummy_func_factory("CALL", self.log))],
            callback=callback,
            controller=self.controller
        )

    def test_register_fork_success(self):
        """Verify the SignalFork registers itself with the controller on creation."""
        fork = self._make_signal_fork(2)
        self.assertIn(fork.id, self.controller._registry)
        self.assertEqual(self.controller._registry[fork.id]['name'], 'signal_fork')

    def test_invoke_reset_command(self):
        """Verify the 'reset' command can be invoked via the controller."""
        fork = self._make_signal_fork(2)

        # Use the fork once
        fork.use_fork()
        self.assertEqual(fork._list_of_forks[0].gate_uses, 1)

        # Invoke reset through the controller
        self.controller.invoke(fork.id, "reset")

        # Check that the fork's state was reset
        self.assertEqual(fork._list_of_forks[0].gate_uses, 0)
        self.assertFalse(fork._callback_executed)

    def test_callback_and_controller_notified_on_exhaustion(self):
        """Verify the callback and controller notification fire when the fork is exhausted."""
        callback_marker = []
        mock_controller = MagicMock()

        fork = SignalFork(
            number_of_forks=1,
            callables=[(1, lambda: None)],
            callback=lambda: callback_marker.append("FIRED"),
            controller=mock_controller
        )

        # Use up the only slot
        fork.use_fork()

        # This call will find the fork exhausted and trigger the signals
        with self.assertRaises(RuntimeError):
            fork.use_fork()

        # Assert callback was fired
        self.assertEqual(callback_marker, ["FIRED"])

        # Assert controller was notified
        mock_controller.notify.assert_called_with(fork.id, "FORK_COMPLETED")

    def test_broadcast_reset(self):
        """Verify broadcasting the 'reset' command works for all SignalForks."""
        forks = [self._make_signal_fork(1) for _ in range(3)]

        # Use up all slots in all forks
        for f in forks:
            f.use_fork()

        # FIX: Verify that each fork is now exhausted by asserting that
        # trying to use it again raises the correct error.
        for f in forks:
            with self.assertRaises(RuntimeError):
                f.use_fork()

        # Broadcast the reset command
        self.controller.invoke_on_all("reset")

        # Verify all forks are reset and usable again
        for f in forks:
            # This should now succeed without error
            f.use_fork()

        # Final check that the logs contain the correct number of calls
        self.assertEqual(self.log.count("CALL"), 6)
    def test_dispose_controller_disposes_forks(self):
        """Verify that disposing the controller also disposes registered forks."""
        forks = [self._make_signal_fork(1) for _ in range(2)]

        self.controller.dispose()

        for f in forks:
            self.assertTrue(f._disposed)

    def test_invalid_command_raises_key_error(self):
        """Verify invoking a non-existent command raises a helpful KeyError."""
        fork = self._make_signal_fork(1)
        with self.assertRaisesRegex(KeyError, "has no command 'launch_missiles'"):
            self.controller.invoke(fork.id, "launch_missiles")

    def test_pre_and_post_invoke_hooks(self):
        """Verify controller hooks are called for SignalFork commands."""
        fork = self._make_signal_fork(1)
        pre_hook = MagicMock()
        post_hook = MagicMock()

        self.controller.add_pre_invoke_hook(pre_hook)
        self.controller.add_post_invoke_hook(post_hook)

        # Invoke a command
        self.controller.invoke(fork.id, "reset")

        # Check that hooks were called with correct arguments
        pre_hook.assert_called_once_with(fork.id, "reset")
        post_hook.assert_called_once()

        # Unpack the call arguments for the post_hook
        call_args = post_hook.call_args[0]
        self.assertEqual(call_args[0], fork.id)  # object_id
        self.assertEqual(call_args[1], "reset")  # command
        self.assertIsNone(call_args[2])  # result (reset returns None)
        self.assertIsNone(call_args[3])  # exception


if __name__ == "__main__":
    unittest.main(verbosity=2)