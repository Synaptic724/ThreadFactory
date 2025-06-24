"""
Full test-suite for SwitchLock – now using DynamicWorker via a small
compatibility wrapper so none of the original test logic had to change.
"""

import threading
import time
import ulid
import unittest
import random
from thread_factory.primatives import SwitchLock
from thread_factory.thread_pool.worker.dynamic_worker import DynamicWorker


# --------------------------------------------------------------------------- #
#  Tiny compatibility layer                                                   #
# --------------------------------------------------------------------------- #
class Worker(DynamicWorker):
    """
    A one-shot façade around DynamicWorker so the legacy tests that expect a
    simple `Worker(target=…, args=…, kwargs=…)` continue to work unchanged.
    """

    def __init__(self, *, target=None, args=(), kwargs=None, name=None):
        super().__init__(name=name)
        self._target = target
        self._args   = args
        self._kwargs = kwargs or {}
        self.set_home(self._run_once_and_quit)

    # ------------------------------------------------------------------ #
    def _run_once_and_quit(self):
        if self._target is not None:
            self._target(*self._args, **self._kwargs)
        self.stop()                       # leave DynamicWorker loop


# --------------------------------------------------------------------------- #
#  Helper utilities                                                           #
# --------------------------------------------------------------------------- #
def wait_for_waiters(lock: SwitchLock, expected: int, timeout: float = 2.0):
    start = time.time()
    while time.time() - start < timeout:
        if len(lock.get_all_waiting_factory_ids()) >= expected:
            return
        time.sleep(0.01)
    raise AssertionError(
        f"Waiters not registered in time. Expected {expected}, "
        f"got {len(lock.get_all_waiting_factory_ids())}"
    )


def _set_thread_factory_id(fid: str):       # kept for completeness
    threading.current_thread().factory_id = fid

