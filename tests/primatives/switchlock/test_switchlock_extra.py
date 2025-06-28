"""
Extra stress & edge-case tests for thread_factory.primatives.SwitchLock.

Covers
1. Fairness / starvation check
2. Explicit dispose wakes GC-like waiters
3. Recursive acquire guard
4. Duplicate factory-ID collision
5. Simple performance smoke (contended vs. uncontended)
6. Bias-threshold reserve (using bypass_bias_and_notify)

(To keep dependencies minimal, the Hypothesis fuzzing block is omitted.)
"""

import queue
import threading
import time
import unittest
from time import perf_counter
from typing import Iterable, Union, Optional, Callable

from thread_factory.primitives import SwitchLock
from thread_factory.agentic_thread_pool.agentic_worker.agentic_worker import AgenticWorker


# --------------------------------------------------------------------------- #
#  Tiny Worker wrapper (fire-and-forget)                                      #
# --------------------------------------------------------------------------- #
class Worker(AgenticWorker):
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
    """Spin-wait until at least `expected` threads are registered as waiters."""
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
        lock = SwitchLock(value=1)
        acquired_ctr = {f"A{i}": 0 for i in range(5)} | {f"B{i}": 0 for i in range(5)}
        stop_flag = threading.Event()

        def actor(name):
            threading.current_thread().factory_id = name
            while not stop_flag.is_set():
                acquired = lock.acquire(timeout=1.0)
                if acquired:
                    acquired_ctr[name] += 1
                    time.sleep(0.01)
                    lock.release()
                else:
                    time.sleep(0.005)

        workers = [
            Worker(target=actor, args=(name,), name=name)
            for name in acquired_ctr
        ]
        for w in workers:
            w.start()

        time.sleep(5)      # run window
        stop_flag.set()

        for w in workers:
            w.join(timeout=2)
        starved = [k for k, v in acquired_ctr.items() if v == 0]
        self.assertFalse(starved, f"Starvation detected: {starved}")

    # ------------------------------------------------------------------- #
    # 2. Explicit dispose wakes waiters                                   #
    # ------------------------------------------------------------------- #
    def test_dispose_wakes_waiters(self):
        lock     = SwitchLock(value=0)
        woke_evt = threading.Event()

        def waiter():
            lock.acquire()
            woke_evt.set()

        Worker(target=waiter, name="DisposeWaiter").start()
        wait_for_waiters(lock, 1)
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
                    with lock:   # nested acquire must fail
                        pass

        Worker(target=naughty, name="RecursiveGuard").start()

    # ------------------------------------------------------------------- #
    # 4. Duplicate factory-ID targeted notify                             #
    # ------------------------------------------------------------------- #
    def test_duplicate_factory_id_targeted_notify(self):
        lock   = SwitchLock(value=0)
        dup_id = "DUP-XYZ"
        ev1, ev2 = threading.Event(), threading.Event()

        def waiter(evt):
            threading.current_thread().factory_id = dup_id
            lock.acquire()
            evt.set()

        Worker(target=waiter, args=(ev1,), name="Dup1").start()
        Worker(target=waiter, args=(ev2,), name="Dup2").start()
        wait_for_waiters(lock, 2)

        lock.notify(n=1, factory_ids=dup_id)
        woken = sum(evt.wait(1) for evt in (ev1, ev2))
        self.assertEqual(woken, 1, "Targeted notify woke more than one duplicate")

        lock.increase_permits(1)
        self.assertTrue(all(evt.wait(1) for evt in (ev1, ev2)))

    # ------------------------------------------------------------------- #
    # 5. Performance smoke                                                #
    # ------------------------------------------------------------------- #
    # ------------------------------------------------------------------- #
    # 5. Performance smoke (contended vs. uncontended)                    #
    # ------------------------------------------------------------------- #
    def test_acquire_latency_ratio(self):
        """
        Compare acquire+release latency with and without contention.
        Passes if contended latency is < 50 × uncontended latency.
        """
        ITER = 1_000
        q    = queue.Queue()

        def bench(name: str, lock_obj: SwitchLock):
            # warm-up
            for _ in range(10):
                lock_obj.acquire(); lock_obj.release()
            start = perf_counter()
            for _ in range(ITER):
                lock_obj.acquire(); lock_obj.release()
            q.put((name, perf_counter() - start))

        # ---------- uncontended case ---------- #
        lock_fast = SwitchLock(value=1)
        fast_worker = Worker(target=bench, args=("fast", lock_fast), name="BenchFast")
        fast_worker.start()

        # ---------- contended case ---------- #
        lock_slow = SwitchLock(value=1)

        def blocker():
            if lock_slow.acquire(timeout=5):
                time.sleep(0.25)
                lock_slow.release()

        blockers = [Worker(target=blocker, name=f"Blocker-{i}") for i in range(20)]
        for b in blockers:
            b.start()

        # We only need “enough” waiters to ensure real contention.
        wait_for_waiters(lock_slow, 10, timeout=2.0)

        slow_worker = Worker(target=bench, args=("slow", lock_slow), name="BenchSlow")
        slow_worker.start()

        # ---------- collect results ---------- #
        name1, t1 = q.get(); name2, t2 = q.get()
        if name1 == "slow":
            fast_time, slow_time = t2, t1
        else:
            fast_time, slow_time = t1, t2

        ratio = slow_time / fast_time if fast_time else 1
        print(f"[Perf] {fast_time*1e6:.1f} µs uncontended  "
              f"{slow_time*1e6:.1f} µs contended  ratio ≈ {ratio:.1f}")

        self.assertLess(
            ratio, 50,
            f"Acquire under contention is too slow ({ratio:.1f}×)"
        )

        # ---------- clean up ---------- #
        fast_worker.join(timeout=2)
        slow_worker.join(timeout=2)
        for b in blockers:
            b.join(timeout=2)


    # ------------------------------------------------------------------- #
    # 6. Bias-threshold reserve (bypass-bias bulk)                        #
    # ------------------------------------------------------------------- #
    def test_bias_threshold_honors_reserve(self):
        """
        Bias threshold keeps the last `BIAS_THRESHOLD` threads in reserve
        until we explicitly bypass bias and wake only `RELEASE_COUNT`.
        """
        TOTAL_THREADS   = 13
        BIAS_THRESHOLD  = 10
        RELEASE_COUNT   = 3

        lock = SwitchLock(value=0, bias_threshold=BIAS_THRESHOLD)
        events = [threading.Event() for _ in range(TOTAL_THREADS)]

        def waiter(evt):
            lock.acquire(); evt.set()

        for i in range(TOTAL_THREADS):
            Worker(target=waiter, args=(events[i],), name=f"BiasWaiter-{i}").start()

        wait_for_waiters(lock, TOTAL_THREADS)

        # Buffer a bunch of permits (they stay pending because bias is active)
        lock.increase_permits(TOTAL_THREADS)

        # Now flush only 3 permits and wake exactly 3 waiters (ignore bias)
        lock.notify(n=RELEASE_COUNT)

        time.sleep(0.1)  # give them time to grab permits
        woken = sum(evt.is_set() for evt in events)
        self.assertEqual(
            woken, RELEASE_COUNT,
            f"Bias reserve broken: expected {RELEASE_COUNT} threads, got {woken}"
        )

        # Clean up remaining waiters
        lock.bypass_bias()
        for evt in events:
            evt.wait(timeout=1)

    # ------------------------------------------------------------------- #
    # 7. Bias-threshold reserve (notify_all respects bias)               #
    # ------------------------------------------------------------------- #
    def test_bias_threshold_notify_all_respects_reserve(self):
        """
        When notify_all is called with bias active, only threads above the
        bias threshold should be woken. The others should remain in reserve.
        """
        TOTAL_THREADS   = 13
        BIAS_THRESHOLD  = 10
        lock = SwitchLock(value=0, bias_threshold=BIAS_THRESHOLD)
        events = [threading.Event() for _ in range(TOTAL_THREADS)]

        def waiter(evt):
            lock.acquire()
            evt.set()

        # Spawn all waiters
        for i in range(TOTAL_THREADS):
            Worker(target=waiter, args=(events[i],), name=f"BiasWaiterAll-{i}").start()

        wait_for_waiters(lock, TOTAL_THREADS)

        # Add enough permits for everyone
        lock.increase_permits(TOTAL_THREADS)

        # Notify all, but bias threshold should still keep 10 in reserve
        lock.notify_all()

        time.sleep(0.1)  # Give them time to claim permits
        woken = sum(evt.is_set() for evt in events)
        expected = TOTAL_THREADS - BIAS_THRESHOLD

        self.assertEqual(
            woken, expected,
            f"Bias threshold broken on notify_all: expected {expected}, got {woken}"
        )

        # Clean up remaining threads
        lock.bypass_bias()
        for evt in events:
            evt.wait(timeout=1)

# --------------------------------------------------------------------------- #
#  Run standalone                                                             #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    unittest.main(verbosity=2)
