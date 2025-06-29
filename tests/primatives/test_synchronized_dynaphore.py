import unittest
import threading
import time
from thread_factory.primitives.synchronized_dynaphore import SynchronizedDynaphore


# --- UNIT TESTS ---

class TestSynchronizedDynaphore(unittest.TestCase):
    """
    Tests for the SynchronizedDynaphore class, focusing on the wait_or_raise mechanic.
    """

    def test_wait_or_raise_throws_timeout_error_when_no_permits(self):
        """
        Verifies that wait_or_raise() correctly raises TimeoutError if no permit is available.
        """
        # Initialize with zero permits
        sync_dyn = SynchronizedDynaphore(value=0)

        # Assert that calling wait_or_raise raises the expected exception
        with self.assertRaises(TimeoutError) as context:
            sync_dyn.wait_or_raise(timeout=0.01)

        self.assertIn("Failed to acquire permit", str(context.exception))
        print("Test 1 PASSED: Correctly raised TimeoutError on timeout.")

    def test_wait_or_raise_succeeds_when_permit_is_available(self):
        """
        Verifies that wait_or_raise() does NOT raise an exception if a permit is immediately available.
        """
        # Initialize with one permit
        sync_dyn = SynchronizedDynaphore(value=1)

        try:
            # This call should succeed and not raise any exception
            sync_dyn.wait_or_raise(timeout=0.01)
            # Verify the permit count was decremented
            # Note: _value is an implementation detail, but useful for testing
            self.assertEqual(sync_dyn._value, 0)
        except TimeoutError:
            self.fail("wait_or_raise() raised TimeoutError unexpectedly.")

        print("Test 2 PASSED: Succeeded immediately when permit was available.")

    def test_wait_or_raise_succeeds_in_multithreaded_scenario(self):
        """
        Verifies that a waiting thread can be unblocked by another thread releasing a permit.
        """
        sync_dyn = SynchronizedDynaphore(value=0)
        result_container = []  # Using a list to share state between threads

        def worker():
            try:
                # This thread will block until the main thread adds a permit
                sync_dyn.wait_or_raise(timeout=1.0)
                result_container.append("Success")
            except TimeoutError:
                result_container.append("Failure")

        worker_thread = threading.Thread(target=worker)
        worker_thread.start()

        # Give the worker thread time to start and block
        time.sleep(0.1)

        # Main thread adds a permit, which should unblock the worker
        print("  [Main Thread] Releasing a permit...")
        sync_dyn.increase_permits(1)

        # Wait for the worker thread to finish
        worker_thread.join()

        self.assertEqual(len(result_container), 1)
        self.assertEqual(result_container[0], "Success")
        print("Test 3 PASSED: Worker thread successfully acquired permit after release.")

    def test_timeout_duration_is_respected(self):
        """
        Verifies that the method blocks for approximately the specified timeout duration.
        """
        sync_dyn = SynchronizedDynaphore(value=0)
        timeout_duration = 0.1  # seconds

        start_time = time.monotonic()
        with self.assertRaises(TimeoutError):
            sync_dyn.wait_or_raise(timeout=timeout_duration)
        end_time = time.monotonic()

        elapsed_time = end_time - start_time

        # Check if the elapsed time is close to the timeout duration.
        # Allow for a small margin of error (e.g., 50ms) due to thread scheduling overhead.
        self.assertGreaterEqual(elapsed_time, timeout_duration)
        self.assertLess(elapsed_time, timeout_duration + 0.05)
        print(f"Test 4 PASSED: Blocked for {elapsed_time:.4f}s (timeout was {timeout_duration}s).")


# This allows the test to be run from the command line
if __name__ == '__main__':
    unittest.main(verbosity=0)