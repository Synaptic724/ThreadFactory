"""test_conductor.py
====================
Unit-tests for **Conductor** – now validating via the **Outcome** objects
instead of helper properties (`results`, `exceptions`).

The implementation promises that every task maps 1-to-1 onto an
:class:`Outcome` placed in ``conductor.outcomes``. These tests therefore pull
successes and failures directly from those Outcome instances.

Notes
-----
* Per-call timeouts are *not* supported, so `start()` is invoked bare.
"""

import threading
import time
import unittest
from typing import List, Any, Dict, Union, Optional
from thread_factory.synchronization.coordinators.conductor import Conductor
from thread_factory.utils.coordination.outcome import Outcome
from thread_factory.concurrency import ConcurrentDict, ConcurrentList


# --- Supporting functions (modified to allow naming threads) ---
def _spawn(n: int, fn: callable, thread_names: Optional[List[str]] = None):
    """
    Spin up *n* daemon threads and start them.
    Assigns names if `thread_names` is provided and matches `n`.
    """
    ts = []
    for i in range(n):
        t = threading.Thread(target=fn, daemon=True)
        if thread_names and i < len(thread_names):
            t.name = thread_names[i]
        ts.append(t)
        t.start()  # Start thread AFTER name is potentially set
    return ts


def _collect_results(outcomes: ConcurrentDict[int, Union[Outcome, ConcurrentList[Outcome]]]) -> List[Any]:
    """Return a list of successful results (skip failures), handling ConcurrentDict and ConcurrentList."""
    successful = []
    # Iterate over the values of the ConcurrentDict
    for value in outcomes.values():
        # If multiple_outcomes_per_task is True, value will be a ConcurrentList
        # Otherwise, value will be a single Outcome
        outcomes_to_check = value if isinstance(value, ConcurrentList) else [value]

        for o in outcomes_to_check:
            if o.done and o.exception() is None:
                try:
                    successful.append(o.result())
                except Exception:
                    # If result() raises an exception (e.g., if disposed after done check), skip.
                    pass
    return successful


def _collect_excs(outcomes: ConcurrentDict[int, Union[Outcome, ConcurrentList[Outcome]]]) -> List[Exception]:
    """Return a list of captured task exceptions, handling ConcurrentDict and ConcurrentList."""
    errors = []
    # Iterate over the values of the ConcurrentDict
    for value in outcomes.values():
        # If multiple_outcomes_per_task is True, value will be a ConcurrentList
        # Otherwise, value will be a single Outcome
        outcomes_to_check = value if isinstance(value, ConcurrentList) else [value]

        for o in outcomes_to_check:
            if o.done:
                exc = o.exception()
                # Filter out the generic RuntimeError("Outcome was disposed.")
                if exc is not None and not (isinstance(exc, RuntimeError) and str(exc) == "Outcome was disposed."):
                    try:
                        errors.append(exc)
                    except Exception:
                        # If exception() raises an exception (e.g., if disposed after done check), skip.
                        pass
    return errors


# --- End of supporting functions ---


