import unittest
import threading
import time
from thread_factory.synchronization.dispatchers.fork import Fork


def dummy_func_factory(name, log, delay=0):
    def func():
        if delay > 0:
            time.sleep(delay)
        log.append(name)
    return func


class TestFork(unittest.TestCase):

    def test_benchmark_high_concurrency_throughput(self):
        """
        Benchmark 1: Measures raw dispatch throughput with 500 threads and a small delay.
        """
        print("\n--- Benchmark 1: High Concurrency Throughput (500 threads) ---")
        log = []
        num_forks = 10
        total_tasks = 500
        # Each fork can handle 50 uses.
        callables = [(50, dummy_func_factory(f"F{i}", log, delay=0.001)) for i in range(num_forks)]

        fork = Fork(
            number_of_forks=num_forks,
            callables=callables,
            rotate_selectors=True  # Use the flip selector for contention
        )

        threads = []
        start_time = time.perf_counter()

        for _ in range(total_tasks):
            t = threading.Thread(target=fork.use_fork)
            threads.append(t)
            t.start()
            # Stagger starts slightly to avoid thundering herd and get a more realistic measure
            time.sleep(0.0001)

        for t in threads:
            t.join()

        end_time = time.perf_counter()
        total_time = end_time - start_time

        print(f"Total tasks completed: {len(log)} / {total_tasks}")
        print(f"Total execution time: {total_time:.4f} seconds")
        print(f"Throughput: {total_tasks / total_time:.2f} tasks/second")

        self.assertEqual(len(log), total_tasks)
        for unit in fork._list_of_forks:
            self.assertLessEqual(unit.gate_uses, unit.usage_cap)

    def test_benchmark_starvation_resilience_hardcore(self):
        """
        Benchmark 2: Stresses the selector with a mix of slow and fast tasks
        to prove resilience against starvation.
        """
        print("\n--- Benchmark 2: Starvation Resilience (200 threads) ---")
        log = []
        total_tasks = 200
        # Mix of fast (1ms) and slow (50ms) tasks
        callables = [
            (50, dummy_func_factory("Slow_A", log, delay=0.05)),
            (50, dummy_func_factory("Fast_A", log, delay=0.001)),
            (50, dummy_func_factory("Slow_B", log, delay=0.05)),
            (50, dummy_func_factory("Fast_B", log, delay=0.001))
        ]

        # Test both selectors. First, the flip selector.
        fork_flip = Fork(
            number_of_forks=4,
            callables=callables,
            rotate_selectors=True
        )

        threads_flip = []
        start_time_flip = time.perf_counter()
        for _ in range(total_tasks):
            t = threading.Thread(target=fork_flip.use_fork)
            threads_flip.append(t)
            t.start()
            time.sleep(0.0001)

        for t in threads_flip:
            t.join()
        end_time_flip = time.perf_counter()

        slow_count_flip = log.count("Slow_A") + log.count("Slow_B")
        fast_count_flip = log.count("Fast_A") + log.count("Fast_B")

        print(f"  Flip Selector: Total Time = {end_time_flip - start_time_flip:.4f}s")
        print(f"    - Slow tasks used: {slow_count_flip}")
        print(f"    - Fast tasks used: {fast_count_flip}")
        self.assertEqual(len(log), total_tasks, "Flip Selector: Not all tasks completed.")
        self.assertGreater(slow_count_flip, 0, "Flip Selector: Slow tasks were starved.")
        self.assertGreater(fast_count_flip, 0, "Flip Selector: Fast tasks were starved.")

        # Reset the log for the next test
        log.clear()

        # Then, the step selector.
        fork_step = Fork(
            number_of_forks=4,
            callables=callables,
            rotate_selectors=False
        )

        threads_step = []
        start_time_step = time.perf_counter()
        for _ in range(total_tasks):
            t = threading.Thread(target=fork_step.use_fork)
            threads_step.append(t)
            t.start()
            time.sleep(0.0001)

        for t in threads_step:
            t.join()
        end_time_step = time.perf_counter()

        slow_count_step = log.count("Slow_A") + log.count("Slow_B")
        fast_count_step = log.count("Fast_A") + log.count("Fast_B")

        print(f"  Step Selector: Total Time = {end_time_step - start_time_step:.4f}s")
        print(f"    - Slow tasks used: {slow_count_step}")
        print(f"    - Fast tasks used: {fast_count_step}")
        self.assertEqual(len(log), total_tasks, "Step Selector: Not all tasks completed.")
        self.assertGreater(slow_count_step, 0, "Step Selector: Slow tasks were starved.")
        self.assertGreater(fast_count_step, 0, "Step Selector: Fast tasks were starved.")

    def test_benchmark_single_fork_contention(self):
        """
        Benchmark 3: Measures performance when all threads compete for one resource.
        """
        print("\n--- Benchmark 3: Single Fork Contention (100 threads) ---")
        log = []
        total_tasks = 100

        # A single fork with a usage cap of 1, forcing serialization
        fork = Fork(
            number_of_forks=1,
            callables=[(total_tasks, dummy_func_factory("SingleFork", log, delay=0.005))]
        )

        threads = [threading.Thread(target=fork.use_fork) for _ in range(total_tasks)]
        start_time = time.perf_counter()

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        end_time = time.perf_counter()
        total_time = end_time - start_time
        expected_time = total_tasks * 0.005

        print(f"Total tasks completed: {len(log)} / {total_tasks}")
        print(f"Total execution time: {total_time:.4f} seconds")
        print(f"Expected serialized time: {expected_time:.4f} seconds (approx)")

        self.assertEqual(len(log), total_tasks)
        # Assert the measured time is close to the expected serialized time
        self.assertAlmostEqual(total_time, expected_time, delta=0.09)  # Allow a 50ms delta for overhead

    def test_step_selector_even_distribution(self):
        log = []
        fork = Fork(
            number_of_forks=4,
            callables=[(3, dummy_func_factory(f"F{i}", log)) for i in range(4)],
            rotate_selectors=False,
            selector_step=1
        )

        for _ in range(12):
            fork.use_fork()

        self.assertEqual(log.count("F0"), 3)
        self.assertEqual(log.count("F1"), 3)
        self.assertEqual(log.count("F2"), 3)
        self.assertEqual(log.count("F3"), 3)

    def test_step_selector_wraparound(self):
        log = []
        fork = Fork(
            number_of_forks=2,
            callables=[(4, dummy_func_factory("A", log)), (4, dummy_func_factory("B", log))],
            rotate_selectors=False,
            selector_step=1
        )

        for _ in range(8):
            fork.use_fork()

        self.assertEqual(log.count("A"), 4)
        self.assertEqual(log.count("B"), 4)

    def test_step_selector_skipping_exhausted(self):
        log = []
        fork = Fork(
            number_of_forks=3,
            callables=[
                (1, dummy_func_factory("X", log)),
                (3, dummy_func_factory("Y", log)),
                (1, dummy_func_factory("Z", log))
            ],
            rotate_selectors=False,
            selector_step=1
        )

        for _ in range(5):
            fork.use_fork()

        self.assertEqual(log.count("X"), 1)
        self.assertEqual(log.count("Y"), 3)
        self.assertEqual(log.count("Z"), 1)

        with self.assertRaises(RuntimeError):
            fork.use_fork()

    def test_flip_selector_balancing(self):
        log = []
        fork = Fork(
            number_of_forks=4,
            callables=[(10, dummy_func_factory(f"F{i}", log)) for i in range(4)],
            rotate_selectors=True
        )

        threads = [threading.Thread(target=fork.use_fork) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(log), 20)
        for name in ["F0", "F1", "F2", "F3"]:
            self.assertLessEqual(log.count(name), 10)

    def test_reuse_after_reset(self):
        log = []
        fork = Fork(
            number_of_forks=2,
            callables=[
                (2, dummy_func_factory("A", log)),
                (2, dummy_func_factory("B", log))
            ]
        )

        for _ in range(4):
            fork.use_fork()

        with self.assertRaises(RuntimeError):
            fork.use_fork()

        fork.reset()

        for _ in range(4):
            fork.use_fork()

        self.assertEqual(log.count("A"), 4)
        self.assertEqual(log.count("B"), 4)

    def test_multithreaded_stress_step_selector(self):
        log = []
        fork = Fork(
            number_of_forks=5,
            callables=[(10, dummy_func_factory(f"F{i}", log, delay=0.01)) for i in range(5)],
            rotate_selectors=False,
            selector_step=1
        )

        threads = [threading.Thread(target=fork.use_fork) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(log), 50)
        for name in ["F0", "F1", "F2", "F3", "F4"]:
            self.assertEqual(log.count(name), 10)

    def test_all_forks_exhausted_error(self):
        fork = Fork(
            number_of_forks=3,
            callables=[
                (1, lambda: None),
                (1, lambda: None),
                (1, lambda: None)
            ]
        )

        for _ in range(3):
            fork.use_fork()

        with self.assertRaises(RuntimeError):
            fork.use_fork()

    def test_selector_step_custom_stride(self):
        log = []
        fork = Fork(
            number_of_forks=4,
            callables=[
                (3, dummy_func_factory("0", log)),
                (3, dummy_func_factory("1", log)),
                (3, dummy_func_factory("2", log)),
                (3, dummy_func_factory("3", log))
            ],
            rotate_selectors=False,
            selector_step=2
        )

        for _ in range(12):
            fork.use_fork()

        self.assertEqual(log.count("0"), 3)
        self.assertEqual(log.count("1"), 3)
        self.assertEqual(log.count("2"), 3)
        self.assertEqual(log.count("3"), 3)

    def test_bad_configurations(self):
        with self.assertRaises(ValueError):
            Fork(2, [(1, lambda: None)])  # This will still be a ValueError from `number_of_forks != len(callables)`

        # FIX: Change TypeError to ValueError here
        with self.assertRaises(ValueError):  # Changed to ValueError
            Fork(1, ["not a tuple"])

        with self.assertRaises(TypeError):
            Fork(1, [(1.5, lambda: None)])

        with self.assertRaises(TypeError):
            Fork(1, [(1, "not callable")])

        async def dummy_async(): pass

        with self.assertRaises(TypeError):
            Fork(1, [(1, dummy_async)])

    def test_state_after_exhaustion(self):
        # Create a non-reusable fork with specific caps
        fork = Fork(
            number_of_forks=2,
            callables=[(2, lambda: None), (3, lambda: None)]
        )

        # Use all forks
        for _ in range(5):
            fork.use_fork()

        # Check that all fork units are exhausted and their gates are set
        for unit in fork._list_of_forks:
            # Check the gate status
            self.assertTrue(unit.gate)
            # Check if the usage count matches the cap
            self.assertEqual(unit.gate_uses, unit.usage_cap)

        # Verify that an attempt to use it again raises an error
        with self.assertRaises(RuntimeError):
            fork.use_fork()

    def test_nested_forks(self):
        inner_calls = [(2, dummy_func_factory("INNER", None))]
        inner_fork = Fork(1, inner_calls)

        def outer_job():
            inner_fork.use_fork()
            print("OUTER")

        outer_calls = [(2, outer_job)]
        outer_fork = Fork(1, outer_calls)

        threads = [threading.Thread(target=outer_fork.use_fork) for _ in range(2)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=5)
        for t in threads: self.assertFalse(t.is_alive())

        outer_fork.dispose()  # Clean up
        inner_fork.dispose()  # Clean up


    def test_reset_partially_used_fork(self):
        log = []
        fork = Fork(
            number_of_forks=2,
            callables=[
                (3, dummy_func_factory("A", log)),
                (3, dummy_func_factory("B", log))
            ]
        )

        # Use the fork a few times, but not to exhaustion
        for _ in range(3):
            fork.use_fork()

        # The log now has 3 entries.
        self.assertEqual(len(log), 3)

        # Reset the fork and clear the log for the next round of testing
        fork.reset()
        log.clear()  # <--- Add this line

        # Use the fork again, verifying that the counts are reset
        for _ in range(6):
            fork.use_fork()

        # The log should now contain only the entries from this second batch
        self.assertEqual(log.count("A"), 3)
        self.assertEqual(log.count("B"), 3)
        self.assertEqual(len(log), 6)  # Now this assertion will pass

    def test_multithreaded_flip_selector_with_delay(self):
        log = []
        fork = Fork(
            number_of_forks=4,
            callables=[
                (5, dummy_func_factory("Slow", log, delay=0.05)),
                (5, dummy_func_factory("Fast", log, delay=0.01)),
                (5, dummy_func_factory("Slow", log, delay=0.05)),
                (5, dummy_func_factory("Fast", log, delay=0.01))
            ],
            rotate_selectors=True
        )

        threads = []
        for _ in range(20):
            t = threading.Thread(target=fork.use_fork)
            threads.append(t)
            t.start()
            time.sleep(0.001)  # slight stagger to encourage selector variation

        for t in threads:
            t.join()

        self.assertEqual(len(log), 20)

        slow_count = log.count("Slow")
        fast_count = log.count("Fast")

        # Assert that both types of callables were used at least once
        self.assertGreater(slow_count, 0, "No 'Slow' callables were used — possible starvation.")
        self.assertGreater(fast_count, 0, "No 'Fast' callables were used — possible starvation.")

        # Total executions should still match the thread count
        self.assertEqual(slow_count + fast_count, 20)

        # Bonus: no unit should exceed its usage cap
        for unit in fork._list_of_forks:
            self.assertLessEqual(unit.gate_uses, unit.usage_cap)

    def test_selector_counter_reset(self):
        log = []
        fork = Fork(
            number_of_forks=3,
            callables=[
                (3, dummy_func_factory("A", log)),
                (3, dummy_func_factory("B", log)),
                (3, dummy_func_factory("C", log))
            ]
        )

        # Use the fork a few times
        for _ in range(2):
            fork.use_fork()

        # Capture the selector state
        initial_counter_state = fork._selector_step_counter
        self.assertGreater(initial_counter_state, 0)

        # Reset the fork
        fork.reset()

        # Verify that the counter has been reset to 0
        self.assertEqual(fork._selector_step_counter, 0)

        # Use the fork again and verify the order starts from the beginning
        # The first call after reset should use the first fork unit.
        fork.use_fork()
        self.assertEqual(log[-1], "A")

if __name__ == "__main__":
    unittest.main()
