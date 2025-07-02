"""test_conductor.py
====================
Unit-tests for Conductor, including controller integration and callbacks.
"""

import threading
import time
import unittest
import logging
from typing import List, Any, Dict, Union, Optional

# Mock the controller for standalone testing if it's not available
# In your actual project, you would import your real classes
try:
    from thread_factory.synchronization.coordinators.conductor import Conductor
    from thread_factory.synchronization.controllers.signal_controller import SignalController
    from thread_factory.utils.coordination.outcome import Outcome
    from thread_factory.concurrency import ConcurrentDict, ConcurrentList
except ImportError:
    # Create mock objects if the real ones aren't in the path
    # This allows the test file to be self-contained for analysis
    SignalController = type('SignalController', (object,), {'_logger': logging.getLogger('mock_controller')})
    Conductor = type('Conductor', (object,), {})
    Outcome = type('Outcome', (object,), {})
    ConcurrentDict = dict
    ConcurrentList = list


# --- Supporting functions ---
def _spawn(n: int, fn: callable, thread_names: Optional[List[str]] = None):
    """Spins up n daemon threads and starts them."""
    ts = []
    for i in range(n):
        t = threading.Thread(target=fn, daemon=True)
        if thread_names and i < len(thread_names):
            t.name = thread_names[i]
        ts.append(t)
        t.start()
    return ts


def _collect_results(outcomes: Dict) -> List[Any]:
    """Return a list of successful results."""
    successful = []
    for value in outcomes.values():
        # FIX: If `value` has a `.done` attr, it's a single Outcome.
        # Otherwise, assume it's the iterable collection of Outcomes.
        outcomes_to_check = [value] if hasattr(value, 'done') else value
        for o in outcomes_to_check:
            if hasattr(o, 'done') and o.done and o.exception() is None:
                try:
                    successful.append(o.result())
                except Exception:
                    pass
    return successful


def _collect_excs(outcomes: Dict) -> List[Exception]:
    """Return a list of captured task exceptions."""
    errors = []
    for value in outcomes.values():
        # FIX: Apply the same logic here.
        outcomes_to_check = [value] if hasattr(value, 'done') else value
        for o in outcomes_to_check:
            if hasattr(o, 'done') and o.done:
                exc = o.exception()
                if exc is not None and not (isinstance(exc, RuntimeError) and "disposed" in str(exc)):
                    errors.append(exc)
    return errors

# --- End of supporting functions ---


