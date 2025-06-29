import unittest
import threading
import time
from thread_factory.primitives.synchronized_signal_semaphore import SynchronizedSignalSemaphore


class TestSynchronizedSignalSemaphore(unittest.TestCase):

    def test_initialization_with_timeout_and_raise_flag(self):
        sema = SynchronizedSignalSemaphore(
            threshold=1,
            timeout=0.5,
            raise_on_timeout=True
        )
        self.assertEqual(sema._threshold, 1)
        self.assertEqual(sema._timeout, 0.5)
        self.assertTrue(sema._raise_on_timeout)
        self.assertFalse(sema.is_spent())

    def test_threads_are_released_at_threshold(self):
        result = []
        sema = SynchronizedSignalSemaphore(threshold=3)

        def worker(i):
            sema.wait()
            result.append(i)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(sorted(result), [0, 1, 2])
        self.assertTrue(sema.is_spent())  # Should be spent since reusable=False

    def test_timeout_returns_false_by_default(self):
        sema = SynchronizedSignalSemaphore(threshold=2, timeout=0.1)
        result = []

        def worker():
            outcome = sema.wait()
            result.append(outcome)

        t = threading.Thread(target=worker)
        t.start()
        t.join(0.5)  # Wait for a sufficient time

        self.assertFalse(t.is_alive())
        self.assertEqual(result, [False])

    def test_wait_with_raise_on_timeout_raises_exception(self):
        sema = SynchronizedSignalSemaphore(threshold=2, timeout=0.1, raise_on_timeout=True)

        def worker():
            # Use a list to capture the result from the thread
            raised_exception = False
            try:
                sema.wait()
            except TimeoutError:
                raised_exception = True
            return raised_exception

        thread_result = []
        t = threading.Thread(target=lambda: thread_result.append(worker()))
        t.start()
        t.join(0.5)  # Wait long enough for a timeout

        self.assertFalse(t.is_alive())
        self.assertEqual(len(thread_result), 1)
        self.assertTrue(thread_result[0], "TimeoutError was not raised by the waiting thread.")
        # CORRECTED ASSERTION:
        # After a timeout, a non-reusable semaphore is spent because its cycle has concluded (with a failure).
        self.assertTrue(sema.is_spent(), "Semaphore should be spent after a timeout.")

    def test_wait_timeout_argument_overrides_init_timeout(self):
        sema = SynchronizedSignalSemaphore(threshold=2, timeout=2.0)  # long init timeout
        start_time = time.monotonic()

        def worker():
            # This should timeout in 0.1 seconds, not 2.0 seconds
            sema.wait(timeout=0.1)

        t = threading.Thread(target=worker)
        t.start()
        t.join(0.5)
        end_time = time.monotonic()

        self.assertLess(end_time - start_time, 0.5)
        self.assertFalse(t.is_alive())
        self.assertEqual(sema._count, 0)  # Counter should be reset

    def test_late_thread_raises_exception_on_broken_timeout(self):
        """
        Tests that a thread entering an already-timed-out semaphore immediately raises an exception.
        """
        # Create a semaphore that will time out and raise an exception.
        sema = SynchronizedSignalSemaphore(threshold=2, timeout=0.1, raise_on_timeout=True)

        def first_worker():
            # This thread will time out and break the semaphore's internal state.
            try:
                sema.wait()
            except TimeoutError:
                # This thread is expected to time out and raise, so we catch it.
                pass

        # Start the first thread and wait for it to time out.
        t1 = threading.Thread(target=first_worker)
        t1.start()
        t1.join(0.5)

        # Assert that the semaphore is in the expected broken state after the timeout.
        self.assertFalse(t1.is_alive())
        # The semaphore is in a released state to unblock other threads, but it's not 'spent' in the logical sense.
        self.assertTrue(sema._released)

        # Now, start a second thread to enter the "broken" semaphore.
        def late_worker(raised_flag):
            try:
                sema.wait()
            except TimeoutError:
                raised_flag["status"] = True

        late_thread_raised_flag = {"status": False}
        t2 = threading.Thread(target=late_worker, args=(late_thread_raised_flag,))
        t2.start()
        t2.join(0.1)  # Give it time to run the check at the start of wait()

        # Assert that the late thread immediately raised the exception.
        self.assertFalse(t2.is_alive())
        self.assertTrue(late_thread_raised_flag["status"], "Late thread should have raised a TimeoutError.")

    def test_dispose_interrupts_and_does_not_raise_on_timeout(self):
        sema = SynchronizedSignalSemaphore(threshold=2, timeout=1.0, raise_on_timeout=True)
        result = []

        def worker():
            try:
                outcome = sema.wait()
                result.append(outcome)
            except Exception as e:
                result.append(type(e).__name__)

        t = threading.Thread(target=worker)
        t.start()

        time.sleep(0.1)  # Let the thread start waiting
        sema.dispose()
        t.join(0.5)

        self.assertFalse(t.is_alive())
        # The result should be False, not a TimeoutError, because dispose() takes precedence.
        self.assertEqual(result, [False])

    def test_count_decrements_after_timeout(self):
        sema = SynchronizedSignalSemaphore(threshold=2, timeout=0.1)

        def worker():
            sema.wait()

        t1 = threading.Thread(target=worker)
        t1.start()

        # Wait for the thread to timeout and exit the wait() method.
        time.sleep(0.5)

        # The thread's wait() call has exited, so the counter should have been decremented.
        self.assertEqual(sema._count, 0)
        self.assertFalse(t1.is_alive())

    def test_reusable_after_timeout_and_reset(self):
        """
        Tests that a reusable semaphore can be used again after a timeout.
        """
        sema = SynchronizedSignalSemaphore(threshold=2, reusable=True, timeout=0.1)

        # --- First round: Cause a timeout ---
        def worker1():
            return sema.wait()

        t1 = threading.Thread(target=worker1)
        t1.start()
        t1.join(0.5)  # Wait for it to time out

        self.assertFalse(t1.is_alive())
        self.assertEqual(sema._count, 0)  # Counter should have been decremented
        self.assertFalse(sema._released)  # Should have reset after the thread left

        # --- Second round: Use it for a normal release ---
        results = []

        def worker2():
            released = sema.wait()
            results.append(released)

        t2_1 = threading.Thread(target=worker2)
        t2_2 = threading.Thread(target=worker2)

        t2_1.start()
        time.sleep(0.1)
        t2_2.start()

        t2_1.join()
        t2_2.join()

        self.assertCountEqual(results, [True, True])
        self.assertEqual(sema._count, 0)  # Should be reset again

    def test_notify_all_override_unblocks_threads(self):
        sema = SynchronizedSignalSemaphore(threshold=5, reusable=True)
        results = []

        def worker(i):
            sema.wait()
            results.append(i)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]

        for t in threads:
            t.start()

        time.sleep(0.1)  # Let threads block
        sema.notify_all_override()

        for t in threads:
            t.join()

        self.assertEqual(len(results), 5)


if __name__ == '__main__':
    # Use argv=[] to prevent unittest from trying to parse command-line arguments.
    unittest.main(argv=['first-arg-is-ignored'], exit=False)