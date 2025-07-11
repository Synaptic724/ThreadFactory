import unittest
import threading
import time
from collections import Counter

# Assuming the Fork class is in this location
from thread_factory import Fork


# =================================================================
# Test Utilities
# =================================================================

def dummy_func_factory(name, log_list, delay=0, exec_event=None):
    """
    A simple function factory for logging task execution with an
    optional delay.
    """

    def func():
        if delay > 0:
            time.sleep(delay)
        log_list.append(name)
        if exec_event:
            exec_event.set()

    return func


def spawn_and_await_barrier(n, barrier, target_func):
    """Creates, starts, and returns threads that immediately wait on a barrier."""
    threads = []
    for i in range(n):
        thread = threading.Thread(target=target_func, name=f"Worker-{i}")
        threads.append(thread)
        thread.start()
    return threads


# =================================================================
# The Crucible: Thundering Herd Tests for Fork
# =================================================================

class TestForkThunderingHerd(unittest.TestCase):
    """
    These tests are designed specifically to replicate the "thundering herd"
    scenario created by MultiConductor, where all threads hit 'use_fork'
    at the exact same time. This is the ultimate test of the Fork's
    distribution logic under extreme, simultaneous contention.
    """

    def setUp(self):
        self.log = []

    def test_thundering_herd_distribution(self):
        """
        [Primary Test]: All threads are released by a barrier at once.
        This test will fail if there is a race condition in the selector.
        """
        print("\n--- Herd Test 1: Perfect Synchronization Distribution ---")
        num_threads = 50
        num_forks = 5
        # 10 uses per fork
        callables = [(10, dummy_func_factory(f"F{i}", self.log)) for i in range(num_forks)]

        fork = Fork(number_of_forks=num_forks, callables=callables)

        # A barrier will hold all 50 threads until the last one arrives,
        # then release them all at once.
        barrier = threading.Barrier(num_threads)

        def worker_task():
            # All threads wait here
            barrier.wait()
            # The moment the barrier breaks, all threads call this simultaneously
            fork.use_fork()

        threads = spawn_and_await_barrier(num_threads, barrier, worker_task)

        for t in threads:
            t.join(timeout=5)  # Use a timeout to prevent hangs
            self.assertFalse(t.is_alive(), f"Thread {t.name} hung.")

        print(f"Execution Log Counts: {Counter(self.log)}")

        # ASSERTION: If the Fork is working correctly, the 50 tasks should be
        # perfectly distributed, with each of the 5 forks being used 10 times.
        self.assertEqual(len(self.log), num_threads, "Not all threads completed their tasks.")

        counts = Counter(self.log)
        for i in range(num_forks):
            self.assertEqual(counts[f"F{i}"], 10, f"Fork F{i} was not used the correct number of times.")

    def test_thundering_herd_resilience_with_reset(self):
        """
        [Resilience Test]: Proves the Fork can be reset and survive a
        second thundering herd, ensuring its internal state is properly cleared.
        """
        print("\n--- Herd Test 2: Resilience and Reset ---")
        num_threads = 20
        num_forks = 4
        # 5 uses per fork
        callables = [(5, dummy_func_factory(f"F{i}", self.log)) for i in range(num_forks)]
        fork = Fork(number_of_forks=num_forks, callables=callables)

        # --- First Wave ---
        print("  - Firing first wave...")
        barrier1 = threading.Barrier(num_threads)

        def worker_task_1():
            barrier1.wait()
            fork.use_fork()

        threads1 = spawn_and_await_barrier(num_threads, barrier1, worker_task_1)
        for t in threads1: t.join()

        self.assertEqual(len(self.log), num_threads)
        with self.assertRaises(RuntimeError, msg="Fork should be exhausted after first wave."):
            fork.use_fork()

        # --- Reset and Second Wave ---
        print("  - Resetting and firing second wave...")
        self.log.clear()
        fork.reset()

        barrier2 = threading.Barrier(num_threads)

        def worker_task_2():
            barrier2.wait()
            fork.use_fork()

        threads2 = spawn_and_await_barrier(num_threads, barrier2, worker_task_2)
        for t in threads2: t.join()

        # ASSERTION: After reset, the Fork should have worked perfectly again.
        self.assertEqual(len(self.log), num_threads, "Fork did not work correctly after reset.")
        counts = Counter(self.log)
        for i in range(num_forks):
            self.assertEqual(counts[f"F{i}"], 5, f"Fork F{i} had incorrect count on second wave.")

    def test_thundering_herd_starvation(self):
        """
        [Starvation Test]: Combines the thundering herd with a mix of slow
        and fast tasks to ensure fair distribution under pressure.
        """
        print("\n--- Herd Test 3: Starvation Check ---")
        num_threads = 40
        # 10 uses per task
        callables = [
            (10, dummy_func_factory("Slow", self.log, delay=0.05)),
            (10, dummy_func_factory("FastA", self.log, delay=0.001)),
            (10, dummy_func_factory("FastB", self.log, delay=0.001)),
            (10, dummy_func_factory("FastC", self.log, delay=0.001)),
        ]
        fork = Fork(number_of_forks=4, callables=callables, rotate_selectors=True)
        barrier = threading.Barrier(num_threads)

        def worker_task():
            barrier.wait()
            fork.use_fork()

        threads = spawn_and_await_barrier(num_threads, barrier, worker_task)
        for t in threads: t.join(timeout=5)

        # ASSERTION: Even though the 'Slow' task holds threads for longer,
        # the selector should have distributed work to it fairly at the start.
        counts = Counter(self.log)
        print(f"Execution Log Counts: {counts}")
        self.assertEqual(len(self.log), num_threads)
        self.assertEqual(counts['Slow'], 10, "Slow task was not fully utilized.")
        self.assertEqual(counts['FastA'], 10)
        self.assertEqual(counts['FastB'], 10)
        self.assertEqual(counts['FastC'], 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)