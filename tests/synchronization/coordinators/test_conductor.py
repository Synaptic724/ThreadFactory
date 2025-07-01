"""test_conductor.py
====================
Unit‑tests for **Conductor** – now validating via the **Outcome** objects
instead of helper properties (`results`, `exceptions`).

The implementation promises that every task maps 1‑to‑1 onto an
:class:`Outcome` placed in ``conductor.outcomes``.  These tests therefore pull
successes and failures directly from those Outcome instances.

Notes
-----
* Per‑call timeouts are *not* supported, so `wait()` is invoked bare.
* A few known‑bugs (manual‑release race, global‑timeout semantics) remain under
  `@expectedFailure` to document desired future behaviour.
"""

import threading
import time
import unittest
from typing import List, Any
from thread_factory.synchronization.coordinators.conductor import Conductor
from thread_factory.utils.coordination.outcome import Outcome


def _spawn(n: int, fn):
    """Spin up *n* daemon threads and start them."""
    ts = [threading.Thread(target=fn, daemon=True) for _ in range(n)]
    for t in ts:
        t.start()
    return ts


def _collect_results(outcomes: List[Outcome]) -> List[Any]:
    """Return a list of successful results (skip failures)."""
    return [o.result() for o in outcomes if o.done and o.exception() is None]


def _collect_excs(outcomes: List[Outcome]) -> List[Exception]:
    return [o.exception() for o in outcomes if o.done and o.exception() is not None]


class TestConductor(unittest.TestCase):
    # ----------------------------------------------------------
    # Core success
    # ----------------------------------------------------------
    def test_threshold_release_and_single_result(self):
        c = Conductor(min_threads=2, tasks=lambda: "done")
        _spawn(2, c.wait)
        time.sleep(0.05)
        self.assertEqual(_collect_results(c.outcomes), ["done"])
        self.assertTrue(c.is_spent())

    def test_exception_capture(self):
        class Boom(Exception):
            pass
        c = Conductor(min_threads=1, tasks=lambda: (_ for _ in ()).throw(Boom("x")))
        c.wait()
        excs = _collect_excs(c.outcomes)
        self.assertEqual(len(excs), 1)
        self.assertIsInstance(excs[0], Boom)

    def test_mixed_task_outcomes(self):
        def ok1():
            return "one"
        def ok2():
            return "two"
        def bad():
            raise ZeroDivisionError()

        c = Conductor(min_threads=1, tasks=[ok1, bad, ok2])
        c.wait()
        self.assertCountEqual(_collect_results(c.outcomes), ["one", "two"])
        self.assertEqual(sum(isinstance(e, ZeroDivisionError) for e in _collect_excs(c.outcomes)), 1)

    # ----------------------------------------------------------
    # Reusable lifecycle
    # ----------------------------------------------------------
    def test_reusable_cycles_increment_counter(self):
        hits = {"n": 0}
        c = Conductor(min_threads=2, tasks=lambda: hits.__setitem__("n", hits["n"] + 1), reusable=True)

        for _ in range(2):
            _spawn(2, c.wait)
            time.sleep(0.05)
        self.assertEqual(hits["n"], 2)

    def test_is_spent(self):
        one = Conductor(min_threads=1)
        self.assertFalse(one.is_spent())
        one.wait(); self.assertTrue(one.is_spent())
        loop = Conductor(min_threads=1, reusable=True)
        loop.wait(); self.assertFalse(loop.is_spent())

    # ----------------------------------------------------------
    # Manual release & disposals
    # ----------------------------------------------------------
    @unittest.expectedFailure  # known bug
    def test_manual_release_blocks_until_called(self):
        c = Conductor(min_threads=2, tasks=lambda: None, manual_release=True)
        flag = threading.Event()
        _spawn(2, lambda: (c.wait(), flag.set()))
        time.sleep(0.1)
        self.assertFalse(flag.is_set())
        c.release(); self.assertTrue(flag.wait(1))

    def test_dispose_unblocks_waiter(self):
        c = Conductor(min_threads=2)
        result = []
        t = threading.Thread(target=lambda: result.append(c.wait()), daemon=True)
        t.start(); time.sleep(0.05)
        c.dispose(); t.join(1)
        self.assertEqual(result, [False])

    # ----------------------------------------------------------
    # Misc edge cases
    # ----------------------------------------------------------
    def test_wait_on_spent_returns_immediately(self):
        c = Conductor(min_threads=1)
        self.assertTrue(c.wait())
        self.assertTrue(c.wait())

    def test_no_tasks_means_no_outcomes(self):
        c = Conductor(min_threads=1)
        c.wait()
        self.assertEqual(c.outcomes, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
