import threading
import time
import unittest

# Assuming these imports are correctly configured in your project
from thread_factory.primitives.transit_gate import TransitGate
from thread_factory.utils import Outcome


class TestTransitGate(unittest.TestCase):
    """
    Test suite for the TransitGate class, ensuring its core functionalities
    like concurrent limiting, concurrency, and state management work as expected.
    """

    def setUp(self):
        """
        Set up a dummy TransitGate instance for tests that don't need a specific
        blocking behavior. For tests requiring blocking, a new gate is created
        within the test method.
        """
        # Provide a simple, non-blocking function to satisfy the constructor's 'func' argument.
        self.gate = TransitGate(func=lambda: "default_ok", limit=1)

    def test_basic_transit(self):
        """
        Verify that a single transit attempt works correctly and returns an outcome.
        """
        gate = TransitGate(func=lambda: "allowed", limit=1)
        outcome = gate.transit()
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome.result(), "allowed")

    def test_transit_beyond_concurrent_limit_is_blocked(self):
        """
        Ensure that attempts to transit beyond the set concurrent limit are blocked.
        The first task will 'hold' the gate, blocking subsequent transits.
        """
        # Define a task that holds the gate open by waiting on an event
        task_done_event = threading.Event()

        def blocking_task():
            task_done_event.wait(timeout=2)  # Wait to simulate a long-running task
            return "first_task_done"

        gate = TransitGate(func=blocking_task, limit=1)

        # Start the first transit in a separate thread to allow main thread to check immediately
        thread1_outcome = [None]
        thread1 = threading.Thread(target=lambda: thread1_outcome.__setitem__(0, gate.transit()))
        thread1.start()

        # Give the thread a moment to acquire the lock and start blocking
        time.sleep(0.05)

        # Now, try a second transit. It should be blocked because the limit is 1 and one is active.
        thread2_outcome = gate.transit()
        self.assertIsNone(thread2_outcome, "Second transit should be blocked when limit is 1 and one task is active.")

        # Allow the first task to complete to clean up the thread
        task_done_event.set()
        thread1.join(timeout=2)

        # Verify the result of the first task
        self.assertIsNotNone(thread1_outcome[0])
        self.assertEqual(thread1_outcome[0].result(), "first_task_done")

    def test_concurrent_limit_is_respected(self):
        """
        Test that the gate correctly limits the number of threads executing concurrently.
        Only 'limit' number of threads should successfully transit.
        """
        gate_limit = 3
        num_threads = 10

        # Use a barrier to ensure all threads try to transit at roughly the same time
        start_barrier = threading.Barrier(num_threads + 1)  # +1 for the main test thread

        # A task that simulates work and allows us to track concurrency
        current_concurrent_count = 0
        max_concurrent_seen = 0
        lock_for_metrics = threading.Lock()

        def concurrent_task():
            nonlocal current_concurrent_count, max_concurrent_seen
            with lock_for_metrics:
                current_concurrent_count += 1
                max_concurrent_seen = max(max_concurrent_seen, current_concurrent_count)
            time.sleep(0.1)  # Simulate a task that holds the gate for a moment
            with lock_for_metrics:
                current_concurrent_count -= 1
            return "pass"

        gate = TransitGate(func=concurrent_task, limit=gate_limit)
        successful_transits = []

        def worker():
            start_barrier.wait()  # All threads wait here
            outcome = gate.transit()
            if outcome is not None:
                successful_transits.append(outcome.result())

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]

        for t in threads:
            t.start()

        start_barrier.wait()  # Release all worker threads to race to the gate

        for t in threads:
            t.join()

        # Only `gate_limit` number of threads should have successfully transited
        self.assertEqual(len(successful_transits), gate_limit,
                         f"Expected {gate_limit} successful transits, but got {len(successful_transits)}")
        self.assertTrue(all(r == "pass" for r in successful_transits))

        # This assertion confirms that the max concurrent count never exceeded the limit
        self.assertEqual(max_concurrent_seen, gate_limit,
                         f"Max concurrent tasks seen ({max_concurrent_seen}) did not match gate limit ({gate_limit})")

    def test_increase_limit(self):
        """
        Check if increasing the limit allows for more concurrent transits.
        """
        task_held_event = threading.Event()
        task_entered_gate_event = threading.Event()

        def holding_task():
            task_entered_gate_event.set()  # Signal that the task has entered the gate
            task_held_event.wait(timeout=4)
            return "held"

        gate = TransitGate(func=holding_task, limit=1)

        # Thread 1 starts and holds the gate
        thread1 = threading.Thread(target=gate.transit)
        thread1.start()
        # Wait for the thread to acquire the gate
        task_entered_gate_event.wait(timeout=1)

        # Verify that a second transit is currently blocked
        self.assertIsNone(gate.transit(), "Second transit should be blocked before limit increase.")

        # Increase the limit
        gate.increase_limit(1)  # Limit becomes 2

        # A new transit should now be allowed immediately
        thread2_outcome = gate.transit()
        self.assertIsNotNone(thread2_outcome, "Second transit should be allowed after limit increase.")
        # We don't need to check the result, just that it's a valid outcome
        # (calling .result() would block this thread, so we don't do it here)

        # Now the limit should be exhausted again (2 active tasks, limit 2)
        self.assertIsNone(gate.transit(), "Third transit should be blocked after limit is exhausted again.")

        # Release the holding tasks to clean up threads
        task_held_event.set()
        thread1.join(timeout=2)

    def test_decrease_limit(self):
        """
        Verify that decreasing the limit correctly restricts concurrent transits.
        """
        # A task that holds the gate open
        task_held_event = threading.Event()
        task_entered_gate_event = threading.Event()

        def holding_task():
            task_entered_gate_event.set()  # Signal that the task has entered the gate
            task_held_event.wait(timeout=2)
            return "held"

        gate = TransitGate(func=holding_task, limit=3)

        # Decrease the limit to 1
        gate.decrease_limit(2)  # Limit becomes 1

        # Only one transit should now be allowed concurrently
        thread1 = threading.Thread(target=gate.transit)
        thread1.start()
        # Wait for the thread to enter the gate
        task_entered_gate_event.wait(timeout=1)

        result2 = gate.transit()

        # Assertions
        self.assertIsNotNone(gate.outcomes()[0], "First transit should be allowed.")
        self.assertIsNone(result2, "Second transit should be blocked after limit decrease to 1.")

        # Release the holding task to clean up the thread
        task_held_event.set()
        thread1.join()

    def test_collapse_prevents_all_transit(self):
        """
        Ensure that collapsing the gate blocks all future transits, regardless of current count.
        """
        gate = TransitGate(func=lambda: "pass", limit=3)
        gate.collapse()
        result = gate.transit()
        self.assertIsNone(result, "Transit should be blocked after gate collapse.")

    def test_reset_allows_transit_again(self):
        """
        Confirm that resetting the gate clears the active count and allows new transits
        up to its (possibly new) limit.
        """
        task_held_event = threading.Event()
        task_entered_gate_event = threading.Event()

        def holding_task_for_reset():
            task_entered_gate_event.set()  # Signal that the task has entered the gate
            task_held_event.wait(timeout=2)
            return "held_for_reset"

        gate = TransitGate(func=holding_task_for_reset, limit=1)

        # A thread transits and holds the gate
        thread1 = threading.Thread(target=gate.transit)
        thread1.start()
        task_entered_gate_event.wait(timeout=1)  # Wait for thread 1 to enter

        # Verify it's now blocked for additional transits
        self.assertIsNone(gate.transit(), "Transit should be blocked before reset.")

        # Reset the gate
        gate.reset()

        # A new transit should now be allowed
        outcome = gate.transit()
        self.assertIsNotNone(outcome, "Transit should be allowed after reset.")
        self.assertEqual(outcome.result(), "held_for_reset", "Outcome after reset should be correct.")

        # Clean up the initial holding task
        task_held_event.set()
        thread1.join()

    def test_callable_raises_exception(self):
        """
        Check that exceptions raised by the callable are captured in the outcome.
        """

        def fail_task():
            raise RuntimeError("Test RuntimeError")

        gate = TransitGate(func=fail_task, limit=1)
        outcome = gate.transit()
        self.assertIsNotNone(outcome)
        with self.assertRaises(RuntimeError) as cm:
            outcome.result()
        self.assertEqual(str(cm.exception), "Test RuntimeError")

    def test_multiple_resets_work(self):
        """
        Ensure the reset functionality can be used multiple times.
        """
        task_held_event = threading.Event()
        task_entered_gate_event = threading.Event()

        def holding_task():
            task_entered_gate_event.set()
            task_held_event.wait(timeout=1)
            return "held"

        gate = TransitGate(func=holding_task, limit=1)

        # First cycle
        thread1 = threading.Thread(target=gate.transit)
        thread1.start()
        task_entered_gate_event.wait(timeout=1)
        self.assertIsNone(gate.transit(), "Transit should be blocked after the first transit is active.")
        gate.reset()
        task_held_event.set()
        thread1.join()

        # Second cycle
        thread2 = threading.Thread(target=gate.transit)
        thread2.start()
        task_entered_gate_event.wait(timeout=1)
        self.assertIsNone(gate.transit(), "Transit should be blocked in the second cycle.")
        gate.reset()

        # Third cycle
        self.assertIsNotNone(gate.transit(), "Transit should be allowed in the third cycle.")

        # Release for cleanup
        task_held_event.set()
        thread2.join()

    def test_transit_with_no_params_callable(self):
        """
        Verify that the gate works with a callable that takes no parameters.
        """

        def no_param_task():
            return "success"

        gate = TransitGate(func=no_param_task, limit=1)
        outcome = gate.transit()
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome.result(), "success")


