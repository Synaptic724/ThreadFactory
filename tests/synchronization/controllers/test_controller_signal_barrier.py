import logging
import threading
import time
import unittest
from typing import List
from unittest.mock import MagicMock, call
# Import the real objects to be tested
from thread_factory.synchronization.controllers.signal_controller import SignalController
from thread_factory.synchronization.primitives.signal_barrier import SignalBarrier
from thread_factory.concurrency import ConcurrentDict


class TestControllerWithSemaphore(unittest.TestCase):
    """Integration-style tests for Controller using real ThresholdSemaphore objects."""

    # --------------------------------------------------------------------- #
    # Helpers
    # --------------------------------------------------------------------- #
    def _make_semaphore(self, threshold: int, **kwargs) -> SignalBarrier:
        """Create a ThresholdSemaphore already wired to this test's controller."""
        return SignalBarrier(
            threshold=threshold,
            controller=self.controller,
            signal_callback=self.controller.on_wait_starting,  # event handshake
            **kwargs,
        )

    # --------------------------------------------------------------------- #
    # Framework plumbing
    # --------------------------------------------------------------------- #
    def setUp(self):
        self.mock_logger = MagicMock(spec=logging.Logger)
        self.controller = SignalController(logger=self.mock_logger)
        self.temp_controller = None

    def tearDown(self):
        if self.controller and not self.controller._disposed:
            self.controller.dispose()
        if self.temp_controller and not self.temp_controller._disposed:
            self.temp_controller.dispose()
        self.controller = None
        self.temp_controller = None

    # --------------------------------------------------------------------- #
    # Tests
    # --------------------------------------------------------------------- #

    def test_register_semaphore_success(self):
        """1. A semaphore should register itself with the controller on creation."""
        sema = self._make_semaphore(threshold=2)
        self.assertIn(sema.id, self.controller._registry)
        self.assertEqual(self.controller._registry[sema.id]['name'], 'threshold_semaphore')
        self.mock_logger.debug.assert_called_with(
            f"Registered object: ID='{sema.id}', Name='threshold_semaphore'"
        )

    def test_invoke_reset_command(self):
        """2. The controller should be able to invoke the 'reset' command."""
        sema = self._make_semaphore(threshold=1, reusable=True)
        sema.wait()  # Use the semaphore once
        self.assertEqual(sema._count, 0)  # It's reusable, so it already reset

        # Manually increment and check reset
        sema._count = 1
        self.controller.invoke(sema.id, "reset")
        self.assertEqual(sema._count, 0)

    def test_invoke_set_threshold(self):
        """3. The controller should be able to invoke 'set_threshold'."""
        sema = self._make_semaphore(threshold=3)
        self.assertEqual(sema._threshold, 3)
        self.controller.invoke(sema.id, "set_threshold", new_threshold=5)
        self.assertEqual(sema._threshold, 5)

    def test_wait_and_manual_release_via_invoke(self):
        """4. Controller can release a manually controlled semaphore."""
        sema = self._make_semaphore(threshold=2, manual_release=True)
        results = []

        def worker():
            if sema.wait(timeout=1.0):
                results.append(True)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()

        time.sleep(0.1)  # Ensure threads are blocked
        self.assertEqual(len(results), 0, "Threads should be blocked before release")

        # Release using the controller
        self.controller.invoke(sema.id, 'release')

        for t in threads:
            t.join()

        self.assertEqual(len(results), 2, "Both threads should be released")

    def test_event_tracking_wait_and_auto_release(self):
        """5. Controller should track a semaphore's waiting and released states."""
        sema = self._make_semaphore(threshold=2, reusable=True)

        def worker():
            sema.wait(timeout=1.0)

        t1 = threading.Thread(target=worker)
        t1.start()

        time.sleep(0.1)  # Let the thread block and signal the controller
        self.assertIn(sema.id, self.controller.get_waiting_objects(), "Semaphore should be in waiting list")

        # Start a second thread to meet the threshold and trigger auto-release
        t2 = threading.Thread(target=worker)
        t2.start()

        t1.join()
        t2.join()

        # After release, the semaphore should no longer be in the waiting list
        self.assertNotIn(sema.id, self.controller.get_waiting_objects(),
                         "Semaphore should be removed from waiting list after release")

    def test_subscribe_to_threshold_met_event(self):
        """6. A subscriber should be notified when the threshold is met."""
        sema = self._make_semaphore(threshold=2, manual_release=True)
        callback = MagicMock()
        self.controller.subscribe(sema.id, "THRESHOLD_MET", callback)

        def worker():
            sema.wait(timeout=1.0)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()

        time.sleep(0.1)  # Let threads hit the threshold

        callback.assert_called_once_with(sema.id, "THRESHOLD_MET", None)

        # Clean up threads
        self.controller.invoke(sema.id, 'release')
        for t in threads:
            t.join()

    def test_subscribe_to_semaphore_released_event(self):
        """7. A subscriber should be notified when the semaphore is released."""
        sema = self._make_semaphore(threshold=1)
        callback = MagicMock()
        self.controller.subscribe(sema.id, "SEMAPHORE_RELEASED", callback)

        sema.wait()  # This will trigger the release immediately

        callback.assert_called_once_with(sema.id, "SEMAPHORE_RELEASED", None)

    def test_broadcast_reset_command(self):
        """8. 'invoke_on_all' should work for commands like 'reset'."""
        semaphores = [self._make_semaphore(threshold=1, reusable=True) for _ in range(3)]

        # Manually set counts to a non-zero value
        for s in semaphores:
            s._count = 1

        self.controller.invoke_on_all("reset")

        for s in semaphores:
            self.assertEqual(s._count, 0)

    def test_broadcast_notify_all_override(self):
        """9. 'invoke_on_all' should release all waiting threads via override."""
        semaphores = [self._make_semaphore(threshold=5) for _ in range(3)]  # High threshold
        results = []

        def worker(sema_instance):
            if sema_instance.wait(timeout=1.0):
                results.append(True)

        threads = [threading.Thread(target=worker, args=(s,)) for s in semaphores]
        for t in threads:
            t.start()

        time.sleep(0.1)
        self.assertEqual(len(results), 0, "No threads should be released yet")

        self.controller.invoke_on_all("notify_all_override")

        for t in threads:
            t.join()

        self.assertEqual(len(results), 3, "All threads should be released by broadcast")

    def test_controller_dispose_handles_semaphores(self):
        """10. Disposing the controller should dispose of all its registered semaphores."""
        semaphores = [self._make_semaphore(threshold=1) for _ in range(3)]

        self.controller.dispose()

        self.assertTrue(self.controller._disposed)
        for s in semaphores:
            self.assertTrue(s._disposed)


if __name__ == "__main__":
    unittest.main()