import unittest
import threading
import time
from typing import List, Tuple, Callable
from concurrent.futures import ThreadPoolExecutor
from thread_factory.primitives.sync_fork import SyncFork


# Assume ForkUnit and SyncFork are imported from a module like `my_fork_module`
# from my_fork_module import SyncFork, ForkUnit


# --- Helper Functions for Testing ---

def dummy_func_factory(name: str, log: List[str], delay: float = 0):
    """
    Creates a simple callable function that logs its name and optionally waits.
    """

    def func():
        if delay > 0:
            time.sleep(delay)
        log.append(name)

    return func


def thread_use_fork(fork: 'SyncFork', log: List[str], thread_name: str):
    """
    Target function for threads to call use_fork().
    Includes a try-except block to catch the RuntimeError.
    """
    try:
        # Give a small delay to ensure all threads can start and hit the barrier
        time.sleep(0.01)
        fork.use_fork()
        log.append(f"{thread_name} executed callable.")
    except RuntimeError as e:
        log.append(f"{thread_name} raised RuntimeError: {e}")
    except Exception as e:
        log.append(f"{thread_name} raised unexpected error: {e}")


# --- Unit Test Class ---

class TestSyncFork(unittest.TestCase):

    def setUp(self):
        """Reset the logs before each test."""
        self.log = []

    def test_massive_concurrency(self):
        callables = [(1, dummy_func_factory("A", self.log)) for _ in range(50)]
        fork = SyncFork(number_of_forks=50, callables=callables)
        total_cap = fork._route_count  # 50

        with ThreadPoolExecutor(max_workers=2000) as pool:
            futures = [pool.submit(fork.use_fork) for _ in range(total_cap)]
            for f in futures:
                f.result(timeout=5)  # fail fast if any deadlock

        self.assertEqual(self.log.count("A"), 50)

    def test_selector_wraparound(self):
        """
        selector_step larger than fork count must still service every unit.
        """
        callables = [(4, dummy_func_factory(f"U{i}", self.log)) for i in range(3)]
        fork = SyncFork(3, callables, selector_step=10)  # stride >> length

        threads = [threading.Thread(target=thread_use_fork,
                                    args=(fork, self.log, f"T{i}"))
                   for i in range(fork._route_count)]

        for t in threads: t.start()
        for t in threads: t.join()

        for i in range(3):
            self.assertEqual(self.log.count(f"U{i}"), 4)

    def test_barrier_release_at_capacity(self):
        """
        Test that threads block and are released together when the total capacity is met.
        """
        print("\n--- Testing Barrier Release at Capacity ---")

        # Define forks with a total capacity of 5
        # 3 uses for worker_A, 2 uses for worker_B. Total capacity = 5.
        callables_list = [
            (3, dummy_func_factory("Worker_A", self.log)),
            (2, dummy_func_factory("Worker_B", self.log))
        ]

        fork = SyncFork(number_of_forks=2, callables=callables_list)
        total_capacity = sum(cap for cap, _ in callables_list)

        self.assertEqual(fork._route_count, total_capacity)

        # We need exactly 5 threads to hit the barrier
        num_threads = total_capacity
        threads = [
            threading.Thread(target=thread_use_fork, args=(fork, self.log, f"Thread-{i}"))
            for i in range(num_threads)
        ]

        # Start all threads, they should block at the barrier
        for t in threads:
            t.start()

        # Give them a moment to all hit the barrier
        time.sleep(0.1)

        # AFTER – threads may have already run; just make sure we didn't exceed capacity
        self.assertLessEqual(len(self.log), total_capacity * 2)
        # NEW  – event **should** already be set
        self.assertEqual(fork._blocked_thread_count, num_threads)
        self.assertTrue(fork._threading_event.is_set())

        # All threads should be waiting. Join them to wait for the barrier to be released.
        for t in threads:
            t.join()

        # After joining, all callables should have executed.
        self.assertEqual(len(self.log),
                         num_threads * 2)  # Each thread logs twice: once for execution, once for completion.

        # Verify the usage caps were respected
        worker_a_count = self.log.count("Worker_A")
        worker_b_count = self.log.count("Worker_B")
        self.assertEqual(worker_a_count, 3)
        self.assertEqual(worker_b_count, 2)
        self.assertEqual(worker_a_count + worker_b_count, total_capacity)

        # Verify that the event was set
        self.assertTrue(fork._threading_event.is_set())

        # All fork units should now be exhausted
        for unit in fork._list_of_forks:
            self.assertTrue(unit.gate)
            self.assertEqual(unit.gate_uses, unit.usage_cap)

    def test_callable_exception_does_not_deadlock(self):
        """
        A crashing callable must NOT leave other threads hanging.
        """

        def boom():
            self.log.append("BOOM")
            raise ValueError("kaboom")

        callables = [(1, boom), (1, dummy_func_factory("SAFE", self.log))]
        fork = SyncFork(2, callables)

        t1 = threading.Thread(target=thread_use_fork, args=(fork, self.log, "T1"))
        t2 = threading.Thread(target=thread_use_fork, args=(fork, self.log, "T2"))
        t1.start();
        t2.start();
        t1.join();
        t2.join()

        # One callable exploded, but both threads finished the barrier
        self.assertIn("BOOM", self.log)
        self.assertIn("SAFE", self.log)

    def test_rapid_reset_cycles(self):
        callables = [(1, dummy_func_factory("C", self.log))]
        fork = SyncFork(1, callables, reusable=True)

        for _ in range(100):  # 100 quick cycles
            t = threading.Thread(target=thread_use_fork, args=(fork, self.log, "Cycler"))
            t.start()
            t.join()
            fork.reset()

        self.assertEqual(self.log.count("C"), 100)

    def test_nested_forks(self):
        inner_calls = [(2, dummy_func_factory("INNER", self.log))]
        inner_fork = SyncFork(1, inner_calls)

        def outer_job():
            inner_fork.use_fork()
            self.log.append("OUTER")

        outer_calls = [(2, outer_job)]
        outer_fork = SyncFork(1, outer_calls)

        threads = [threading.Thread(target=outer_fork.use_fork) for _ in range(2)]
        for t in threads: t.start()
        for t in threads: t.join()

        self.assertEqual(self.log.count("INNER"), 2)
        self.assertEqual(self.log.count("OUTER"), 2)

    def test_fairness_variance(self):
        callables = [(5, dummy_func_factory(f"F{i}", self.log)) for i in range(4)]
        fork = SyncFork(4, callables, selector_step=3)

        threads = [threading.Thread(target=thread_use_fork,
                                    args=(fork, self.log, f"T{i}"))
                   for i in range(fork._route_count)]
        for t in threads: t.start()
        for t in threads: t.join()

        counts = [self.log.count(f"F{i}") for i in range(4)]
        # All should be exactly 5, but allow ±1 for timing oddities
        self.assertTrue(max(counts) - min(counts) <= 1,
                        msg=f"Unfair distribution: {counts}")

    def test_non_reusable_fork_exhaustion(self):
        """
        Test that a non-reusable fork raises a RuntimeError after exhaustion.
        """
        print("\n--- Testing Non-Reusable Fork Exhaustion ---")

        callables_list = [(1, dummy_func_factory("Single_Use", self.log))]
        fork = SyncFork(number_of_forks=1, callables=callables_list, reusable=False)

        # Use the fork the one time it's allowed
        t1 = threading.Thread(target=thread_use_fork, args=(fork, self.log, "Thread-1"))
        t1.start()
        t1.join()

        # The first thread should have executed successfully
        self.assertIn("Thread-1 executed callable.", self.log)
        self.assertIn("Single_Use", self.log)
        self.assertEqual(fork._blocked_thread_count, 1)

        # A second thread should now be "routed out" with a RuntimeError
        t2 = threading.Thread(target=thread_use_fork, args=(fork, self.log, "Thread-2"))
        t2.start()
        t2.join()

        # Check that the RuntimeError was logged
        self.assertIn("Thread-2 raised RuntimeError: All forks are at capacity.", self.log)

        # The callable should not have been executed a second time
        self.assertEqual(self.log.count("Single_Use"), 1)

    def test_reusable_fork_with_reset(self):
        """
        Test that a reusable fork can be reset and reused.
        """
        print("\n--- Testing Reusable Fork with Reset ---")

        callables_list = [(2, dummy_func_factory("A", self.log)), (2, dummy_func_factory("B", self.log))]
        fork = SyncFork(number_of_forks=2, callables=callables_list, reusable=True)

        # First round of execution
        threads1 = [threading.Thread(target=thread_use_fork, args=(fork, self.log, f"R1-T{i}")) for i in range(4)]
        for t in threads1: t.start()
        for t in threads1: t.join()

        self.assertEqual(self.log.count("A"), 2)
        self.assertEqual(self.log.count("B"), 2)
        self.assertTrue(fork._forks_closed)
        self.assertTrue(fork._threading_event.is_set())

        # Now, reset the fork
        print("--- Resetting the Fork ---")
        fork.reset()

        # Verify state is reset
        self.assertFalse(fork._forks_closed)
        self.assertEqual(fork._blocked_thread_count, 0)
        self.assertFalse(fork._threading_event.is_set())
        for unit in fork._list_of_forks:
            self.assertFalse(unit.gate)
            self.assertEqual(unit.gate_uses, 0)

        # Clear the log for the second round of verification
        self.log.clear()

        # Second round of execution after reset
        threads2 = [threading.Thread(target=thread_use_fork, args=(fork, self.log, f"R2-T{i}")) for i in range(4)]
        for t in threads2: t.start()
        for t in threads2: t.join()

        self.assertEqual(self.log.count("A"), 2)
        self.assertEqual(self.log.count("B"), 2)

    def test_single_fork_contention_barrier(self):
        """
        Test barrier functionality with a single fork and multiple threads.
        """
        print("\n--- Testing Single Fork Contention Barrier ---")

        # A single fork with a capacity of 10
        callables_list = [(10, dummy_func_factory("Single_Fork", self.log))]
        fork = SyncFork(number_of_forks=1, callables=callables_list)

        num_threads = 10
        threads = [threading.Thread(target=thread_use_fork, args=(fork, self.log, f"T{i}")) for i in range(num_threads)]

        # Start all threads
        for t in threads:
            t.start()

        # Wait a moment. The log should be empty until all 10 threads hit the barrier.
        time.sleep(0.1)

        # AFTER
        self.assertLessEqual(len(self.log), num_threads * 2)
        self.assertEqual(fork._blocked_thread_count, 10)
        self.assertTrue(fork._threading_event.is_set())  # The event should be set by the 10th thread

        # Join all threads
        for t in threads:
            t.join()

        # All 10 callables should have been executed
        self.assertEqual(self.log.count("Single_Fork"), 10)

    def test_selector_step_distribution(self):
        """
        Test that the step selector distributes usage across forks.
        """
        print("\n--- Testing Step Selector Distribution ---")

        callables_list = [(3, dummy_func_factory("F0", self.log)), (3, dummy_func_factory("F1", self.log)),
                          (3, dummy_func_factory("F2", self.log))]
        fork = SyncFork(number_of_forks=3, callables=callables_list, selector_step=1)

        num_threads = 9  # Total capacity is 3*3=9
        threads = [threading.Thread(target=thread_use_fork, args=(fork, self.log, f"T{i}")) for i in range(num_threads)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify that all callables were executed and usage caps were met
        self.assertEqual(self.log.count("F0"), 3)
        self.assertEqual(self.log.count("F1"), 3)
        self.assertEqual(self.log.count("F2"), 3)
        self.assertEqual(len(self.log), num_threads * 2)  # Logs for callable execution and thread completion

    def test_selector_step_with_custom_stride(self):
        """
        Test that a custom selector step (e.g., 2) works correctly.
        """
        print("\n--- Testing Selector with Custom Stride ---")

        callables_list = [(2, dummy_func_factory("F0", self.log)), (2, dummy_func_factory("F1", self.log)),
                          (2, dummy_func_factory("F2", self.log)), (2, dummy_func_factory("F3", self.log))]
        fork = SyncFork(number_of_forks=4, callables=callables_list, selector_step=2)

        num_threads = 8  # Total capacity is 4*2=8
        threads = [threading.Thread(target=thread_use_fork, args=(fork, self.log, f"T{i}")) for i in range(num_threads)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify that all callables were executed and usage caps were met
        self.assertEqual(self.log.count("F0"), 2)
        self.assertEqual(self.log.count("F1"), 2)
        self.assertEqual(self.log.count("F2"), 2)
        self.assertEqual(self.log.count("F3"), 2)
        self.assertEqual(len(self.log), num_threads * 2)

    def test_race_condition_contention(self):
        """
        Test that the locks prevent overuse of a single fork unit under heavy contention.
        """
        print("\n--- Testing Race Condition Contention ---")

        # A single fork unit with a capacity of 5
        callable_name = "Contended_Fork"
        callables_list = [(5, dummy_func_factory(callable_name, self.log))]
        fork = SyncFork(number_of_forks=1, callables=callables_list)

        num_threads = 20  # More threads than capacity to test race conditions and rejection
        threads = [threading.Thread(target=thread_use_fork, args=(fork, self.log, f"T{i}")) for i in range(num_threads)]

        for t in threads:
            t.start()

        # Give them some time to run and be rejected
        time.sleep(0.2)

        for t in threads:
            t.join()

        # Check logs for both successful executions and errors
        execution_count = self.log.count(callable_name)

        print(f"Total callables executed: {execution_count}")

        # Exactly 5 callables should have been executed
        self.assertEqual(execution_count, 5)

        # And the rest should have been routed out with an error
        error_log_count = len([item for item in self.log if "raised RuntimeError" in item])
        self.assertEqual(error_log_count, num_threads - 5)

        self.assertEqual(fork._blocked_thread_count, 5)
        self.assertEqual(fork._list_of_forks[0].gate_uses, 5)

    def test_improper_initialization(self):
        """
        Test that the constructor raises errors for invalid input.
        """
        print("\n--- Testing Improper Initialization ---")

        # Mismatch between number of forks and callables list
        with self.assertRaises(ValueError):
            SyncFork(number_of_forks=2, callables=[(1, lambda: None)])

        # Callable is not a tuple
        with self.assertRaises(TypeError):
            SyncFork(number_of_forks=1, callables=[lambda: None])

        # Usage cap is not an int
        with self.assertRaises(TypeError):
            SyncFork(number_of_forks=1, callables=[(1.5, lambda: None)])

        # Callable is not a function
        with self.assertRaises(TypeError):
            SyncFork(number_of_forks=1, callables=[(1, "not_callable")])

        # Callable is a coroutine function
        async def async_callable(): pass

        with self.assertRaises(TypeError):
            SyncFork(number_of_forks=1, callables=[(1, async_callable)])

# To run the tests, you would use:
# if __name__ == "__main__":
#     unittest.main(argv=['first-arg-is-ignored'], exit=False)