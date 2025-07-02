import unittest
import threading
import time
import logging
from typing import List, Any, Dict
from thread_factory.synchronization.coordinators.conductor import Conductor
from thread_factory.synchronization.controllers.signal_controller import SignalController


# --- A simple helper function to spawn threads ---
def _spawn(n: int, fn: callable):
    """Spins up n daemon threads to run the target function."""
    threads = [threading.Thread(target=fn, daemon=True) for _ in range(n)]
    for t in threads:
        t.start()
    return threads


# --- The Integration Test Class ---

class TestConductorControllerIntegration(unittest.TestCase):
    """
    Integration tests for the Conductor and SignalController.

    Verifies that a Conductor correctly registers with a SignalController,
    emits lifecycle events, and can be controlled remotely.
    """

    def setUp(self):
        """Set up a new SignalController and an event recorder before each test."""
        # Suppress noisy logging from the controller during tests for cleaner output
        self.logger = logging.getLogger("test_controller")
        self.logger.setLevel(logging.CRITICAL)

        self.controller = SignalController(logger=self.logger)
        self.received_events: List[Dict[str, Any]] = []

    def tearDown(self):
        """Clean up the controller after each test."""
        if not self.controller.is_disposed:
            self.controller.dispose()

    def _event_recorder(self, obj_id: str, event_type: str, data: Any):
        """A simple callback to record events received from the controller."""
        self.received_events.append({"id": obj_id, "event": event_type, "data": data})

    def test_successful_run_emits_correct_event_sequence(self):
        """
        Verify Conductor registers and emits a full, successful event sequence.
        """
        print("\n--- Running: test_successful_run_emits_correct_event_sequence ---")

        # 1. Arrange: Create a conductor with a task and a controller
        task_result = {"value": 0}

        def increment_task():
            task_result["value"] += 1
            return "DONE"

        # The Conductor should auto-register with the controller on creation
        c = Conductor(
            threshold=2,
            tasks=increment_task,
            controller=self.controller
        )

        # Subscribe to the conductor's lifecycle events
        self.controller.subscribe(c.id, "BARRIER_PASSED", self._event_recorder)
        self.controller.subscribe(c.id, "EXECUTION_STARTED", self._event_recorder)
        self.controller.subscribe(c.id, "EXECUTION_COMPLETED", self._event_recorder)

        # 2. Act: Start threads to meet the threshold and trigger the work
        threads = _spawn(2, c.start)
        for t in threads:
            t.join(timeout=2)  # Use a timeout to prevent test hangs

        # 3. Assert: Verify the results and the events received
        self.assertEqual(task_result["value"], 1, "The task should have been executed once.")
        self.assertIn("DONE", c.results, "Conductor results should contain the task's return value.")

        # Check that the events were received in the correct order
        event_types = [e['event'] for e in self.received_events]
        expected_sequence = ["BARRIER_PASSED", "EXECUTION_STARTED", "EXECUTION_COMPLETED"]
        self.assertEqual(event_types, expected_sequence,
                         "The controller did not receive the correct sequence of events.")

        # Verify it was registered
        self.assertEqual(len(self.controller.list_objects(name_filter="conductor")), 1)
        print("✅ Events received in correct order.")

    def test_controller_can_invoke_reset_on_reusable_conductor(self):
        """
        Verify the controller can remotely invoke 'reset' on a reusable Conductor.
        """
        print("\n--- Running: test_controller_can_invoke_reset_on_reusable_conductor ---")

        # 1. Arrange: Create a reusable conductor and run it once
        c = Conductor(threshold=1, reusable=True, controller=self.controller)

        # First run
        _spawn(1, c.start)[0].join(timeout=1)
        self.assertTrue(c._released, "Conductor should be in a released state after the first run.")

        # 2. Act: Use the controller to invoke the 'reset' command
        self.controller.invoke(c.id, 'reset')

        # 3. Assert: Check that the conductor's state was reset
        self.assertFalse(c._released, "Conductor should be reset to a non-released state.")
        self.assertFalse(c._broken, "Conductor should not be broken after reset.")

        # Prove it works by running it again
        _spawn(1, c.start)[0].join(timeout=1)
        self.assertTrue(c._released, "Conductor should be in a released state again after the second run.")
        print("✅ Controller successfully invoked 'reset'.")

    def test_timeout_emits_barrier_broken_event(self):
        """
        Verify a timeout correctly emits a BARRIER_BROKEN event.
        """
        print("\n--- Running: test_timeout_emits_barrier_broken_event ---")

        # 1. Arrange: Create a conductor designed to time out
        c = Conductor(
            threshold=2,  # Requires 2 threads
            timeout=0.1,  # But will time out quickly
            controller=self.controller
        )
        self.controller.subscribe(c.id, "BARRIER_BROKEN", self._event_recorder)

        # 2. Act: Start only one thread, forcing a timeout
        thread = _spawn(1, c.start)[0]
        thread.join(timeout=1)

        # 3. Assert: Check the conductor's state and the event
        self.assertTrue(c._broken, "Conductor should be in a broken state after timeout.")

        self.assertEqual(len(self.received_events), 1, "Exactly one event should have been received.")
        self.assertEqual(self.received_events[0]['event'], "BARRIER_BROKEN",
                         "A BARRIER_BROKEN event should have been recorded.")
        print("✅ BARRIER_BROKEN event correctly received on timeout.")

    def test_controller_can_invoke_override_to_unblock_waiters(self):
        """
        Verify the controller can invoke 'notify_all_override' to unblock waiters.
        """
        print("\n--- Running: test_controller_can_invoke_override_to_unblock_waiters ---")

        # 1. Arrange
        c = Conductor(threshold=2, controller=self.controller)
        self.controller.subscribe(c.id, "BARRIER_BROKEN", self._event_recorder)

        waiter_finished = threading.Event()

        # Start a thread that will wait indefinitely on the Conductor
        waiter_thread = threading.Thread(target=lambda: (c.start(), waiter_finished.set()), daemon=True)
        waiter_thread.start()

        time.sleep(0.1)  # Give the thread time to start and block
        self.assertTrue(waiter_thread.is_alive(), "Waiter thread should be blocked.")

        # 2. Act: Use the controller to break the barrier
        self.controller.invoke(c.id, 'notify_all_override')

        # 3. Assert
        waiter_finished.wait(timeout=1)  # Wait for the thread to finish
        self.assertFalse(waiter_thread.is_alive(), "Waiter thread should have been unblocked and finished.")
        self.assertTrue(c._broken, "Conductor should be in a broken state.")
        self.assertEqual(self.received_events[0]['event'], 'BARRIER_BROKEN',
                         "Controller should have received BARRIER_BROKEN event from the override.")
        print("✅ Controller successfully unblocked waiters with 'notify_all_override'.")


if __name__ == "__main__":
    unittest.main(verbosity=2)