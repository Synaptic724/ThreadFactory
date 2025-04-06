import unittest
import threading
import time
import random
from typing import List

# Make sure to import your SmartCondition from where you've defined it
# from your_smart_condition_module import SmartCondition
from thread_factory.primatives import SmartCondition  # Example import

class TestSmartCondition(unittest.TestCase):
    def test_basic_wait_notify_single_id(self):
        cond = SmartCondition()
        results: List[str] = []

        def worker():
            with cond:
                # This thread will wait for factory_ids=42
                cond.wait(factory_ids=42)
                results.append("woken")

        t = threading.Thread(target=worker)
        t.start()

        # Give the worker time to start and enter cond.wait()
        time.sleep(0.1)
        # Worker should be blocked
        self.assertEqual(results, [], "Worker should still be waiting")

        # Notify with a different ID => should not wake the worker
        with cond:
            cond.notify(factory_ids=999)
        time.sleep(0.1)
        self.assertEqual(results, [], "Wrong ID notify shouldn't wake the worker")

        # Now notify with ID=42 => should wake up
        with cond:
            cond.notify(factory_ids=42)
        t.join(timeout=1.0)

        self.assertEqual(results, ["woken"], "Worker should be woken by correct ID")

    def test_notify_multiple_ids(self):
        cond = SmartCondition()
        results: List[str] = []

        def worker(ids):
            with cond:
                cond.wait(factory_ids=ids)
                results.append(f"woken_{ids}")

        t1 = threading.Thread(target=worker, args=([1, 2],))
        t2 = threading.Thread(target=worker, args=([2, 3],))
        t1.start()
        t2.start()

        # Let them block
        time.sleep(0.1)
        self.assertEqual(results, [])

        # Notify threads waiting on ID=1 => only t1 should wake
        with cond:
            cond.notify_all(factory_ids=1)
        time.sleep(0.1)
        self.assertEqual(results, ["woken_[1, 2]"])

        # Next, notify threads waiting on ID=3 => t2 should wake
        with cond:
            cond.notify_all(factory_ids=3)
        t1.join()
        t2.join()

        self.assertEqual(results, ["woken_[1, 2]", "woken_[2, 3]"])

    def test_wait_for_predicate(self):
        cond = SmartCondition()
        ready_flag = [False]  # mutable container so we can change inside function

        def worker():
            def predicate():
                return ready_flag[0]

            with cond:
                # Wait until predicate is True
                cond.wait_for(predicate, factory_ids=7)
                # Once awakened because predicate==True, do something
                ready_flag.append("done")

        t = threading.Thread(target=worker)
        t.start()

        # Let thread start and wait
        time.sleep(0.1)
        self.assertEqual(len(ready_flag), 1, "Predicate not met yet")

        # Setting the flag
        with cond:
            ready_flag[0] = True
            # We must notify so that the waiting thread checks the predicate again
            cond.notify_all(factory_ids=7)

        t.join(timeout=1.0)
        self.assertEqual(len(ready_flag), 2, "Worker should have appended 'done'")

    def test_wait_timeout(self):
        cond = SmartCondition()
        results: List[bool] = []

        def worker():
            with cond:
                # Wait with an ID that won't be notified, and a short timeout
                woke = cond.wait(factory_ids=99, timeout=0.2)
                results.append(woke)

        t = threading.Thread(target=worker)
        t.start()

        t.join(timeout=1.0)
        # The worker was never notified with ID=99, so it should time out
        self.assertEqual(results, [False], "Worker should time out and return False")

    def test_notify_all_no_id(self):
        """
        If we don't pass any factory_ids to notify_all,
        it should wake every waiting thread, regardless of their IDs.
        """
        cond = SmartCondition()
        results: List[str] = []

        def worker(i):
            with cond:
                cond.wait(factory_ids=i)
                results.append(f"worker_{i}_woken")

        threads = [threading.Thread(target=worker, args=(i,)) for i in [10, 20, 30]]
        for t in threads:
            t.start()

        # Let them start
        time.sleep(0.1)
        with cond:
            cond.notify_all()  # no IDs => wake everyone

        for t in threads:
            t.join()

        self.assertCountEqual(
            results,
            ["worker_10_woken", "worker_20_woken", "worker_30_woken"],
            "All workers should be woken by notify_all with no IDs"
        )

    def test_massive_concurrency_and_wakeups(self):
        cond = SmartCondition()
        num_threads = 100
        results = []
        threads = []
        ready_event = threading.Event()

        def worker(i):
            factory_id = random.randint(1, 10)
            with cond:
                # Wait until predicate or notify wakes this thread
                cond.wait(factory_ids=factory_id)
                results.append((i, factory_id))

        for i in range(num_threads):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        time.sleep(0.2)

        # Notify all factory_ids, in random order
        for fid in random.sample(range(1, 11), 10):
            with cond:
                cond.notify_all(factory_ids=fid)
            time.sleep(0.01)  # simulate churn

        for t in threads:
            t.join(timeout=2)

        self.assertEqual(len(results), num_threads, "All threads should have been woken")

    def test_predicate_spam_wakeup(self):
        cond = SmartCondition()
        predicate_toggle = [False]
        results = []

        def predicate():
            return predicate_toggle[0]

        def toggle_predicate():
            # Rapidly flip the predicate on/off
            for _ in range(100):
                time.sleep(0.005)
                predicate_toggle[0] = not predicate_toggle[0]
                with cond:
                    cond.notify_all(factory_ids=1)

        def worker(i):
            with cond:
                cond.wait_for(predicate, timeout=1, factory_ids=1)
                results.append(i)

        workers = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        toggler = threading.Thread(target=toggle_predicate)

        for w in workers:
            w.start()
        toggler.start()

        for w in workers:
            w.join(timeout=2)

        self.assertEqual(len(results), 10, "All predicate-based threads should finish")

    def test_starvation_protection(self):
        cond = SmartCondition()
        results = []
        lock = threading.Lock()

        def worker(i, fid):
            with cond:
                # Wait a while with ID that will only be notified late
                cond.wait(factory_ids=fid)
                with lock:
                    results.append(fid)

        fids = [1] * 5 + [2] * 5 + [3] * 5
        threads = [threading.Thread(target=worker, args=(i, fid)) for i, fid in enumerate(fids)]

        for t in threads:
            t.start()

        time.sleep(0.1)

        # Only notify ID 1 initially
        with cond:
            cond.notify_all(factory_ids=1)

        time.sleep(0.2)

        # Then ID 3 (skipping 2 to test starvation risk)
        with cond:
            cond.notify_all(factory_ids=3)

        time.sleep(0.2)

        # Finally wake ID 2
        with cond:
            cond.notify_all(factory_ids=2)

        for t in threads:
            t.join(timeout=1)

        self.assertCountEqual(results, fids, "All IDs should eventually be woken (no starvation)")

    def test_randomized_wakeup_patterns(self):
        cond = SmartCondition()
        num_threads = 50
        factory_groups = [set(random.sample(range(1, 10), random.randint(1, 3))) for _ in range(num_threads)]
        results = []
        lock = threading.Lock()

        def worker(i, fids):
            with cond:
                cond.wait(factory_ids=fids)
                with lock:
                    results.append((i, fids))

        threads = []
        for i in range(num_threads):
            t = threading.Thread(target=worker, args=(i, factory_groups[i]))
            threads.append(t)
            t.start()

        time.sleep(0.1)

        # Notify random groups, simulate chaos
        for _ in range(20):
            with cond:
                random_fids = random.sample(range(1, 10), random.randint(1, 3))
                cond.notify(n=random.randint(1, 5), factory_ids=random_fids)
            time.sleep(0.02)

        for t in threads:
            t.join(timeout=1)

        self.assertEqual(len(results), num_threads, "All randomized wakeup threads should have completed")

    def test_condition_lock_recursion(self):
        cond = SmartCondition()
        log = []

        def recursive_notify(depth):
            if depth == 0:
                with cond:
                    cond.notify_all(factory_ids=1)
                return
            with cond:
                log.append(f"enter-{depth}")
                recursive_notify(depth - 1)
                log.append(f"exit-{depth}")

        def waiter():
            with cond:
                cond.wait(factory_ids=1)
                log.append("woken")

        thread = threading.Thread(target=waiter)
        thread.start()
        time.sleep(0.1)
        recursive_notify(5)
        thread.join(timeout=1)

        self.assertIn("woken", log, "Thread should wake after deep recursion")

    def test_get_all_waiting_factory_ids(self):
        cond = SmartCondition()
        results = []

        def blocking_thread(fid):
            with cond:
                cond.wait(factory_ids=fid)
            results.append(fid)

        threads = [threading.Thread(target=blocking_thread, args=(fid,)) for fid in [42, 42, 99, 123]]
        for t in threads:
            t.start()

        time.sleep(0.1)  # Let all threads block

        with cond:
            ids = cond.get_all_waiting_factory_ids()
            self.assertEqual(sorted(ids), [42, 42, 99, 123])
            self.assertEqual(ids.count(42), 2)
            self.assertIn(99, ids)
            self.assertIn(123, ids)

            cond.notify_all()

        for t in threads:
            t.join()

        self.assertEqual(len(results), 4)


if __name__ == '__main__':
    unittest.main()
