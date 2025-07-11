import threading
import time
import unittest
from typing import List
from thread_factory import TransitCondition

# ---------------------------------------------------------------------------
# Helper thread classes
# ---------------------------------------------------------------------------
class SimpleWorker(threading.Thread):
    """Worker that blocks on a TransitCondition and records a wake event."""

    def __init__(self, cond: TransitCondition, sink: List[str], name: str, cb_suffix: str = ""):
        super().__init__(name=name)
        self._cond = cond
        self._sink = sink
        self._cb_suffix = cb_suffix

    def run(self):
        with self._cond:
            self._cond.wait()
        # This executes *after* any callback inside the waiter thread
        self._sink.append(f"woken_{self.name}{self._cb_suffix}")


class CallbackRecorder:
    """Records callback invocations in a threadsafe list."""

    def __init__(self, buffer: List[str], tag: str):
        self._buf, self._tag, self._lock = buffer, tag, threading.Lock()

    def __call__(self):
        with self._lock:
            self._buf.append(self._tag)


# ---------------------------------------------------------------------------
# Test‑suite for TransitCondition
# ---------------------------------------------------------------------------
class TestTransitConditionBasic(unittest.TestCase):
    """Re‑implements the original five basic tests (sanity coverage)."""


    def test_notify_executes_callback_n_times(self):
        count = {"hits": 0}
        lock = threading.RLock()

        def transit():
            with threading.Lock():
                count["hits"] += 1

        cond = TransitCondition(lock)

        def worker():
            with cond:
                cond.wait()

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()

        # Allow threads to block on wait()
        threading.Event().wait(0.1)

        with cond:
            cond.notify(3, transit)

        for t in threads:
            t.join(timeout=1)

        self.assertEqual(count["hits"], 3)

    def test_notify_all_executes_callback_for_all(self):
        count = {"hits": 0}
        lock = threading.RLock()

        def transit():
            with threading.Lock():
                count["hits"] += 1

        cond = TransitCondition(lock)

        def worker():
            with cond:
                cond.wait()

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()

        threading.Event().wait(0.1)

        with cond:
            cond.notify_all(transit)

        for t in threads:
            t.join(timeout=1)

        self.assertEqual(count["hits"], 4)

    def test_notify_wakes_exact_n(self):
        cond, results = TransitCondition(), []
        workers = [SimpleWorker(cond, results, f"t{i}") for i in range(4)]
        for w in workers:
            w.start()
        time.sleep(0.05)
        with cond:
            cond.notify(n=2)
        time.sleep(0.1)
        self.assertEqual(len(results), 2)
        with cond:
            cond.notify_all()
        for w in workers:
            w.join()
        self.assertEqual(len(results), 4)

    def test_notify_all_with_inline_callback(self):
        cond, results, lock = TransitCondition(), [], threading.Lock()
        inline_cb = CallbackRecorder(results, "inline_cb")
        workers = [SimpleWorker(cond, results, f"w{i}") for i in range(3)]
        for w in workers:
            w.start()
        time.sleep(0.05)
        with cond:
            cond.notify_all(callback=inline_cb)
        for w in workers:
            w.join()
        self.assertEqual(results.count("inline_cb"), 3)
        self.assertEqual(sum(r.startswith("woken_") for r in results), 3)

    def test_dispose_clears_waiters_and_disallows_future_use(self):
        cond = TransitCondition()
        results = []

        class W(threading.Thread):
            def run(self):
                try:
                    with cond:
                        cond.wait()
                    results.append("woken")
                except RuntimeError as e:
                    results.append(str(e))

        t = W()
        t.start()
        time.sleep(0.05)

        cond.dispose()
        t.join(timeout=1)

        # ✅ The thread is allowed to wake up cleanly from dispose
        self.assertIn("woken", results, "Thread should wake and proceed after dispose")
        self.assertEqual(cond.find_waiter_count(), 0)

        # 🧨 But new waiters are not allowed
        with self.assertRaises(RuntimeError):
            with cond:
                cond.wait()

    def test_default_callback(self):
        cond, results = TransitCondition(), []
        cond.set_default_callback(CallbackRecorder(results, "default_cb"))
        worker = SimpleWorker(cond, results, "solo")
        worker.start(); time.sleep(0.02)
        with cond:
            cond.notify()
        worker.join()
        self.assertIn("default_cb", results)
        self.assertIn("woken_solo", results)

    def test_wait_timeout_removes_waiter(self):
        cond, timed_out = TransitCondition(), []

        class TimeoutWorker(threading.Thread):
            def run(self):
                with cond:
                    ok = cond.wait(timeout=0.05)
                timed_out.append(ok)

        t = TimeoutWorker(); t.start(); t.join(2)
        self.assertEqual(timed_out, [False])
        self.assertEqual(cond.find_waiter_count(), 0)

    def test_get_all_waiters_snapshot(self):
        cond, snapshot = TransitCondition(), []

        class W(threading.Thread):
            def run(self):
                with cond:
                    cond.wait()
        ws = [W() for _ in range(3)]
        for w in ws: w.start()
        time.sleep(0.05)
        with cond:
            snapshot.append(cond.find_waiter_count())
            cond.notify_all()
        for w in ws: w.join()
        self.assertEqual(snapshot[0], 3)
        self.assertEqual(cond.find_waiter_count(), 0)


