import unittest
import threading
import time
from thread_factory.synchronization.primitives.threshold_semaphore import ThresholdSemaphore


class TestThresholdSemaphore(unittest.TestCase):

    def test_threads_are_released_at_threshold(self):
        result = []
        barrier = ThresholdSemaphore(threshold=3)

        def worker(i):
            barrier.wait()
            result.append(i)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(sorted(result), [0, 1, 2])

    def test_notify_all_override_unblocks_threads(self):
        barrier = ThresholdSemaphore(threshold=5, reusable=True)
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
        barrier = ThresholdSemaphore(threshold=3, reusable=True)
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
        barrier = ThresholdSemaphore(threshold=10)
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
        barrier = ThresholdSemaphore(threshold=2)
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
        sema = ThresholdSemaphore(threshold=2, reusable=False)
        t1 = threading.Thread(target=sema.wait)
        t2 = threading.Thread(target=sema.wait)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertTrue(sema.is_spent())

    def test_is_spent_returns_false_if_not_triggered(self):
        sema = ThresholdSemaphore(threshold=3, reusable=False)

        def slow_wait():
            sema.wait(timeout=0.2)  # Let it timeout

        t1 = threading.Thread(target=slow_wait)
        t1.start()
        t1.join()

        self.assertFalse(sema.is_spent())

    def test_is_spent_returns_false_if_reusable(self):
        sema = ThresholdSemaphore(threshold=2, reusable=True)
        t1 = threading.Thread(target=sema.wait)
        t2 = threading.Thread(target=sema.wait)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertFalse(sema.is_spent())  # Because it resets automatically

    def test_error_if_threshold_reached_but_not_reusable(self):
        barrier = ThresholdSemaphore(threshold=2, reusable=False)
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
        barrier = ThresholdSemaphore(threshold=3, manual_release=True)
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
        barrier = ThresholdSemaphore(threshold=2, reusable=True, manual_release=True)
        results = []

        def worker(i):
            for _ in range(2):
                barrier.wait()
                results.append(i)

        t1 = threading.Thread(target=worker, args=(1,))
        t2 = threading.Thread(target=worker, args=(2,))

        t1.start()
        t2.start()

        time.sleep(0.1)
        barrier.release()  # Round 1
        time.sleep(0.1)
        barrier.release()  # Round 2

        t1.join()
        t2.join()

        self.assertEqual(len(results), 4)

    def test_release_does_nothing_if_threshold_not_met(self):
        barrier = ThresholdSemaphore(threshold=3, manual_release=True)
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

    def test_callback_fires_only_once_on_manual_release(self):
        called = {"count": 0}

        def cb():
            called["count"] += 1

        barrier = ThresholdSemaphore(threshold=2, manual_release=True, callback=cb)

        threads = [
            threading.Thread(target=barrier.wait)
            for _ in range(2)
        ]
        for t in threads:
            t.start()

        time.sleep(0.1)
        barrier.release()

        for t in threads:
            t.join()

        self.assertEqual(called["count"], 1)

    def test_notify_all_override_respects_manual_mode(self):
        barrier = ThresholdSemaphore(threshold=4, manual_release=True)
        results = []

        def worker(i):
            out = barrier.wait()
            results.append(i)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()

        time.sleep(0.1)
        barrier.notify_all_override()

        for t in threads:
            t.join()

        self.assertCountEqual(results, [0, 1, 2, 3])

    def test_callback_only_triggers_once_in_reusable_false(self):
        call_count = {"count": 0}

        def cb():
            call_count["count"] += 1

        barrier = ThresholdSemaphore(threshold=3, reusable=False, callback=cb)

        threads = [
            threading.Thread(target=barrier.wait)
            for _ in range(3)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(call_count["count"], 1)

        # Second round, should not trigger
        t = threading.Thread(target=barrier.wait, args=(), kwargs={"timeout": 0.1})
        t.start()
        t.join()

        self.assertEqual(call_count["count"], 1)  # Still 1

    def test_timeout_behavior(self):
        barrier = ThresholdSemaphore(threshold=3)
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

        def callback():
            flag["called"] = True

        barrier = ThresholdSemaphore(threshold=2, callback=callback)

        t1 = threading.Thread(target=barrier.wait)
        t2 = threading.Thread(target=barrier.wait)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertTrue(flag["called"])

    def test_reusable_threshold(self):
        barrier = ThresholdSemaphore(threshold=2, reusable=True)
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
        barrier = ThresholdSemaphore(threshold=3)
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

    def test_threads_are_released_at_threshold(self):
        result = []
        barrier = ThresholdSemaphore(threshold=3)

        def worker(i):
            barrier.wait()
            result.append(i)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(sorted(result), [0, 1, 2])

    def test_notify_all_override_unblocks_threads(self):
        barrier = ThresholdSemaphore(threshold=5, reusable=True)
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
        barrier = ThresholdSemaphore(threshold=3, reusable=True)
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
        barrier = ThresholdSemaphore(threshold=10)
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
        barrier = ThresholdSemaphore(threshold=2)
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
        sema = ThresholdSemaphore(threshold=2, reusable=False)
        t1 = threading.Thread(target=sema.wait)
        t2 = threading.Thread(target=sema.wait)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertTrue(sema.is_spent())

    def test_is_spent_returns_false_if_not_triggered(self):
        sema = ThresholdSemaphore(threshold=3, reusable=False)

        def slow_wait():
            sema.wait(timeout=0.2)  # Let it timeout

        t1 = threading.Thread(target=slow_wait)
        t1.start()
        t1.join()

        self.assertFalse(sema.is_spent())

    def test_is_spent_returns_false_if_reusable(self):
        sema = ThresholdSemaphore(threshold=2, reusable=True)
        t1 = threading.Thread(target=sema.wait)
        t2 = threading.Thread(target=sema.wait)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertFalse(sema.is_spent())  # Because it resets automatically

    def test_error_if_threshold_reached_but_not_reusable(self):
        barrier = ThresholdSemaphore(threshold=2, reusable=False)
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
        barrier = ThresholdSemaphore(threshold=3, manual_release=True)
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
        barrier = ThresholdSemaphore(threshold=2, reusable=True, manual_release=True)
        results = []

        def worker(i):
            for _ in range(2):
                barrier.wait()
                results.append(i)

        t1 = threading.Thread(target=worker, args=(1,))
        t2 = threading.Thread(target=worker, args=(2,))

        t1.start()
        t2.start()

        time.sleep(0.1)
        barrier.release()  # Round 1
        time.sleep(0.1)
        barrier.release()  # Round 2

        t1.join()
        t2.join()

        self.assertEqual(len(results), 4)

    def test_release_does_nothing_if_threshold_not_met(self):
        barrier = ThresholdSemaphore(threshold=3, manual_release=True)
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

    def test_callback_fires_only_once_on_manual_release(self):
        called = {"count": 0}

        def cb():
            called["count"] += 1

        barrier = ThresholdSemaphore(threshold=2, manual_release=True, callback=cb)

        threads = [
            threading.Thread(target=barrier.wait)
            for _ in range(2)
        ]
        for t in threads:
            t.start()

        time.sleep(0.1)
        barrier.release()

        for t in threads:
            t.join()

        self.assertEqual(called["count"], 1)

    def test_notify_all_override_respects_manual_mode(self):
        barrier = ThresholdSemaphore(threshold=4, manual_release=True)
        results = []

        def worker(i):
            out = barrier.wait()
            results.append(i)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()

        time.sleep(0.1)
        barrier.notify_all_override()

        for t in threads:
            t.join()

        self.assertCountEqual(results, [0, 1, 2, 3])

    def test_callback_only_triggers_once_in_reusable_false(self):
        call_count = {"count": 0}

        def cb():
            call_count["count"] += 1

        barrier = ThresholdSemaphore(threshold=3, reusable=False, callback=cb)

        threads = [
            threading.Thread(target=barrier.wait)
            for _ in range(3)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(call_count["count"], 1)

        # Second round, should not trigger
        t = threading.Thread(target=barrier.wait, args=(), kwargs={"timeout": 0.1})
        t.start()
        t.join()

        self.assertEqual(call_count["count"], 1)  # Still 1

    def test_timeout_behavior(self):
        barrier = ThresholdSemaphore(threshold=3)
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

        def callback():
            flag["called"] = True

        barrier = ThresholdSemaphore(threshold=2, callback=callback)

        t1 = threading.Thread(target=barrier.wait)
        t2 = threading.Thread(target=barrier.wait)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertTrue(flag["called"])

    def test_reusable_threshold(self):
        barrier = ThresholdSemaphore(threshold=2, reusable=True)
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
        barrier = ThresholdSemaphore(threshold=3)
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

    def test_set_threshold_triggers_early_release(self):
        """
        Tests that changing the threshold mid-wait releases threads immediately.
        """
        initial_threshold = 5
        new_threshold = 2
        semaphore = ThresholdSemaphore(threshold=initial_threshold)
        results = []

        def worker():
            results.append(semaphore.wait())

        threads = [threading.Thread(target=worker) for _ in range(initial_threshold)]
        for t in threads:
            t.start()

        # Let some threads enter but not enough to trigger the initial threshold
        time.sleep(0.1)

        # Change the threshold to a value that is already met by the current count
        semaphore.set_threshold(new_threshold)

        # All threads should be released immediately
        for t in threads:
            t.join(timeout=1)

        self.assertEqual(len(results), initial_threshold)
        self.assertTrue(all(results))  # Check that they all returned True

    def test_set_threshold_with_manual_release(self):
        """
        Tests that changing the threshold does not trigger an auto-release
        when the semaphore is in manual mode.
        """
        semaphore = ThresholdSemaphore(threshold=5, manual_release=True)
        results = []

        def worker():
            results.append(semaphore.wait())

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()

        # Threads should be waiting and not released
        time.sleep(0.1)

        # Change threshold to a value that is already met
        semaphore.set_threshold(3)

        # The threads should still be blocked
        self.assertEqual(len(results), 0)

        # Now, manually release them
        semaphore.release()

        for t in threads:
            t.join()

        self.assertEqual(len(results), 3)
        self.assertTrue(all(results))

    def test_set_threshold_raises_value_error(self):
        """
        Tests that setting a non-positive threshold raises a ValueError.
        """
        semaphore = ThresholdSemaphore(threshold=5)
        with self.assertRaises(ValueError):
            semaphore.set_threshold(0)
        with self.assertRaises(ValueError):
            semaphore.set_threshold(-1)


    def test_increase_threshold_above_current_count(self):
        """
        Tests that increasing the threshold does not release threads,
        but allows more threads to be added to meet the new threshold.
        """
        initial_threshold = 3
        new_threshold = 5
        sema = ThresholdSemaphore(threshold=initial_threshold)
        results = []

        # Start 3 threads, which will meet the initial threshold and release
        threads_part1 = [threading.Thread(target=lambda: results.append(sema.wait())) for _ in range(initial_threshold)]
        for t in threads_part1: t.start()
        for t in threads_part1: t.join()

        # At this point, the semaphore is spent (reusable=False by default), so change threshold has no effect.
        # To properly test this, we need a reusable semaphore.
        sema_reusable = ThresholdSemaphore(threshold=initial_threshold, reusable=True)
        results_reusable = []

        def worker_reusable():
            results_reusable.append(sema_reusable.wait())

        # Start 2 threads (less than the threshold)
        threads_part1 = [threading.Thread(target=worker_reusable) for _ in range(2)]
        for t in threads_part1: t.start()

        # Wait for them to block
        time.sleep(0.1)
        self.assertEqual(len(results_reusable), 0)  # Should be blocked

        # Now increase the threshold. They should remain blocked.
        sema_reusable.set_threshold(new_threshold)
        time.sleep(0.1)  # Give time for state to update
        self.assertEqual(len(results_reusable), 0)  # Still blocked

        # Now start the remaining threads to meet the new threshold
        threads_part2 = [threading.Thread(target=worker_reusable) for _ in range(new_threshold - 2)]
        for t in threads_part2: t.start()

        # Wait for all threads to finish
        for t in threads_part1 + threads_part2:
            t.join()

        self.assertEqual(len(results_reusable), new_threshold)  # All 5 should be released
        self.assertTrue(all(results_reusable))


if __name__ == '__main__':
    unittest.main()
