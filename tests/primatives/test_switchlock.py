import unittest
import threading
import time
import random

# Replace this import with your actual SwitchLock path
from thread_factory.primatives import SwitchLock

class Worker(threading.Thread):
    """
    A custom Thread that assigns a random large integer for factory_id by default.
    If you want a specific factory_id (e.g. 42), pass factory_id=42 to the constructor.
    """
    def __init__(self, factory_id=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if factory_id is None:
            # Generate a random "big" integer for testing
            factory_id = random.randint(1_000_000_000, 9_999_999_999)
        self.factory_id = factory_id

def setUpModule():
    """
    Called once before any tests in this file run.
    We ensure the main test-running thread has a .factory_id attribute.
    """
    main_thr = threading.current_thread()
    if not hasattr(main_thr, 'factory_id'):
        # pick any default, e.g. 0 or a random big int
        main_thr.factory_id = random.randint(1_000_000_000, 9_999_999_999)

class TestSwitchLockNew(unittest.TestCase):


    def test_init_negative_value_raises(self):
        """Ensure negative initial values raise an exception."""
        with self.assertRaises(ValueError):
            SwitchLock(value=-1)

    def test_init_zero_acquire_block(self):
        """
        Starting with value=0 => an immediate acquire() should block and
        not succeed unless we release or increase permits.
        """
        lock = SwitchLock(value=0)
        acquired = [False]

        def attempt_acquire():
            acq = lock.acquire(timeout=0.2)
            acquired[0] = acq

        # Use Worker instead of threading.Thread
        t = Worker(target=attempt_acquire)
        t.start()
        time.sleep(0.1)

        # Thread should still be blocked => no permit
        self.assertFalse(acquired[0], "Should not have acquired yet.")
        lock.release()  # now 1 permit
        t.join()
        self.assertTrue(acquired[0], "Should eventually acquire after release.")

    def test_basic_single_permit(self):
        """Simple test with a single permit => one acquire is immediate; second blocks."""
        lock = SwitchLock(value=1)

        # 1st acquire => immediate
        self.assertTrue(lock.acquire(blocking=False), "Should succeed with 1 available permit")

        # 2nd acquire => no permit left, non-blocking => should fail
        self.assertFalse(lock.acquire(blocking=False), "Should fail; no permits left")

        # Now release => 1 permit again
        lock.release()
        self.assertTrue(lock.acquire(blocking=False), "Should succeed again after release")

    def test_acquire_timeout(self):
        """Ensure we can time out when no permits are available."""
        lock = SwitchLock(value=0)
        start_time = time.time()
        got_it = lock.acquire(timeout=0.3)
        end_time = time.time()

        self.assertFalse(got_it, "Should time out if no release occurs.")
        self.assertGreaterEqual(end_time - start_time, 0.3,
                                "Acquire should block for ~0.3 seconds before returning False")

    def test_increase_then_acquire(self):
        """Test that increasing permits unblocks a waiting thread."""
        lock = SwitchLock(value=0)
        acquired_flag = [False]

        def blocking_acquire():
            with lock:  # context manager => acquire
                acquired_flag[0] = True

        t = Worker(target=blocking_acquire)
        t.start()
        time.sleep(0.1)
        self.assertFalse(acquired_flag[0], "Thread should still be blocked (no permits).")

        lock.increase_permits(1)  # Now there's 1 permit
        t.join(timeout=1)
        self.assertTrue(acquired_flag[0], "Thread should have acquired after increase.")

    def test_decrease_permits_check(self):
        """Ensure decreasing permits is reflected and doesn't go below zero."""
        lock = SwitchLock(value=2)
        lock.acquire()  # consume 1 => left with 1
        self.assertTrue(lock.acquire(blocking=False), "Should still have 1 permit left")

        with self.assertRaises(ValueError):
            lock.decrease_permits(n=1)  # can't go from 0 to -1

    def test_targeted_release_wakes_correct_factory_id(self):
        """
        Create multiple threads with different .factory_id, all blocked.
        Release with a specific factory_id => only that thread should wake.
        """
        lock = SwitchLock(value=0)
        results = {}
        threads = []

        def blocking_acquire(fid):
            # No need to set current_thread().factory_id here,
            # because each Worker is already initialized with that fid.
            lock.acquire()
            results[fid] = results.get(fid, 0) + 1

        factory_ids = [1, 1, 2, 3]
        for fid in factory_ids:
            # Provide the factory_id to the Worker constructor
            t = Worker(factory_id=fid, target=blocking_acquire, args=(fid,))
            threads.append(t)
            t.start()

        time.sleep(0.2)
        # Everyone is blocked => check waiting IDs
        waiting_ids = lock.get_all_waiting_factory_ids()
        self.assertEqual(len(waiting_ids), 4, "All 4 threads should be waiting.")
        self.assertEqual(waiting_ids.count(1), 2)

        # Now targeted release => should wake only the ones with fid=1
        lock.release(n=2, factory_ids=1)
        time.sleep(0.2)

        # The threads with .factory_id=1 should have succeeded
        self.assertEqual(results.get(1, 0), 2, "Both factory_id=1 threads should be unblocked.")

        # The others are still blocked => release them globally
        lock.release(n=2)
        for t in threads:
            t.join(timeout=1)
        self.assertEqual(results.get(2, 0), 1, "factory_id=2 should eventually get a permit.")
        self.assertEqual(results.get(3, 0), 1, "factory_id=3 should eventually get a permit.")

    def test_nonblocking_acquire(self):
        """Test the non-blocking scenario with insufficient permits."""
        lock = SwitchLock(value=1)
        # first is immediate
        got_it_1 = lock.acquire(blocking=False)
        self.assertTrue(got_it_1)

        # second => no permits left, fails immediately
        got_it_2 = lock.acquire(blocking=False)
        self.assertFalse(got_it_2)

    def test_dispose_wakes_waiters(self):
        """
        If we call dispose(), all waiting threads should be released
        (even if they cannot acquire a permit).
        """
        lock = SwitchLock(value=0)
        blocked = [False, False]

        def wait_thread(idx):
            blocked[idx] = True
            lock.acquire()
            blocked[idx] = False

        threads = [Worker(target=wait_thread, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()

        time.sleep(1)
        self.assertTrue(all(blocked), "Both threads should be blocked.")

        lock.dispose()  # forcibly wakes waiters
        for t in threads:
            t.join(timeout=1)

        self.assertFalse(any(blocked), "All threads should have been unblocked on dispose.")

    def test_get_all_waiting_factory_ids(self):
        """Check we gather correct .factory_id from blocked threads."""
        lock = SwitchLock(value=0)

        def blocking(fid):
            lock.acquire()

        fids = [42, 42, 99]
        threads = [Worker(factory_id=fid, target=blocking, args=(fid,)) for fid in fids]
        for t in threads:
            t.start()

        time.sleep(0.1)
        waiting_ids = lock.get_all_waiting_factory_ids()
        self.assertEqual(len(waiting_ids), len(fids))
        self.assertEqual(waiting_ids.count(42), 2)
        self.assertIn(99, waiting_ids)

        lock.release(n=3)
        for t in threads:
            t.join(timeout=1)

    def test_concurrent_stress_simple(self):
        """
        Launch multiple threads acquiring/releasing a single lock.
        Just ensures no deadlocks, all eventually succeed.
        """
        lock = SwitchLock(value=3)
        success_count = 0
        success_count_lock = threading.Lock()

        def worker_job():
            nonlocal success_count
            for _ in range(50):
                got_it = lock.acquire(timeout=1)
                if got_it:
                    with success_count_lock:
                        success_count += 1
                    time.sleep(0.002)  # simulate some "work"
                    lock.release()
                else:
                    # If we fail the timeout for any reason, that's a problem
                    with success_count_lock:
                        success_count -= 100  # indicate major error

        threads = [Worker(target=worker_job) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # We expect each thread to do 50 acquisitions => total 500
        self.assertEqual(success_count, 500, "All acquisitions should succeed without timeouts.")


if __name__ == '__main__':
    unittest.main()
