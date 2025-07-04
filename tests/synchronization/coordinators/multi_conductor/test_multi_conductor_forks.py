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

        # FIX: Enable multiple outcomes for this specific test
        group = Group(name="uneven_dist", tasks=tasks, multiple_outcomes_per_task=True)
        mc = MultiConductor(
            threshold=num_workers,
            groups=[group],
            distributed_execution=True,
            multiple_outcomes_per_task=True  # This is the key
        )
        self.addCleanup(mc.dispose)

        threads = _spawn(num_workers, mc.start)
        for t in threads:
            t.join(timeout=3)

        # This assertion will now pass
        self.assertEqual(len(mc.results), num_workers)

        expected_counts = {'task_0': 3, 'task_1': 2, 'task_2': 2}
        self.assertDictEqual(Counter(self.execution_log), expected_counts)

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

    def test_sync_fork_distribution_more_workers(self):
        """
        Tests SyncFork distribution where there are more workers than tasks.
        """
        num_workers = 7
        num_tasks = 5

        tasks = [self.make_logging_task(f"sync_task_{i}") for i in range(num_tasks)]
        group = Group(name="sync_group", tasks=tasks, multiple_outcomes_per_task=True)

        # This setup is now valid because you moved the eligibility check
        mc = MultiConductor(
            threshold=num_workers,
            groups=[group],
            sync_distributed_execution=True,
            multiple_outcomes_per_task=True
        )
        self.addCleanup(mc.dispose)

        threads = _spawn(num_workers, mc.start)
        for t in threads: t.join(timeout=3)

        # --- CORRECTED ASSERTIONS ---

        # 1. The total number of executions should equal the number of workers.
        self.assertEqual(len(self.execution_log), num_workers)

        # 2. Check the exact distribution of tasks.
        # 7 workers / 5 tasks = 1 execution each, with 2 workers remaining.
        # The first 2 tasks get the remainder, so they run twice.
        expected_counts = {
            'sync_task_0': 2,
            'sync_task_1': 2,
            'sync_task_2': 1,
            'sync_task_3': 1,
            'sync_task_4': 1
        }

        # Use collections.Counter to verify the counts precisely.
        self.assertDictEqual(Counter(self.execution_log), expected_counts)

    def test_sync_fork_raises_error_if_threshold_is_less_than_tasks(self):
        """
        Tests that the conductor raises a RuntimeError if the SyncFork
        eligibility check (workers < tasks) fails.
        """
        # This is the actual failure condition for your check.
        num_workers = 4
        num_tasks = 5

        tasks = [self.make_logging_task(f"task_{i}") for i in range(num_tasks)]
        group = Group(name="fail_group", tasks=tasks, multiple_outcomes_per_task=True)

        mc = MultiConductor(
            threshold=num_workers,
            groups=[group],
            sync_distributed_execution=True,
            multiple_outcomes_per_task=True
        )
        self.addCleanup(mc.dispose)

        # The check correctly fails when 4 < 5.
        with self.assertRaisesRegex(RuntimeError, "More workers are required"):
            mc.enable()
    # -------------------------------------------------------------------------
    # CORRECTED Edge Case Tests
    # -------------------------------------------------------------------------
    def test_fork_with_empty_group(self):
        """
        Tests that the conductor raises a ValueError when it tries to
        create a Fork for a group with no tasks.
        """
        num_workers = 3
        group = Group(name="empty_group", tasks=[])  # Group with no tasks

        mc = MultiConductor(
            threshold=num_workers,
            groups=[group],
            distributed_execution=True
        )
        self.addCleanup(mc.dispose)

        # FIX: The conductor now raises a ValueError when _execute_operations is called.
        # We test for this specific error and message.
        with self.assertRaisesRegex(ValueError, "Cannot create Fork processor for a group with no tasks"):
            mc._execute_operations()

if __name__ == "__main__":
    unittest.main(verbosity=2)