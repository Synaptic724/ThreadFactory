"""test_conductor.py
====================
Unit-tests for Conductor, including controller integration and callbacks.
"""

import threading
import time
import unittest
from typing import List, Any, Dict, Union, Optional
from thread_factory import Conductor


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
    # ----------------------------------------------------------
    #  EXTRA CONCURRENCY & PERMIT-HANDLING TESTS
    # ----------------------------------------------------------

    def test_all_threads_exit_after_tasks(self):
        """Every thread that calls start() must return once work is done."""
        c = Conductor(threshold=4, tasks=lambda: "x")
        threads = _spawn(4, c.start)
        for t in threads:
            t.join(5)
        self.assertTrue(all(not t.is_alive() for t in threads))
        self.assertTrue(c.is_spent())
        c.dispose()


    def test_exception_releases_permit_and_other_threads_continue(self):
        """An exception in one task must not strand the other threads."""
        active = {"cnt": 0}
        mtx = threading.Lock()

        def sometimes_boom():
            with mtx:
                active["cnt"] += 1
            try:
                # FIX: Reliably trigger the exception in one thread by name.
                if threading.current_thread().name.endswith("-0"):
                    raise ValueError("boom")
                return "ok"
            finally:
                with mtx:
                    active["cnt"] -= 1

        c = Conductor(threshold=3,
                      tasks=[sometimes_boom],
                      multiple_outcomes_per_task=True)

        # FIX: Provide explicit thread names to _spawn to make the test deterministic.
        thread_names = [f"worker-{i}" for i in range(3)]
        threads = _spawn(3, c.start, thread_names=thread_names)
        for t in threads: t.join(2)

        # One exception, two successes
        self.assertEqual(len(c.outcomes[0]), 3)
        successes = [o.result() for o in c.outcomes[0] if o.exception() is None]
        errors = [o.exception() for o in c.outcomes[0] if o.exception() is not None]
        self.assertEqual(successes, ["ok"] * 2)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ValueError)
        c.dispose()

    # 1 ─ results() only returns successful results, never exceptions
    def test_results_property_filters_exceptions(self):
        def good(): return "ok"

        def bad(): raise ValueError("boom")

        c = Conductor(threshold=2, tasks=[good, bad], multiple_outcomes_per_task=True)
        # FIX: Join on all spawned threads, not just the first one.
        threads = _spawn(2, c.start)
        for t in threads:
            t.join(2)

        self.assertEqual(c.results, ["ok"] * 2)
        self.assertEqual(len(c.exceptions), 2)
        c.dispose()

    def test_reset_after_success_allows_fresh_outcomes(self):
        """After reset(), old outcomes must be gone and new ones recorded."""
        c = Conductor(threshold=2,
                      tasks=[lambda: "cycle1"],
                      reusable=True,
                      multiple_outcomes_per_task=True)

        _spawn(2, c.start)[0].join()
        self.assertEqual([o.result() for o in c.outcomes[0]], ["cycle1"] * 2)

        c.reset()
        self.assertEqual(len(c.outcomes), 0)

        c.tasks = [lambda: "cycle2"]          # new task body
        c._callback_executed_flags = [False]  # reset callback tracking
        _spawn(2, c.start)[0].join()
        self.assertEqual([o.result() for o in c.outcomes[0]], ["cycle2"] * 2)
        c.dispose()

    def test_internal_barrier_synchronises_between_tasks(self):
        """
        The second task should not run until *all* threads have completed
        the first task – verified via a shared counter snapshot.
        """
        first_phase_hits = {"cnt": 0}
        snapshot_values  = []

        snap_lock = threading.Lock()

        def phase1():
            with snap_lock:
                first_phase_hits["cnt"] += 1

        def phase2():
            # record how many threads had reached phase-1 *before* this ran
            snapshot_values.append(first_phase_hits["cnt"])

        c = Conductor(threshold=3,
                      tasks=[phase1, phase2],
                      multiple_outcomes_per_task=True)

        threads = _spawn(3, c.start)
        for t in threads: t.join(2)

        # All three threads should have reached phase-1 before any phase-2 runs
        self.assertEqual(first_phase_hits["cnt"], 3)
        self.assertEqual(snapshot_values, [3, 3, 3])
        c.dispose()

    def test_surplus_threads_are_handled_gracefully(self):
        """
        Verify that if N > threshold threads call start(), only `threshold`
        threads execute the tasks.
        """
        task_executions = {"count": 0}
        task_lock = threading.Lock()

        def increment_task():
            with task_lock:
                task_executions["count"] += 1

        # Threshold is 3, but we will spawn 10 threads.
        c = Conductor(threshold=3, tasks=increment_task)

        # Spawn 10 threads to rush the Conductor
        threads = _spawn(10, c.start)
        for t in threads:
            # Use a longer join to ensure all threads finish, even those
            # that might have to wait for a permit briefly.
            t.join(2)

        # The task should have been executed exactly `threshold` times.
        self.assertEqual(task_executions["count"], 3)
        self.assertTrue(c.is_spent())
        c.dispose()

    def test_concurrent_dispose_unblocks_all_waiters(self):
        """
        Verify that calling dispose() unblocks all threads currently
        waiting in start().
        """
        # High threshold that won't be met.
        c = Conductor(threshold=10)
        waiters_are_blocked = threading.Event()

        # This list will hold the thread objects that we expect to be blocked.
        waiting_threads = []

        def blocking_waiter():
            # Let the main thread know this waiter is about to block.
            waiters_are_blocked.set()
            # This call should block until dispose() is called.
            c.start()

        # Spawn 3 threads that will all block on the barrier.
        for _ in range(3):
            t = threading.Thread(target=blocking_waiter, daemon=True)
            waiting_threads.append(t)
            t.start()

        # Wait until at least one thread is confirmed to be at the barrier.
        self.assertTrue(waiters_are_blocked.wait(timeout=1), "Waiters never blocked.")

        # Give a moment for all waiters to block, then dispose.
        time.sleep(0.1)
        self.assertTrue(any(t.is_alive() for t in waiting_threads))
        c.dispose()

        # All threads should have been unblocked by dispose() and terminated.
        for t in waiting_threads:
            t.join(timeout=1)

        self.assertFalse(any(t.is_alive() for t in waiting_threads), "Not all waiters were unblocked by dispose.")
    # 2 ─ exceptions() never returns disposals / internal runtime errors
    def test_exceptions_property_ignores_disposed_noise(self):
        def nop(): return None

        c = Conductor(threshold=1, tasks=[nop])
        _spawn(1, c.start)[0].join()
        c.dispose()  # dispose triggers RuntimeError in outcomes
        self.assertEqual(c.exceptions, [])  # should filter them
        c.dispose()

    # 3 ─ manual_release does not unblock until release() is called
    def test_manual_release_waits_for_explicit_call(self):
        c = Conductor(threshold=1, manual_release=True)
        flag = threading.Event()
        threading.Thread(target=lambda: (c.start(), flag.set()), daemon=True).start()
        time.sleep(0.10)
        self.assertFalse(flag.is_set())  # still blocked
        c.release()
        self.assertTrue(flag.wait(1))  # unblocked after release()
        c.dispose()
    #
    # def test_callback_exception_is_handled_without_crashing(self):
    #     class CallbackError(Exception):
    #         pass
    #
    #     task_completed = threading.Event()
    #     callback_log_emitted = threading.Event()  # New event for logging confirmation
    #
    #     def faulty_callback():
    #         try:
    #             raise CallbackError("Callback failed!")
    #         finally:
    #             # This doesn't guarantee the log has been *processed* by assertLogs,
    #             # but it tells us the point where it should have been emitted.
    #             # A small sleep *after* this might still be needed for assertLogs to catch it.
    #             callback_log_emitted.set()
    #
    #     def simple_task():
    #         task_completed.set()
    #         return "done"
    #
    #     controller = SignalController()
    #     controller._logger = logging.getLogger(f"controller-{ulid.ULID()}")
    #     c = Conductor(
    #         threshold=1,
    #         tasks=simple_task,
    #         callback=faulty_callback,
    #         controller=controller
    #     )
    #
    #     with self.assertLogs(controller._logger, level='ERROR') as cm:
    #         thread = _spawn(1, c.start)[0]
    #         thread.join(timeout=5)
    #         self.assertFalse(thread.is_alive(), "Conductor thread did not terminate.")
    #
    #         # Wait for the callback to indicate it finished its execution path
    #         self.assertTrue(callback_log_emitted.wait(timeout=1), "Callback did not emit log signal.")
    #         # A very small sleep might still be necessary here if logger buffers are large
    #         time.sleep(0.3)
    #
    #         self.assertTrue(any("Error in Conductor callback" in line for line in cm.output),
    #                         f"Expected log not found. Captured logs:\n{cm.output}")
    #         self.assertTrue(any("CallbackError: Callback failed!" in line for line in cm.output),
    #                         f"Expected exception message not found. Captured logs:\n{cm.output}")
    #
    #     self.assertTrue(task_completed.is_set())
    #     self.assertEqual(c.results, ["done"])
    #
    #     c.dispose()
    #     controller.dispose()
    # 4 ─ release() has no effect if threshold not yet met
    def test_release_before_threshold_is_noop(self):
        c = Conductor(threshold=2, manual_release=True)
        waiter = threading.Thread(target=c.start, daemon=True)
        waiter.start()
        time.sleep(0.05)
        c.release()  # threshold still 1/2
        self.assertTrue(waiter.is_alive())  # thread still waiting
        c.notify_all_override()  # unblock so test ends
        waiter.join(1)
        c.dispose()

    # 5 ─ reusable Conductor can be reset twice in a row
    def test_double_reset_on_reusable(self):
        c = Conductor(threshold=1, reusable=True)
        _spawn(1, c.start)[0].join()
        c.reset()
        _spawn(1, c.start)[0].join()
        c.reset()  # second reset must not raise
        self.assertFalse(c._broken)
        c.dispose()

    # 6 ─ surplus threads call start() after barrier already spent
    def test_surplus_threads_return_immediately(self):
        c = Conductor(threshold=3)  # only first 3 participate
        threads = _spawn(5, c.start)  # 2 surplus callers
        for t in threads: t.join(2)
        self.assertEqual(len(c.results), 0)  # no tasks so no outcomes
        c.dispose()

    # 7 ─ Dynaphore never allows more than threshold concurrent executions
    def test_dynaphore_permit_limit(self):
        running = 0
        lock = threading.RLock()
        max_seen = {"v": 0}

        def task():
            nonlocal running
            with lock:
                running += 1
                max_seen["v"] = max(max_seen["v"], running)
            time.sleep(0.05)
            with lock:
                running -= 1

        c = Conductor(threshold=3, tasks=[task])
        _spawn(3, c.start)  # exactly threshold threads
        time.sleep(0.2)
        self.assertLessEqual(max_seen["v"], 3)  # ≤ threshold OK
        c.dispose()

    # 8 ─ callback is NOT fired when tasks list is empty
    def test_callback_not_called_without_tasks(self):
        flag = {"called": False}

        def cb(): flag["called"] = True

        c = Conductor(threshold=1, callback=cb)  # no tasks
        _spawn(1, c.start)[0].join()
        self.assertFalse(flag["called"])
        c.dispose()

    # 9 ─ dispose() during wait unblocks all threads without exceptions propagated
    def test_dispose_mid_wait_unblocks_threads(self):
        c = Conductor(threshold=5)
        started = threading.Event()

        def waiter():
            started.set()
            c.start()

        ts = _spawn(3, waiter)
        started.wait()
        time.sleep(0.05)
        c.dispose()  # should unblock
        for t in ts: t.join(1)
        self.assertTrue(all(not t.is_alive() for t in ts))
        self.assertTrue(c._disposed)

    # 10 ─ notify_all_override emits BARRIER_BROKEN to controller exactly once
    def test_notify_all_override_broadcasts_once(self):
        controller = SignalController()
        events = []
        c = Conductor(threshold=2, controller=controller)
        controller.subscribe(c.id, "BARRIER_BROKEN",
                             lambda i, e, d: events.append(e))
        threading.Thread(target=c.start, daemon=True).start()
        time.sleep(0.05)
        c.notify_all_override()
        c.notify_all_override()  # second call should be ignored
        self.assertEqual(events.count("BARRIER_BROKEN"), 1)
        c.dispose()
        controller.dispose()

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
                t.join(5)
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
        # FIX: Check the public properties, which are safe on a disposed object.
        self.assertEqual(c.results, [])
        self.assertEqual(c.exceptions, [])

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
            t.join(2)

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
        for t in threads: t.join(5)
        self.assertEqual(len(c.outcomes[0]), 3)
        self.assertEqual([o.result() for o in c.outcomes[0]], ["result"] * 3)
        c.dispose()

    def test_multiple_threads_multiple_outcomes_per_task_exception(self):
        class ThreadSpecificError(Exception): pass
        def task_zero_error(): raise ThreadSpecificError("fail")
        c = Conductor(threshold=3, tasks=[task_zero_error], multiple_outcomes_per_task=True)
        threads = _spawn(3, c.start)
        for t in threads: t.join(5)
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
            t.join(5)

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
            t.join(2)

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



