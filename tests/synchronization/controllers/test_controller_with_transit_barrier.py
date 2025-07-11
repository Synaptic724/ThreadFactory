import unittest
from unittest.mock import MagicMock
import threading
import time

from thread_factory.synchronization.controllers.signal_controller import SignalController
from thread_factory.synchronization.coordinators.transit_barrier import TransitBarrier


class TestControllerWithTransitBarrier(unittest.TestCase):
    """
    Tests the integration between the SignalController and the TransitBarrier.
    """

    def setUp(self):
        """Set up a new controller for each test."""
        self.controller = SignalController()
        # Suppress logging to keep test output clean
        self.controller._logger.disabled = True

    def tearDown(self):
        """Ensure the controller is disposed of after each test."""
        if self.controller and not self.controller._disposed:
            self.controller.dispose()

    def test_registration_on_creation(self):
        """A TransitBarrier should successfully register with the Controller upon creation."""
        barrier = TransitBarrier(threshold=1, controller=self.controller)
        self.assertIn(barrier.id, self.controller._registry, "Barrier should be in the controller's registry.")
        self.assertEqual(self.controller._registry[barrier.id]['name'], 'transit_barrier')

    def test_auto_release_executes_transit_action(self):
        """A barrier in auto-release mode should release and run its transit action."""
        transit_executed = threading.Event()
        barrier = TransitBarrier(threshold=2, transit=transit_executed.set)

        threads = [threading.Thread(target=barrier.wait) for _ in range(2)]
        for t in threads: t.start()
        for t in threads: t.join()

        self.assertTrue(transit_executed.is_set(), "The transit action should have been executed.")
        self.assertTrue(barrier._transit_fired)

    def test_manual_release_signals_and_waits(self):
        """A manual barrier should signal THRESHOLD_MET and wait for a command."""
        event_subscriber = MagicMock()
        barrier = TransitBarrier(threshold=2, manual_release=True, controller=self.controller)
        self.controller.subscribe(barrier.id, "THRESHOLD_MET", event_subscriber)

        threads = [threading.Thread(target=barrier.wait) for _ in range(2)]
        for t in threads: t.start()

        time.sleep(0.1)  # Give threads time to hit the barrier.

        event_subscriber.assert_called_once_with(barrier.id, "THRESHOLD_MET", None)
        for t in threads:
            self.assertTrue(t.is_alive(), "Threads should be blocked waiting for release.")

        # Clean up by releasing the barrier so threads can exit.
        self.controller.invoke(barrier.id, 'release')
        for t in threads: t.join()

    def test_controller_releases_with_default_action(self):
        """The Controller should release a waiting barrier using its default transit action."""
        action_counter = 0
        lock = threading.Lock()

        def default_action():
            with lock:
                nonlocal action_counter
                action_counter += 1

        barrier = TransitBarrier(threshold=2, transit=default_action, manual_release=True, controller=self.controller)

        threads = [threading.Thread(target=barrier.wait) for _ in range(2)]
        for t in threads: t.start()
        time.sleep(0.1)  # Wait for threads to hit barrier.

        self.assertEqual(action_counter, 0, "Action should not run before release command.")

        self.controller.invoke(barrier.id, 'release')
        for t in threads: t.join()

        self.assertEqual(action_counter, 2, "Default action should have run for both threads.")

    def test_controller_releases_with_override_action(self):
        """The Controller should release a barrier with a new, one-time action, overriding the default."""
        default_called = threading.Event()
        override_called_count = 0
        lock = threading.Lock()

        def override_action():
            with lock:
                nonlocal override_called_count
                override_called_count += 1

        barrier = TransitBarrier(threshold=2, transit=default_called.set, manual_release=True,
                                 controller=self.controller)

        threads = [threading.Thread(target=barrier.wait) for _ in range(2)]
        for t in threads: t.start()
        time.sleep(0.1)

        self.controller.invoke(barrier.id, 'release_with_action', callback=override_action)
        for t in threads: t.join()

        self.assertEqual(override_called_count, 2, "Override action should have run for both threads.")
        self.assertFalse(default_called.is_set(), "Default action should have been ignored.")

    def test_controller_can_query_waiter_count(self):
        """The Controller should be able to query the barrier's internal waiter count."""
        barrier = TransitBarrier(threshold=3, controller=self.controller)

        threads = [threading.Thread(target=lambda: barrier.wait(timeout=0.2)) for _ in range(2)]
        for t in threads: t.start()
        time.sleep(0.1)

        waiter_count = self.controller.invoke(barrier.id, 'get_waiter_count')
        self.assertEqual(waiter_count, 2)

        for t in threads: t.join()


if __name__ == '__main__':
    unittest.main()