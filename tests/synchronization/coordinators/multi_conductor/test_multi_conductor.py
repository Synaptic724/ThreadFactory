import unittest
import threading
import time
from typing import List, Any, Optional, Callable
from thread_factory.synchronization.coordinators.multi_conductor import MultiConductor
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

        # FIX: Define tasks using a helper function and a 'with' statement
        # to ensure the lock is always released safely.
        def make_logging_task(name: str) -> Callable:
            def task():
                with log_lock:
                    execution_log.append(name)

            return task

        task_g1_t1 = make_logging_task("g1-t1")
        task_g1_t2 = make_logging_task("g1-t2")
        task_g2_t1 = make_logging_task("g2-t1")

        group1 = Group(name="group1", tasks=[task_g1_t1, task_g1_t2])
        group2 = Group(name="group2", tasks=[task_g2_t1])
        mc = MultiConductor(threshold=3, groups=[group1, group2])

        threads = _spawn(3, mc.start)
        for t in threads:
            t.join(2)

        # Now, this assertion will pass because the deadlock is gone.
        self.assertEqual(execution_log.count("g1-t1"), 3)
        self.assertEqual(execution_log.count("g1-t2"), 3)
        self.assertEqual(execution_log.count("g2-t1"), 3)

        # Verify the lock-step order
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

    def test_dynamic_add_and_remove_groups_before_start(self):
        """
        Ensure adding and then removing a group leaves the conductor in a
        clean state.
        """
        group_alpha = Group(name="alpha", tasks=[lambda: "a"])
        group_beta = Group(name="beta", tasks=[lambda: "b"])

        # Start with one group
        mc = MultiConductor(threshold=1, groups=[group_alpha])

        # Add and then immediately remove a second group
        mc.add_group(group_beta)
        mc.remove_group(group_beta)

        # Run the conductor
        _spawn(1, mc.start)[0].join(1)

        # Only the results from the alpha group should be present
        self.assertEqual(mc.results, ["a"])
        self.assertNotIn("beta", mc.outcomes, "Beta group should not have any outcomes.")
        self.assertEqual(len(mc.groups), 1)
        self.assertIs(mc.groups[0], group_alpha)
        mc.dispose()

    def test_outcomes_dictionary_reference_integrity(self):
        """
        Verify that the MultiConductor.outcomes dict correctly references
        the outcomes of its Group objects.
        """
        group1 = Group(name="alpha", tasks=[lambda: "a1"])
        mc = MultiConductor(threshold=1, groups=[group1])

        # Before running, check if the outcomes object is the same instance
        self.assertIs(mc.outcomes[group1.name], group1.outcomes,
                      "Conductor's outcomes should be a direct reference to the group's outcomes.")

        # Run the conductor
        _spawn(1, mc.start)[0].join(1)

        # Check the result via the group first
        self.assertEqual(group1.results, ["a1"])

        # Now confirm the same result can be seen through the conductor's reference
        self.assertEqual(mc.outcomes["alpha"][0].result(), "a1")
        mc.dispose()

    @unittest.skip("Cancellation tokens not ready yet")
    def test_dispose_during_manual_release_wait(self):
        """
        Verify that calling dispose() unblocks threads waiting on the
        manual_release_gate.
        """
        group = Group(name="wait_group", tasks=[lambda: True])
        mc = MultiConductor(threshold=1, groups=[group], manual_release=True)

        worker_finished = threading.Event()
        entered_manual_gate = threading.Event()

        def worker_job():
            mc.start()
            # Signal that we reached the manual release wait
            entered_manual_gate.set()
            worker_finished.set()

        # Start the worker and let it run to the manual_release_gate
        worker = threading.Thread(target=worker_job)
        worker.start()

        # Wait until we are sure the worker reached the manual gate
        self.assertTrue(entered_manual_gate.wait(1), "Worker never reached manual release wait.")

        # Now dispose the conductor
        mc.dispose()

        # The worker should now immediately unblock and terminate
        self.assertTrue(worker_finished.wait(1), "Worker was not unblocked by dispose().")
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive(), "Worker thread should have exited after dispose().")

    def test_reset_after_timeout_allows_successful_rerun(self):
        """Verify a reusable conductor can succeed after a timeout and reset."""
        group = Group("alpha", tasks=[lambda: 100])
        mc = MultiConductor(
            threshold=2,
            groups=[group],
            reusable=True,
            timeout=0.1
        )

        # --- Cycle 1: Force a timeout ---
        # Only start one thread, which is less than the threshold
        _spawn(1, mc.start)[0].join(0.5)
        self.assertTrue(mc._broken, "Conductor should be in a broken state after timeout.")
        self.assertEqual(mc.results, [])

        # --- Reset the conductor ---
        mc.reset()
        self.assertFalse(mc._broken, "Reset should clear the broken state.")

        # --- Cycle 2: Succeed normally ---
        threads = _spawn(2, mc.start)
        for t in threads:
            t.join(1)

        self.assertFalse(mc._broken, "Second run should succeed without breaking.")
        self.assertEqual(mc.results, [100])
        mc.dispose()

    def test_start_with_no_groups_is_graceful(self):
        """Ensure starting a MultiConductor with no groups completes without error."""
        # No groups are added
        mc = MultiConductor(threshold=2)

        threads = _spawn(2, mc.start)
        for t in threads:
            t.join(1)

        # All threads should have exited cleanly
        self.assertTrue(all(not t.is_alive() for t in threads))
        self.assertTrue(mc.is_spent())
        self.assertEqual(mc.results, [])
        self.assertEqual(mc.exceptions, [])
        mc.dispose()
    def test_manual_release_and_reset_cycle(self):
        """Verify a reusable conductor with manual_release can be cycled."""
        group = Group(name="cycle", tasks=[lambda: "run"])
        mc = MultiConductor(threshold=1, groups=[group], reusable=True, manual_release=True)
        worker_finished = threading.Event()

        # Define the worker's job for one full cycle
        def worker_job():
            mc.start()
            worker_finished.set()

        # --- Cycle 1 ---
        worker = threading.Thread(target=worker_job)
        worker.start()

        # The worker should block after tasks are done, waiting for release
        time.sleep(0.1)
        self.assertFalse(worker_finished.is_set())
        self.assertEqual(mc.results, ["run"])

        # Manually release the worker
        mc.release()
        self.assertTrue(worker_finished.wait(1), "Worker did not finish after release.")
        self.assertFalse(mc.is_spent())

        # --- Reset for Cycle 2 ---
        mc.reset()
        self.assertEqual(mc.results, [])  # Ensure results are cleared

        # --- Cycle 2 ---
        worker_finished.clear()
        group.tasks = [lambda: "run2"]  # Change task for second run
        worker2 = threading.Thread(target=worker_job)
        worker2.start()
        time.sleep(0.1)  # Let it run
        self.assertFalse(worker_finished.is_set())
        self.assertEqual(mc.results, ["run2"])

        mc.release()
        self.assertTrue(worker_finished.wait(1))
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