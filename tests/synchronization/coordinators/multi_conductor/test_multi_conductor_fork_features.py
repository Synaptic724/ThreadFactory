import unittest
import threading
import time
from queue import Queue
from collections import Counter
from thread_factory import MultiConductor, Group


def _spawn(n: int, fn: callable):
    """Spins up n daemon threads and starts them."""
    threads = []
    for i in range(n):
        t = threading.Thread(target=fn, name=f"Worker-{i + 1}", daemon=True)
        threads.append(t)
    for t in threads:
        t.start()
    return threads


class TestMultiConductorForkFeatures(unittest.TestCase):
    """
    Tests advanced features like manual release, timeouts, and exception
    handling specifically for the Fork and SyncFork execution modes.
    """

    def make_logging_task(self, name: str, log: list):
        """Helper to create a task that logs its execution."""

        def task():
            log.append(name)
            return f"{name}_result"

        return task

    def test_fork_mode_manual_release(self):
        """Verify manual_release works correctly with distributed_execution."""
        log = []
        num_workers = 3
        tasks = [self.make_logging_task(f"task_{i}", log) for i in range(num_workers)]
        group = Group("alpha", tasks)
        mc = MultiConductor(
            threshold=num_workers,
            groups=[group],
            distributed_execution=True,
            manual_release=True
        )
        self.addCleanup(mc.cleanup)

        threads = _spawn(num_workers, mc.start)

        # Wait until the tasks are done (results are populated)
        for _ in range(10):  # Poll for up to 1 second
            if len(mc.results) == num_workers:
                break
            time.sleep(0.1)

        self.assertCountEqual(log, ["task_0", "task_1", "task_2"])

        # At this point, tasks are done but threads should be blocked at the release gate
        for t in threads:
            self.assertTrue(t.is_alive(), "Worker thread terminated before manual release.")

        # Now, release the threads
        mc.release()

        for t in threads:
            t.join(timeout=1)  # Give them 1 second to exit
            self.assertFalse(t.is_alive(), "Worker thread did not terminate after release.")

    def test_fork_mode_task_exception_handling(self):
        """Verify an exception in one task doesn't stop others in Fork mode."""

        class TaskError(Exception): pass

        log = []
        num_workers = 4
        # One task will fail, the other three will succeed
        tasks = [
            self.make_logging_task("task_0", log),
            lambda: (_ for _ in ()).throw(TaskError("Task 1 Failed!")),
            self.make_logging_task("task_2", log),
            self.make_logging_task("task_3", log)
        ]
        group = Group("mixed_outcomes", tasks)
        mc = MultiConductor(
            threshold=num_workers,
            groups=[group],
            distributed_execution=True
        )
        self.addCleanup(mc.cleanup)

        threads = _spawn(num_workers, mc.start)
        for t in threads:
            t.join(timeout=2)

        # Assert that the successful tasks ran and their results were collected
        self.assertEqual(len(log), 3)
        self.assertEqual(len(mc.results), 3)
        self.assertCountEqual(mc.results, ["task_0_result", "task_2_result", "task_3_result"])

        # Assert that the single exception was correctly captured
        self.assertEqual(len(mc.exceptions), 1)
        self.assertIsInstance(mc.exceptions[0], TaskError)

    def test_sync_fork_mode_task_exception_handling(self):
        """Verify an exception in one task doesn't stop others in SyncFork mode."""

        class TaskError(Exception): pass

        log = []
        # FIX: Use a valid configuration (workers >= tasks) to pass the eligibility check.
        num_workers = 4
        num_tasks = 4

        tasks = [
            self.make_logging_task("task_0", log),
            lambda: (_ for _ in ()).throw(TaskError("Task 1 Failed!")),
            self.make_logging_task("task_2", log),
            self.make_logging_task("task_3", log)
        ]
        group = Group("sync_mixed", tasks, multiple_outcomes_per_task=True)
        mc = MultiConductor(
            threshold=num_workers,
            groups=[group],
            sync_distributed_execution=True,
            multiple_outcomes_per_task=True
        )
        self.addCleanup(mc.cleanup)

        threads = _spawn(num_workers, mc.start)
        for t in threads:
            t.join(timeout=2)

        # --- CORRECTED ASSERTIONS ---
        # With 4 workers and 4 tasks, 3 will succeed and 1 will fail.
        self.assertEqual(len(mc.results), 3, "Should have 3 successful results.")
        self.assertEqual(len(mc.exceptions), 1, "Should have 1 captured exception.")
        self.assertIsInstance(mc.exceptions[0], TaskError)
        self.assertCountEqual(log, ["task_0", "task_2", "task_3"])
        
    def test_main_barrier_timeout_with_fork_mode(self):
        """Verify the main barrier timeout works with fork mode enabled."""
        error_queue = Queue()

        def worker_task_with_catch():
            try:
                mc.start()
            except TimeoutError as e:
                error_queue.put(e)

        mc = MultiConductor(
            threshold=5,
            groups=[Group("alpha", [lambda: 1])],  # A dummy group
            distributed_execution=True,
            timeout=0.2,
            raise_on_timeout=True
        )
        self.addCleanup(mc.cleanup)

        # Spawn only 3 threads, which is less than the threshold of 5
        threads = _spawn(3, worker_task_with_catch)

        for t in threads:
            t.join(timeout=1)

        # Check that the conductor is broken and no work was done
        self.assertTrue(mc._broken, "Conductor should be in a broken state.")
        self.assertEqual(len(mc.results), 0)

        # Check that all 3 threads caught the TimeoutError
        self.assertEqual(error_queue.qsize(), 3, "All threads should have caught a TimeoutError.")


if __name__ == "__main__":
    unittest.main(verbosity=2)