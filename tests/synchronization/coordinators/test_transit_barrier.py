import threading
import time
import unittest

from thread_factory.synchronization import TransitBarrier


class TestTransitBarrier(unittest.TestCase):

    def test_threads_are_released_at_threshold(self):
        result = []
        barrier = TransitBarrier(threshold=3)

        def worker(i):
            barrier.wait()
            result.append(i)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(sorted(result), [0, 1, 2])

    class TestTransitBarrierCallback(unittest.TestCase):

        def test_transit_callback_called_by_all_threads(self):
            """
            Ensure every waiting thread executes the transit callback
            when the TransitBarrier reaches its threshold.
            """
            lock = threading.Lock()
            call_count = 0

            def transit():
                nonlocal call_count
                with lock:
                    call_count += 1

            barrier = TransitBarrier(threshold=5, transit=transit)
            threads = [threading.Thread(target=barrier.wait) for _ in range(5)]

            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self.assertEqual(call_count, 5, f"Expected 5 transit calls, got {call_count}")


    def test_notify_all_override_unblocks_threads(self):
        barrier = TransitBarrier(threshold=5, reusable=True)
        results = []

        def worker(i):
            barrier.wait()
            results.append(i)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]

        for t in threads:
            t.start()

        time.sleep(0.1)  # Let threads block
        barrier.notify_all_override()

        for t in threads:
            t.join()

        self.assertEqual(len(results), 5)


    def test_multiple_groups_waiting_serially(self):
        barrier = TransitBarrier(threshold=3, reusable=True)
        result = []

        def worker(group_id):
            barrier.wait()
            result.append(group_id)

        # First group
        t1 = threading.Thread(target=worker, args=(1,))
        t2 = threading.Thread(target=worker, args=(1,))
        t3 = threading.Thread(target=worker, args=(1,))

        # Second group
        t4 = threading.Thread(target=worker, args=(2,))
        t5 = threading.Thread(target=worker, args=(2,))
        t6 = threading.Thread(target=worker, args=(2,))

        for t in [t1, t2, t3]:
            t.start()
        for t in [t1, t2, t3]:
            t.join()

        for t in [t4, t5, t6]:
            t.start()
        for t in [t4, t5, t6]:
            t.join()

        self.assertEqual(result.count(1), 3)
        self.assertEqual(result.count(2), 3)

    def test_high_volume_workers(self):
        barrier = TransitBarrier(threshold=10)
        results = []
        lock = threading.Lock()

        def worker(i):
            barrier.wait()
            with lock:
                results.append(i)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), 10)
        self.assertCountEqual(results, list(range(10)))

    def test_waiters_get_blocked_properly(self):
        barrier = TransitBarrier(threshold=2)
        results = []

        def first():
            results.append("before-1")
            barrier.wait()
            results.append("after-1")

        def second():
            results.append("before-2")
            barrier.wait()
            results.append("after-2")

        t1 = threading.Thread(target=first)
        t2 = threading.Thread(target=second)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(results[:2], ["before-1", "before-2"])
        self.assertCountEqual(results[2:], ["after-1", "after-2"])

    def test_is_spent_returns_true_after_threshold_met_and_not_reusable(self):
        sema = TransitBarrier(threshold=2, reusable=False)
        t1 = threading.Thread(target=sema.wait)
        t2 = threading.Thread(target=sema.wait)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertTrue(sema.is_spent())

    def test_is_spent_returns_false_if_not_triggered(self):
        sema = TransitBarrier(threshold=3, reusable=False)

        def slow_wait():
            sema.wait(timeout=0.2)  # Let it timeout

        t1 = threading.Thread(target=slow_wait)
        t1.start()
        t1.join()

        self.assertFalse(sema.is_spent())

    def test_is_spent_returns_false_if_reusable(self):
        sema = TransitBarrier(threshold=2, reusable=True)
        t1 = threading.Thread(target=sema.wait)
        t2 = threading.Thread(target=sema.wait)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertFalse(sema.is_spent())  # Because it resets automatically

    def test_error_if_threshold_reached_but_not_reusable(self):
        barrier = TransitBarrier(threshold=2, reusable=False)
        result = []

        def early():
            barrier.wait()

        def later():
            out = barrier.wait(timeout=0.2)
            result.append(out)

        t1 = threading.Thread(target=early)
        t2 = threading.Thread(target=early)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Now the barrier has been used once, and reusable is False.

        t3 = threading.Thread(target=later)
        t3.start()
        t3.join()

        self.assertEqual(result[0], False)

    def test_manual_release_blocks_until_called(self):
        barrier = TransitBarrier(threshold=3, manual_release=True)
        released = []

        def worker(i):
            barrier.wait()
            released.append(i)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()

        # Threads should be waiting
        time.sleep(0.1)
        self.assertEqual(len(released), 0)

        # Manual release
        barrier.release()

        for t in threads:
            t.join()

        self.assertCountEqual(released, [0, 1, 2])

    def test_manual_release_with_reusable_true(self):
        barrier = TransitBarrier(threshold=2, reusable=True, manual_release=True)
        results = []
        ready = threading.Barrier(3)  # Main thread + 2 workers

        def worker(i):
            for _ in range(2):
                ready.wait()  # Sync point to ensure both threads reach before we release
                barrier.wait()
                results.append(i)

        t1 = threading.Thread(target=worker, args=(1,))
        t2 = threading.Thread(target=worker, args=(2,))

        t1.start()
        t2.start()

        for _ in range(2):  # Trigger release twice
            ready.wait()  # Wait for both threads to be ready at the barrier
            time.sleep(0.05)  # Ensure wait() has been entered
            barrier.release()  # Manually release the current cycle

        t1.join()
        t2.join()

        self.assertEqual(len(results), 4)

    def test_release_does_nothing_if_threshold_not_met(self):
        barrier = TransitBarrier(threshold=3, manual_release=True)
        result = []

        def worker():
            result.append(barrier.wait(timeout=0.3))

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()

        time.sleep(0.1)
        barrier.release()  # Should NOT release anything

        for t in threads:
            t.join()

        self.assertEqual(result, [False, False])

    def test_callback_increments_count_by_threads(self):
        call_info = {"count": 0}
        lock = threading.Lock()
        num_threads = 5

        # The transit action is now correctly called by all threads that pass the barrier.
        barrier = TransitBarrier(threshold=num_threads, transit=lambda: self._increment_count(call_info, lock))

        threads = [threading.Thread(target=barrier.wait) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # FIX: The assertion should expect 'num_threads' calls, not 'num_threads - 1'.
        self.assertEqual(call_info["count"], num_threads)

    def _increment_count(self, call_info, lock):
        with lock:
            call_info["count"] += 1

    def test_wait_times_out_correctly(self):
        barrier = TransitBarrier(threshold=2)  # Set threshold to 2, but only use one thread.
        start_time = time.time()
        timed_out = False

        def worker():
            nonlocal timed_out
            timed_out = not barrier.wait(timeout=0.5)  # Short timeout

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        end_time = time.time()

        self.assertTrue(timed_out, "wait() should have timed out.")
        self.assertGreaterEqual(end_time - start_time, 0.5, "wait() timeout was too short.")
        self.assertLess(end_time - start_time, 0.6, "wait() timeout was too long.")  # Accept a small buffer.


    def test_callback_triggers_on_woken_threads_on_manual_release(self):
        called = {"count": 0}

        def cb():
            called["count"] += 1

        barrier = TransitBarrier(threshold=2, manual_release=True, transit=cb)
        threads = [threading.Thread(target=barrier.wait) for _ in range(2)]
        for t in threads: t.start()
        time.sleep(0.1)
        barrier.release()
        for t in threads: t.join()
        # Corrected assertion: Two threads are woken up, so the callback runs twice.
        self.assertEqual(called["count"], 2)

    # CORRECTION: This test's assertion was incorrect.
    # The callback runs on each thread that is woken up.
    # With a threshold of 3, 2 threads are woken up (the 3rd thread triggers it and returns).
    def test_callback_triggers_on_woken_threads_in_reusable_false(self):
        call_count = {"count": 0}

        def cb():
            call_count["count"] += 1

        barrier = TransitBarrier(threshold=3, reusable=False, transit=cb)

        threads = [
            threading.Thread(target=barrier.wait)
            for _ in range(3)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # FIX: With a threshold of 3, all 3 threads should execute the callback.
        self.assertEqual(call_count["count"], 3)

        # Second round, should not trigger as the barrier is not reusable
        t = threading.Thread(target=barrier.wait, args=(), kwargs={"timeout": 0.1})
        t.start()
        t.join()

        self.assertEqual(call_count["count"], 3)  # Still 3
    def test_timeout_behavior(self):
        barrier = TransitBarrier(threshold=3)
        result = []

        def worker():
            outcome = barrier.wait(timeout=0.2)
            result.append(outcome)

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        self.assertEqual(result[0], False)

    def test_callback_triggered(self):
        flag = {"called": False}
        lock = threading.Lock()

        def callback():
            with lock:
                flag["called"] = True

        barrier = TransitBarrier(threshold=2, transit=callback)

        t1 = threading.Thread(target=barrier.wait)
        t2 = threading.Thread(target=barrier.wait)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertTrue(flag["called"])

    def test_reusable_threshold(self):
        barrier = TransitBarrier(threshold=2, reusable=True)
        counter = []

        def worker():
            for _ in range(2):
                barrier.wait()
                counter.append(1)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(len(counter), 4)

    def test_dispose_interrupts_waiters(self):
        barrier = TransitBarrier(threshold=3)
        result = []

        def waiter():
            out = barrier.wait(timeout=2)
            result.append(out)

        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.1)
        barrier.dispose()
        t.join()

        self.assertFalse(result[0])