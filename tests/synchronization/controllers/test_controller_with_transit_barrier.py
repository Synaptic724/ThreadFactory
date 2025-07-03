import unittest
from unittest.mock import MagicMock
import threading
import time

# Assuming classes are in this structure
from thread_factory.synchronization.controllers.signal_controller import SignalController
from thread_factory.synchronization.coordinators.transit_barrier import TransitBarrier


class TestControllerWithTransitBarrier(unittest.TestCase):
    """
    Tests the integration between the Controller and the TransitBarrier,
    covering auto-release, manual release signals, and command overrides.
    """

    def setUp(self):
        """Set up a new controller with a mock logger for each test."""
        self.mock_logger = MagicMock()
        self.controller = SignalController(logger=self.mock_logger)

    def tearDown(self):
        """Ensure the controller is disposed of after each test."""
        if self.controller and not self.controller.disposed:
            self.controller.dispose()

    # --- Test Cases ---

    def test_registration_success(self):
        """1. A TransitBarrier should register with the Controller upon creation."""
        barrier = TransitBarrier(threshold=1, controller=self.controller)

        self.assertIn(barrier.id, self.controller._registry)
        self.assertEqual(self.controller._registry[barrier.id]['name'], 'transit_barrier')

    def test_auto_release_with_transit(self):
        """2. A barrier in auto-release mode should release and run its transit action without the Controller."""

        # Define the transit action directly as a normal function
        def transit_action():
            print("Transit action executed")

        # Create the TransitBarrier with the real transit action
        barrier = TransitBarrier(
            threshold=2,
            transit=transit_action,  # Use the real function, not MagicMock
            manual_release=False,  # Auto-release mode
            controller=self.controller
        )

        def worker():
            barrier.wait()

        # Start the threads
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # We print the output from the transit action to verify execution
        # The action will execute twice, once for each thread
        self.assertEqual(barrier._transit_fired, True)

        # # No signals should have been sent to the controller, since it's auto-released
        # self.mock_logger.info.assert_not_called()

    def test_manual_release_signal_and_wait(self):
        """3. A manual barrier should signal the Controller and wait for a command."""
        # This will subscribe to the event the barrier sends
        event_subscriber = MagicMock()
        self.controller.add_post_invoke_hook = MagicMock()  # To prevent other logging

        barrier = TransitBarrier(
            threshold=2,
            manual_release=True,
            controller=self.controller
        )
        self.controller.subscribe(barrier.id, "THRESHOLD_MET", event_subscriber)

        def worker():
            # This thread will block until explicitly released by a controller command
            barrier.wait()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()

        # Give threads time to hit the barrier and send the signal
        time.sleep(0.1)

        # VERIFY: The barrier sent the signal correctly
        event_subscriber.assert_called_once_with(barrier.id, "THRESHOLD_MET", None)

        # VERIFY: The threads are still blocked and waiting
        for t in threads:
            self.assertTrue(t.is_alive())

    def test_manual_release_with_default_transit(self):
        """4. The Controller should be able to release a waiting barrier with its default action."""

        # --- Setup ---
        # The default action that should be called by the barrier.
        def default_transit_action():
            with self.lock:
                self.default_action_counter += 1  # Increment the counter safely when the action is called

        # Initialize counters and lock
        self.default_action_counter = 0
        self.lock = threading.Lock()  # Lock to protect the counters from race conditions

        # Create the barrier with the default action
        barrier = TransitBarrier(
            threshold=2,
            transit=default_transit_action,  # Use the real function
            manual_release=True,
            controller=self.controller
        )

        def worker():
            """A simple worker that waits at the barrier."""
            barrier.wait()

        # --- Execution ---
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()

        time.sleep(0.5)  # Wait for threads to hit barrier and signal

        # Verify: No action should have been called yet
        self.assertEqual(self.default_action_counter, 0)

        # The application logic (simulated here) tells the controller to issue the standard 'release' command.
        self.controller.invoke(barrier.id, 'release')

        for t in threads:
            t.join(2)

        # --- Verification ---
        # Verify that the default transit action was executed by both threads
        self.assertEqual(self.default_action_counter, 2)  # Both threads should have triggered the default action

    import threading
    import time

    def test_manual_release_with_override_action(self):
        """5. The Controller should release a barrier with a new, one-time action."""

        # --- Setup ---
        # Default action that should NOT be called once the override action is invoked.
        def default_transit_action():
            with self.lock:
                self.default_action_counter += 1  # Increment when the default action is called

        # Override action that should be called when the controller intercepts and releases with it.
        def override_action():
            with self.lock:
                self.override_action_counter += 1  # Increment when the override action is called

        # Initialize counters and lock
        self.default_action_counter = 0
        self.override_action_counter = 0
        self.lock = threading.Lock()  # Lock to protect the counters from race conditions

        # Create the barrier with the default action
        barrier = TransitBarrier(
            threshold=2,
            transit=default_transit_action,  # Use the real function
            manual_release=True,
            controller=self.controller
        )

        def worker():
            """A simple worker that waits at the barrier."""
            barrier.wait()

        # --- Execution ---
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()

        time.sleep(0.1)  # Wait for threads to hit barrier and signal

        # The application logic tells the controller to invoke the override action.
        self.controller.invoke(
            barrier.id,
            'release_with_action',  # The special command we added
            callback=override_action  # The new, overriding action
        )

        for t in threads:
            t.join()

        # --- Verification ---
        # Verify the override action was called for both threads
        self.assertEqual(self.override_action_counter, 2)  # Both threads should have triggered the override action

        # Verify the default action was NOT called
        self.assertEqual(self.default_action_counter, 0)  # The default action should not have been called

    def test_proxy_command_get_waiter_count(self):
        """6. The Controller should be able to query the barrier's internal state."""
        barrier = TransitBarrier(threshold=3, controller=self.controller)

        def worker():
            barrier.wait(timeout=0.5)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()

        time.sleep(0.1)  # Let threads enter the wait state

        # Use the controller to invoke the "proxy" command
        waiter_count = self.controller.invoke(barrier.id, 'get_waiter_count')

        self.assertEqual(waiter_count, 2)

        for t in threads:
            t.join()

    import threading

    def test_controller_can_intercept_and_override_transit(self):
        """
        Verifies the controller can intercept a release and provide a new action.
        """

        # --- Setup ---
        # The barrier is created with a default action that should NOT run.
        def default_transit_action():
            with self.lock:
                self.default_action_counter += 1  # Increment the counter safely when the action is called

        # This is the new, one-time action the controller will inject.
        def intercept_action():
            with self.lock:
                self.intercept_action_counter += 1  # Increment the counter safely when the action is called

        # Initialize counters and lock
        self.default_action_counter = 0
        self.intercept_action_counter = 0
        self.lock = threading.Lock()  # Lock to protect the counters from race conditions

        # Create the barrier with the default action
        barrier = TransitBarrier(
            threshold=2,
            transit=default_transit_action,  # Use the real function
            manual_release=True,
            controller=self.controller
        )

        def worker():
            """A simple worker that waits at the barrier."""
            barrier.wait()

        # --- Execution ---
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()

        # Allow threads to hit the barrier and signal the controller.
        time.sleep(0.1)

        # At this point, no action should have been called yet.
        self.assertTrue(all(t.is_alive() for t in threads))  # Threads should still be alive

        # The controller intercepts and commands the barrier to release
        # with the NEW action, overriding the default.
        self.controller.invoke(
            barrier.id,
            'release_with_action',  # The special command we added
            callback=intercept_action  # The new, overriding action
        )

        # Wait for the threads to finish.
        for t in threads:
            t.join()

        # --- Verification ---
        # Check that the intercept action has been executed
        self.assertEqual(self.intercept_action_counter, 2)  # Both threads should have triggered the intercept action

        # Ensure the default transit action was NOT executed
        self.assertEqual(self.default_action_counter, 0)  # Default action should not have been called


if __name__ == '__main__':
    unittest.main()