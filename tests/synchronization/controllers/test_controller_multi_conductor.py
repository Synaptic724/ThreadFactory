import unittest
import threading
import time
from typing import List, Callable, Optional

# Assuming your project structure allows these imports
from thread_factory.utilities.coordination.group import Group
from thread_factory.synchronization.coordinators.multi_conductor import MultiConductor
from thread_factory.synchronization.controllers.signal_controller import SignalController


# Helper function from your previous tests
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


# --- Integration Test Suite ---

class TestMultiConductorIntegration(unittest.TestCase):

    def test_registration_with_controller(self):
        """Verify that a MultiConductor registers itself with the controller upon creation."""
        controller = SignalController()
        mc = MultiConductor(threshold=1, controller=controller)

        # Check the controller's registry
        registered_objects = controller.list_objects(name_filter='multiconductor')

        self.assertEqual(len(registered_objects), 1, "MultiConductor should be registered.")
        self.assertEqual(registered_objects[0]['id'], mc.id, "Registered ID should match the conductor's ID.")

        mc.dispose()
        controller.dispose()

    def test_controller_can_invoke_reset(self):
        """Verify the controller can invoke a command like 'reset' on the MultiConductor."""
        controller = SignalController()
        group = Group(name="alpha", tasks=[lambda: True])
        mc = MultiConductor(threshold=1, groups=[group], reusable=True, controller=controller)

        # Run one cycle to put the conductor in a "released" state
        _spawn(1, mc.start)[0].join(1)
        self.assertTrue(mc._released, "Conductor should be in a released state after the first run.")

        # Use the controller to invoke the 'reset' command
        controller.invoke(mc.id, 'reset')

        # Verify the conductor's state has been reset
        self.assertFalse(mc._released, "Conductor should be reset to a non-released state.")
        self.assertFalse(mc._broken, "Conductor should not be broken after reset.")

        mc.dispose()
        controller.dispose()

    def test_controller_hooks_fire_on_invoke(self):
        """
        Verify the SignalController's diagnostic hooks are called when invoking
        a command on the MultiConductor.
        """
        controller = SignalController()
        mc = MultiConductor(threshold=1, reusable=True, controller=controller)

        pre_invoke_log = []
        post_invoke_log = []

        # Define and add the hook callbacks to the controller
        def pre_hook(obj_id, command):
            pre_invoke_log.append((obj_id, command))

        def post_hook(obj_id, command, result, exception):
            post_invoke_log.append((obj_id, command, result, exception))

        controller.add_pre_invoke_hook(pre_hook)
        controller.add_post_invoke_hook(post_hook)

        # Invoke a command through the controller
        controller.invoke(mc.id, 'reset')

        # --- Assert Pre-Invoke Hook ---
        self.assertEqual(len(pre_invoke_log), 1)
        self.assertEqual(pre_invoke_log[0][0], mc.id)
        self.assertEqual(pre_invoke_log[0][1], 'reset')

        # --- Assert Post-Invoke Hook ---
        self.assertEqual(len(post_invoke_log), 1)
        self.assertEqual(post_invoke_log[0][0], mc.id)
        self.assertEqual(post_invoke_log[0][1], 'reset')
        self.assertIsNone(post_invoke_log[0][2], "Result of reset should be None.")
        self.assertIsNone(post_invoke_log[0][3], "Exception from reset should be None.")

        mc.dispose()
        controller.dispose()
    def test_controller_receives_lifecycle_events(self):
        """Verify the controller receives lifecycle events from the MultiConductor."""
        controller = SignalController()
        received_events = []

        def event_recorder(obj_id, event_type, data):
            received_events.append(event_type)

        group = Group(name="work", tasks=[lambda: "done"])
        mc = MultiConductor(threshold=2, groups=[group], controller=controller)

        # Subscribe to events via the controller
        controller.subscribe(mc.id, "BARRIER_PASSED", event_recorder)
        controller.subscribe(mc.id, "EXECUTION_STARTED", event_recorder)
        controller.subscribe(mc.id, "EXECUTION_COMPLETED", event_recorder)

        # Run the conductor
        threads = _spawn(2, mc.start)
        for t in threads:
            t.join(1)

        expected_events = ["BARRIER_PASSED", "EXECUTION_STARTED", "EXECUTION_COMPLETED"]
        self.assertListEqual(received_events, expected_events,
                             "Controller did not receive the correct sequence of events.")

        mc.dispose()
        controller.dispose()

    def test_controller_invokes_manual_release(self):
        """Verify the controller can manually release a waiting MultiConductor."""
        controller = SignalController()
        events = []

        mc = MultiConductor(threshold=1, manual_release=True, controller=controller)
        controller.subscribe(mc.id, "MANUALLY_RELEASED", lambda i, e, d: events.append(e))

        worker_finished = threading.Event()
        _spawn(1, lambda: (mc.start(), worker_finished.set()))

        # Wait a moment, confirm the worker is blocked and no event has been fired
        time.sleep(0.1)
        self.assertFalse(worker_finished.is_set())
        self.assertEqual(len(events), 0)

        # Use the controller to release the conductor
        controller.invoke(mc.id, 'release')

        # The worker should now finish
        self.assertTrue(worker_finished.wait(1), "Worker was not unblocked by remote release.")

        # Verify the correct event was fired
        self.assertIn("MANUALLY_RELEASED", events)

        mc.dispose()
        controller.dispose()