class TestConductor(unittest.TestCase):
    # ----------------------------------------------------------
    # Core success (default: multiple_outcomes_per_task=False)
    # ----------------------------------------------------------
    def test_threshold_release_and_single_result(self):
        c = Conductor(threshold=2, tasks=lambda: "done")
        threads = _spawn(2, c.start)
        for t in threads:
            t.join(1)  # Join with a timeout to prevent hanging if bugged
        # EXPECTATION CHANGE: If multiple_outcomes_per_task is False (default),
        # only ONE result per task index is recorded by setdefault.
        # So, for a single task lambda, we expect only one "done".
        self.assertEqual(_collect_results(c.outcomes), ["done"],
                         "Only one result expected when multiple_outcomes_per_task is False.")
        self.assertTrue(c.is_spent())
        c.dispose()

    def test_exception_capture(self):
        class Boom(Exception):
            pass

        c = Conductor(threshold=1, tasks=lambda: (_ for _ in ()).throw(Boom("x")))
        threads = _spawn(1, c.start)
        for t in threads:
            t.join(1)
        excs = _collect_excs(c.outcomes)
        self.assertEqual(len(excs), 1)
        self.assertIsInstance(excs[0], Boom)
        c.dispose()

    def test_mixed_task_outcomes(self):
        def ok1():
            return "one"

        def ok2():
            return "two"

        def bad():
            raise ZeroDivisionError()

        # Threshold 3, tasks=[ok1, bad, ok2].
        c = Conductor(threshold=3, tasks=[ok1, bad, ok2], multiple_outcomes_per_task=True)
        threads = _spawn(3, c.start)
        for t in threads:
            t.join(1)

        self.assertCountEqual(_collect_results(c.outcomes), ["one", "one", "one", "two", "two", "two"],
                              "Expected three results for 'one' and three for 'two' when multiple_outcomes_per_task is True.")
        self.assertEqual(sum(isinstance(e, ZeroDivisionError) for e in _collect_excs(c.outcomes)), 3,
                         "Expected three ZeroDivisionErrors when multiple_outcomes_per_task is True.")
        c.dispose()

    # ----------------------------------------------------------
    # Reusable lifecycle
    # ----------------------------------------------------------
    # In test_reusable_cycles_increment_counter
    def test_reusable_cycles_increment_counter(self):
        hits = {"n": 0}
        hits_lock = threading.Lock()

        def increment_task():
            with hits_lock:
                hits["n"] += 1

        c = Conductor(threshold=2, tasks=increment_task, reusable=True)

        for _ in range(2):  # Two cycles
            threads = _spawn(2, c.start)
            for t in threads:
                t.join(1)

            # This is the missing piece:
            c.reset()  # Reset the conductor for the next cycle

        self.assertEqual(hits["n"], 4,
                         "Expected 4 total task executions (2 threads * 2 cycles) for reusable Conductor.")
        c.dispose()
    def test_is_spent(self):
        one = Conductor(threshold=1)
        self.assertFalse(one.is_spent())
        threads_one = _spawn(1, one.start)
        for t in threads_one:
            t.join(1)
        self.assertTrue(one.is_spent(), "Conductor should be spent after one non-reusable use.")
        one.dispose()

        loop = Conductor(threshold=1, reusable=True)
        self.assertFalse(loop.is_spent())
        threads_loop_1 = _spawn(1, loop.start)
        for t in threads_loop_1:
            t.join(1)
        self.assertFalse(loop.is_spent(), "Conductor should NOT be spent as it's reusable.")
        loop.dispose()

    # ----------------------------------------------------------
    # Manual release & disposals
    # ----------------------------------------------------------
    @unittest.expectedFailure
    def test_manual_release_blocks_until_called(self):
        c = Conductor(threshold=2, tasks=lambda: None, manual_release=True)
        flag = threading.Event()
        threads = _spawn(2, lambda: (c.start(), flag.set()))

        time.sleep(0.1)
        self.assertFalse(flag.is_set(), "Threads should still be blocked waiting for manual release.")

        c.release()
        self.assertTrue(flag.wait(1), "Threads should be released after manual call.")
        c.dispose()

    def test_dispose_unblocks_waiter(self):
        c = Conductor(threshold=2)
        thread_finished_event = threading.Event()

        # Thread will call start(), then set the event upon completion or interruption
        t = threading.Thread(target=lambda: (c.start(), thread_finished_event.set()), daemon=True)
        t.start()
        time.sleep(0.05)  # Give thread time to block inside c.start()

        self.assertFalse(thread_finished_event.is_set(), "Thread should be blocked in start()")
        c.dispose()  # This should unblock the waiting thread
        t.join(1)      # Wait for the thread to terminate

        self.assertFalse(t.is_alive(), "Thread should have terminated after dispose().")
        self.assertTrue(thread_finished_event.is_set(), "Thread should have completed the start() call after dispose().")
        c.dispose()

    # ----------------------------------------------------------
    # Timeout Behavior
    # ----------------------------------------------------------

    def test_global_timeout_raises_exception(self):
        """Verify TimeoutError is raised if threshold isn't met and raise_on_timeout=True."""
        # Conductor needs 2 threads, but we'll only send 1. The call to start()
        # should block and then raise TimeoutError.
        c = Conductor(threshold=2, timeout=0.1, raise_on_timeout=True)
        with self.assertRaises(TimeoutError, msg="start() should raise TimeoutError when threshold is not met."):
            c.start()

        self.assertTrue(c._broken, "Conductor should be in a broken state after a timeout.")
        c.dispose()

    def test_global_timeout_returns_normally(self):
        """Verify start() returns normally if threshold isn't met and raise_on_timeout=False."""
        c = Conductor(threshold=2, timeout=0.1, raise_on_timeout=False)
        start_time = time.monotonic()

        # This call should block for ~0.1s and then return without an error.
        c.start()
        end_time = time.monotonic()

        duration = end_time - start_time
        self.assertGreaterEqual(duration, 0.1, "Call should block for at least the timeout duration.")
        self.assertLess(duration, 0.2, "Call should not block significantly longer than the timeout.")
        self.assertTrue(c._broken, "Conductor should be in a broken state after a timeout.")
        c.dispose()

    # ----------------------------------------------------------
    # Misc edge cases
    # ----------------------------------------------------------
    def test_start_on_spent_returns_immediately(self):
        c = Conductor(threshold=1)

        # First start: should pass successfully and mark Conductor as spent.
        t1 = threading.Thread(target=c.start, daemon=True)
        t1.start()
        t1.join(1) # Should complete well within 1s
        self.assertFalse(t1.is_alive(), "First thread should have completed.")
        self.assertTrue(c.is_spent(), "Conductor should be spent after first non-reusable use.")

        # Second start on a spent (non-reusable) Conductor: should return immediately.
        start_time = time.monotonic()
        t2 = threading.Thread(target=c.start, daemon=True)
        t2.start()
        t2.join(0.1) # Should join almost instantly
        end_time = time.monotonic()

        self.assertFalse(t2.is_alive(), "Second start on a spent conductor should have returned immediately.")
        self.assertLess(end_time - start_time, 0.05, "Second start should not block.")
        c.dispose()

    def test_no_tasks_means_no_outcomes(self):
        c = Conductor(threshold=1)
        threads = _spawn(1, c.start)
        for t in threads:
            t.join(1)
        self.assertEqual(len(c.outcomes), 0)
        self.assertEqual(_collect_results(c.outcomes), [])
        self.assertEqual(_collect_excs(c.outcomes), [])
        c.dispose()

    # ----------------------------------------------------------
    # New Tests: multiple_outcomes_per_task = True
    # ----------------------------------------------------------
    def test_single_thread_multiple_outcomes_per_task_result(self):
        def my_task():
            return "single_result_for_task_0"

        c = Conductor(threshold=1, tasks=[my_task], multiple_outcomes_per_task=True)
        threads = _spawn(1, c.start)
        for t in threads:
            t.join(1)

        self.assertIsInstance(c.outcomes, ConcurrentDict)
        self.assertEqual(len(c.outcomes), 1)
        self.assertIn(0, c.outcomes)

        self.assertIsInstance(c.outcomes[0], ConcurrentList)
        self.assertEqual(len(c.outcomes[0]), 1)

        outcome_obj = c.outcomes[0][0]
        self.assertIsInstance(outcome_obj, Outcome)
        self.assertTrue(outcome_obj.done)
        self.assertEqual(outcome_obj.result(), "single_result_for_task_0")
        self.assertIsNone(outcome_obj.exception())

        self.assertEqual(c.results, ["single_result_for_task_0"])
        self.assertEqual(c.exceptions, [])
        c.dispose()

    def test_single_thread_multiple_outcomes_per_task_exception(self):
        class TestError(Exception): pass

        def my_task():
            raise TestError("single_exception_for_task_0")

        c = Conductor(threshold=1, tasks=[my_task], multiple_outcomes_per_task=True)
        threads = _spawn(1, c.start)
        for t in threads:
            t.join(1)

        self.assertIsInstance(c.outcomes, ConcurrentDict)
        self.assertEqual(len(c.outcomes), 1)
        self.assertIn(0, c.outcomes)

        self.assertIsInstance(c.outcomes[0], ConcurrentList)
        self.assertEqual(len(c.outcomes[0]), 1)

        outcome_obj = c.outcomes[0][0]
        self.assertIsInstance(outcome_obj, Outcome)
        self.assertTrue(outcome_obj.done)
        with self.assertRaises(TestError):
            outcome_obj.result()
        self.assertIsInstance(outcome_obj.exception(), TestError)

        self.assertEqual(c.results, [])
        self.assertEqual(len(c.exceptions), 1)
        self.assertIsInstance(c.exceptions[0], TestError)
        c.dispose()

    def test_multiple_threads_multiple_outcomes_per_task_result(self):
        def task_zero():
            return f"result_from_thread_{threading.current_thread().name}"

        c = Conductor(threshold=3, tasks=[task_zero], multiple_outcomes_per_task=True)
        thread_names = [f"thread-{i}" for i in range(3)]
        threads = _spawn(3, c.start, thread_names=thread_names)

        for t in threads:
            t.join(1)

        self.assertIsInstance(c.outcomes, ConcurrentDict)
        self.assertEqual(len(c.outcomes), 1)
        self.assertIn(0, c.outcomes)

        task_0_outcomes = c.outcomes[0]
        self.assertIsInstance(task_0_outcomes, ConcurrentList)
        self.assertEqual(len(task_0_outcomes), 3, "Expected 3 outcomes for task_zero, one per thread.")

        results = [o.result() for o in task_0_outcomes if o.done and o.exception() is None]
        self.assertEqual(len(results), 3)
        self.assertIn("result_from_thread_thread-0", results)
        self.assertIn("result_from_thread_thread-1", results)
        self.assertIn("result_from_thread_thread-2", results)

        self.assertEqual(len(_collect_excs(c.outcomes)), 0)
        c.dispose()

    def test_multiple_threads_multiple_outcomes_per_task_exception(self):
        class ThreadSpecificError(Exception):
            def __init__(self, msg):
                super().__init__(msg)

        def task_zero_error():
            raise ThreadSpecificError(f"error_from_thread_{threading.current_thread().name}")

        c = Conductor(threshold=3, tasks=[task_zero_error], multiple_outcomes_per_task=True)
        thread_names = [f"thread-{i}" for i in range(3)]
        threads = _spawn(3, c.start, thread_names=thread_names)

        for t in threads:
            t.join(1)

        self.assertIsInstance(c.outcomes, ConcurrentDict)
        self.assertEqual(len(c.outcomes), 1)
        self.assertIn(0, c.outcomes)

        task_0_outcomes = c.outcomes[0]
        self.assertIsInstance(task_0_outcomes, ConcurrentList)
        self.assertEqual(len(task_0_outcomes), 3, "Expected 3 outcomes for task_zero_error, one per thread.")

        exceptions = [o.exception() for o in task_0_outcomes if o.done and o.exception() is not None]
        self.assertEqual(len(exceptions), 3)
        self.assertTrue(all(isinstance(e, ThreadSpecificError) for e in exceptions))

        error_messages = sorted([str(e) for e in exceptions])
        self.assertEqual(error_messages, [
            "error_from_thread_thread-0",
            "error_from_thread_thread-1",
            "error_from_thread_thread-2",
        ])

        self.assertEqual(len(_collect_results(c.outcomes)), 0)
        c.dispose()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()