import unittest
import threading
import time
import random

# Adjust the import to match wherever your SwitchLock is defined.
# from my_module import SwitchLock
from thread_factory.primatives import SwitchLock  # Example import

class TestSwitchLock(unittest.TestCase):

    def test_init_value(self):
        """Test that the initial value is set correctly and cannot be negative."""
        lock = SwitchLock(value=5)
        self.assertIsNotNone(lock.condition)
        self.assertTrue(lock.acquire(), "Should acquire a permit immediately when value=5")

        with self.assertRaises(ValueError):
            # Negative initial value should raise ValueError
            SwitchLock(value=-1)

    def test_basic_acquire_release(self):
        """Test basic semaphore-like acquire/release with default single permit."""
        lock = SwitchLock(value=1)

        # Should acquire immediately
        acquired = lock.acquire()
        self.assertTrue(acquired, "Should acquire the single available permit")

        # Another thread cannot acquire now unless we release
        result = [None]
        def worker():
            res = lock.acquire(timeout=0.2)
            result[0] = res

        t = threading.Thread(target=worker)
        t.start()
        time.sleep(0.1)
        self.assertIsNone(result[0], "Worker should still be blocked")

        lock.release()
        t.join()
        self.assertTrue(result[0], "Worker should acquire after release")

    def test_increase_permits(self):
        """Test increasing permits dynamically."""
        lock = SwitchLock(value=0)

        def try_acquire(lock, result_list):
            with lock:
                result_list.append("acquired")

        result = []
        t = threading.Thread(target=try_acquire, args=(lock, result))
        t.start()
        time.sleep(0.1)
        self.assertEqual(len(result), 0, "Thread should be blocked, no permits initially")

        lock.increase_permits(n=2)
        t.join(timeout=1)
        self.assertEqual(len(result), 1, "Thread should have acquired after permits increased")

    def test_decrease_permits(self):
        """Test decreasing permits dynamically."""
        lock = SwitchLock(value=3)
        lock.acquire()  # use 1 permit
        self.assertTrue(True, "Acquired one permit, 2 remain")

        # Decreasing more than available => ValueError
        with self.assertRaises(ValueError):
            lock.decrease_permits(n=5)

        # Decreasing within range
        lock.decrease_permits(n=1)  # from 2 -> 1
        # Acquire 2 times now => only 1 permit left, so second acquire will block
        lock.acquire()  # uses the last permit
        result = [None]
        def worker():
            res = lock.acquire(timeout=0.2)
            result[0] = res

        t = threading.Thread(target=worker)
        t.start()
        time.sleep(0.1)
        self.assertIsNone(result[0], "Should still be blocked, no permits remain")

        # Release 1 so that worker can proceed
        lock.release()
        t.join(timeout=1)
        self.assertTrue(result[0], "Worker got the permit after release")

    def test_acquire_timeout(self):
        """Test that acquire times out properly when no permits are available."""
        lock = SwitchLock(value=0)
        start = time.time()
        got_it = lock.acquire(timeout=0.5)
        end = time.time()
        self.assertFalse(got_it, "Should time out waiting for permit")
        self.assertGreaterEqual(end - start, 0.5, "Should wait at least 0.5 seconds")

    def test_acquire_nonblocking(self):
        """
        Test non-blocking acquire (blocking=False).
        Should return False immediately if no permits are available.
        """
        lock = SwitchLock(value=1)
        # Acquire the single permit
        first = lock.acquire(blocking=False)
        self.assertTrue(first, "First acquire should succeed immediately")

        # Second non-blocking acquire should fail
        second = lock.acquire(blocking=False)
        self.assertFalse(second, "Second acquire should fail immediately (no permits left)")

    def test_targeted_wakeups(self):
        """
        Test using factory_ids for targeted acquire/release.
        Worker 1 waits on ID=42, Worker 2 on ID=99.
        We'll only wake one or the other.
        """
        lock = SwitchLock(value=0)
        results = []

        def worker(id_val):
            acquired = lock.acquire(factory_ids=id_val, timeout=2)
            results.append((id_val, acquired))

        t1 = threading.Thread(target=worker, args=(42,))
        t2 = threading.Thread(target=worker, args=(99,))


    def test_massive_concurrent_targeted_race(self):
        """
        Stress test with 100+ threads, mixing factory_ids and random timeouts.
        Ensures SwitchLock doesn’t deadlock and threads honor their target IDs.
        """
        lock = SwitchLock(value=5)
        results = []
        num_threads = 150
        id_pool = list(range(10))  # factory_ids range

        def chaos_worker(i):
            factory_id = random.choice(id_pool)
            timeout = random.uniform(0.2, 1.0)
            acquired = lock.acquire(factory_ids=factory_id, timeout=timeout)
            if acquired:
                # Hold the lock briefly
                time.sleep(random.uniform(0.01, 0.05))
                # 50/50 targeted or global release
                if random.random() < 0.5:
                    lock.release(factory_ids=factory_id)
                else:
                    lock.release()
            results.append((i, factory_id, acquired))

        threads = [threading.Thread(target=chaos_worker, args=(i,)) for i in range(num_threads)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        acquired_count = sum(1 for (_, _, acq) in results if acq)
        self.assertGreaterEqual(acquired_count, 5, f"Expected at least 5 to acquire, got {acquired_count}")
        self.assertEqual(len(results), num_threads, "All threads should have completed")

    def test_targeted_starvation_check(self):
        """
        Ensure that threads targeting IDs aren't starved if permits exist and are released with matching IDs.
        """
        lock = SwitchLock(value=0)
        factory_ids = [100, 101, 102]
        completed = []

        def targeted_worker(fid):
            got_it = lock.acquire(factory_ids=fid, timeout=2)
            completed.append((fid, got_it))

        threads = [threading.Thread(target=targeted_worker, args=(fid,)) for fid in factory_ids]
        for t in threads:
            t.start()

        time.sleep(0.1)  # ensure they're all blocked

        # Notify each ID after delay
        for fid in factory_ids:
            time.sleep(0.1)
            lock.release(factory_ids=fid)

        for t in threads:
            t.join()

        self.assertEqual(len(completed), len(factory_ids), "All targeted workers should complete")
        self.assertTrue(all(success for _, success in completed), "All targeted workers should succeed")

    def test_tight_loop_hammering(self):
        """
        Hammer the lock with rapid-fire acquire and release from multiple threads.
        """
        lock = SwitchLock(value=3)
        permit_counter = 0
        error_flag = False
        lock_guard = threading.Lock()

        def hammer_worker():
            nonlocal permit_counter, error_flag
            for _ in range(100):
                acquired = lock.acquire(timeout=0.5)
                if not acquired:
                    error_flag = True
                    break
                with lock_guard:
                    permit_counter += 1
                time.sleep(0.001)
                lock.release()

        threads = [threading.Thread(target=hammer_worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertFalse(error_flag, "No worker should fail to acquire")
        self.assertEqual(permit_counter, 1000, "All permits should have been acquired and released properly")

    def test_mixed_targeted_and_global_release_fairness(self):
        """
        Tests fairness between threads using factory_ids vs no factory_ids.
        Ensures neither group gets completely starved.
        """
        lock = SwitchLock(value=0)
        results = []
        targeted_ids = [200, 201]
        untargeted_results = []
        targeted_results = []

        def targeted_worker(fid):
            success = lock.acquire(factory_ids=fid, timeout=2)
            targeted_results.append((fid, success))

        def untargeted_worker():
            success = lock.acquire(timeout=2)
            untargeted_results.append(success)

        threads = []
        for _ in range(10):
            threads.append(threading.Thread(target=untargeted_worker))
        for fid in targeted_ids:
            threads.append(threading.Thread(target=targeted_worker, args=(fid,)))

        for t in threads:
            t.start()

        time.sleep(0.2)
        # Release in a fair pattern
        for _ in range(5):
            lock.release()  # Global
            time.sleep(0.05)
        for fid in targeted_ids:
            lock.release(factory_ids=fid)

        for t in threads:
            t.join()

        self.assertTrue(any(t[1] for t in targeted_results), "At least one targeted thread should acquire")
        self.assertTrue(any(untargeted_results), "At least one untargeted thread should acquire")


    def test_switchlock_get_all_waiting_factory_ids(self):
        lock = SwitchLock(value=0)
        results = []

        def worker(fid):
            lock.acquire(factory_ids=fid)
            results.append(fid)

        threads = [threading.Thread(target=worker, args=(fid,)) for fid in [10, 10, 20, 30]]
        for t in threads:
            t.start()

        time.sleep(0.1)  # Let threads block

        ids = lock.get_all_waiting_factory_ids()
        self.assertEqual(sorted(ids), [10, 10, 20, 30])
        self.assertEqual(ids.count(10), 2)
        self.assertIn(20, ids)
        self.assertIn(30, ids)

        lock.release(n=4)  # Wake them all

        for t in threads:
            t.join()

        self.assertEqual(len(results), 4)


if __name__ == "__main__":
    unittest.main()