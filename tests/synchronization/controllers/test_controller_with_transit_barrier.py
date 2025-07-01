import unittest
from unittest.mock import MagicMock
import threading
import time

# Assuming classes are in this structure
from thread_factory.synchronization.controllers.signal_controller import Controller
from thread_factory.synchronization.coordinators.transit_barrier import TransitBarrier


class TestControllerWithTransitBarrier(unittest.TestCase):
    """
    Tests the integration between the Controller and the TransitBarrier,
    covering auto-release, manual release signals, and command overrides.
    """

    def setUp(self):
        """Set up a new controller with a mock logger for each test."""
        self.mock_logger = MagicMock()
        self.controller = Controller(logger=self.mock_logger)

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
        transit_action = MagicMock()

        barrier = TransitBarrier(
            threshold=2,
            transit=transit_action,
            manual_release=False,  # Auto-release is default, but explicit here
            controller=self.controller
        )

        def worker():
            barrier.wait()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # The transit action should have been called twice, once by each thread.
        self.assertEqual(transit_action.call_count, 2)
        # No signals should have been sent to the controller for a decision.
        self.mock_logger.info.assert_not_called()

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
        default_transit_action = MagicMock()

        barrier = TransitBarrier(
            threshold=2,
            transit=default_transit_action,
            manual_release=True,
            controller=self.controller
        )

        def worker():
            barrier.wait()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()

        time.sleep(0.1)  # Wait for threads to hit barrier and signal
        self.assertTrue(default_transit_action.call_count == 0)

        # The application logic (simulated here) tells the controller to issue the standard 'release' command.
        self.controller.invoke(barrier.id, 'release')

        for t in threads:
            t.join()

        # VERIFY: The default transit action was executed by both threads
        self.assertEqual(default_transit_action.call_count, 2)

    def test_manual_release_with_override_action(self):
        """5. The Controller should release a barrier with a new, one-time action."""
        default_transit_action = MagicMock()
        override_action = MagicMock()

        barrier = TransitBarrier(
            threshold=2,
            transit=default_transit_action,
            manual_release=True,
            controller=self.controller
        )

        def worker():
            barrier.wait()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()

        time.sleep(0.1)  # Wait for threads to hit barrier and signal

        # The application logic tells the controller to invoke the override command.
        self.controller.invoke(
            barrier.id,
            'release_with_action',
            callback=override_action
        )

        for t in threads:
            t.join()

        # VERIFY: The new override action was called, and the default was NOT.
        self.assertEqual(override_action.call_count, 2)
        default_transit_action.assert_not_called()

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

    def test_controller_can_intercept_and_override_transit(self):
        """
        7. Verifies the controller can intercept a release and provide a new action.
        """
        # --- Setup ---
        # The barrier is created with a default action that should NOT run.
        default_transit_action = MagicMock(name="DefaultAction")

        # This is the new, one-time action the controller will inject.
        intercept_action = MagicMock(name="InterceptAction")

        barrier = TransitBarrier(
            threshold=2,
            transit=default_transit_action,
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

        # At this point, no action should have been called.
        default_transit_action.assert_not_called()
        intercept_action.assert_not_called()
        self.assertTrue(all(t.is_alive() for t in threads))

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
        # The new, intercepting action should have been called by both threads.
        self.assertEqual(intercept_action.call_count, 2)

        # The original, default transit action should have been ignored.
        default_transit_action.assert_not_called()


if __name__ == '__main__':
    unittest.main()