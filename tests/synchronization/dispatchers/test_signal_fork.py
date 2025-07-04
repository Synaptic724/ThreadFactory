import unittest
import threading
import time
from collections import Counter
from unittest.mock import MagicMock

# Assuming SignalFork is in this location.
from thread_factory.synchronization.dispatchers.signal_fork import SignalFork


# --- Test Utilities ---

def dummy_func_factory(name, log_list, delay=0):
    """A simple function factory for logging task execution."""

    def func():
        if delay > 0:
            time.sleep(delay)
        log_list.append(name)

    return func


def _spawn(n: int, fn: callable):
    """Spins up n daemon threads and starts them."""
    threads = []
    for i in range(n):
        t = threading.Thread(target=fn, name=f"Worker-{i + 1}", daemon=True)
        threads.append(t)
    for t in threads:
        t.start()
    return threads


# --- Test Suite for SignalFork ---

class TestSignalFork(unittest.TestCase):
    """
    A comprehensive test suite for the SignalFork class, verifying both its
    core dispatching logic and its new signaling features.
    """

    def setUp(self):
        """Set up a fresh log for each test."""
        self.log = []

    # ===============================================================
    # Tests Adapted from TestFork (Verifying Core Logic)
    # ===============================================================

    def test_step_selector_even_distribution(self):
        """Verify basic round-robin distribution works correctly."""
        fork = SignalFork(
            number_of_forks=4,
            callables=[(3, dummy_func_factory(f"F{i}", self.log)) for i in range(4)],
        )

        for _ in range(12):
            fork.use_fork()

        counts = Counter(self.log)
        self.assertEqual(counts["F0"], 3)
        self.assertEqual(counts["F1"], 3)
        self.assertEqual(counts["F2"], 3)
        self.assertEqual(counts["F3"], 3)

    def test_all_forks_exhausted_error(self):
        """Verify that a RuntimeError is raised after all slots are used."""
        fork = SignalFork(
            number_of_forks=2,
            callables=[(1, lambda: None), (1, lambda: None)]
        )
        fork.use_fork()
        fork.use_fork()

        with self.assertRaises(RuntimeError):
            fork.use_fork()

    def test_multithreaded_stress_distribution(self):
        """Verify correct distribution under concurrent load."""
        fork = SignalFork(
            number_of_forks=5,
            callables=[(10, dummy_func_factory(f"F{i}", self.log, delay=0.01)) for i in range(5)]
        )

        threads = _spawn(50, fork.use_fork)
        for t in threads:
            t.join()

        self.assertEqual(len(self.log), 50)
        counts = Counter(self.log)
        for i in range(5):
            self.assertEqual(counts[f"F{i}"], 10)

    # ===============================================================
    # New Tests for SignalFork Features (Callback & Controller)
    # ===============================================================

    def test_callback_fires_once_on_exhaustion(self):
        """Verify the callback is executed exactly once when the fork is exhausted."""
        callback_log = []

        def on_complete_callback():
            callback_log.append("completed")

        fork = SignalFork(
            number_of_forks=2,
            callables=[(1, lambda: None), (1, lambda: None)],
            callback=on_complete_callback
        )

        fork.use_fork()
        # The callback should not have fired yet.
        self.assertEqual(len(callback_log), 0)

        # The second call will use the last slot.
        fork.use_fork()

        # The third call will find the fork exhausted, trigger the callback, and raise an error.
        with self.assertRaises(RuntimeError):
            fork.use_fork()

        # Assert that the callback was fired exactly once.
        self.assertEqual(callback_log, ["completed"])

    def test_callback_is_reusable_after_reset(self):
        """Verify that after a reset, the callback can fire again."""
        callback_log = []

        def on_complete_callback():
            callback_log.append("completed")

        fork = SignalFork(
            number_of_forks=1,
            callables=[(2, lambda: None)],
            callback=on_complete_callback
        )

        # First run
        fork.use_fork()
        fork.use_fork()
        with self.assertRaises(RuntimeError):
            fork.use_fork()
        self.assertEqual(len(callback_log), 1)

        # Reset and run again
        fork.reset()
        fork.use_fork()
        fork.use_fork()
        with self.assertRaises(RuntimeError):
            fork.use_fork()

        # The callback should have fired a second time.
        self.assertEqual(len(callback_log), 2)

    def test_controller_is_notified_on_completion(self):
        """Verify the controller is registered and notified correctly."""
        # A MagicMock acts as a "spy" to record calls to it.
        mock_controller = MagicMock()

        fork = SignalFork(
            number_of_forks=1,
            callables=[(1, lambda: None)],
            controller=mock_controller,
            callback=lambda: None
        )

        # 1. Verify that the fork registered itself on __init__
        mock_controller.register.assert_called_once_with(fork)

        # Exhaust the fork to trigger the notification
        fork.use_fork()
        with self.assertRaises(RuntimeError):
            fork.use_fork()

        # 2. Verify that the controller was notified with the correct message
        mock_controller.notify.assert_called_once_with(fork.id, "FORK_COMPLETED")

    def test_callback_fires_only_once_under_concurrency(self):
        """Verify the callback's lock prevents race conditions."""
        callback_log = []

        def on_complete_callback():
            # This sleep makes a race condition more likely if there's no lock
            time.sleep(0.01)
            callback_log.append("completed")

        fork = SignalFork(
            number_of_forks=1,
            callables=[(10, lambda: None)],  # 10 slots
            callback=on_complete_callback
        )

        # Spawn more threads than slots, so several will find the fork exhausted
        # at roughly the same time.
        threads = _spawn(20, fork.use_fork)

        for t in threads:
            t.join()

        # Even though multiple threads detected exhaustion, the callback
        # should only have been executed by the first one to get the lock.
        self.assertEqual(len(callback_log), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)