# --- Corrected Integration Test Cases ---

class TestTransitGateIntegration(unittest.TestCase):
    """
    Integration tests to check how the TransitGate behaves in more complex,
    multi-threaded scenarios.
    """

    def test_transit_bypass_and_execution_with_sleep(self):
        """
        Simulate a scenario where one thread is allowed to execute a long task,
        and then the gate is collapsed, blocking others.
        """
        # Events to control task flow and track execution
        task_started_event = threading.Event()

        def long_task():
            task_started_event.set()  # Signal that the task has begun
            time.sleep(0.5)  # Simulate work
            return "executed"

        gate = TransitGate(func=long_task, limit=1)
        start_threads_event = threading.Event()
        result_holder = []

        def thread_worker(name, delay):
            start_threads_event.wait()  # Wait for all threads to be ready
            time.sleep(delay)  # Introduce staggered start

            outcome = gate.transit()
            result = outcome.result() if outcome else None
            result_holder.append((name, result))

        threads = [threading.Thread(target=thread_worker, args=(f"worker-{i}", i * 0.05)) for i in range(5)]

        for t in threads:
            t.start()

        start_threads_event.set()  # Release all worker threads

        # Wait for the first task to start and enter the gate
        task_started_event.wait(timeout=2)

        # Immediately collapse the gate AFTER the first task has entered
        gate.collapse()

        # Join all threads
        for t in threads:
            t.join(timeout=1)

        results = [r for _, r in result_holder]
        executed_count = results.count("executed")
        bypassed_count = results.count(None)

        self.assertEqual(executed_count, 1, "Exactly one thread should execute the task.")
        self.assertEqual(bypassed_count, 4, "The remaining four threads should be bypassed.")

    def test_transit_with_event_release(self):
        """
        Test a more complex interaction: one thread gets the gate and blocks,
        while all *other* threads are bypassed because the first is still active.
        """
        num_workers = 5
        start_threads_event = threading.Event()
        # Barrier for all workers + the main thread to sync after their transit attempt
        # before the active task is allowed to finish.
        after_transit_attempt_barrier = threading.Barrier(num_workers + 1)  # +1 for the main test thread

        # This event will unblock the long_blocking_task.
        # It's set *after* all other workers have tried to transit.
        unblock_active_task_event = threading.Event()

        result_holder = []  # To collect results from all threads

        def long_blocking_task():
            """
            This task will enter the gate, then wait for an explicit signal
            to ensure it holds the gate open while other workers attempt transit.
            """
            unblock_active_task_event.wait(timeout=5)
            return "done"

        gate = TransitGate(func=long_blocking_task, limit=1)

        def worker_thread(name, delay):
            start_threads_event.wait()  # All threads start together
            time.sleep(delay)  # Introduce a slight staggered entry for race conditions

            outcome = gate.transit()

            # Record the result for later assertion
            if outcome is None:
                result_holder.append(f"{name} bypassed")
            else:
                result_holder.append(outcome.result())

            # All workers (successful or bypassed) must hit this barrier
            # to ensure the main thread doesn't unblock the first task too early.
            try:
                after_transit_attempt_barrier.wait(timeout=5)
            except threading.BrokenBarrierError:
                # Barrier might break if a timeout occurs elsewhere, handle gracefully
                pass

        # Create threads with staggered start times to ensure race conditions are hit
        threads = [threading.Thread(target=worker_thread, args=(f"worker-{i}", i * 0.01)) for i in range(num_workers)]

        for t in threads:
            t.start()

        # Release all worker threads to start their attempts
        start_threads_event.set()

        # The main thread waits for all workers to attempt transit (and hit their barrier)
        # This ensures all others are processed as 'bypassed' *while* the gate is held by worker-0.
        try:
            after_transit_attempt_barrier.wait(timeout=5)
        except threading.BrokenBarrierError:
            # This can happen if one of the worker threads times out before reaching the barrier.
            # This indicates a potential issue, but we proceed to unblock anyway.
            pass

        # Now, explicitly unblock the task that successfully entered the gate
        unblock_active_task_event.set()

        # Join all threads to ensure they've completed their execution
        for t in threads:
            t.join(timeout=2)  # Shorter timeout after unblock

        # Assertions
        # Check that 'done' is in the results (meaning one thread completed)
        self.assertIn("done", result_holder, "The long-blocking task should have completed.")

        # Check counts
        done_count = len([res for res in result_holder if res == "done"])
        bypassed_count = len([res for res in result_holder if "bypassed" in res])

        self.assertEqual(done_count, 1, "Only one thread should have successfully transited and returned 'done'.")
        self.assertEqual(bypassed_count, num_workers - 1, f"Expected {num_workers - 1} threads to be bypassed.")


if __name__ == "__main__":
    unittest.main()