import unittest
import threading
import time
import random
from typing import Any

try:
    from hypothesis import given, settings, strategies as st
    _HYP = True
except ImportError:  # pragma: no cover – property tests will be skipped
    _HYP = False
from thread_factory.primitives.transit_gate import TransitGate


class TestTransitGate(unittest.TestCase):
    """Revised test‑suite for `TransitGate` aligned with current semantics."""

    # ------------------------------------------------------------------ utils
    def setUp(self):
        self.lock = threading.Lock()
        self.results: list[str] = []
        self.call_count = 0

    def record(self, val: str):
        with self.lock:
            self.results.append(val)
            self.call_count += 1
            return val

    def blocking_task(self, evt: threading.Event, val: str):
        def _():
            evt.wait()
            return self.record(val)
        return _

    # ----------------------------------------------------------- 1. basics
    def test_single_thread_executes(self):
        gate = TransitGate(func=[lambda: self.record("ok")], limit=1)
        self.assertIsNone(gate.transit())
        self.assertEqual(len(gate.outcomes()), 1)
        self.assertEqual(gate.outcomes()[0].result(), "ok")

    def test_limit_respected(self):
        gate = TransitGate(func=[lambda: self.record("run")], limit=3)
        threads = [threading.Thread(target=gate.transit) for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()

        # only three executions but a single Outcome (one stage)
        self.assertEqual(self.call_count, 3)
        self.assertEqual(len(gate.outcomes()), 1)

    def test_blocking_tasks_wait(self):
        evt = threading.Event()
        gate = TransitGate(func=[self.blocking_task(evt, "done")], limit=2)
        threads = [threading.Thread(target=gate.transit) for _ in range(3)]
        for t in threads: t.start()
        time.sleep(0.1)

        # two admitted threads are waiting inside → no outcomes yet
        self.assertEqual(self.call_count, 0)
        self.assertEqual(len(gate.outcomes()), 0)

        evt.set()
        for t in threads: t.join()

        self.assertEqual(self.call_count, 2)
        self.assertEqual(len(gate.outcomes()), 1)

    def test_callable_with_params(self):
        def greet(msg):
            return self.record(msg)
        gate = TransitGate(func=greet, limit=1, msg="hi")
        gate.transit()
        self.assertEqual(gate.outcomes()[0].result(), "hi")

    def test_exception_captured(self):
        def boom():
            raise ValueError("x")
        gate = TransitGate(func=[boom], limit=1)
        gate.transit()
        with self.assertRaises(ValueError):
            gate.outcomes()[0].result()

    # ---------------------------------------------------- 2. pipeline
    def test_pipeline_runs_all_stages(self):
        flags = {"a": False, "b": False}
        def a(): flags["a"] = True
        def b(): flags["b"] = True
        gate = TransitGate(func=[a, b], limit=1)
        gate.transit()
        self.assertTrue(all(flags.values()))
        self.assertEqual(len(gate.outcomes()), 2)

    def test_barrier_between_stages(self):
        stage_order: list[str] = []
        barrier = threading.Barrier(2)

        def stage1():
            stage_order.append("1")
            barrier.wait()

        def stage2():
            stage_order.append("2")

        gate = TransitGate(func=[stage1, stage2], limit=2)
        t1 = threading.Thread(target=gate.transit)
        t2 = threading.Thread(target=gate.transit)
        t1.start(); t2.start(); t1.join(); t2.join()

        # stage1 should appear twice *before* any stage2 entry
        first_two = stage_order[:2]
        self.assertEqual(first_two, ["1", "1"])
        self.assertEqual(stage_order.count("2"), 2)

    def test_outcome_per_stage(self):
        gate = TransitGate(func=[lambda: "A", lambda: "B"], limit=1)
        gate.transit()
        self.assertEqual([o.result() for o in gate.outcomes()], ["A", "B"])

    def test_pipeline_collapse(self):
        gate = TransitGate(func=[lambda: "x"], limit=1)
        gate.transit(); self.assertTrue(gate._collapsed)
        self.assertIsNone(gate.transit())

    def test_pipeline_exception_continues(self):
        gate = TransitGate(func=[lambda: "ok", lambda: (_ for _ in ()).throw(ValueError()), lambda: "ok"], limit=1)
        gate.transit()
        a, b, c = gate.outcomes()
        self.assertEqual(a.result(), "ok")
        with self.assertRaises(ValueError):
            b.result()
        self.assertEqual(c.result(), "ok")

    # ------------------------------------------------ 3. dynamic limit / state
    def test_increase_limit_allows_concurrent_entry(self):
        """If we grow the limit *while a task is still inside*, another thread can enter."""
        block_event = threading.Event()
        gate = TransitGate(func=[self.blocking_task(block_event, "run")], limit=1)

        # Thread 1 grabs the sole permit and blocks inside the task
        t1 = threading.Thread(target=gate.transit)
        t1.start()
        time.sleep(0.1)
        self.assertEqual(self.call_count, 0)  # task not finished yet

        # Grow the limit before collapsing happens
        gate.increase_limit(1)

        # Thread 2 should now be able to enter and also block
        t2 = threading.Thread(target=gate.transit)
        t2.start()
        time.sleep(0.1)
        self.assertEqual(self.call_count, 0)  # still blocked

        # Release both tasks
        block_event.set(); t1.join(); t2.join()

        self.assertEqual(self.call_count, 2)
        # Only one Outcome because one stage
        self.assertEqual(len(gate.outcomes()), 1)

    def test_decrease_limit_blocks_new(self):
        evt = threading.Event()
        gate = TransitGate(func=[self.blocking_task(evt, "run")], limit=3)
        t1 = threading.Thread(target=gate.transit); t2 = threading.Thread(target=gate.transit)
        t1.start(); t2.start(); time.sleep(0.2)

        # decrease by 1 (cannot exceed available permits)
        gate.decrease_limit(1)
        t3 = threading.Thread(target=gate.transit); t3.start(); time.sleep(0.1)
        self.assertEqual(self.call_count, 0)  # still blocked
        evt.set(); t1.join(); t2.join(); t3.join()
        self.assertEqual(self.call_count, 2)

    def test_collapse(self):
        gate = TransitGate(func=[lambda: "x"], limit=5)
        gate.collapse(); self.assertIsNone(gate.transit())

    def test_reset(self):
        gate = TransitGate(func=[lambda: self.record("x")], limit=1)
        gate.transit(); gate.reset(); gate.transit()
        self.assertEqual(self.call_count, 2)
        self.assertEqual(len(gate.outcomes()), 1)  # outcomes cleared on reset

    def test_dispose(self):
        gate = TransitGate(func=[lambda: "x"], limit=1)
        t = threading.Thread(target=gate.transit); t.start(); time.sleep(0.1)
        gate.dispose(); t.join(timeout=1)
        self.assertTrue(gate._disposed)
        self.assertIsNone(gate._dynaphore)
        self.assertIsNone(gate._threshold_sema)
        self.assertFalse(t.is_alive())

# --------------------------------------------------------------------------
# Utilities shared by many tests
# --------------------------------------------------------------------------
class _Base(unittest.TestCase):
    def setUp(self):
        self.lock = threading.Lock()
        self.results: list[Any] = []
        self.call_count = 0

    def record(self, val: Any):
        with self.lock:
            self.results.append(val)
            self.call_count += 1
            return val

    def blocking_task(self, evt: threading.Event, val: Any):
        def _():
            evt.wait()
            return self.record(val)
        return _


# --------------------------------------------------------------------------
# 1. BASIC + PIPELINE + DYNAMIC (unchanged core expectations)
# --------------------------------------------------------------------------
class TestTransitGate1(_Base):
    def test_single_thread_executes(self):
        gate = TransitGate(func=[lambda: self.record("ok")], limit=1)
        self.assertIsNone(gate.transit())
        self.assertEqual(self.call_count, 1)
        self.assertEqual(len(gate.outcomes()), 1)

    def test_limit_respected(self):
        gate = TransitGate(func=[lambda: self.record("run")], limit=3)
        threads = [threading.Thread(target=gate.transit) for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(self.call_count, 3)
        self.assertEqual(len(gate.outcomes()), 1)

    def test_blocking_pass_through(self):
        evt = threading.Event()
        gate = TransitGate(func=[self.blocking_task(evt, "done")], limit=2)
        thr = [threading.Thread(target=gate.transit) for _ in range(3)]
        for t in thr: t.start()
        time.sleep(0.1)
        self.assertEqual(self.call_count, 0)
        evt.set()
        for t in thr: t.join()
        self.assertEqual(self.call_count, 2)
        self.assertEqual(len(gate.outcomes()), 1)

    def test_pipeline_two_stages(self):
        order: list[str] = []
        def a(): order.append("a")
        def b(): order.append("b")
        gate = TransitGate(func=[a, b], limit=1)
        gate.transit(); self.assertEqual(order, ["a", "b"])
        self.assertEqual(len(gate.outcomes()), 2)

    def test_increase_limit_runtime(self):
        evt = threading.Event()
        gate = TransitGate(func=[self.blocking_task(evt, "x")], limit=1)

        t1 = threading.Thread(target=gate.transit)
        t1.start()
        time.sleep(0.05)  # t1 enters and blocks

        gate.increase_limit(1)

        t2 = threading.Thread(target=gate.transit)
        t2.start()
        time.sleep(0.05)  # let t2 enter and block

        # Now release both
        evt.set()
        t1.join()
        t2.join()

        self.assertEqual(self.call_count, 2)
        self.assertEqual(len(gate.outcomes()), 1)

    def test_decrease_limit_blocks_new(self):
        evt = threading.Event()
        gate = TransitGate(func=[self.blocking_task(evt, "x")], limit=3)

        t1 = threading.Thread(target=gate.transit)
        t2 = threading.Thread(target=gate.transit)
        t1.start()
        t2.start()
        time.sleep(0.1)  # let them in

        gate.decrease_limit(1)  # leave 2 permits total (equal to current usage)

        t3 = threading.Thread(target=gate.transit)
        t3.start()
        time.sleep(0.1)

        self.assertEqual(self.call_count, 0)  # nobody's completed yet
        evt.set()
        t1.join()
        t2.join()
        t3.join()

        self.assertEqual(self.call_count, 2)  # t3 never got in
        self.assertEqual(len(gate.outcomes()), 1)

    def test_callable_with_parameters_is_bound_correctly(self):
        def greet(name: str):
            return self.record(f"Hi {name}!")

        gate = TransitGate(func=greet, limit=1, name="Mark")
        gate.transit()

        self.assertEqual(self.call_count, 1)
        self.assertEqual(gate.outcomes()[0].result(), "Hi Mark!")

    def test_callable_with_multiple_parameters(self):
        def add(a, b):
            return self.record(a + b)

        gate = TransitGate(func=add, limit=1, a=10, b=20)
        gate.transit()

        self.assertEqual(self.call_count, 1)
        self.assertEqual(gate.outcomes()[0].result(), 30)


    def test_lambda_with_bound_params(self):
        gate = TransitGate(func=lambda: self.record(7 * 3), limit=1)
        gate.transit()
        self.assertEqual(gate.outcomes()[0].result(), 21)

# --------------------------------------------------------------------------
# 2. STRESS + ADVANCED
# --------------------------------------------------------------------------
class StressTransitGate2(_Base):
    def _run_many(self, limit: int, n_threads: int):
        gate = TransitGate(func=[lambda: self.record(1)], limit=limit)
        threads = [threading.Thread(target=gate.transit) for _ in range(n_threads)]
        random.shuffle(threads)
        for t in threads: t.start()
        for t in threads: t.join()
        return gate

    def test_high_concurrency_no_deadlock(self):
        """Spawn 1k threads against limit=10 and ensure exactly 10 executions."""
        gate = self._run_many(limit=10, n_threads=1000)
        self.assertEqual(self.call_count, 10)
        self.assertEqual(len(gate.outcomes()), 1)

# --------------------------------------------------------------------------
# 3. PROPERTY‑BASED (optional)
# --------------------------------------------------------------------------
if _HYP:
    class PropTests(_Base):
        @settings(deadline=None, max_examples=50)
        @given(limit=st.integers(min_value=1, max_value=15),
               ratio=st.integers(min_value=1, max_value=5))
        def test_call_count_equals_limit(self, limit: int, ratio: int):
            """For N threads >= limit, exactly `limit` tasks run."""
            n_threads = limit * ratio
            gate = TransitGate(func=[lambda: self.record(1)], limit=limit)
            thr = [threading.Thread(target=gate.transit) for _ in range(n_threads)]
            for t in thr: t.start()
            for t in thr: t.join()
            self.assertEqual(self.call_count, limit)
            self.assertEqual(len(gate.outcomes()), 1)
else:
    print("[prop tests skipped – install hypothesis to enable]")


if __name__ == "__main__":
    unittest.main()