# ---------------------------------------------------------------------------
# Advanced behavioural tests
# ---------------------------------------------------------------------------
class TestTransitConditionAdvanced(unittest.TestCase):
    def test_inline_overrides_default(self):
        cond, results = TransitCondition(), []
        cond.set_default_callback(CallbackRecorder(results, "default_cb"))
        inline_cb = CallbackRecorder(results, "inline_cb")
        worker = SimpleWorker(cond, results, "x")
        worker.start(); time.sleep(0.02)
        with cond:
            cond.notify(callback=inline_cb)
        worker.join()
        self.assertIn("inline_cb", results)
        self.assertNotIn("default_cb", results)

    def test_callback_exception_isolated(self):
        cond, results = TransitCondition(), []

        def bad_cb():
            results.append("bad_cb"); raise ValueError("boom")

        good_cb = CallbackRecorder(results, "good_cb")
        workers = [SimpleWorker(cond, results, "bad"), SimpleWorker(cond, results, "good")]
        for w in workers: w.start()
        time.sleep(0.05)
        with cond:
            cond.notify(callback=bad_cb)   # first wake gets bad_cb
            cond.notify(callback=good_cb)  # second wake gets good_cb
        for w in workers: w.join()
        self.assertIn("bad_cb", results)
        self.assertIn("good_cb", results)
        # even though exception happened, second worker should still run its callback

    def test_fifo_order(self):
        cond, awaken = TransitCondition(), []
        workers = [SimpleWorker(cond, awaken, f"w{i}") for i in range(5)]
        for w in workers: w.start()
        time.sleep(0.05)
        wake_sequence = []
        for _ in range(5):
            with cond:
                cond.notify()
            time.sleep(0.02)
            wake_sequence.append(awaken[-1])
        self.assertEqual(wake_sequence, [f"woken_w{i}" for i in range(5)], "Workers should wake FIFO")

    def test_notify_after_timeout_does_not_resurrect(self):
        cond = TransitCondition(); done = []

        class W(threading.Thread):
            def run(self):
                with cond:
                    ok = cond.wait(timeout=0.05)
                done.append(ok)

        w = W(); w.start(); w.join()
        with cond:
            cond.notify()   # nobody waiting anymore
        self.assertEqual(done, [False])
        self.assertEqual(cond.find_waiter_count(), 0)

    def test_recursive_lock_safety(self):
        base_lock = threading.RLock()
        cond = TransitCondition(base_lock)
        depth_entered = []

        def deep_fn(level):
            if level == 3:
                depth_entered.append(level)
                return
            with cond:
                deep_fn(level + 1)
        deep_fn(0)
        self.assertEqual(depth_entered, [3])

    def test_high_contention_throughput(self):
        cond = TransitCondition()
        counter = 0
        counter_lock = threading.Lock()

        n_threads, loops = 55, 250
        total_signals = n_threads * loops
        started_evts = [threading.Event() for _ in range(n_threads)]

        class W(threading.Thread):
            def __init__(self, idx):
                super().__init__()
                self.idx = idx

            def run(self):
                nonlocal counter
                started_evts[self.idx].set()
                for _ in range(loops):
                    with cond:
                        cond.wait()
                    with counter_lock:
                        counter += 1

        workers = [W(i) for i in range(n_threads)]
        for w in workers:
            w.start()
        for e in started_evts:
            e.wait()  # wait for all threads to start

        start = time.perf_counter()
        for _ in range(loops):
            with cond:
                cond.notify(n_threads)  # notify one round of threads
            time.sleep(0.01)  # allow them to reach .wait() again

        for w in workers:
            w.join()
        elapsed = time.perf_counter() - start

        self.assertEqual(counter, total_signals, "Not all signals were handled")
        self.assertLess(elapsed, 5, "High-contention loop took too long")
        print(f"✅ High-contention test passed in {elapsed:.6f} seconds")


class TestRLockVsTransitCondition(unittest.TestCase):
    def test_signal_vs_reentrant_lock_baseline(self):
        NUM_THREADS = 50
        results = []

        def run_signal_condition():
            cond = TransitCondition()
            ready = threading.Event()

            def worker():
                with cond:
                    ready.wait()
                    cond.wait()
                results.append("signal")

            threads = [threading.Thread(target=worker) for _ in range(NUM_THREADS)]
            for t in threads: t.start()
            time.sleep(0.05)
            start = time.perf_counter()
            ready.set()
            time.sleep(0.01)
            with cond:
                cond.notify_all()
            for t in threads: t.join()
            end = time.perf_counter()
            return end - start

        def run_reentrant_lock_only():
            rlock = threading.RLock()
            ready = threading.Event()

            def worker():
                ready.wait()
                with rlock:
                    results.append("rlock")

            threads = [threading.Thread(target=worker) for _ in range(NUM_THREADS)]
            for t in threads: t.start()
            time.sleep(0.05)
            start = time.perf_counter()
            ready.set()
            for t in threads: t.join()
            end = time.perf_counter()
            return end - start

        sig_time = run_signal_condition()
        rlock_time = run_reentrant_lock_only()

        print(f"TransitCondition (full wait/wake): {sig_time:.6f} sec")
        print(f"RLock baseline (no wait):         {rlock_time:.6f} sec")

        self.assertGreater(sig_time, rlock_time * 1.2, "TransitCondition should be slower than plain RLock")

if __name__ == "__main__":
    unittest.main(verbosity=2)