# --------------------------------------------------------------------------- #
#  Test-suite                                                                 #
# --------------------------------------------------------------------------- #
class TestSwitchLock(unittest.TestCase):

    # ------------------------------------------------------------------- #
    #  Basic behaviour                                                    #
    # ------------------------------------------------------------------- #
    def test_init_negative_value_raises(self):
        with self.assertRaises(ValueError):
            SwitchLock(value=-1)

    def test_init_zero_acquire_block(self):
        lock = SwitchLock(value=0)
        ev   = threading.Event()

        def attempt():
            if lock.acquire(timeout=0.5):
                ev.set()

        t = Worker(target=attempt)
        t.start()
        wait_for_waiters(lock, 1)
        lock.release()
        t.join(timeout=1)
        self.assertTrue(ev.wait(timeout=1))

    # ------------------------------------------------------------------- #
    #  Permit manipulation                                                #
    # ------------------------------------------------------------------- #
    def test_permit_increase_unblocks_thread(self):
        lock = SwitchLock(value=0)
        done = threading.Event()
        out = []

        def wait_and_append():
            with lock:
                out.append("done")
                done.set()

        t = Worker(target=wait_and_append)
        t.start()
        wait_for_waiters(lock, 1)
        lock.increase_permits(1)
        self.assertTrue(done.wait(timeout=1))
        t.join(timeout=1)
        self.assertEqual(out, ["done"])

    # ------------------------------------------------------------------- #
    #  Targeted release & notify                                          #
    # ------------------------------------------------------------------- #
    def test_targeted_release_uses_factory_ids(self):
        lock     = SwitchLock(value=0)
        results  = {}
        threads  = []

        def blocking():
            lock.acquire()
            fid = threading.current_thread().factory_id
            with threading.Lock():
                results[fid] = results.get(fid, 0) + 1

        for _ in range(4):
            t = Worker(target=blocking)
            threads.append(t)
            t.start()

        wait_for_waiters(lock, 4)

        ids   = lock.get_all_waiting_factory_ids()
        group = ids[:2]
        lock.release(n=2, factory_ids=group)
        time.sleep(0.2)

        for fid in group:
            self.assertIn(fid, results)

        lock.release(n=2)  # free the rest
        for t in threads:
            t.join(timeout=1)
            self.assertFalse(t.is_alive())
        self.assertEqual(len(results), 4)

    def test_dispose_wakes_waiters(self):
        lock  = SwitchLock(value=0)
        done  = [threading.Event(), threading.Event()]

        def waiter(idx):
            lock.acquire()
            done[idx].set()

        threads = [Worker(target=waiter, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()

        wait_for_waiters(lock, 2)
        lock.dispose()

        for e in done:
            self.assertTrue(e.wait(timeout=1))
        for t in threads:
            t.join(timeout=1)
            self.assertFalse(t.is_alive())

    # ------------------------------------------------------------------- #
    #  Waiting list                                                       #
    # ------------------------------------------------------------------- #
    def test_get_all_waiting_factory_ids(self):
        lock = SwitchLock(value=0)

        def blocking():
            lock.acquire()

        threads = [Worker(target=blocking) for _ in range(3)]
        for t in threads:
            t.start()

        wait_for_waiters(lock, 3)
        waiting = lock.get_all_waiting_factory_ids()
        self.assertEqual(len(waiting), 3)
        for fid in waiting:
            self.assertEqual(len(fid), 26)

        lock.release(n=3)
        for t in threads:
            t.join(timeout=1)
            self.assertFalse(t.is_alive())

    # ------------------------------------------------------------------- #
    #  Release N unblocks N                                               #
    # ------------------------------------------------------------------- #
    def test_release_n_unblocks_n_threads(self):
        lock      = SwitchLock(value=0)
        released  = []
        events    = [threading.Event() for _ in range(5)]

        def waiter(idx, evt):
            if lock.acquire(timeout=2):
                with threading.Lock():
                    released.append(idx)
                evt.set()

        threads = []
        for i in range(5):
            t = Worker(target=waiter, args=(i, events[i]))
            threads.append(t)
            t.start()

        time.sleep(0.2)
        lock.release(n=2)

        self.assertEqual(sum(e.wait(timeout=1) for e in events), 2)
        self.assertEqual(len(released), 2)

        lock.release(n=3)
        for t in threads:
            t.join(timeout=1)
            self.assertFalse(t.is_alive())

    # ------------------------------------------------------------------- #
    #  Targeted release by ULID                                           #
    # ------------------------------------------------------------------- #
    def test_targeted_release_by_ulid(self):
        lock   = SwitchLock(value=0)
        got    = []
        events = [threading.Event() for _ in range(4)]

        def waiter(evt):
            fid = threading.current_thread().factory_id
            if lock.acquire(timeout=2):
                with threading.Lock():
                    got.append(fid)
                evt.set()

        threads = []
        for i in range(4):
            t = Worker(target=waiter, args=(events[i],), name=f"TestWorker-{i}")
            threads.append(t)
            t.start()

        time.sleep(0.2)
        wait_for_waiters(lock, 4)

        targets = lock.get_all_waiting_factory_ids()[:2]
        lock.release(n=2, factory_ids=targets)

        self.assertEqual(sum(e.wait(timeout=1) for e in events), 2)
        self.assertEqual(len(got), 2)
        self.assertCountEqual(got, targets)

        lock.release(n=2)
        for t in threads:
            t.join(timeout=1)
            self.assertFalse(t.is_alive())

    def test_release_excessive_does_not_corrupt_state(self):
        lock = SwitchLock(value=1)
        results = []

        def work():
            if lock.acquire(timeout=1):
                results.append("acquired")
                lock.release()
                lock.release()  # excessive release to simulate over-permit

        t = Worker(target=work)
        t.start()
        t.join(timeout=1)

        self.assertIn("acquired", results)
        self.assertEqual(lock._value, 2)  # May want to enforce upper cap later

    def test_acquire_from_non_dynamic_worker_raises(self):
        lock = SwitchLock(value=1)

        def try_acquire():
            with self.assertRaises(RuntimeError):
                lock.acquire()

        t = threading.Thread(target=try_acquire)
        t.start()
        t.join(timeout=1)
        self.assertFalse(t.is_alive())

    def test_return_home_not_called_if_permit_immediately_available(self):
        lock = SwitchLock(value=1, return_home_on_block=True)
        flag = threading.Event()

        class SneakyWorker(DynamicWorker):
            def __init__(self):
                super().__init__(name="Sneaky")
                self.set_home(self._work)

            def return_home(self):
                flag.set()

            def _work(self):
                # Permit is available, should not block, so return_home should not fire
                if lock.acquire(timeout=1):
                    time.sleep(0.1)
                    lock.release()
                    self.stop()

        w = SneakyWorker()
        w.start()
        w.join(timeout=1)
        self.assertFalse(flag.is_set(), "return_home should NOT have been triggered.")

    def test_permit_exhaustion_recovery(self):
        lock = SwitchLock(value=1)
        count = 0
        barrier = threading.Barrier(2)

        def run():
            nonlocal count
            for _ in range(50):
                if lock.acquire(timeout=1):
                    count += 1
                    time.sleep(0.005)
                    lock.release()
                barrier.wait()  # Force racey contention

        t1 = Worker(target=run)
        t2 = Worker(target=run)
        t1.start()
        t2.start()
        t1.join(timeout=2)
        t2.join(timeout=2)
        self.assertEqual(count, 100)

    def test_notify_with_awaited_caller_executes_in_target_thread(self):
        lock = SwitchLock(value=0)
        owner = []

        def cb():
            owner.append(threading.current_thread().name)

        def waiter():
            lock.set_callback(threading.current_thread().factory_id, cb)
            lock.acquire()
            lock.release()

        t = Worker(target=waiter, name="AwaitedCallerTest")
        t.start()
        wait_for_waiters(lock, 1)
        lock.notify(n=1, awaited_caller=True)
        t.join(timeout=1)
        self.assertIn("AwaitedCallerTest", owner)

    def test_callback_exception_is_handled(self):
        lock = SwitchLock(value=0)

        def bad_cb():
            raise RuntimeError("Boom")

        def waiter():
            lock.set_default_callback(bad_cb)
            lock.acquire()
            lock.release()

        t = Worker(target=waiter)
        t.start()
        wait_for_waiters(lock, 1)
        # Should not crash, even if callback throws
        lock.notify()
        t.join(timeout=1)
        self.assertFalse(t.is_alive())

    def test_dispose_during_acquire_returns_false(self):
        lock = SwitchLock(value=0)

        result = []

        def wait():
            result.append(lock.acquire(timeout=1))

        t = Worker(target=wait)
        t.start()
        wait_for_waiters(lock, 1)
        time.sleep(0.1)
        lock.dispose()
        t.join(timeout=2)
        self.assertIn(False, result)

    # ------------------------------------------------------------------- #
    #  Notify all                                                         #
    # ------------------------------------------------------------------- #
    def test_notify_all_threads(self):
        lock   = SwitchLock(value=0)
        events = []

        def waiter(evt):
            if lock.acquire(timeout=2):
                evt.set()

        threads = []
        for _ in range(4):
            ev = threading.Event()
            events.append(ev)
            t  = Worker(target=waiter, args=(ev,))
            threads.append(t)
            t.start()

        time.sleep(0.2)
        wait_for_waiters(lock, 4)

        lock.release(n=4)
        self.assertTrue(all(e.wait(timeout=1) for e in events))

        for t in threads:
            t.join(timeout=1)
            self.assertFalse(t.is_alive())

    # ------------------------------------------------------------------- #
    #  Simple concurrent stress test                                      #
    # ------------------------------------------------------------------- #
    def test_concurrent_stress_simple(self):
        num_threads = 10
        ops_per_thr = 50
        total_ops   = num_threads * ops_per_thr

        lock     = SwitchLock(value=num_threads // 2)
        counter  = 0
        c_lock   = threading.Lock()
        events   = [threading.Event() for _ in range(num_threads)]

        def job(evt):
            nonlocal counter
            for _ in range(ops_per_thr):
                if lock.acquire(timeout=1):
                    try:
                        time.sleep(0.001)
                        with c_lock:
                            counter += 1
                    finally:
                        lock.release()
            evt.set()

        threads = [Worker(target=job, args=(events[i],), name=f"Stress-{i}")
                   for i in range(num_threads)]

        start = time.perf_counter()
        for t in threads:
            t.start()

        self.assertTrue(all(e.wait(timeout=5) for e in events))
        end = time.perf_counter()

        for t in threads:
            t.join(timeout=1)
            self.assertFalse(t.is_alive())

        print(f"\n--- Stress simple --- "
              f"time={end-start:.3f}s  ops={counter}")

        self.assertEqual(counter, total_ops)

# --------------------------------------------------------------------------- #
#  Test-suite                                                                 #
# --------------------------------------------------------------------------- #
class TestSwitchLock2(unittest.TestCase):

    #  … ALL THE PREVIOUS TESTS ARE UNCHANGED …
    #  (omitted here for brevity – keep the ones you already have!)
    #  ------------------------------------------------------------------- #

    # ===================================================================== #
    #  NEW   –  return_home behaviour                                       #
    # ===================================================================== #
    def test_return_home_called_for_dynamic_worker(self):
        """
        When return_home_on_block=True and a DynamicWorker blocks on acquire,
        its custom `return_home` method must be invoked.
        """
        lock   = SwitchLock(value=0, return_home_on_block=True)
        fired  = threading.Event()

        class HomeyWorker(DynamicWorker):
            def __init__(self):
                super().__init__(name="Homey")
                self.set_home(self._home)

            # called from SwitchLock when blocked
            def return_home(self):
                fired.set()
                # (optional) you could do more “go-home” logic here

            def _home(self):
                # will block for a bit, then caller (test) will release
                lock.acquire()
                lock.release()
                self.stop()

        w = HomeyWorker()
        w.start()

        # make sure the worker reaches the wait state and return_home fires
        wait_for_waiters(lock, 1)
        self.assertTrue(fired.wait(timeout=0.5),
                        "return_home was not executed by DynamicWorker")

        # clean up
        lock.release()         # let the worker finish
        w.join(timeout=1)
        self.assertFalse(w.is_alive())

    def test_return_home_missing_raises_runtime_error(self):
        """
        A normal thread that lacks `return_home` should trigger a RuntimeError
        when return_home_on_block=True (exactly as SwitchLock._return_home
        specifies).
        """
        lock = SwitchLock(value=0, return_home_on_block=True)

        # call acquire in *this* thread – main thread has no return_home
        with self.assertRaises(RuntimeError):
            lock.acquire(timeout=0.2)      # will try to block → raise

# --------------------------------------------------------------------------- #
#  Bias-threshold behaviour                                                   #
# --------------------------------------------------------------------------- #
class TestSwitchLockBias(unittest.TestCase):
    """
    Verifies that permits are buffered when bias is ON and that the buffer
    is flushed exactly once the waiter count reaches the threshold.
    """

    def test_bias_holds_until_threshold_exceeded(self):
        bias = 3
        lock = SwitchLock(value=0, bias_threshold=bias)

        events = [threading.Event() for _ in range(bias)]  # 3 workers
        threads = []

        def waiter(evt):
            if lock.acquire():  # no timeout  → will wait indefinitely
                evt.set()
                lock.release()

        for ev in events:
            t = Worker(target=waiter, args=(ev,))
            threads.append(t)
            t.start()

        wait_for_waiters(lock, bias)  # all three are blocked
        lock.increase_permits(bias)  # buffer 3 permits

        # --- Assertions ---
        self.assertFalse(any(e.wait(0.2) for e in events),
                         "No waiter should wake while bias holds")
        self.assertEqual(lock._pending_permits, bias,
                         "All permits must stay buffered")
        self.assertEqual(lock._value, 0, "No live permits yet")

        # clean-up
        lock.set_bias_threshold(None)  # drop bias → flush
        self.assertTrue(all(e.wait(1) for e in events),
                        "Now everyone should wake")
        for t in threads: t.join()

    def test_bias_lowering_triggers_flush(self):
        lock = SwitchLock(value=0, bias_threshold=10)
        evs = [threading.Event() for _ in range(5)]

        for ev in evs:
            Worker(target=lambda e=ev: (lock.acquire(), e.set())).start()

        wait_for_waiters(lock, 5)
        lock.increase_permits(5)  # buffered
        lock.set_bias_threshold(5)  # should flush now

        self.assertTrue(all(e.wait(1) for e in evs))


    def test_fourth_waiter_triggers_flush(self):
        lock = SwitchLock(value=0, bias_threshold=3)

        # start three waiters – bias not exceeded
        for _ in range(3):
            Worker(target=lambda: lock.acquire(timeout=1)).start()
        wait_for_waiters(lock, 3)
        lock.increase_permits(3)  # buffer

        # spawn the *fourth* waiter – should trigger flush
        flag = threading.Event()
        Worker(target=lambda: (lock.acquire(timeout=1) and flag.set())).start()

        self.assertTrue(flag.wait(1), "Fourth waiter should acquire after flush")
        self.assertEqual(lock._pending_permits, 0, "Buffer must be empty")

    def test_bias_off_behaves_like_normal_semaphore(self):
        lock  = SwitchLock(value=0, bias_threshold=None)  # bias disabled
        evt   = threading.Event()

        def waiter():
            if lock.acquire(timeout=1):
                evt.set()

        t = Worker(target=waiter)
        t.start()
        wait_for_waiters(lock, 1)

        # one permit should wake the waiter immediately
        lock.increase_permits(1)
        self.assertTrue(evt.wait(timeout=0.5))
        t.join(timeout=1)
        self.assertFalse(t.is_alive())
        self.assertEqual(lock._value, 0)



# --------------------------------------------------------------------------- #
#  Run as script                                                              #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    unittest.main()
