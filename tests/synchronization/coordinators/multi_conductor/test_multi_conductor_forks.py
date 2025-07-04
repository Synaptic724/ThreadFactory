import unittest
import threading
import time
import logging
from collections import Counter
from typing import List, Callable

# Assuming the provided classes are in these locations.
from thread_factory.synchronization.coordinators.multi_conductor import MultiConductor
from thread_factory.utils.coordination.group import Group

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d - %(threadName)-15s - %(levelname)-8s - %(message)s',
    datefmt='%H:%M:%S'
)


def _spawn(n: int, fn: callable):
    threads = []
    for i in range(n):
        t = threading.Thread(target=fn, name=f"Worker-{i + 1}", daemon=True)
        threads.append(t)
    for t in threads:
        t.start()
    return threads


class TestForkAndSyncFork(unittest.TestCase):

    def setUp(self):
        self.execution_log = []
        self.log_lock = threading.Lock()
        logging.info(f"\n{'=' * 30} Starting Test: {self.id()} {'=' * 30}")

    def tearDown(self):
        logging.info(f"{'=' * 30} Finished Test: {self.id()} {'=' * 30}")

    def make_logging_task(self, name: str) -> Callable[[], str]:
        def task():
            with self.log_lock:
                self.execution_log.append(name)
            logging.info(f"Task '{name}' executed.")
            time.sleep(0.01)
            return f"{name}_result"

        return task

    # -------------------------------------------------------------------------
    # CORRECTED Fork Tests
    # -------------------------------------------------------------------------

    def test_fork_1_to_1_distribution(self):
        """IMPROVED FOR DEBUGGING: Checks for hidden exceptions."""
        num_workers = 5
        num_tasks = 5

        # Set your logger to DEBUG level to see everything
        logging.getLogger().setLevel(logging.DEBUG)

        tasks = [self.make_logging_task(f"task_{i}") for i in range(num_tasks)]
        group = Group(name="dist_group", tasks=tasks)

        mc = MultiConductor(threshold=num_workers, groups=[group], distributed_execution=True)
        self.addCleanup(mc.dispose)

        threads = _spawn(num_workers, mc.start)
        for t in threads:
            t.join(timeout=3)

        # --- THE FIX IS HERE ---
        # Instead of just checking the log, first check if any exceptions were
        # silently caught by the MultiConductor.
        if mc.exceptions:
            self.fail(
                f"Test failed because {len(mc.exceptions)} exceptions were caught "
                f"by the conductor. The first one was: \n{repr(mc.exceptions[0])}"
            )
        # --- END OF FIX ---

        self.assertEqual(len(self.execution_log), num_tasks,
                         "Execution log does not have the expected number of tasks.")
        self.assertCountEqual(self.execution_log, [f"task_{i}" for i in range(num_tasks)],
                              "Not all tasks were executed exactly once in Fork mode.")
        self.assertCountEqual(mc.results, [f"task_{i}_result" for i in range(num_tasks)])

    def test_fork_uneven_distribution_more_workers(self):
        num_workers = 7
        num_tasks = 3
        tasks = [self.make_logging_task(f"task_{i}") for i in range(num_tasks)]
        group = Group(name="uneven_dist", tasks=tasks)
        mc = MultiConductor(threshold=num_workers, groups=[group], distributed_execution=True)
        self.addCleanup(mc.dispose)

        threads = _spawn(num_workers, mc.start)
        for t in threads: t.join(timeout=3)

        expected_counts = {'task_0': 3, 'task_1': 2, 'task_2': 2}
        self.assertEqual(len(self.execution_log), num_workers)
        self.assertDictEqual(Counter(self.execution_log), expected_counts)
        self.assertEqual(len(mc.results), num_workers)

    def test_fork_reusability_with_reset(self):
        num_workers = 2
        num_tasks = 2
        tasks = [self.make_logging_task(f"task_{i}") for i in range(num_tasks)]
        group = Group(name="reusable_dist", tasks=tasks)
        mc = MultiConductor(threshold=num_workers, groups=[group], distributed_execution=True, reusable=True)
        self.addCleanup(mc.dispose)

        # First Run
        _spawn(num_workers, mc.start)
        time.sleep(0.5)  # Give threads time to complete
        self.assertEqual(len(self.execution_log), 2)

        # Reset and Second Run
        mc.reset()
        self.execution_log.clear()
        threads2 = _spawn(num_workers, mc.start)
        for t in threads2: t.join(timeout=3)

        self.assertEqual(len(self.execution_log), 2)
        self.assertCountEqual(self.execution_log, ["task_0", "task_1"])

    # -------------------------------------------------------------------------
    # CORRECTED SyncFork Tests (Respecting threshold < tasks constraint)
    # -------------------------------------------------------------------------

    def test_sync_fork_distribution_fewer_workers(self):
        num_workers = 3
        num_tasks = 5  # Must be > num_workers for SyncFork
        tasks = [self.make_logging_task(f"sync_task_{i}") for i in range(num_tasks)]
        group = Group(name="sync_group", tasks=tasks, multiple_outcomes_per_task=True)

        mc = MultiConductor(
            threshold=num_workers,
            groups=[group],
            sync_distributed_execution=True,
            multiple_outcomes_per_task=True
        )
        self.addCleanup(mc.dispose)

        threads = _spawn(num_workers, mc.start)
        for t in threads: t.join(timeout=3)

        # 3 workers will be distributed among 5 tasks. First 3 tasks run once.
        self.assertEqual(len(self.execution_log), num_workers)
        self.assertCountEqual(self.execution_log, ["sync_task_0", "sync_task_1", "sync_task_2"])
        self.assertNotIn("sync_task_3", self.execution_log)
        self.assertNotIn("sync_task_4", self.execution_log)

    def test_sync_fork_raises_error_if_threshold_equals_tasks(self):
        num_workers = 5
        num_tasks = 5
        tasks = [self.make_logging_task(f"task_{i}") for i in range(num_tasks)]
        group = Group(name="fail_group", tasks=tasks, multiple_outcomes_per_task=True)

        with self.assertRaisesRegex(RuntimeError, "does not match the total number of tasks"):
            MultiConductor(
                threshold=num_workers,
                groups=[group],
                sync_distributed_execution=True,
                multiple_outcomes_per_task=True
            )

    # -------------------------------------------------------------------------
    # CORRECTED Edge Case Tests
    # -------------------------------------------------------------------------

    def test_fork_with_empty_group(self):
        """CORRECTED: Test Fork mode with an empty group."""
        num_workers = 3
        group = Group(name="empty_group", tasks=[])
        mc = MultiConductor(threshold=num_workers, groups=[group], distributed_execution=True)
        self.addCleanup(mc.dispose)

        threads = _spawn(num_workers, mc.start)
        for t in threads: t.join(timeout=3)

        # The threads will encounter the error and stop.
        # We verify that no tasks ran and the conductor captured the exception.
        self.assertEqual(len(self.execution_log), 0)
        self.assertEqual(len(mc.results), 0)
        self.assertEqual(len(mc.exceptions), num_workers)  # Each worker's fork attempt fails
        self.assertIsInstance(mc.exceptions[0], ValueError)
        self.assertIn("Cannot create Fork processor for a group with no tasks", str(mc.exceptions[0]))


if __name__ == "__main__":
    unittest.main(verbosity=2)