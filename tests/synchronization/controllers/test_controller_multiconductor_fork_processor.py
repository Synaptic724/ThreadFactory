import unittest
import threading
import time
from typing import List, Callable, Optional
from unittest.mock import MagicMock

# Assuming your classes are in these locations
from thread_factory.utils.coordination.group import Group
from thread_factory.synchronization.coordinators.multi_conductor import MultiConductor
from thread_factory.synchronization.controllers.signal_controller import SignalController


# --- Helper function (previously omitted) ---
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


# --- Integration Test Suite for Fork Modes---

class TestMultiConductorForkControllerIntegration(unittest.TestCase):

    def setUp(self):
        self.controller = SignalController()

    def tearDown(self):
        self.controller.dispose()

    def make_logging_task(self, name: str, log: list, delay=0):
        """Helper to create a task that logs its execution."""

        def task():
            if delay > 0:
                time.sleep(delay)
            log.append(name)
            return f"{name}_result"

        return task

    def test_fork_mode_creates_and_registers_signal_fork(self):
        """
        Verify that when a MultiConductor runs in fork mode, the internal
        SignalFork it creates also registers itself with the controller.
        """
        group = Group(name="alpha", tasks=[lambda: 1])
        mc = MultiConductor(
            threshold=1,
            groups=[group],
            distributed_execution=True,
            controller=self.controller
        )
        self.addCleanup(mc.dispose)

        threads = _spawn(1, mc.start)
        for t in threads:
            t.join(1)

        object_names = {obj['name'] for obj in self.controller.list_objects()}
        self.assertIn('multiconductor', object_names)
        self.assertIn('signal_fork', object_names)

    def test_controller_receives_fork_completed_event(self):
        """
        Verify the 'FORK_COMPLETED' event is received from an internal SignalFork
        using an event-chaining pattern to subscribe reliably.
        """
        fork_completed_event = threading.Event()
        internal_fork_id = None

        # This is the handler for the fork's event. It just sets our Event.
        def fork_event_handler(obj_id, event_type, data):
            fork_completed_event.set()

        # This is the handler for the conductor's event. Its job is to find
        # the newly created fork and subscribe to it.
        def conductor_startup_handler(obj_id, event_type, data):
            nonlocal internal_fork_id
            # The fork is created right after EXECUTION_STARTED, so we can find it.
            fork_info = self.controller.list_objects(name_filter='signal_fork')
            if fork_info:
                internal_fork_id = fork_info[0]['id']
                # Now we dynamically subscribe to the correct event on the correct object.
                self.controller.subscribe(internal_fork_id, "FORK_COMPLETED", fork_event_handler)

        group = Group(name="beta", tasks=[lambda: 1])
        mc = MultiConductor(
            threshold=1,
            groups=[group],
            distributed_execution=True,
            controller=self.controller
        )
        self.addCleanup(mc.dispose)

        # Subscribe to the MultiConductor's startup event *before* starting it.
        self.controller.subscribe(mc.id, "EXECUTION_STARTED", conductor_startup_handler)

        # Start the worker. This will:
        # 1. Fire EXECUTION_STARTED, which runs our handler to set up the real subscription.
        # 2. Exhaust the fork, which will fire FORK_COMPLETED.
        threads = _spawn(1, mc.start)
        for t in threads:
            t.join(1)

        # Assert that our final event was received.
        self.assertTrue(
            fork_completed_event.wait(timeout=1),
            "The FORK_COMPLETED event was never received."
        )

    def test_sync_fork_mode_receives_sync_events(self):
        """
        Verify the controller receives 'THRESHOLD_MET' from an internal SyncSignalFork.
        """
        event_log = []

        def event_recorder(obj_id, event_type, data):
            event_log.append(event_type)

        tasks = [lambda: 1, lambda: 2]
        group = Group("gamma", tasks=tasks, multiple_outcomes_per_task=True)
        mc = MultiConductor(
            threshold=2,
            groups=[group],
            sync_distributed_execution=True,
            multiple_outcomes_per_task=True,
            controller=self.controller,
            manual_release=True
        )
        self.addCleanup(mc.dispose)

        internal_fork_id = None

        threads = _spawn(2, mc.start)

        for _ in range(10):
            fork_info = self.controller.list_objects(name_filter='sync_signal_fork')
            if fork_info:
                internal_fork_id = fork_info[0]['id']
                break
            time.sleep(0.1)

        self.assertIsNotNone(internal_fork_id, "Internal fork was never registered.")

        self.controller.subscribe(internal_fork_id, "THRESHOLD_MET", event_recorder)

        time.sleep(0.2)

        self.assertIn("THRESHOLD_MET", event_log)

        self.controller.invoke(internal_fork_id, 'release')
        mc.release()
        for t in threads:
            t.join(1)


if __name__ == "__main__":
    unittest.main(verbosity=2)