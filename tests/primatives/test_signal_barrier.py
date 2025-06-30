import unittest
import threading
import time
from thread_factory.synchronization.orchestrators.signal_barrier import SignalBarrier, Group


class TestSignalBarrier(unittest.TestCase):

    def test_single_group_data_aware(self):
        """Tests that a group's task is run and its result is captured."""

        def task_with_result():
            return "done"

        group = Group(threshold=2, tasks=task_with_result)
        barrier = SignalBarrier([group], reusable=False)

        def worker():
            self.assertTrue(barrier.wait(0, timeout=1), "wait() should return True on successful release")

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start();
        t2.start()
        t1.join();
        t2.join()

        self.assertEqual(group.results, ["done"])
        self.assertTrue(barrier.is_spent())

    def test_group_initialization_errors(self):
        """Tests that the Group class raises errors on invalid initialization."""
        with self.assertRaises(ValueError, msg="Group should not allow zero threshold"):
            Group(threshold=0)

        with self.assertRaises(TypeError, msg="Group should not allow non-callable tasks"):
            Group(threshold=1, tasks="not a function")

        with self.assertRaises(TypeError, msg="Group should not allow list with non-callables"):
            Group(threshold=1, tasks=[lambda: True, "not a function"])

        async def coro(): pass

        with self.assertRaises(TypeError, msg="Group should not allow coroutines"):
            Group(threshold=1, tasks=coro)

    def test_barrier_runtime_errors(self):
        """Tests for runtime errors with incorrect barrier usage."""
        # Cannot add group after barrier is enabled
        barrier_add = SignalBarrier()
        barrier_add.add_group(1)
        barrier_add.enable()
        with self.assertRaises(RuntimeError):
            barrier_add.add_group(1)
        barrier_add.dispose()

        # Cannot enable a barrier with no groups
        barrier_enable = SignalBarrier()
        with self.assertRaises(ValueError):
            barrier_enable.enable()
        barrier_enable.dispose()

        # Cannot wait with an invalid group index
        barrier_wait = SignalBarrier([Group(1)])
        barrier_wait.enable()
        with self.assertRaises(IndexError):
            barrier_wait.wait(99)  # Index out of bounds
        barrier_wait.dispose()

    def test_task_raising_exception(self):
        """Tests that a failing task's exception is caught and stored."""

        class CustomException(Exception):
            pass

        def failing_task():
            raise CustomException("Task failed as expected")

        def successful_task():
            return "success"

        group = Group(threshold=1, tasks=[failing_task, successful_task])
        barrier = SignalBarrier([group])

        # The barrier should release even if a task fails
        self.assertTrue(barrier.wait(0, timeout=1))

        # Check the captured outcomes
        self.assertEqual(len(group.results), 1, "Should have one successful result")
        self.assertEqual(group.results[0], "success")

        self.assertEqual(len(group.exceptions), 1, "Should have one captured exception")
        self.assertIsInstance(group.exceptions[0], CustomException)

    def test_group_with_multiple_tasks(self):
        """Tests a single group with multiple tasks, ensuring all are executed."""
        results_list = []

        def task1(): results_list.append("A")

        def task2(): results_list.append("B")

        group = Group(threshold=2, tasks=[task1, task2])
        barrier = SignalBarrier([group])

        def worker():
            barrier.wait(0, timeout=1)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start();
        t2.start()
        t1.join();
        t2.join()

        # Both tasks should have been executed by the thread that completed the group
        self.assertCountEqual(results_list, ["A", "B"])

    def test_context_manager_usage_for_disposal(self):
        """Tests that using the barrier as a context manager calls dispose."""
        results = []
        barrier = SignalBarrier([Group(threshold=5)])  # High threshold to ensure blocking

        def worker():
            # This should return False because the barrier is disposed
            released = barrier.wait(0, timeout=1)
            results.append(released)

        with barrier:
            t1 = threading.Thread(target=worker)
            t1.start()
            time.sleep(0.1)  # Give the thread time to enter wait()
            self.assertFalse(barrier.disposed)

        # dispose() is called automatically on exiting the 'with' block
        self.assertTrue(barrier.disposed)
        t1.join()
        self.assertEqual(results, [False])

    def test_high_contention(self):
        """A stress test with many threads and groups to check for deadlocks."""
        num_groups = 4
        threads_per_group = 5
        total_threads = num_groups * threads_per_group

        groups = [Group(threshold=threads_per_group) for _ in range(num_groups)]
        barrier = SignalBarrier(groups, reusable=False)

        results = []
        lock = threading.Lock()

        def worker(group_index):
            released = barrier.wait(group_index, timeout=2)
            with lock:
                results.append(released)

        threads = []
        for i in range(num_groups):
            for _ in range(threads_per_group):
                t = threading.Thread(target=worker, args=(i,))
                threads.append(t)
                t.start()

        for t in threads:
            t.join()

        self.assertEqual(len(results), total_threads, "All threads should have completed")
        self.assertTrue(all(results), "All threads should have been released successfully")
        self.assertTrue(barrier.is_spent())

    def test_multiple_groups_auto_release(self):
        """Tests that all groups must be ready before the barrier releases."""
        results = []

        def task1(): results.append("g1")

        def task2(): results.append("g2")

        g1 = Group(threshold=1, tasks=task1)
        g2 = Group(threshold=2, tasks=task2)
        barrier = SignalBarrier([g1, g2], reusable=False)

        def group1_worker(): barrier.wait(0)

        def group2_worker(): barrier.wait(1)

        t1 = threading.Thread(target=group2_worker)
        t2 = threading.Thread(target=group2_worker)
        t3 = threading.Thread(target=group1_worker)

        t1.start();
        t2.start();
        t3.start()
        t1.join();
        t2.join();
        t3.join()

        self.assertCountEqual(results, ["g1", "g2"])
        self.assertTrue(barrier.is_spent())

    def test_manual_release(self):
        """Tests that threads wait until release() is called, even after group is ready."""
        g = Group(threshold=2)
        barrier = SignalBarrier([g], manual_release=True)

        worker_finished = threading.Event()

        def worker():
            barrier.wait(0)
            worker_finished.set()

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start();
        t2.start()

        # Wait until the group's threshold is met. A short sleep is pragmatic here.
        time.sleep(0.1)

        # The group is ready, but threads are blocked due to manual_release=True.
        self.assertTrue(g.ready, "Group should be ready after threshold is met")
        self.assertFalse(worker_finished.is_set(), "Worker should be blocked before release()")

        barrier.release()

        # The worker should now finish quickly.
        finished_in_time = worker_finished.wait(timeout=1)
        self.assertTrue(finished_in_time, "Worker did not finish after release()")

        t1.join();
        t2.join()
        self.assertTrue(barrier.is_spent())

    def test_reusable_barrier_with_data(self):
        """Tests reusability and confirms the barrier can run multiple cycles."""
        group = Group(threshold=2, tasks=lambda: "cycle_done")
        barrier = SignalBarrier([group], reusable=True)

        def run_phase():
            phase_threads = [
                threading.Thread(target=lambda: barrier.wait(0, timeout=1)),
                threading.Thread(target=lambda: barrier.wait(0, timeout=1))
            ]
            for t in phase_threads:
                t.start()
            for t in phase_threads:
                t.join()

        # Run cycle 1
        run_phase()
        self.assertFalse(barrier.is_spent())
        # The fact that a second cycle can start proves the reset logic worked.

        # Run cycle 2
        run_phase()
        self.assertFalse(barrier.is_spent())
        # You can add checks on task results here if needed, but the primary
        # goal is to ensure the barrier doesn't lock up on the second run.

    def test_notify_all_override(self):
        """Tests that notify_all_override releases all threads regardless of state."""
        g = Group(threshold=10)  # Threshold is intentionally unreachable
        barrier = SignalBarrier([g])
        threads = [threading.Thread(target=lambda: barrier.wait(0, timeout=1)) for _ in range(3)]

        for t in threads: t.start()
        time.sleep(0.1)  # Allow threads to block

        barrier.notify_all_override()

        for t in threads: t.join()
        self.assertTrue(g.ready)
        self.assertTrue(barrier.is_spent())

    def test_timeout_behavior(self):
        """Tests that wait() returns False if the timeout is reached."""
        g = Group(threshold=2)
        barrier = SignalBarrier([g])

        # This thread will time out because the threshold of 2 is not met.
        result = barrier.wait(0, timeout=0.1)
        self.assertFalse(result, "wait() should return False on timeout")

    def test_dispose_releases_waiting_threads(self):
        """Tests that waiting threads are released with False when barrier is disposed."""
        g = Group(threshold=5)  # High threshold to ensure threads block
        barrier = SignalBarrier([g])
        results = []

        def worker():
            released = barrier.wait(0, timeout=1)  # Use timeout to prevent test hangs
            results.append(released)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads: t.start()

        time.sleep(0.1)
        self.assertEqual(len(results), 0, "Threads should be waiting on the barrier")

        barrier.dispose()  # Dispose the barrier

        for t in threads: t.join()

        self.assertTrue(barrier.disposed)
        # All waiting threads should have been released with a 'False' result
        self.assertEqual(results, [False, False])


if __name__ == "__main__":
    unittest.main(argv=['first-arg-is-ignored'], exit=False)