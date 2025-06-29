import unittest
import threading
import time
from thread_factory.primitives.conductor import SynchronizedSignalSemaphore


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
        self.assertTrue(sema.is_spent(), "Semaphore should be spent after a timeout.")

    # =================================================================
    # ===== NEW TESTS FOR CALLBACK FUNCTIONALITY =====
    # =================================================================

    def test_single_callback_is_executed(self):
        """
        Tests that passing a single function to `callback` works correctly.
        """
        results = []
        # Pass a single lambda function
        sema = SynchronizedSignalSemaphore(threshold=2, callback=lambda: results.append("fired"))

        def worker():
            sema.wait()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Assert that the single callback was executed
        self.assertEqual(results, ["fired"])
        self.assertTrue(sema.is_spent())

    def test_list_of_callbacks_are_all_executed(self):
        """
        Tests that passing a list of functions to `callback` results in all of them being executed.
        """
        results = []
        # Pass a list of two lambda functions
        callbacks = [
            lambda: results.append("cb1_fired"),
            lambda: results.append("cb2_fired")
        ]
        sema = SynchronizedSignalSemaphore(threshold=2, callback=callbacks)

        def worker():
            sema.wait()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Use assertCountEqual because the order of execution is not guaranteed
        self.assertCountEqual(results, ["cb1_fired", "cb2_fired"])
        self.assertTrue(sema.is_spent())

    def test_exception_in_one_callback_does_not_stop_others(self):
        """
        Tests that if one callback in a list raises an exception, the others still run.
        """
        results = []

        def faulty_callback():
            raise ValueError("This is a test exception")

        def working_callback():
            results.append("ok")

        # Create a list with a faulty callback and a working one
        callbacks = [faulty_callback, working_callback]
        sema = SynchronizedSignalSemaphore(threshold=1, callback=callbacks)

        def worker():
            sema.wait()

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        # Assert that the working callback still completed its job, even though the other failed.
        self.assertEqual(results, ["ok"])

    # =================================================================
    # ===== END OF NEW TESTS =====
    # =================================================================


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
        self.assertEqual(sema._count, 0)

    def test_late_thread_raises_exception_on_broken_timeout(self):
        """
        Tests that a thread entering an already-timed-out semaphore immediately raises an exception.
        """
        sema = SynchronizedSignalSemaphore(threshold=2, timeout=0.1, raise_on_timeout=True)

        def first_worker():
            try:
                sema.wait()
            except TimeoutError:
                pass

        t1 = threading.Thread(target=first_worker)
        t1.start()
        t1.join(0.5)

        self.assertFalse(t1.is_alive())
        self.assertTrue(sema._released)

        def late_worker(raised_flag):
            try:
                sema.wait()
            except TimeoutError:
                raised_flag["status"] = True

        late_thread_raised_flag = {"status": False}
        t2 = threading.Thread(target=late_worker, args=(late_thread_raised_flag,))
        t2.start()
        t2.join(0.1)

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

        time.sleep(0.1)
        sema.dispose()
        t.join(0.5)

        self.assertFalse(t.is_alive())
        self.assertEqual(result, [False])

    def test_count_decrements_after_timeout(self):
        sema = SynchronizedSignalSemaphore(threshold=2, timeout=0.1)

        def worker():
            sema.wait()

        t1 = threading.Thread(target=worker)
        t1.start()
        time.sleep(0.5)

        self.assertEqual(sema._count, 0)
        self.assertFalse(t1.is_alive())

    def test_reusable_after_timeout_and_reset(self):
        sema = SynchronizedSignalSemaphore(threshold=2, reusable=True, timeout=0.1)

        def worker1():
            return sema.wait()

        t1 = threading.Thread(target=worker1)
        t1.start()
        t1.join(0.5)

        self.assertFalse(t1.is_alive())
        self.assertEqual(sema._count, 0)
        self.assertFalse(sema._released)

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
        self.assertEqual(sema._count, 0)

    def test_notify_all_override_unblocks_threads(self):
        sema = SynchronizedSignalSemaphore(threshold=5, reusable=True)
        results = []

        def worker(i):
            sema.wait()
            results.append(i)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        time.sleep(0.1)
        sema.notify_all_override()
        for t in threads:
            t.join()

        self.assertEqual(len(results), 5)


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)