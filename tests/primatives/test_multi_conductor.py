import unittest
import threading
import time
from typing import List, Any

from thread_factory.primitives.multi_conductor import MultiConductor
from thread_factory.utils import Group


class TestMultiConductor(unittest.TestCase):

    def setUp(self):
        # This ensures we have access to the corrected MultiConductor class for testing
        self.MultiConductor = MultiConductor

    def test_1_basic_multi_group_release(self):
        """Tests the happy path: two groups meeting their thresholds for auto-release."""
        g1 = Group(threshold=1, tasks=[lambda: "group1_done"])
        g2 = Group(threshold=2, tasks=[lambda: "group2_done"])
        conductor = self.MultiConductor(groups=[g1, g2])

        results = []

        def worker(group_index):
            released = conductor.wait(group_index)
            results.append(released)

        threads = [
            threading.Thread(target=worker, args=(0,)),
            threading.Thread(target=worker, args=(1,)),
            threading.Thread(target=worker, args=(1,))
        ]
        for t in threads: t.start()
        for t in threads: t.join()

        self.assertTrue(all(results))
        self.assertEqual(g1.results, ["group1_done"])
        self.assertEqual(g2.results, ["group2_done"])

    def test_2_manual_release(self):
        """Tests that threads wait for an explicit release() call in manual mode."""
        g1 = Group(threshold=1)
        conductor = self.MultiConductor(groups=[g1], manual_release=True)
        worker_finished = threading.Event()

        def worker():
            conductor.wait(0)
            worker_finished.set()

        t = threading.Thread(target=worker)
        t.start()

        time.sleep(0.1)
        self.assertTrue(g1.ready)
        self.assertFalse(worker_finished.is_set(), "Thread should be blocked before release()")

        conductor.release()
        self.assertTrue(worker_finished.wait(timeout=1), "Thread should be released after call")
        t.join()

    def test_3_reusable_mode_with_multiple_cycles(self):
        """Tests that reusable mode resets the conductor and all groups."""
        counter = [0]
        g1 = Group(threshold=1, tasks=[lambda: counter.append(1)])
        g2 = Group(threshold=1, tasks=[lambda: counter.append(2)])
        conductor = self.MultiConductor(groups=[g1, g2], reusable=True)

        def run_cycle():
            t1 = threading.Thread(target=lambda: conductor.wait(0))
            t2 = threading.Thread(target=lambda: conductor.wait(1))
            t1.start();
            t2.start()
            t1.join();
            t2.join()

        run_cycle()
        self.assertCountEqual(counter, [0, 1, 2])

        # Reset counter for next cycle, proving the conductor itself reset
        counter = [0]
        run_cycle()
        self.assertCountEqual(counter, [0, 1, 2])

    def test_4_task_results_are_captured_correctly(self):
        """Tests that data from tasks is correctly stored in group results."""
        g1 = Group(threshold=1, tasks=[lambda: 42])
        g2 = Group(threshold=1, tasks=[lambda: "hello", lambda: "world"])
        conductor = self.MultiConductor(groups=[g1, g2])

        t1 = threading.Thread(target=lambda: conductor.wait(0))
        t2 = threading.Thread(target=lambda: conductor.wait(1))
        t1.start();
        t2.start()
        t1.join();
        t2.join()

        self.assertEqual(g1.results, [42])
        self.assertCountEqual(g2.results, ["hello", "world"])

    def test_5_task_exceptions_are_captured_correctly(self):
        """Tests that task exceptions are caught but do not stop the barrier."""

        class MyTestException(Exception): pass

        g1 = Group(threshold=1, tasks=[lambda: 1 / 0])
        g2 = Group(threshold=1, tasks=[lambda: "ok"])
        conductor = self.MultiConductor(groups=[g1, g2])

        released_status = []

        def worker(idx): released_status.append(conductor.wait(idx))

        t1 = threading.Thread(target=worker, args=(0,))
        t2 = threading.Thread(target=worker, args=(1,))
        t1.start();
        t2.start()
        t1.join();
        t2.join()

        self.assertTrue(all(released_status), "Barrier should release despite exception")
        self.assertEqual(len(g1.exceptions), 1)
        self.assertIsInstance(g1.exceptions[0], ZeroDivisionError)
        self.assertEqual(g2.results, ["ok"])

    def test_6_timeout_returns_false(self):
        """Tests that wait() returns False if the global timeout is exceeded."""
        g1 = Group(threshold=2)
        conductor = self.MultiConductor(groups=[g1], timeout=0.1)

        results = []

        def worker(): results.append(conductor.wait(0))

        t1 = threading.Thread(target=worker)
        t1.start();
        t1.join()  # Only one thread, threshold of 2 is not met

        self.assertEqual(results, [False])

    def test_7_timeout_raises_exception(self):
        """Tests that TimeoutError is raised when configured."""
        g1 = Group(threshold=2)
        conductor = self.MultiConductor(groups=[g1], timeout=0.1, raise_on_timeout=True)
        with self.assertRaises(TimeoutError):
            conductor.wait(0)

    def test_8_dispose_releases_waiting_threads(self):
        """Tests that dispose() releases all waiting threads with a False status."""
        g1 = Group(threshold=2)
        conductor = self.MultiConductor(groups=[g1])
        result = []

        def worker(): result.append(conductor.wait(0))

        t1 = threading.Thread(target=worker)
        t1.start()
        time.sleep(0.1)  # Ensure thread is waiting

        conductor.dispose()
        t1.join()

        self.assertEqual(result, [False])
        self.assertTrue(conductor.disposed)

    def test_9_add_group_and_enable_logic(self):
        """Tests the state machine of adding groups and enabling the conductor."""
        conductor = self.MultiConductor()
        with self.assertRaises(RuntimeError, msg="Should not allow wait before enable"):
            conductor.wait(0)

        conductor.add_group(Group(1))
        conductor.enable()

        with self.assertRaises(RuntimeError, msg="Should not allow add_group after enable"):
            conductor.add_group(Group(1))

        with self.assertRaises(TypeError, msg="Should not allow adding non-Group objects"):
            self.MultiConductor().add_group("not a group")

    def test_10_all_outcomes_property(self):
        """Tests that the all_outcomes property flattens results correctly."""
        g1 = Group(threshold=1, tasks=[lambda: 1])
        g2 = Group(threshold=1, tasks=[lambda: 2, lambda: 3])
        conductor = self.MultiConductor(groups=[g1, g2])

        t1 = threading.Thread(target=lambda: conductor.wait(0))
        t2 = threading.Thread(target=lambda: conductor.wait(1))
        t1.start();
        t2.start()
        t1.join();
        t2.join()

        outcomes = conductor.all_outcomes
        self.assertEqual(len(outcomes), 3)
        results = sorted([o.result() for o in outcomes])
        self.assertEqual(results, [1, 2, 3])

    def test_11_high_contention(self):
        """A stress test with many groups and threads to check for deadlocks."""
        num_groups = 5
        threads_per_group = 4
        groups = [Group(threads_per_group) for _ in range(num_groups)]
        conductor = self.MultiConductor(groups=groups)

        results = []
        lock = threading.Lock()

        def worker(idx):
            if conductor.wait(idx):
                with lock: results.append(True)

        threads = []
        for i in range(num_groups):
            for _ in range(threads_per_group):
                threads.append(threading.Thread(target=worker, args=(i,)))

        for t in threads: t.start()
        for t in threads: t.join()

        self.assertEqual(len(results), num_groups * threads_per_group)

    def test_12_wait_with_invalid_group_index(self):
        """Tests that calling wait() with an out-of-bounds index raises an error."""
        conductor = self.MultiConductor(groups=[Group(1)])
        with self.assertRaises(IndexError):
            conductor.wait(99)

    def test_13_asymmetric_group_completion(self):
        """Tests that one group's tasks run early but threads wait for all groups."""
        task_run_time = threading.Event()
        g1 = Group(threshold=1, tasks=[lambda: task_run_time.set()])
        g2 = Group(threshold=2)
        conductor = self.MultiConductor(groups=[g1, g2])

        g1_finished = threading.Event()

        def g1_worker():
            conductor.wait(0);
            g1_finished.set()

        t1 = threading.Thread(target=g1_worker)
        t1.start()

        self.assertTrue(task_run_time.wait(timeout=1), "Group 1 task should run immediately")
        self.assertFalse(g1_finished.is_set(), "Group 1 thread should still be waiting")

        # Now complete the second group
        t2 = threading.Thread(target=lambda: conductor.wait(1))
        t3 = threading.Thread(target=lambda: conductor.wait(1))
        t2.start();
        t3.start()

        self.assertTrue(g1_finished.wait(timeout=1), "Group 1 thread should now be released")
        t1.join();
        t2.join();
        t3.join()

    def test_14_context_manager_usage(self):
        """Tests that `dispose()` is called automatically when using a `with` statement."""
        conductor = self.MultiConductor(groups=[Group(2)])
        with conductor:
            self.assertFalse(conductor.disposed)
        self.assertTrue(conductor.disposed)

    def test_15_reset_cascades_to_all_groups(self):
        """Tests specifically that the top-level reset cascades to all groups."""
        g1 = Group(threshold=1)
        g2 = Group(threshold=1)
        conductor = self.MultiConductor(groups=[g1, g2], reusable=True)

        # Run one full cycle.
        t1 = threading.Thread(target=lambda: conductor.wait(0))
        t2 = threading.Thread(target=lambda: conductor.wait(1))
        t1.start();
        t2.start()
        t1.join();
        t2.join()

        # After the cycle is fully complete (including the reset),
        # all groups should have their `ready` flag set back to False.
        self.assertFalse(g1.ready, "Group 1 should be reset to not ready")
        self.assertFalse(g2.ready, "Group 2 should be reset to not ready")
        self.assertEqual(g1.count, 0, "Group 1 count should be reset to 0")


if __name__ == '__main__':
    # This setup allows running the tests directly from a script.
    # The prerequisite classes must be defined or imported above.
    unittest.main(argv=['first-arg-is-ignored'], exit=False)