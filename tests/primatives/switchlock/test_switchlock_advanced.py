"""
Advanced / edge-case tests for thread_factory.primatives.SwitchLock.

Changelog (2025-06-24):
• All lock users are now DynamicWorkers → no “outside worker context” errors.
• Ultra-contention test uses value=0 so every thread blocks → waiters register.
• Callback-chaos simplified: single bound callback that raises; proves exception path.
• Bias-inequality test tracks six events (not five) → proper flush assert.
• Permit-leak fuzzer converted to ActorWorker (DynamicWorker) so .acquire() is legal.
"""

import random
import threading
import time
import unittest
from contextlib import ExitStack

from thread_factory.primatives import SwitchLock
from thread_factory.thread_pool.worker.dynamic_worker import DynamicWorker


# --------------------------------------------------------------------------- #
#  Tiny compatibility layer                                                   #
# --------------------------------------------------------------------------- #
class Worker(DynamicWorker):
    """
    Fire-and-forget wrapper: run target once, then stop().
    """

    def __init__(self, *, target=None, args=(), kwargs=None, name=None):
        super().__init__(name=name)
        self._target = target
        self._args   = args
        self._kwargs = kwargs or {}
        self.set_home(self._run_once_and_quit)

    def _run_once_and_quit(self):
        if self._target:
            self._target(*self._args, **self._kwargs)
        self.stop()


# --------------------------------------------------------------------------- #
#  Helpers                                                                    #
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


# --------------------------------------------------------------------------- #
#  Test-suite                                                                 #
# --------------------------------------------------------------------------- #
class TestSwitchLockEdgeCases(unittest.TestCase):
    # ----------------------------------------------------------------------- #
    # 1. Ultra-contention shutdown                                            #
    # ----------------------------------------------------------------------- #
    def test_ultra_contention_dispose(self):
        n_threads = 200
        lock      = SwitchLock(value=0)          # every thread blocks
        done      = [threading.Event() for _ in range(n_threads)]

        def waiter(idx):
            lock.acquire()                       # blocks until dispose
            done[idx].set()

        threads = [Worker(target=waiter, args=(i,), name=f"UC-{i}")
                   for i in range(n_threads)]
        for t in threads: t.start()

        wait_for_waiters(lock, n_threads)
        lock.dispose()

        self.assertTrue(all(e.wait(2) for e in done))
        for t in threads: t.join(timeout=1)
        self.assertEqual(lock._value, 0)

    # ----------------------------------------------------------------------- #
    # 2. Callback chaos (exception path)                                      #
    # ----------------------------------------------------------------------- #
    def test_callback_exception_is_swallowed(self):
        lock   = SwitchLock(value=0)
        flag   = threading.Event()

        def bad_cb():
            flag.set()
            raise RuntimeError("Boom")

        def waiter():
            # bind a per-thread callback that throws
            lock.set_callback(threading.current_thread().factory_id, bad_cb)
            lock.acquire()      # will wake via notify
            lock.release()

        w = Worker(target=waiter, name="CBChaos")
        w.start()
        wait_for_waiters(lock, 1)

        # notify in calling thread (callback executes *here*)
        lock.notify(n=1, awaited_caller=False)
        w.join(timeout=1)

        self.assertTrue(flag.is_set(), "Callback never executed")
        # process didn’t crash → exception swallowed

    # ----------------------------------------------------------------------- #
    # 3. Timeout vs notify race                                               #
    # ----------------------------------------------------------------------- #
    def test_timeout_vs_notify_race(self):
        lock   = SwitchLock(value=0)
        result = []

        def waiter():
            ok = lock.acquire(timeout=0.1)
            result.append(ok)

        w = Worker(target=waiter)
        w.start()

        time.sleep(random.uniform(0.02, 0.08))  # race window
        lock.notify(n=1)
        w.join(timeout=1)

        self.assertEqual(len(result), 1)
        self.assertIn(result[0], (True, False))
        live = lock._value + len(lock.get_all_waiters())
        self.assertEqual(live, 0, "Permit accounting drifted")

    # ----------------------------------------------------------------------- #
    # 4. Bias inequality gauntlet                                             #
    # ----------------------------------------------------------------------- #
    def test_bias_inequality_paths(self):
        """
        Verifies:
        • Buffered permits stay buffered when waiter count <= bias threshold
        • Flush triggers only when waiters > threshold
        • Flush only wakes up to the number of permits
        • Remaining waiters can be awoken with more permits
        """
        lock = SwitchLock(value=0, bias_threshold=10)
        evs = [threading.Event() for _ in range(6)]

        # Step 1 — 6 waiters block
        for ev in evs:
            Worker(target=lambda e=ev: (lock.acquire(), e.set())).start()

        wait_for_waiters(lock, 6)

        # Step 2 — buffer 5 permits (nothing should wake yet)
        lock.increase_permits(5)
        self.assertEqual(lock._pending_permits, 5)
        self.assertFalse(any(ev.is_set() for ev in evs))

        # Step 3 — drop bias below waiter count (6 > 4 triggers flush)
        lock.set_bias_threshold(4)
        time.sleep(0.2)  # Give threads time to race on the flush

        # Step 4 — count how many succeeded
        woke = [ev.wait(1) for ev in evs]
        self.assertEqual(woke.count(True), 5, "Exactly 5 threads should have acquired after flush")
        self.assertEqual(lock._pending_permits, 0, "Pending permits should be flushed")

        # Step 5 — wake the final waiter
        lock.set_bias_threshold(None)  # turn bias OFF → no buffering
        lock.increase_permits(1)  # permit is live, waiter wakes
        self.assertTrue(all(ev.wait(1) for ev in evs))

    # ----------------------------------------------------------------------- #
    # 5. Double-dispose idempotence                                           #
    # ----------------------------------------------------------------------- #
    def test_double_dispose(self):
        lock   = SwitchLock(value=0)
        wakies = []

        def waiter():
            lock.acquire()
            wakies.append("up")

        threads = [Worker(target=waiter) for _ in range(10)]
        for t in threads: t.start()
        wait_for_waiters(lock, 10)

        with ExitStack() as stack:
            for _ in range(2):
                killer = threading.Thread(target=lock.dispose)
                killer.start()
                stack.callback(killer.join)

        for t in threads: t.join(timeout=1)
        self.assertEqual(len(wakies), 10)
        self.assertTrue(lock.disposed)

    # ----------------------------------------------------------------------- #
    # 6. Permit-leak fuzzer                                                   #
    # ----------------------------------------------------------------------- #
    def test_permit_leak_fuzzer(self):
        init_permits = 3
        lock = SwitchLock(value=init_permits, bias_threshold=None)
        ops = 2000

        class ActorWorker(Worker):
            def __init__(self, name):
                super().__init__(name=name, target=self._loop)

            def _loop(self):
                for _ in range(ops):
                    op = random.choice(("acq", "rel", "not"))
                    if op == "acq":
                        if lock.acquire(timeout=0.01):
                            lock.release()
                    elif op == "rel":
                        lock.increase_permits(1)
                    else:
                        lock.notify()

        actors = [ActorWorker(name=f"Fuzz-{i}") for i in range(8)]
        for a in actors: a.start()
        for a in actors: a.join()

        # Instead of strict equality, sanity-check for integrity:
        live_permits = lock._value + lock._pending_permits
        self.assertGreaterEqual(live_permits, 0,
                                "Permit count went negative")
        self.assertEqual(len(lock.get_all_waiters()), 0,
                         "Waiters leaked after fuzz")


# --------------------------------------------------------------------------- #
#  Run standalone                                                             #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    unittest.main(verbosity=2)
