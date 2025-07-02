import unittest
import threading
import time
from typing import List, Any, Optional
from thread_factory.synchronization.coordinators.multi_conductor import MultiConductor
from thread_factory.utils import IDisposable
from thread_factory.concurrency import ConcurrentDict, ConcurrentList
from thread_factory.utils.coordination.group import Group

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


# --- Test Suite ---

class TestMultiConductor(unittest.TestCase):

    def test_single_group_execution(self):
        """Verify basic execution with a single group of tasks."""
        group1 = Group("alpha", [lambda: "a1", lambda: "a2"])
        mc = MultiConductor(threshold=2, groups=[group1])

        threads = _spawn(2, mc.start)
        for t in threads:
            t.join(1)

        self.assertTrue(mc.is_spent())
        self.assertEqual(len(mc.results), 2)
        # Check outcomes are correctly nested by group name and task index
        self.assertEqual(mc.outcomes["alpha"][0].result(), "a1")
        self.assertEqual(mc.outcomes["alpha"][1].result(), "a2")
        mc.dispose()

    def test_multiple_group_lockstep_execution(self):
        """Verify tasks from all groups run in a synchronized, sequential order."""
        execution_log = []
        log_lock = threading.Lock()

        # Tasks that log their execution
        task_g1_t1 = lambda: log_lock.acquire() and execution_log.append("g1-t1") and log_lock.release()
        task_g1_t2 = lambda: log_lock.acquire() and execution_log.append("g1-t2") and log_lock.release()
        task_g2_t1 = lambda: log_lock.acquire() and execution_log.append("g2-t1") and log_lock.release()

        group1 = Group("group1", [task_g1_t1, task_g1_t2])
        group2 = Group("group2", [task_g2_t1])
        mc = MultiConductor(threshold=3, groups=[group1, group2])

        threads = _spawn(3, mc.start)
        for t in threads:
            t.join(1)

        # Expect each task to appear `threshold` times in the log
        self.assertEqual(execution_log.count("g1-t1"), 3)
        self.assertEqual(execution_log.count("g1-t2"), 3)
        self.assertEqual(execution_log.count("g2-t1"), 3)

        # Verify the lock-step order: all t1, then all t2, etc.
        self.assertEqual(execution_log[0:3], ["g1-t1"] * 3)
        self.assertEqual(execution_log[3:6], ["g1-t2"] * 3)
        self.assertEqual(execution_log[6:9], ["g2-t1"] * 3)
        mc.dispose()

    def test_reusable_multiconductor_with_reset(self):
        """Ensure reset clears outcomes in all groups for a second run."""
        group1 = Group("numbers", [lambda: 1])
        mc = MultiConductor(threshold=2, groups=[group1], reusable=True)

        # First cycle
        _spawn(2, mc.start)[0].join(1)
        self.assertEqual(mc.results, [1])
        self.assertFalse(mc.is_spent())

        # Reset for the second cycle
        mc.reset()
        self.assertEqual(mc.results, [])  # Results should be cleared
        self.assertFalse(mc._released)
        # Update the task for the second run
        group1.tasks = [lambda: 2]

        # Second cycle
        _spawn(2, mc.start)[0].join(1)
        self.assertEqual(mc.results, [2])
        mc.dispose()

    def test_mixed_outcomes_across_groups(self):
        """Verify results and exceptions are correctly captured from different groups."""

        class TestError(Exception): pass

        group_good = Group("good_tasks", [lambda: "success"])
        group_bad = Group("bad_tasks", [lambda: (_ for _ in ()).throw(TestError("failure"))])
        mc = MultiConductor(threshold=1, groups=[group_good, group_bad])

        _spawn(1, mc.start)[0].join(1)

        # Check flattened properties
        self.assertEqual(mc.results, ["success"])
        self.assertEqual(len(mc.exceptions), 1)
        self.assertIsInstance(mc.exceptions[0], TestError)

        # Check nested outcome structure
        self.assertEqual(mc.outcomes["good_tasks"][0].result(), "success")
        self.assertIsInstance(mc.outcomes["bad_tasks"][0].exception(), TestError)
        mc.dispose()

    def test_add_group_after_start_raises_error(self):
        """Verify that modifying groups after the conductor is active is forbidden."""
        mc = MultiConductor(threshold=1)
        # The first call to start() will "enable" the conductor
        thread = _spawn(1, mc.start)[0]
        thread.join(1)

        group_new = Group("new", [lambda: "new"])
        with self.assertRaises(RuntimeError):
            mc.add_group(group_new)

        mc.dispose()


if __name__ == "__main__":
    unittest.main()