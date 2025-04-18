import unittest
import threading
import time
import random
from typing import List
from thread_factory.runtime.worker.worker.worker import Worker
from thread_factory.primatives import SmartCondition  # Example import

class TestSmartCondition(unittest.TestCase):
    def test_basic_wait_notify_single_id(self):
        cond = SmartCondition()
        results: List[str] = []

        def worker():
            # This thread is waiting on a single factory_id=42
            threading.current_thread().factory_id = 42
            with cond:
                cond.wait(timeout=None)  # 'factory_ids' param is removed in your new design
                results.append("woken")

        t = threading.Thread(target=worker)
        t.start()

        # Give the worker time to block in wait()
        time.sleep(0.1)
        self.assertEqual(results, [], "Worker should still be waiting")

        # Notify with a different ID => no wake
        with cond:
            cond.notify(factory_ids=999)
        time.sleep(0.1)
        self.assertEqual(results, [], "Wrong ID notify shouldn't wake the worker")

        # Now notify with ID=42 => worker should wake
        with cond:
            cond.notify(factory_ids=42)
        t.join(timeout=1.0)

        self.assertEqual(results, ["woken"], "Worker should be woken by correct ID")

    def test_wait_timeout(self):
        """Test that wait times out properly when no notify is issued for that ID."""
        cond = SmartCondition()
        results: List[bool] = []

        def worker():
            threading.current_thread().factory_id = 99
            with cond:
                woke = cond.wait(timeout=0.2)
                results.append(woke)

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=1.0)

        # Should time out => return False
        self.assertEqual(results, [False], "Worker should time out")

    def test_notify_all_no_id(self):
        """
        If we don't pass any factory_ids to notify_all,
        it should wake every waiting thread, regardless of their IDs.
        """
        cond = SmartCondition()
        results: List[str] = []

        def worker(i):
            threading.current_thread().factory_id = i
            with cond:
                cond.wait()  # indefinite wait
                results.append(f"worker_{i}_woken")

        threads = [threading.Thread(target=worker, args=(i,)) for i in [10, 20, 30]]
        for t in threads:
            t.start()

        time.sleep(0.1)
        with cond:
            cond.notify_all()  # no factory_ids => wake everyone

        for t in threads:
            t.join()

        self.assertCountEqual(
            results,
            ["worker_10_woken", "worker_20_woken", "worker_30_woken"],
            "All workers should be woken by notify_all with no IDs"
        )

    def test_massive_concurrency_and_wakeups(self):
        cond = SmartCondition()
        num_threads = 50
        results = []

        def worker(i):
            # Each thread picks an ID in [1..5] at random
            fid = random.randint(1, 5)
            threading.current_thread().factory_id = fid
            with cond:
                cond.wait()
                results.append((i, fid))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()

        time.sleep(0.2)

        # Randomly notify_all different IDs
        for fid in random.sample(range(1, 6), 5):
            with cond:
                cond.notify_all(factory_ids=fid)
            time.sleep(0.01)

        for t in threads:
            t.join(timeout=2)

        self.assertEqual(len(results), num_threads, "All threads should have been woken")

    def test_starvation_protection(self):
        """
        Make sure threads with different IDs eventually get woken.
        """
        cond = SmartCondition()
        results = []
        lock = threading.Lock()

        def worker(i, fid):
            threading.current_thread().factory_id = fid
            with cond:
                cond.wait()
            with lock:
                results.append(fid)

        fids = [1] * 3 + [2] * 3 + [3] * 3
        threads = [threading.Thread(target=worker, args=(i, fid)) for i, fid in enumerate(fids)]
        for t in threads:
            t.start()

        time.sleep(0.1)

        # Notify ID=1 first
        with cond:
            cond.notify_all(factory_ids=1)
        time.sleep(0.1)

        # Then ID=3
        with cond:
            cond.notify_all(factory_ids=3)
        time.sleep(0.1)

        # Finally ID=2
        with cond:
            cond.notify_all(factory_ids=2)

        for t in threads:
            t.join(timeout=1)

        self.assertCountEqual(results, fids, "All IDs should eventually be woken (no starvation)")

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
            # single ID => 1
            threading.current_thread().factory_id = 1
            with cond:
                cond.wait()
            log.append("woken")

        thread = threading.Thread(target=waiter)
        thread.start()
        time.sleep(0.1)
        recursive_notify(3)
        thread.join(timeout=1)

        self.assertIn("woken", log, "Thread should wake after deep recursion")

    def test_get_all_waiting_factory_ids(self):
        cond = SmartCondition()
        results = []

        def blocking_thread(fid):
            threading.current_thread().factory_id = fid
            with cond:
                cond.wait()
            results.append(fid)

        threads = [threading.Thread(target=blocking_thread, args=(fid,)) for fid in [42, 42, 99, 123]]
        for t in threads:
            t.start()

        time.sleep(0.1)  # Let them all block

        with cond:
            ids = cond.get_all_waiting_factory_ids()
            self.assertEqual(sorted(ids), [42, 42, 99, 123])
            self.assertEqual(ids.count(42), 2)
            self.assertIn(99, ids)
            self.assertIn(123, ids)

            # Wake them all
            cond.notify_all()

        for t in threads:
            t.join()
        self.assertEqual(len(results), 4)

if __name__ == '__main__':
    unittest.main()