class TestConductor(unittest.TestCase):

    # ... (all of your existing passing tests remain the same) ...

    # ----------------------------------------------------------
    # Core success (default: multiple_outcomes_per_task=False)
    # ----------------------------------------------------------
    def test_threshold_release_and_single_result(self):
        c = Conductor(threshold=2, tasks=lambda: "done")
        threads = _spawn(2, c.start)
        for t in threads:
            t.join(1)
        self.assertEqual(_collect_results(c.outcomes), ["done"])
        self.assertTrue(c.is_spent())
        c.dispose()

    def test_exception_capture(self):
        class Boom(Exception): pass
        c = Conductor(threshold=1, tasks=lambda: (_ for _ in ()).throw(Boom("x")))
        threads = _spawn(1, c.start)
        for t in threads:
            t.join(1)
        excs = _collect_excs(c.outcomes)
        self.assertEqual(len(excs), 1)
        self.assertIsInstance(excs[0], Boom)
        c.dispose()

    def test_mixed_task_outcomes(self):
        def ok1(): return "one"
        def ok2(): return "two"
        def bad(): raise ZeroDivisionError()
        c = Conductor(threshold=3, tasks=[ok1, bad, ok2], multiple_outcomes_per_task=True)
        threads = _spawn(3, c.start)
        for t in threads:
            t.join(1)
        self.assertCountEqual(_collect_results(c.outcomes), ["one"] * 3 + ["two"] * 3)
        self.assertEqual(sum(isinstance(e, ZeroDivisionError) for e in _collect_excs(c.outcomes)), 3)
        c.dispose()

    # ----------------------------------------------------------
    # Reusable lifecycle
    # ----------------------------------------------------------
    def test_reusable_cycles_increment_counter(self):
        hits = {"n": 0}
        hits_lock = threading.Lock()
        def increment_task():
            with hits_lock:
                hits["n"] += 1
        c = Conductor(threshold=2, tasks=increment_task, reusable=True)
        for _ in range(2):
            threads = _spawn(2, c.start)
            for t in threads:
                t.join(1)
            c.reset()
        self.assertEqual(hits["n"], 4)
        c.dispose()

    def test_is_spent(self):
        one = Conductor(threshold=1)
        threads_one = _spawn(1, one.start)
        for t in threads_one:
            t.join(1)
        self.assertTrue(one.is_spent())
        one.dispose()
        loop = Conductor(threshold=1, reusable=True)
        threads_loop_1 = _spawn(1, loop.start)
        for t in threads_loop_1:
            t.join(1)
        self.assertFalse(loop.is_spent())
        loop.dispose()

    def test_start_on_disposed_conductor_is_noop(self):
        hits = {"n": 0}
        c = Conductor(threshold=1, tasks=lambda: hits.update(n=1))
        c.dispose()
        c.start()
        self.assertEqual(hits["n"], 0)
        self.assertEqual(len(c.outcomes), 0)

    def test_reset_on_disposed_conductor_raises_error(self):
        c = Conductor(threshold=1, reusable=True)
        c.dispose()
        with self.assertRaises(RuntimeError):
            c.reset()

    def test_notify_all_override_unblocks_waiters(self):
        c = Conductor(threshold=2)
        waiter_thread = threading.Thread(target=c.start, daemon=True)
        waiter_thread.start()
        time.sleep(0.1)
        self.assertTrue(waiter_thread.is_alive())
        c.notify_all_override()
        waiter_thread.join(timeout=0.1)
        self.assertFalse(waiter_thread.is_alive())
        self.assertTrue(c._broken)
        c.dispose()

    # ----------------------------------------------------------
    # FIX FOR `test_reusable_conductor_timeout_then_success`
    # ----------------------------------------------------------
    def test_reusable_conductor_timeout_then_success(self):
        """Verify a reusable conductor can timeout, be reset, and then succeed."""
        hits = {"n": 0}
        hits_lock = threading.Lock()

        # FIX: The lambda must be thread-safe as it's called by multiple threads.
        def safe_increment_task():
            with hits_lock:
                hits["n"] += 1

        c = Conductor(
            threshold=2,
            tasks=safe_increment_task,
            reusable=True,
            timeout=0.1
        )

        # Cycle 1: Force a timeout
        t1 = threading.Thread(target=c.start, daemon=True)
        t1.start()
        t1.join()
        self.assertTrue(c._broken)
        self.assertEqual(hits["n"], 0)

        # Reset for the next cycle
        c.reset()
        self.assertFalse(c._broken)

        # Cycle 2: Succeed normally
        threads = _spawn(2, c.start)
        for t in threads:
            t.join()

        # Both threads execute the task, so we expect 2 hits.
        self.assertEqual(hits["n"], 2, "Task should run on the successful second cycle.")
        self.assertFalse(c._broken)
        c.dispose()

    # ... (Manual release, dispose, other timeout tests remain the same) ...
    def test_manual_release_blocks_until_called(self):
        c = Conductor(threshold=2, manual_release=True)
        flag = threading.Event()
        _spawn(2, lambda: (c.start(), flag.set()))
        time.sleep(0.1)
        self.assertFalse(flag.is_set())
        c.release()
        self.assertTrue(flag.wait(1))
        c.dispose()

    def test_dispose_unblocks_waiter(self):
        c = Conductor(threshold=2)
        thread_finished_event = threading.Event()
        t = threading.Thread(target=lambda: (c.start(), thread_finished_event.set()), daemon=True)
        t.start()
        time.sleep(0.05)
        self.assertFalse(thread_finished_event.is_set())
        c.dispose()
        t.join(1)
        self.assertFalse(t.is_alive())
        self.assertTrue(thread_finished_event.is_set())
        c.dispose()

    def test_global_timeout_raises_exception(self):
        c = Conductor(threshold=2, timeout=0.1, raise_on_timeout=True)
        with self.assertRaises(TimeoutError):
            c.start()
        self.assertTrue(c._broken)
        c.dispose()

    def test_global_timeout_returns_normally(self):
        c = Conductor(threshold=2, timeout=0.1, raise_on_timeout=False)
        start_time = time.monotonic()
        c.start()
        end_time = time.monotonic()
        duration = end_time - start_time
        self.assertGreaterEqual(duration, 0.1)
        self.assertLess(duration, 0.2)
        self.assertTrue(c._broken)
        c.dispose()

    def test_start_on_spent_returns_immediately(self):
        c = Conductor(threshold=1)
        t1 = threading.Thread(target=c.start, daemon=True)
        t1.start()
        t1.join(1)
        self.assertFalse(t1.is_alive())
        self.assertTrue(c.is_spent())
        start_time = time.monotonic()
        t2 = threading.Thread(target=c.start, daemon=True)
        t2.start()
        t2.join(0.1)
        end_time = time.monotonic()
        self.assertFalse(t2.is_alive())
        self.assertLess(end_time - start_time, 0.05)
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

    # ... (all multiple_outcomes tests remain the same) ...
    def test_single_thread_multiple_outcomes_per_task_result(self):
        c = Conductor(threshold=1, tasks=[lambda: "result"], multiple_outcomes_per_task=True)
        _spawn(1, c.start)[0].join(1)
        self.assertEqual(len(c.outcomes[0]), 1)
        self.assertEqual(c.outcomes[0][0].result(), "result")
        c.dispose()

    def test_single_thread_multiple_outcomes_per_task_exception(self):
        class TestError(Exception): pass
        def my_task(): raise TestError("fail")
        c = Conductor(threshold=1, tasks=[my_task], multiple_outcomes_per_task=True)
        _spawn(1, c.start)[0].join(1)
        self.assertEqual(len(c.outcomes[0]), 1)
        self.assertIsInstance(c.outcomes[0][0].exception(), TestError)
        c.dispose()

    def test_multiple_threads_multiple_outcomes_per_task_result(self):
        c = Conductor(threshold=3, tasks=[lambda: "result"], multiple_outcomes_per_task=True)
        threads = _spawn(3, c.start)
        for t in threads: t.join(1)
        self.assertEqual(len(c.outcomes[0]), 3)
        self.assertEqual([o.result() for o in c.outcomes[0]], ["result"] * 3)
        c.dispose()

    def test_multiple_threads_multiple_outcomes_per_task_exception(self):
        class ThreadSpecificError(Exception): pass
        def task_zero_error(): raise ThreadSpecificError("fail")
        c = Conductor(threshold=3, tasks=[task_zero_error], multiple_outcomes_per_task=True)
        threads = _spawn(3, c.start)
        for t in threads: t.join(1)
        self.assertEqual(len(c.outcomes[0]), 3)
        self.assertTrue(all(isinstance(e.exception(), ThreadSpecificError) for e in c.outcomes[0]))
        c.dispose()

    # ----------------------------------------------------------
    # NEW TESTS for Callback and Controller Integration
    # ----------------------------------------------------------

    def test_once_per_task_callback(self):
        """Verify the 'callback' is fired exactly once per task in the loop."""
        callback_counts = {"count": 0}

        def my_callback():
            callback_counts["count"] += 1

        # Conductor with 2 tasks and the callback
        c = Conductor(threshold=2, tasks=[lambda: "task1", lambda: "task2"], callback=my_callback)

        threads = _spawn(2, c.start)
        for t in threads:
            t.join()

        # The callback should have been fired once for task1 and once for task2.
        self.assertEqual(callback_counts["count"], 2, "Callback should be fired once per task.")
        c.dispose()

    def test_conductor_registers_with_controller(self):
        """Verify the Conductor registers itself with the controller on creation."""
        controller = SignalController()
        c = Conductor(threshold=1, controller=controller)

        registered_objects = controller.list_objects(name_filter="conductor")
        self.assertEqual(len(registered_objects), 1, "Conductor should be registered.")
        self.assertEqual(registered_objects[0]['id'], c.id, "Registered ID should match conductor's ID.")
        c.dispose()
        controller.dispose()

    def test_controller_receives_events(self):
        """Verify the controller receives lifecycle events from the Conductor."""
        controller = SignalController()
        received_events = []

        def event_recorder(obj_id, event_type, data):
            received_events.append(event_type)

        # Create conductor and subscribe to its events via the controller
        c = Conductor(threshold=2, tasks=[lambda: "work"], controller=controller)
        controller.subscribe(c.id, "BARRIER_PASSED", event_recorder)
        controller.subscribe(c.id, "EXECUTION_STARTED", event_recorder)
        controller.subscribe(c.id, "EXECUTION_COMPLETED", event_recorder)

        threads = _spawn(2, c.start)
        for t in threads:
            t.join()

        expected_events = ["BARRIER_PASSED", "EXECUTION_STARTED", "EXECUTION_COMPLETED"]
        self.assertListEqual(received_events, expected_events, "Controller did not receive the correct sequence of events.")
        c.dispose()
        controller.dispose()

    def test_controller_invokes_command(self):
        """Verify the controller can invoke a command on the Conductor."""
        controller = SignalController()
        c = Conductor(threshold=1, reusable=True, controller=controller)

        # Run the conductor once
        _spawn(1, c.start)[0].join()
        self.assertTrue(c._released, "Conductor should be in a released state after first run.")

        # Use the controller to invoke the 'reset' command
        controller.invoke(c.id, 'reset')

        self.assertFalse(c._released, "Conductor should be reset to a non-released state.")
        self.assertFalse(c._broken, "Conductor should not be broken after reset.")
        c.dispose()
        controller.dispose()


if __name__ == "__main__":
    unittest.main()