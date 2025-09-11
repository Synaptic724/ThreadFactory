import unittest
import time
import random
from thread_factory import Dynaphore

import threading, atexit

class TestDynaphore(unittest.TestCase):

    def test_basic_acquire_release(self):
        sema = Dynaphore(2)
        self.assertEqual(sema._value, 2)

        acquired = sema.wait_for_permit(timeout=1)
        self.assertTrue(acquired)
        self.assertEqual(sema._value, 1)

        sema.release_permit()
        self.assertEqual(sema._value, 2)

    def test_increase_permits(self):
        sema = Dynaphore(1)
        sema.increase_permits(3)
        self.assertEqual(sema._value, 4)

    def test_decrease_permits(self):
        sema = Dynaphore(8)
        sema.decrease_permits(3)
        self.assertEqual(sema._value, 5)

        with self.assertRaises(ValueError):
            sema.decrease_permits(10)  # 10 > 5 triggers error

    def test_concurrent_acquire_release(self):
        sema = Dynaphore(0)
        acquired_threads = []
        lock = threading.Lock()

        def worker(thread_id):
            if sema.wait_for_permit(timeout=3):
                with lock:
                    acquired_threads.append(thread_id)
                time.sleep(random.uniform(0.1, 0.3))
                sema.release_permit()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads: t.start()

        time.sleep(0.5)
        sema.increase_permits(10)

        for t in threads:
            t.join(timeout=2)

        self.assertEqual(len(acquired_threads), 10)
    # ------------------------------------------------------------------
    #  Additional edge / stress tests
    # ------------------------------------------------------------------

    def test_wait_timeout_returns_false(self):
        sema = Dynaphore(0)
        start = time.perf_counter()
        ok = sema.wait_for_permit(timeout=0.2)
        elapsed = time.perf_counter() - start
        self.assertFalse(ok)
        self.assertGreaterEqual(elapsed, 0.2)

    def test_release_all_wakes_waiters(self):
        sema = Dynaphore(0)
        flag = {'awake': False}

        def waiter():
            if sema.wait_for_permit(timeout=1):
                flag['awake'] = True

        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.1)            # ensure thread is blocked

        sema.release_all()         # notify – thread re-checks predicate
        time.sleep(0.05)           # still blocked (no permits yet)
        self.assertFalse(flag['awake'])

        sema.increase_permits(1)   # now predicate true, thread acquires
        t.join(timeout=1)
        self.assertTrue(flag['awake'])
        self.assertEqual(sema._value, 0)   # 1 was consumed


    def test_pause_and_resume(self):
        sema = Dynaphore(2)
        sema.set_permits(0)                 # logical pause
        ok = sema.wait_for_permit(timeout=0.1)
        self.assertFalse(ok)                # nothing should pass
        sema.increase_permits(1)            # resume with 1
        self.assertTrue(sema.wait_for_permit(timeout=0.1))

    def test_over_release_is_allowed(self):
        sema = Dynaphore(0)
        sema.release_permit(5)              # over-release (never acquired)
        self.assertEqual(sema._value, 5)

    def test_cleanup_unblocks_waiters(self):
        sema = Dynaphore(0)
        released = []

        def w():
            sema.wait_for_permit()
            released.append(True)

        t = threading.Thread(target=w)
        t.start()
        time.sleep(0.1)
        sema.cleanup()          # should wake waiter with False
        t.join(timeout=1)
        self.assertEqual(len(released), 0)  # waiter exits without permit

    def test_high_concurrency_scaling(self):
        sema = Dynaphore(0)
        total  = 100
        passed = []

        def worker():
            if sema.wait_for_permit(timeout=2):
                passed.append(1)
                sema.release_permit()

        threads = [threading.Thread(target=worker) for _ in range(total)]
        for t in threads:
            t.start()

        sema.increase_permits(total)      # open flood-gate

        # --- add bounded join so we never hang -------------
        for t in threads:
            t.join(timeout=3)
            self.assertFalse(t.is_alive(), "worker thread hung")

        self.assertEqual(len(passed), total)

    def test_negative_increase_raises(self):
        sema = Dynaphore(1)
        with self.assertRaises(ValueError):
            sema.increase_permits(-3)

    def test_negative_decrease_raises(self):
        sema = Dynaphore(1)
        with self.assertRaises(ValueError):
            sema.decrease_permits(-1)

    def test_decrease_to_zero_then_resume(self):
        sema = Dynaphore(3)
        sema.decrease_permits(3)            # now zero
        ok = sema.wait_for_permit(timeout=0.1)
        self.assertFalse(ok)
        sema.increase_permits(2)
        self.assertTrue(sema.wait_for_permit(timeout=0.1))

    def test_set_permits_notifies_waiters(self):
        sema = Dynaphore(0)
        woke = []

        def waiter():
            if sema.wait_for_permit(timeout=1):
                woke.append(1)

        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.1)
        sema.set_permits(1)     # should wake waiter
        t.join(timeout=1)
        self.assertEqual(len(woke), 1)


    def test_stress_dynaphore(self):
        sema = Dynaphore(0)
        results = []
        lock = threading.Lock()
        num_threads = 20

        def worker(thread_id):
            if sema.wait_for_permit(timeout=5):
                with lock:
                    results.append(thread_id)
                time.sleep(random.uniform(0.2, 0.5))
                sema.release_permit()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads: t.start()

        for _ in range(5):
            time.sleep(0.5)
            permits = random.randint(5, 10)
            sema.increase_permits(permits)
            try:
                sema.decrease_permits(random.randint(0, permits))
            except ValueError:
                pass  # Expected in some rounds

        for t in threads:
            t.join(timeout=3)

        self.assertEqual(len(results), num_threads)

    def test_set_permits_directly(self):
        sema = Dynaphore(0)
        sema.set_permits(5)
        self.assertEqual(sema._value, 5)

        sema.set_permits(0)
        self.assertEqual(sema._value, 0)

        with self.assertRaises(ValueError):
            sema.set_permits(-1)

@atexit.register
def show_lingering():
    alive = [t for t in threading.enumerate() if t is not threading.main_thread()]
    if alive:
        print("⚠️  Lingering threads:", alive)

if __name__ == '__main__':
    unittest.main()