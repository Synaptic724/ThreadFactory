"""
Extra stress & edge-case tests for thread_factory.primatives.SwitchLock.

Covers
1. Fairness / starvation check
2. Explicit dispose wakes GC-like waiters
3. Recursive acquire guard
4. Duplicate factory-ID collision
5. Simple performance smoke (contended vs. uncontended)

(To keep dependencies minimal, the Hypothesis property-fuzz was removed;
add it back whenever Hypothesis is in your environment.)
"""

import queue
import random
import threading
import time
import unittest

from thread_factory.primatives import SwitchLock
from thread_factory.thread_pool.worker.dynamic_worker import DynamicWorker


# --------------------------------------------------------------------------- #
#  Tiny Worker wrapper (fire-and-forget)                                      #
# --------------------------------------------------------------------------- #
class Worker(DynamicWorker):
    def __init__(self, *, target=None, args=(), kwargs=None, name=None):
        super().__init__(name=name)
        self._target = target
        self._args   = args or ()
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
class TestSwitchLockExtra(unittest.TestCase):

    # ------------------------------------------------------------------- #
    # 1. Fairness / starvation                                            #
    # ------------------------------------------------------------------- #
    def test_fairness_no_starvation(self):
        """
        Ensure multiple workers eventually acquire the lock at least once,
        verifying SwitchLock doesn't starve low-priority contenders.
        """
        lock = SwitchLock(value=1)
        acquired_ctr = {f"A{i}": 0 for i in range(5)} | {f"B{i}": 0 for i in range(5)}
        stop_flag = threading.Event()

        def actor(name):
            threading.current_thread().factory_id = name # Ensure unique ID for logging/targeting
            while not stop_flag.is_set():
                # Make the timeout much longer, or remove it entirely,
                # to allow the FIFO queue of SmartCondition to work effectively
                # for fairness. A shorter timeout causes threads to remove
                # themselves from the queue and re-add at the back.
                acquired = lock.acquire(timeout=1.0) # Increased timeout to 1 second
                if acquired:
                    acquired_ctr[name] += 1
                    time.sleep(0.01) # Hold the lock for a short duration
                    lock.release()
                else:
                    # If timeout occurred (which should be rare with 1s timeout),
                    # sleep briefly before trying again to avoid busy-waiting.
                    time.sleep(0.005) # Keep a small sleep, but it should be less relevant now

        workers = [
            Worker(target=actor, args=(name,), name=name) # Pass name to Worker for thread naming
            for name in acquired_ctr
        ]
        for w in workers:
            w.start()

        # Give them significantly longer to run
        time.sleep(5) # Increased test duration to 5 seconds
        stop_flag.set()

        for w in workers:
            w.join(timeout=2) # Add a join timeout to prevent test from hanging if a worker gets stuck
            if w.is_alive():
                print(f"Warning: Worker {w.name} did not terminate in time.")

        starved = [k for k, v in acquired_ctr.items() if v == 0]
        self.assertFalse(starved, f"Starvation detected: {starved}   counts={acquired_ctr}")
        # Optional: Assert that all workers acquired it at least N times
        for name, count in acquired_ctr.items():
            self.assertGreater(count, 0, f"Worker {name} never acquired the lock.")
            # Can also assert minimum count: self.assertGreaterEqual(count, 5, f"Worker {name} acquired too few times.")


    # ------------------------------------------------------------------- #
    # 2. Explicit dispose wakes waiters (GC-like scenario)                #
    # ------------------------------------------------------------------- #
    def test_dispose_wakes_waiters(self):
        """
        Simulates GC cleanup by calling dispose() in another thread.
        """
        lock     = SwitchLock(value=0)
        woke_evt = threading.Event()

        def waiter():
            lock.acquire()
            woke_evt.set()

        Worker(target=waiter, name="DisposeWaiter").start()
        wait_for_waiters(lock, 1)

        # Dispose from separate thread to mimic async GC finalizer
        threading.Thread(target=lock.dispose, name="Disposer").start()

        self.assertTrue(woke_evt.wait(2), "Waiter was not released by dispose()")

    # ------------------------------------------------------------------- #
    # 3. Recursive acquire guard                                          #
    # ------------------------------------------------------------------- #
    def test_recursive_acquire_raises(self):
        lock = SwitchLock(value=1)

        def naughty():
            with self.assertRaises(RuntimeError):
                with lock:
                    with lock:  # nested acquire must fail
                        pass

        w = Worker(target=naughty, name="RecursiveGuard")
        w.start()
        w.join(timeout=1)

    # ------------------------------------------------------------------- #
    # 4. Duplicate factory-ID targeted notify                             #
    # ------------------------------------------------------------------- #
    def test_duplicate_factory_id_targeted_notify(self):
        lock   = SwitchLock(value=0)
        dup_id = "DUP-XYZ"
        ev1, ev2 = threading.Event(), threading.Event()

        def waiter(evt):
            threading.current_thread().factory_id = dup_id  # manual collision
            lock.acquire()
            evt.set()

        Worker(target=waiter, args=(ev1,), name="Dup1").start()
        Worker(target=waiter, args=(ev2,), name="Dup2").start()
        wait_for_waiters(lock, 2)

        # Notify should wake only one of the duplicates
        lock.notify(n=1, factory_ids=dup_id)
        woken = sum(evt.wait(1) for evt in (ev1, ev2))
        self.assertEqual(woken, 1, "Targeted notify woke more than one duplicate")

        # Clean up the second waiter
        lock.increase_permits(1)
        self.assertTrue(all(evt.wait(1) for evt in (ev1, ev2)))

    # ------------------------------------------------------------------- #
    # 5. Performance smoke                                                #
    # ------------------------------------------------------------------- #
    def test_acquire_latency_ratio(self):
        """
        Benchmark acquire+release speed with and without contention.

        Measures the time it takes to perform a sequence of lock operations
        in both uncontended and contended scenarios. Ensures contention
        does not degrade performance beyond acceptable limits.
        """
        ITER = 1000
        q = queue.Queue()

        def bench(name, lock_obj):
            # Warm-up
            for _ in range(10):
                lock_obj.acquire()
                lock_obj.release()

            # Timed benchmark
            start = time.perf_counter()
            for _ in range(ITER):
                lock_obj.acquire()
                lock_obj.release()
            q.put((name, time.perf_counter() - start))

        # Case 1: Uncontended
        lock_fast = SwitchLock(value=1)
        Worker(target=bench, args=("fast", lock_fast)).start()

        # Case 2: Contended
        lock_slow = SwitchLock(value=1)

        def blocker():
            if lock_slow.acquire(timeout=5):
                time.sleep(0.25)
                lock_slow.release()

        # Launch 20 blockers to simulate contention
        blockers = [Worker(target=blocker) for _ in range(20)]
        for b in blockers:
            b.start()

        try:
            wait_for_waiters(lock_slow, 20, timeout=2.0)
        except AssertionError:
            print("⚠️ Warning: Not all blockers registered in time, continuing anyway.")

        Worker(target=bench, args=("slow", lock_slow)).start()

        fast_name, fast_time = q.get()
        slow_name, slow_time = q.get()
        if fast_name == "slow":
            fast_time, slow_time = slow_time, fast_time

        ratio = slow_time / fast_time if fast_time else 1
        print(f"[Perf] {fast_time * 1e6:.1f} µs uncontended  "
              f"{slow_time * 1e6:.1f} µs contended  ratio ≈ {ratio:.1f}")

        self.assertLess(ratio, 50,
                        f"Acquire under contention is too slow ({ratio:.1f}×)")


# --------------------------------------------------------------------------- #
#  Run standalone                                                             #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    unittest.main(verbosity=2)
