import unittest
import threading
import time
from thread_factory.utils import Group
# Assuming the corrected class is in the path below
from thread_factory.primitives.synchronized_signal_barrier import SynchronizedSignalBarrier


class TestSignalBarrier(unittest.TestCase):

    def test_initialization(self):
        barrier = SynchronizedSignalBarrier(groups=[Group(2)], reusable=True, timeout=0.1)
        self.assertEqual(len(barrier.groups), 1)
        self.assertTrue(barrier.reusable)
        self.assertEqual(barrier.timeout, 0.1)
        self.assertFalse(barrier._released)
        self.assertFalse(barrier._broken)
        self.assertFalse(barrier._enabled)

    def test_add_group_and_enable(self):
        barrier = SynchronizedSignalBarrier()
        barrier.add_group(2)
        self.assertEqual(len(barrier.groups), 1)
        barrier.enable()
        self.assertTrue(barrier._enabled)
        with self.assertRaises(RuntimeError):
            barrier.add_group(3)

    def test_enable_without_groups_raises_error(self):
        barrier = SynchronizedSignalBarrier()
        with self.assertRaises(ValueError):
            barrier.enable()

    def test_group_threshold_met_with_callback(self):
        results = []
        # Use a callback to modify the results list
        barrier = SynchronizedSignalBarrier(groups=[Group(2, callback=lambda: results.append("callback_fired"))])
        barrier.enable()

        def thread_func():
            released = barrier.wait(0)
            # This append happens after the thread is released
            results.append(released)

        threads = [threading.Thread(target=thread_func) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertTrue(barrier._released)
        self.assertIn("callback_fired", results)
        self.assertEqual(results.count(True), 2)

    def test_timeout_behavior(self):
        barrier = SynchronizedSignalBarrier(groups=[Group(2)], timeout=0.1)
        barrier.enable()

        def thread_func():
            barrier.wait(0)

        thread1 = threading.Thread(target=thread_func)
        thread1.start()

        thread1.join(0.5)

        self.assertTrue(barrier._broken)
        self.assertTrue(barrier._released)

    def test_manual_release(self):
        barrier = SynchronizedSignalBarrier(groups=[Group(2)], manual_release=True)
        barrier.enable()
        released_flags = [False, False]

        def thread_func(idx):
            barrier.wait(0)
            released_flags[idx] = True

        threads = [threading.Thread(target=thread_func, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()

        time.sleep(0.1)
        self.assertFalse(barrier._released)

        barrier.release()

        for t in threads:
            t.join(0.5)

        self.assertTrue(barrier._released)
        self.assertTrue(all(released_flags))

    def test_reusable_behavior(self):
        barrier = SynchronizedSignalBarrier(groups=[Group(2)], reusable=True)
        barrier.enable()

        def thread_func():
            barrier.wait(0)

        # --- First wave ---
        threads1 = [threading.Thread(target=thread_func) for _ in range(2)]
        for t in threads1:
            t.start()
        for t in threads1:
            t.join()

        # After the first wave, the last thread out should have reset the barrier.
        self.assertFalse(barrier._released, "Barrier should reset to not-released after wave 1")
        self.assertFalse(barrier._broken)
        self.assertEqual(barrier.groups[0].count, 0)

        # --- Second wave ---
        threads2 = [threading.Thread(target=thread_func) for _ in range(2)]
        for t in threads2:
            t.start()
        for t in threads2:
            t.join()

        # The barrier should have released and reset again.
        self.assertFalse(barrier._released, "Barrier should reset to not-released after wave 2")
        self.assertEqual(barrier.groups[0].count, 0)

    def test_is_spent(self):
        barrier = SynchronizedSignalBarrier(groups=[Group(2)], reusable=False)
        barrier.enable()

        def thread_func():
            barrier.wait(0)

        threads = [threading.Thread(target=thread_func) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertTrue(barrier.is_spent())

    def test_notify_all_override(self):
        barrier = SynchronizedSignalBarrier(groups=[Group(3)])
        barrier.enable()

        threads = [threading.Thread(target=barrier.wait, args=(0,)) for _ in range(2)]
        for t in threads:
            t.start()

        time.sleep(0.1)
        self.assertFalse(barrier._released)

        barrier.notify_all_override()

        for t in threads:
            t.join(0.5)

        self.assertTrue(barrier._released)

    def test_dispose(self):
        barrier = SynchronizedSignalBarrier(groups=[Group(2)])
        barrier.enable()

        thread = threading.Thread(target=barrier.wait, args=(0,))
        thread.start()

        time.sleep(0.1)
        barrier.dispose()

        thread.join(0.5)

        self.assertTrue(barrier._disposed)
        self.assertTrue(barrier._broken)
        self.assertFalse(thread.is_alive())


    def test_multiple_groups(self):
        """
        Test multiple groups with different thresholds.
        The barrier should only release when all groups are ready.
        """
        results = []

        # Define two groups: one with threshold 2 and another with threshold 3
        barrier = SynchronizedSignalBarrier(groups=[
            Group(2, callback=lambda: results.append("group_1_ready")),
            Group(3, callback=lambda: results.append("group_2_ready"))
        ], reusable=True)
        barrier.enable()

        def thread_func(group_index):
            return barrier.wait(group_index)

        # Start threads for both groups
        threads = [
            threading.Thread(target=thread_func, args=(0,)) for _ in range(2)
        ] + [
            threading.Thread(target=thread_func, args=(1,)) for _ in range(3)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Assert that both callbacks were fired
        self.assertIn("group_1_ready", results)
        self.assertIn("group_2_ready", results)

        # Check that the barrier has reset for reuse
        self.assertFalse(barrier._released)

    def test_broken_barrier_on_manual_release_timeout(self):
        """
        Test that barrier becomes broken and releases all threads if manual release is not called within the timeout.
        """
        barrier = SynchronizedSignalBarrier(groups=[Group(2)], manual_release=True, timeout=0.5)
        barrier.enable()

        def thread_func():
            # This will return False if the barrier is broken or disposed
            return barrier.wait(0)

        # Start the thread and wait for the timeout to occur.
        thread1 = threading.Thread(target=thread_func)
        thread1.start()

        # Wait long enough for the timeout to trigger inside the thread.
        time.sleep(0.6)

        # The thread should have exited from the barrier due to the timeout.
        self.assertFalse(thread1.is_alive())

        # Assert that the barrier is now broken and released, which is the behavior after a timeout.
        self.assertTrue(barrier._broken)
        self.assertTrue(barrier._released)  # This assertion now passes, as the barrier releases threads on timeout.

    def test_early_thread_arrival(self):
        """
        Test that threads that arrive early will be blocked until all threads meet the threshold.
        """
        results = []
        barrier = SynchronizedSignalBarrier(groups=[Group(3, callback=lambda: results.append("released"))], timeout=1)
        barrier.enable()

        def thread_func():
            barrier.wait(0)

        # Start the first thread and let it wait
        thread1 = threading.Thread(target=thread_func)
        thread1.start()

        # Start the second thread and let it wait
        thread2 = threading.Thread(target=thread_func)
        thread2.start()

        # The third thread arrives later
        thread3 = threading.Thread(target=thread_func)
        thread3.start()

        # Wait for all threads to complete
        for t in [thread1, thread2, thread3]:
            t.join()

        # Assert the callback was fired and the barrier was released
        self.assertIn("released", results)
        self.assertTrue(barrier._released)

    def test_reset_after_timeout(self):
        """
        Test that a timeout properly resets the barrier.
        """
        barrier = SynchronizedSignalBarrier(groups=[Group(2)], timeout=0.5, reusable=True)
        barrier.enable()

        def thread_func():
            return barrier.wait(0)

        # Start the first thread and let it time out
        thread1 = threading.Thread(target=thread_func)
        thread1.start()
        thread1.join(1)  # Wait long enough for it to time out

        # The thread should have timed out and set the broken flag.
        self.assertTrue(barrier._broken)  # Ensure it's broken after timeout
        # At this point, _released should be True to unblock other potential threads
        self.assertTrue(barrier._released)
        self.assertFalse(thread1.is_alive())

        # Now, manually reset the barrier
        barrier.reset()

        # After reset, the state should be clean for reuse.
        self.assertFalse(barrier._released)
        self.assertFalse(barrier._broken)

        # Start new threads to test the reset barrier
        thread2 = threading.Thread(target=thread_func)
        thread3 = threading.Thread(target=thread_func)
        thread2.start()
        thread3.start()

        # Wait for the second wave to complete
        thread2.join()
        thread3.join()

        # After the second wave, the reusable barrier should have released and reset again.
        # This assert depends on the state after the last thread has reset the barrier.
        # It's more reliable to check the counts and released state after they've joined.
        self.assertEqual(barrier.groups[0].count, 0)
        self.assertFalse(barrier._released)

    def test_thread_group_count_management(self):
        """
        Test that the barrier properly handles thread count management per group.
        """
        barrier = SynchronizedSignalBarrier(groups=[Group(3)], timeout=1)
        barrier.enable()

        def thread_func():
            return barrier.wait(0)

        # Start 2 threads and check the group count.
        # They will block until a 3rd thread joins.
        thread1 = threading.Thread(target=thread_func)
        thread2 = threading.Thread(target=thread_func)
        thread1.start()
        thread2.start()

        # Give the threads a small moment to enter the barrier and increment the count.
        time.sleep(0.1)

        # Now, check the barrier's state. It should not be released yet.
        self.assertEqual(barrier.groups[0].count, 2)  # The count should be 2.
        self.assertFalse(barrier._released)  # The barrier should NOT be released.

        # Start the 3rd thread to meet the threshold.
        thread3 = threading.Thread(target=thread_func)
        thread3.start()

        # Now, wait for all threads to complete. They should be released now.
        for t in [thread1, thread2, thread3]:
            t.join()

        # Assert the count matches the threshold and the barrier is released.
        self.assertEqual(barrier.groups[0].count, 3)
        self.assertTrue(barrier._released)

    def test_broken_state_after_dispose(self):
        """
        Test that after dispose, the barrier should remain broken and prevent further use.
        """
        barrier = SynchronizedSignalBarrier(groups=[Group(2)], timeout=1)
        barrier.enable()

        # Start a thread that waits on the barrier
        thread1 = threading.Thread(target=barrier.wait, args=(0,))
        thread1.start()

        # Dispose of the barrier while the thread is waiting
        barrier.dispose()
        thread1.join(0.5)

        # Assert that the barrier is disposed and broken
        self.assertTrue(barrier._disposed)
        self.assertTrue(barrier._broken)
        self.assertFalse(thread1.is_alive())

    def test_timeout_raises_exception(self):
        """
        Test that `raise_on_timeout=True` causes the waiting thread to raise a TimeoutError.
        """
        barrier = SynchronizedSignalBarrier(groups=[Group(2)], timeout=0.1, raise_on_timeout=True)
        barrier.enable()

        def thread_func():
            # The exception will be raised here.
            try:
                barrier.wait(0)
            except TimeoutError as e:
                # Catch the exception and return True to indicate it was caught.
                return True, str(e)
            return False, None # Should not be reached

        thread1 = threading.Thread(target=lambda: self.result.append(thread_func()))
        self.result = [] # Use a shared list to get the result from the thread.
        thread1.start()

        # Wait for the timeout to occur.
        thread1.join(0.5)

        # Assert that the thread exited and raised the correct exception.
        self.assertFalse(thread1.is_alive())
        self.assertEqual(len(self.result), 1)
        # Check if the function returned True (indicating exception was caught) and the message is correct.
        self.assertTrue(self.result[0][0])
        self.assertIn("Barrier wait timed out", self.result[0][1])

        # Assert the barrier is in a broken state.
        self.assertTrue(barrier._broken)
        self.assertTrue(barrier._released)

    def test_late_thread_raises_exception_on_broken_barrier(self):
        """
        Test that a thread entering an already broken barrier also raises a TimeoutError
        when `raise_on_timeout` is True.
        """
        # First, set up a barrier that will break due to timeout.
        barrier = SynchronizedSignalBarrier(groups=[Group(2)], timeout=0.1, raise_on_timeout=True)
        barrier.enable()

        def thread_func():
            # This thread will time out and break the barrier.
            try:
                barrier.wait(0)
            except TimeoutError:
                pass # Suppress the exception in this thread for the test's purpose.

        # Start the thread that will cause the timeout.
        thread1 = threading.Thread(target=thread_func)
        thread1.start()
        thread1.join(0.5) # Wait for it to time out and exit.

        # Now, the barrier is in a broken state.
        self.assertTrue(barrier._broken)

        # Start a new thread (the "late" thread) that tries to enter the broken barrier.
        late_thread_raised = False
        def late_thread_func():
            nonlocal late_thread_raised
            try:
                barrier.wait(0)
            except TimeoutError:
                late_thread_raised = True
            except Exception:
                pass # Catch any other exceptions

        thread2 = threading.Thread(target=late_thread_func)
        thread2.start()
        thread2.join(0.1) # Give it a chance to run.

        # Assert that the late thread raised the exception.
        self.assertFalse(thread2.is_alive())
        self.assertTrue(late_thread_raised, "The late thread should have raised a TimeoutError.")


if __name__ == "__main__":
    unittest.main(argv=['first-arg-is-ignored'], exit=False)