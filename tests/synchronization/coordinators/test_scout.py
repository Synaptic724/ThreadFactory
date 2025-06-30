import threading
import time
import unittest
from unittest.mock import Mock

from thread_factory.synchronization.coordinators.scout import Scout


class TestScout(unittest.TestCase):

    def setUp(self):
        self.mock_on_success = Mock()
        self.mock_on_timeout = Mock()
        self.event_to_control_predicate = threading.Event()
        self.predicate_result = False

        def simple_predicate():
            return self.event_to_control_predicate.is_set() or self.predicate_result

        self.predicate = simple_predicate

    def tearDown(self):
        # Ensure any leftover Scout instances are disposed
        if hasattr(self, 'scout') and self.scout and not self.scout._disposed:
            self.scout.dispose()

    # --- Initialization Tests ---
    def test_init_invalid_predicate(self):
        with self.assertRaises(TypeError):
            Scout(predicate="not_callable", timeout_duration=1, on_timeout_callable=self.mock_on_timeout)

    def test_init_invalid_timeout(self):
        with self.assertRaises(ValueError):
            Scout(predicate=self.predicate, timeout_duration=0, on_timeout_callable=self.mock_on_timeout)
        with self.assertRaises(ValueError):
            Scout(predicate=self.predicate, timeout_duration=-1, on_timeout_callable=self.mock_on_timeout)

    def test_init_invalid_on_timeout_callable(self):
        with self.assertRaises(TypeError):
            Scout(predicate=self.predicate, timeout_duration=1, on_timeout_callable="not_callable")

    def test_init_invalid_on_success_callable(self):
        with self.assertRaises(TypeError):
            Scout(predicate=self.predicate, timeout_duration=1, on_timeout_callable=self.mock_on_timeout,
                  on_success_callable="not_callable")

    # --- Basic Functionality Tests ---
    def test_monitor_success_predicate_becomes_true(self):
        # Predicate starts False, will be set True by another thread
        self.event_to_control_predicate.clear()
        self.scout = Scout(
            predicate=self.predicate,
            timeout_duration=0.5,
            on_timeout_callable=self.mock_on_timeout,
            on_success_callable=self.mock_on_success
        )

        def set_predicate_later():
            time.sleep(0.1)  # Simulate some work
            self.event_to_control_predicate.set()
            self.scout._condition.acquire()  # Notify condition when state changes
            self.scout._condition.notify_all()
            self.scout._condition.release()

        setter_thread = threading.Thread(target=set_predicate_later)
        setter_thread.start()

        # The calling thread monitors
        result = self.scout.monitor()
        setter_thread.join()

        self.assertTrue(result)
        self.mock_on_success.assert_called_once()
        self.mock_on_timeout.assert_not_called()
        self.assertFalse(self.scout.is_active())
        self.assertTrue(self.scout.is_latched())  # Lached by default

    def test_monitor_timeout_occurs(self):
        # Predicate will always be False, leading to timeout
        self.event_to_control_predicate.clear()
        self.scout = Scout(
            predicate=self.predicate,
            timeout_duration=0.1,  # Short timeout
            on_timeout_callable=self.mock_on_timeout,
            on_success_callable=self.mock_on_success
        )

        start_time = time.time()
        result = self.scout.monitor()
        end_time = time.time()

        self.assertFalse(result)
        self.mock_on_timeout.assert_called_once()
        self.mock_on_success.assert_not_called()
        self.assertGreaterEqual(end_time - start_time, 0.1)  # Ensure it waited
        self.assertFalse(self.scout.is_active())
        self.assertTrue(self.scout.is_latched())

    def test_monitor_predicate_already_true(self):
        self.event_to_control_predicate.set()  # Predicate is true immediately
        self.scout = Scout(
            predicate=self.predicate,
            timeout_duration=0.1,
            on_timeout_callable=self.mock_on_timeout,
            on_success_callable=self.mock_on_success
        )
        result = self.scout.monitor()

        self.assertTrue(result)
        self.mock_on_success.assert_called_once()
        self.mock_on_timeout.assert_not_called()
        self.assertFalse(self.scout.is_active())
        self.assertTrue(self.scout.is_latched())

    def test_monitor_no_on_success_callable(self):
        self.event_to_control_predicate.set()  # Predicate is true immediately
        self.scout = Scout(
            predicate=self.predicate,
            timeout_duration=0.1,
            on_timeout_callable=self.mock_on_timeout,
            on_success_callable=None  # No success callable
        )
        result = self.scout.monitor()

        self.assertTrue(result)
        self.mock_on_success.assert_not_called()  # Should not be called
        self.mock_on_timeout.assert_not_called()
        self.assertFalse(self.scout.is_active())
        self.assertTrue(self.scout.is_latched())

    # --- Latching and Reset Tests (autoreset_on_exit=False) ---
    def test_latching_prevents_reentry(self):
        self.event_to_control_predicate.set()
        self.scout = Scout(
            predicate=self.predicate,
            timeout_duration=0.1,
            on_timeout_callable=self.mock_on_timeout,
            autoreset_on_exit=False  # Explicitly test latching
        )

        # First call should succeed and latch
        first_result = self.scout.monitor()
        self.assertTrue(first_result)
        self.assertTrue(self.scout.is_latched())

        # Second call should be rejected immediately (not block)
        second_result = self.scout.monitor()
        self.assertFalse(second_result)
        self.mock_on_timeout.assert_not_called()  # No timeout, just rejection

        # Ensure no unintended calls
        self.assertEqual(self.mock_on_success.call_count, 1 if self.scout._on_success_callable else 0)

    def test_reset_rearms_latch(self):
        self.event_to_control_predicate.set()
        self.scout = Scout(
            predicate=self.predicate,
            timeout_duration=0.1,
            on_timeout_callable=self.mock_on_timeout,
            on_success_callable=self.mock_on_success,
            autoreset_on_exit=False
        )

        # First call, success and latch
        self.assertTrue(self.scout.monitor())
        self.assertTrue(self.scout.is_latched())
        self.mock_on_success.assert_called_once()
        self.mock_on_timeout.assert_not_called()

        # Reset the scout
        self.scout.reset()
        self.assertFalse(self.scout.is_latched())
        self.assertFalse(self.scout.is_active())

        # Prepare for second successful call
        self.mock_on_success.reset_mock()
        self.mock_on_timeout.reset_mock()
        self.event_to_control_predicate.set()  # Ensure predicate is still true if it was cleared by callback

        # Second call should now succeed
        self.assertTrue(self.scout.monitor())
        self.assertTrue(self.scout.is_latched())
        self.mock_on_success.assert_called_once()
        self.mock_on_timeout.assert_not_called()

    # --- Auto-Reset Tests (autoreset_on_exit=True) ---
    def test_autoreset_on_exit_allows_reentry(self):
        self.event_to_control_predicate.set()
        self.scout = Scout(
            predicate=self.predicate,
            timeout_duration=0.1,
            on_timeout_callable=self.mock_on_timeout,
            on_success_callable=self.mock_on_success,
            autoreset_on_exit=True
        )

        # First call, success and should auto-reset
        self.assertTrue(self.scout.monitor())
        self.assertFalse(self.scout.is_latched())  # Should NOT be latched

        # Second call should also succeed without explicit reset
        self.mock_on_success.reset_mock()
        self.mock_on_timeout.reset_mock()
        self.assertTrue(self.scout.monitor())
        self.assertFalse(self.scout.is_latched())

        self.mock_on_success.assert_called_once()  # Called once per monitor() call
        self.mock_on_timeout.assert_not_called()

    def test_autoreset_on_exit_after_timeout(self):
        self.event_to_control_predicate.clear()  # Predicate will not become true
        self.scout = Scout(
            predicate=self.predicate,
            timeout_duration=0.05,  # Short timeout
            on_timeout_callable=self.mock_on_timeout,
            on_success_callable=self.mock_on_success,
            autoreset_on_exit=True
        )

        # First call, timeout and should auto-reset
        self.assertFalse(self.scout.monitor())  # Returns False on timeout
        self.mock_on_timeout.assert_called_once()
        self.assertFalse(self.scout.is_latched())  # Should NOT be latched

        # Second call should also trigger timeout and auto-reset
        self.mock_on_timeout.reset_mock()
        self.assertFalse(self.scout.monitor())
        self.mock_on_timeout.assert_called_once()
        self.assertFalse(self.scout.is_latched())

    # --- Concurrency / Single Entry Tests ---
    def test_only_one_thread_monitors_at_a_time(self):
        self.event_to_control_predicate.clear()  # Keep predicate false
        self.scout = Scout(
            predicate=self.predicate,
            timeout_duration=0.5,  # Long enough for other threads to try
            on_timeout_callable=self.mock_on_timeout
        )

        results = []

        def thread_target():
            results.append(self.scout.monitor())

        # Start a thread that will be the first monitor
        first_thread = threading.Thread(target=thread_target)
        first_thread.start()

        # Give it a moment to enter the monitor method
        time.sleep(0.01)
        self.assertTrue(self.scout.is_active())  # Verify the first thread is active

        # Start several other threads that should be rejected
        other_threads = []
        for _ in range(5):
            t = threading.Thread(target=thread_target)
            other_threads.append(t)
            t.start()

        # Join all threads
        for t in other_threads:
            t.join()
        first_thread.join()

        # The first thread should have timed out and returned False
        # The other threads should have immediately returned False due to rejection
        self.assertEqual(len(results), 6)  # 1 from first_thread + 5 from other_threads
        self.assertEqual(results.count(False), 6)  # All should be False (1 timeout, 5 rejections)

        self.assertFalse(self.scout.is_active())  # No thread should be active now
        self.assertTrue(self.scout.is_latched())  # Scout should be latched (default mode)

    # --- Disposal Tests ---
    def test_dispose_prevents_further_use(self):
        self.scout = Scout(
            predicate=self.predicate,
            timeout_duration=0.1,
            on_timeout_callable=self.mock_on_timeout
        )
        self.assertFalse(self.scout._disposed)

        self.scout.dispose()
        self.assertTrue(self.scout._disposed)

        # Attempt to monitor after dispose
        result = self.scout.monitor()
        self.assertFalse(result)  # Should immediately return False
        self.mock_on_timeout.assert_not_called()  # No callbacks should fire

        # Attempt to reset after dispose
        with self.assertRaises(RuntimeError):
            self.scout.reset()

    # --- Callback Exception Handling ---
    def test_on_timeout_callable_exception(self):
        def crashing_timeout():
            raise ValueError("Timeout callback crashed!")

        self.scout = Scout(
            predicate=self.predicate,
            timeout_duration=0.1,
            on_timeout_callable=crashing_timeout
        )

        # We expect a print to stderr, but the monitor call itself shouldn't raise
        # and should still return False for timeout.
        result = self.scout.monitor()
        self.assertFalse(result)
        self.assertFalse(self.scout.is_active())
        self.assertTrue(self.scout.is_latched())

    def test_on_success_callable_exception(self):
        self.event_to_control_predicate.set()

        def crashing_success():
            raise ValueError("Success callback crashed!")

        self.scout = Scout(
            predicate=self.predicate,
            timeout_duration=0.1,
            on_timeout_callable=self.mock_on_timeout,
            on_success_callable=crashing_success
        )

        # Expected to print to stderr, but monitor should still return True for success.
        result = self.scout.monitor()
        self.assertTrue(result)
        self.mock_on_timeout.assert_not_called()
        self.assertFalse(self.scout.is_active())
        self.assertTrue(self.scout.is_latched())


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
