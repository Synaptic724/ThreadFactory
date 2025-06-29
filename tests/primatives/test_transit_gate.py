import unittest
import threading
import time
from typing import Callable, Optional, List, Union, Any

# Assuming these are correctly configured in your project
from thread_factory.primitives.transit_gate import TransitGate
from thread_factory.utils import Outcome


class TestTransitGate(unittest.TestCase):
    """
    Test suite for the TransitGate class, covering basic, pipeline, and dynamic features.
    """

    def setUp(self):
        """
        Setup common data for tests.
        """
        self.lock = threading.Lock()
        self.results = []
        self.call_count = 0

    def record_result(self, value):
        with self.lock:
            self.results.append(value)
            self.call_count += 1
            return value

    def create_blocking_task(self, block_event: threading.Event, result):
        """Creates a task that blocks until an event is set."""

        def task():
            block_event.wait()
            return self.record_result(result)

        return task

    # --- 1. Basic Functionality (Single Callable) ---
    def test_single_thread_transit(self):
        """Tests that a single thread can transit and execute a callable."""
        gate = TransitGate(func=[lambda: self.record_result("pass")], limit=1)
        outcome = gate.transit()

        self.assertIsNone(outcome)  # Transit() no longer returns the Outcome
        self.assertEqual(len(gate.outcomes()), 1)
        self.assertEqual(gate.outcomes()[0].result(), "pass")

    def test_multiple_threads_respect_limit(self):
        """Tests that more threads than the limit are skipped."""
        gate = TransitGate(func=[lambda: self.record_result("pass")], limit=3)
        threads = [threading.Thread(target=gate.transit) for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()

        # Based on _set_result logic, only one outcome is recorded.
        self.assertEqual(len(gate.outcomes()), 1)
        self.assertEqual(self.call_count, 1)

    def test_threads_respect_limit_with_blocking_task(self):
        """Tests threads blocking until the gate is available."""
        block_event = threading.Event()
        task = self.create_blocking_task(block_event, "pass")
        gate = TransitGate(func=[task], limit=2)

        # Start 3 threads. 2 will enter, 1 will be skipped.
        threads = [threading.Thread(target=gate.transit) for _ in range(3)]
        for t in threads: t.start()

        # Give threads time to hit the gate and block
        time.sleep(0.1)

        # The gate should be full with 2 threads blocking.
        # But `call_count` is 0 because the tasks haven't finished yet.
        self.assertEqual(self.call_count, 0)

        # Release the blocking tasks
        block_event.set()
        for t in threads: t.join()

        # Now all 3 threads should have completed their transit attempts,
        # and the tasks have now returned.
        # The outcome logic should have only recorded one outcome per stage (i.e., for the first task).
        self.assertEqual(len(gate.outcomes()), 1)
        self.assertEqual(self.call_count, 2)

    def test_callable_with_params_is_bound(self):
        """Tests that a single callable with parameters is correctly bound at init."""

        def param_task(msg):
            return self.record_result(msg)

        gate = TransitGate(func=param_task, limit=1, msg="Hello")
        gate.transit()

        self.assertEqual(len(gate.outcomes()), 1)
        self.assertEqual(gate.outcomes()[0].result(), "Hello")

    def test_callable_raises_exception(self):
        """Tests that a callable raising an exception is caught and recorded."""

        def fail_task():
            raise RuntimeError("Test exception")

        gate = TransitGate(func=[fail_task], limit=1)
        gate.transit()

        self.assertEqual(len(gate.outcomes()), 1)
        with self.assertRaises(RuntimeError):
            gate.outcomes()[0].result()

    # --- 2. Pipeline Functionality (List of Callables) ---
    def test_thread_executes_all_callables_in_pipeline(self):
        """Tests that a single thread executes all callables in the list."""
        flags = {"task1_done": False, "task2_done": False}

        def task_1(): flags["task1_done"] = True

        def task_2(): flags["task2_done"] = True

        gate = TransitGate(func=[task_1, task_2], limit=1)
        gate.transit()

        self.assertTrue(flags["task1_done"])
        self.assertTrue(flags["task2_done"])
        # Each task in the list sets an outcome
        self.assertEqual(len(gate.outcomes()), 2)

    def test_pipeline_synchronizes_threads_at_stages(self):
        """
        Tests that threads wait for each other at the ThresholdSemaphore
        between each callable in the pipeline.
        """
        # A task that signals its completion of a stage
        stage_1_complete = threading.Event()
        stage_2_complete = threading.Event()

        def task_1(): stage_1_complete.set()

        def task_2(): stage_2_complete.set()

        gate = TransitGate(func=[task_1, task_2], limit=2)

        # Start 2 threads
        t1 = threading.Thread(target=gate.transit)
        t2 = threading.Thread(target=gate.transit)
        t1.start()
        t2.start()

        # Wait for both threads to complete Stage 1
        # The ThresholdSemaphore should make them wait here.
        stage_1_complete.wait(timeout=1)

        # Check that Stage 2 has not started yet
        self.assertFalse(stage_2_complete.is_set())

        # The semaphore will release them after the 2nd thread hits it.
        # Now wait for Stage 2 to complete
        stage_2_complete.wait(timeout=1)

        self.assertTrue(stage_2_complete.is_set())

        t1.join()
        t2.join()

    def test_outcome_is_recorded_for_each_callable(self):
        """Tests that the outcomes list contains an outcome for each callable in the list."""

        def task_a(): return "A"

        def task_b(): return "B"

        gate = TransitGate(func=[task_a, task_b], limit=1)
        gate.transit()

        self.assertEqual(len(gate.outcomes()), 2)
        self.assertEqual(gate.outcomes()[0].result(), "A")
        self.assertEqual(gate.outcomes()[1].result(), "B")

    def test_pipeline_collapses_after_completion(self):
        """Tests that the gate collapses after a thread completes the entire pipeline."""
        gate = TransitGate(func=[lambda: "stage1", lambda: "stage2"], limit=1)

        # First transit completes the pipeline and collapses the gate
        gate.transit()

        # Subsequent transit attempts should be blocked
        outcome = gate.transit()
        self.assertIsNone(outcome)
        self.assertTrue(gate._collapsed)

    def test_exception_in_pipeline_is_recorded_and_continues(self):
        """Tests that an exception in a stage is recorded but the pipeline continues."""

        def task_1(): return "success"

        def task_2(): raise ValueError("Stage 2 fail")

        def task_3(): return "success again"

        gate = TransitGate(func=[task_1, task_2, task_3], limit=1)
        gate.transit()

        outcomes = gate.outcomes()
        self.assertEqual(len(outcomes), 3)
        self.assertEqual(outcomes[0].result(), "success")
        with self.assertRaises(ValueError):
            outcomes[1].result()
        self.assertEqual(outcomes[2].result(), "success again")

    # --- 3. Dynamic Limit & State Management ---
    def test_increase_limit_allows_more_transits(self):
        """Tests that increasing the limit allows more threads to enter the gate."""
        gate = TransitGate(func=[lambda: "stage1"], limit=1)

        # Thread 1 starts and acquires the single permit
        t1 = threading.Thread(target=gate.transit)
        t1.start()
        time.sleep(0.1)

        # A second thread should be blocked
        t2 = threading.Thread(target=gate.transit)
        t2.start()
        time.sleep(0.1)

        self.assertEqual(len(gate.outcomes()), 1)

        # Now increase the limit to 2
        gate.increase_limit(1)
        time.sleep(0.1)  # Give time for state to update

        # The second thread should now acquire the new permit and finish its transit
        self.assertEqual(len(gate.outcomes()), 2)

        t1.join()
        t2.join()

    def test_decrease_limit_blocks_future_transits(self):
        """Tests that decreasing the limit blocks subsequent transit attempts."""
        # Use a blocking task to ensure threads hold the gate
        block_event = threading.Event()
        task = self.create_blocking_task(block_event, "stage1")
        gate = TransitGate(func=[task], limit=3)

        # Start 2 threads (below the initial limit)
        threads = [threading.Thread(target=gate.transit) for _ in range(2)]
        for t in threads: t.start()

        # Wait for threads to enter the gate and block
        time.sleep(0.1)
        self.assertEqual(len(gate.outcomes()), 2)

        # Decrease the limit to 1
        gate.decrease_limit(2)

        # A new thread should now be blocked
        t3 = threading.Thread(target=gate.transit)
        t3.start()
        time.sleep(0.1)

        # The gate should be full (count=2, limit=1), so no new outcomes should be added.
        self.assertEqual(len(gate.outcomes()), 2)

        # Release the blocking tasks to clean up
        block_event.set()
        for t in threads: t.join()
        t3.join()

    def test_collapse_prevents_all_transits(self):
        """Tests that collapse() immediately stops all future transits."""
        gate = TransitGate(func=[lambda: "pass"], limit=10)
        gate.collapse()

        outcome = gate.transit()
        self.assertIsNone(outcome)
        self.assertEqual(len(gate.outcomes()), 0)

    def test_reset_clears_state_and_allows_reuse(self):
        """Tests that the gate can be reset and used again."""
        gate = TransitGate(func=[lambda: "pass"], limit=1)

        # Use the gate once, which will collapse it
        gate.transit()
        self.assertTrue(gate._collapsed)

        # Reset the gate
        gate.reset()

        # It should now be usable again
        self.assertFalse(gate._collapsed)
        outcome = gate.transit()
        self.assertIsNone(outcome)
        self.assertEqual(len(gate.outcomes()), 2)  # Outcome from first and second transit

    def test_outcomes_are_cleared_on_reset(self):
        """Tests that the outcomes list is cleared when the gate is reset."""
        gate = TransitGate(func=[lambda: "pass"], limit=1)

        gate.transit()
        self.assertGreater(len(gate.outcomes()), 0)

        gate.reset()
        self.assertEqual(len(gate.outcomes()), 0)

    def test_re_entering_gate_after_completion_is_blocked(self):
        """Tests that a thread that completed the pipeline cannot transit again."""
        gate = TransitGate(func=[lambda: "pass"], limit=1)

        # First transit completes and collapses the gate
        t = threading.Thread(target=gate.transit)
        t.start()
        t.join()

        # A second attempt by the same thread should be blocked
        outcome = gate.transit()
        self.assertIsNone(outcome)
        self.assertTrue(gate._collapsed)

    def test_negative_count_behavior(self):
        """Tests that the internal count can go negative due to the decrement logic."""
        gate = TransitGate(func=[lambda: "stage1", lambda: "stage2"], limit=1)
        gate.transit()

        # The count is decremented twice in the loop, but only incremented once at the start.
        # So, the final count should be negative.
        self.assertLess(gate._count, 0)

    def test_dispose_shuts_down_gate_and_dependencies(self):
        """Tests that dispose() releases threads and shuts down components."""
        gate = TransitGate(func=[lambda: "pass"], limit=1)
        t = threading.Thread(target=gate.transit)
        t.start()

        time.sleep(0.1)  # Let the thread acquire the gate

        gate.dispose()
        t.join(timeout=1)

        # Check if the thread was unblocked and if dependencies are gone
        self.assertFalse(t.is_alive())
        self.assertTrue(gate._disposed)
        self.assertIsNone(gate._dynaphore)
        self.assertIsNone(gate._threshold_sema)


if __name__ == '__main__':
    unittest.main()