import unittest
import threading
import time
from typing import List, Callable, Optional
from thread_factory import MultiConductor, SignalController, SignalFork, Group


# Helper function
def _spawn(n: int, fn: callable, thread_names: Optional[List[str]] = None):
    """Spins up n daemon threads and starts them."""
    threads = []
    for i in range(n):
        name = f"Worker-{i + 1}"
        if thread_names and i < len(thread_names):
            name = thread_names[i]
        t = threading.Thread(target=fn, daemon=True, name=name)
        threads.append(t)
    for t in threads:
        t.start()
    return threads


class TestMultiConductorForkControllerIntegration(unittest.TestCase):

    def setUp(self):
        self.controller = SignalController()

    def tearDown(self):
        self.controller.dispose()

    # YOUR EXISTING, CORRECT TEST
    def test_fork_mode_creates_and_registers_signal_fork(self):
        """
        Verify that when a MultiConductor runs in fork mode, the internal
        SignalFork it creates also registers itself with the controller.
        """
        group = Group(name="alpha", tasks=[lambda: 1])
        mc = MultiConductor(threshold=1, groups=[group], distributed_execution=True, controller=self.controller)
        self.addCleanup(mc.dispose)

        threads = _spawn(1, mc.start)
        for t in threads:
            t.join(1)

        object_names = {obj['name'] for obj in self.controller.list_objects()}
        self.assertIn('multiconductor', object_names)
        self.assertIn('signal_fork', object_names)

    def test_reusability_creates_new_internal_fork(self):
        """
        Verify that resetting a reusable conductor creates a new internal fork on the next run.
        """
        group = Group(name="alpha", tasks=[lambda: 1])
        mc = MultiConductor(
            threshold=1,
            groups=[group],
            reusable=True,
            distributed_execution=True,
            controller=self.controller
        )
        self.addCleanup(mc.dispose)

        # --- First Run ---
        _spawn(1, mc.start)[0].join(1)
        registered_forks = self.controller.list_objects(name_filter='signal_fork')
        self.assertEqual(len(registered_forks), 1)
        first_fork_id = registered_forks[0]['id']

        # --- Reset and Second Run ---
        mc.reset()
        _spawn(1, mc.start)[0].join(1)

        # FIX: Assert that there are now TWO forks registered in the controller.
        registered_forks_after_reset = self.controller.list_objects(name_filter='signal_fork')
        self.assertEqual(len(registered_forks_after_reset), 2)

        # Prove that the second fork is a new instance by checking that the IDs are different.
        all_fork_ids = {fork['id'] for fork in registered_forks_after_reset}
        self.assertNotEqual(len(all_fork_ids), 1, "A new fork with a unique ID should have been created.")
        self.assertIn(first_fork_id, all_fork_ids)

    def test_broadcast_reset_with_name_filter(self):
        """
        Verify that invoke_on_all with a name_filter only affects matching conductors.
        """
        mc_to_reset = MultiConductor(threshold=1, reusable=True, distributed_execution=True, controller=self.controller)
        ignored_fork = SignalFork(1, [(1, lambda: None)], controller=self.controller)
        self.addCleanup(mc_to_reset.dispose)
        self.addCleanup(ignored_fork.dispose)

        _spawn(1, mc_to_reset.start)[0].join(1)

        # FIX: Check the internal 'released' flag, not the 'is_spent' property.
        self.assertTrue(mc_to_reset._released)

        self.controller.invoke_on_all('reset', name_filter='multiconductor')

        self.assertFalse(mc_to_reset._released)
    # --- NEW TEST 3 ---
    def test_conflicting_configuration_raises_error(self):
        """
        Verify that enabling both distributed and sync_distributed execution
        raises a ValueError.
        """
        # FIX: Create the object first, as the check is no longer in __init__.
        mc = MultiConductor(
            threshold=1,
            distributed_execution=True,
            sync_distributed_execution=True
        )

        # Assert that calling enable() triggers the error.
        with self.assertRaises(ValueError):
            mc.enable()

if __name__ == "__main__":
    unittest.main(verbosity=2)