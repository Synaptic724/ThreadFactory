import logging
import threading
import time
import unittest
from unittest.mock import MagicMock, call
# Import the real objects to be tested
from thread_factory import SignalController, SignalBarrier


class TestComprehensiveControllerSemaphore(unittest.TestCase):
    """
    A comprehensive integration test suite for the Controller and ThresholdSemaphore.
    This suite tests all major features of their interaction.
    """

    # --------------------------------------------------------------------- #
    # Test Framework Plumbing
    # --------------------------------------------------------------------- #

    def setUp(self):
        """Set up a new controller with a mock logger for each test."""
        self.mock_logger = MagicMock(spec=logging.Logger)
        self.controller = SignalController(logger=self.mock_logger)

    def tearDown(self):
        """Ensure the controller is disposed of after each test."""
        if self.controller and not self.controller._disposed:
            self.controller.dispose()
        self.controller = None

    def _make_semaphore(self, threshold: int, **kwargs) -> SignalBarrier:
        """Helper to create a ThresholdSemaphore already wired to the controller."""
        return SignalBarrier(
            threshold=threshold,
            controller=self.controller,
            signal_callback=self.controller.on_wait_starting,
            **kwargs,
        )

    # --------------------------------------------------------------------- #
    # Section 1: Registration & Lifecycle
    # --------------------------------------------------------------------- #

    def test_1_registration_and_details(self):
        """A semaphore should register itself and provide correct details."""
        sema = self._make_semaphore(threshold=2)

        # Check registration
        self.assertIn(sema.id, self.controller._registry)

        # Check details provided to the controller
        details = self.controller._registry[sema.id]
        self.assertEqual(details['name'], 'signal_barrier')
        self.assertIn('release', details['commands'])
        self.assertIn('reset', details['commands'])

    def test_2_unregister_cleans_up_state(self):
        """Unregistering should remove the object from all internal controller state."""
        sema = self._make_semaphore(threshold=2)

        # Add to various states
        self.controller.on_wait_starting(sema.id)
        self.controller.subscribe(sema.id, "TEST_EVENT", lambda: None)

        # Verify it's in the states
        self.assertIn(sema.id, self.controller._registry)
        self.assertIn(sema.id, self.controller.get_waiting_objects())
        self.assertIn(sema.id, self.controller._subscribers)

        # Unregister
        self.controller.unregister(sema.id)

        # Verify it's gone from all states
        self.assertNotIn(sema.id, self.controller._registry)
        self.assertNotIn(sema.id, self.controller.get_waiting_objects())
        self.assertNotIn(sema.id, self.controller._subscribers)
        self.assertTrue(sema._disposed, "Unregister should dispose the object by default")

    def test_3_controller_dispose_cascades(self):
        """Disposing the controller should dispose of all its registered semaphores."""
        semaphores = [self._make_semaphore(threshold=1) for _ in range(3)]

        self.controller.dispose()

        self.assertTrue(self.controller._disposed)
        for s in semaphores:
            self.assertTrue(s._disposed, "Semaphore should be disposed when controller is disposed")

    # --------------------------------------------------------------------- #
    # Section 2: Command Invocation
    # --------------------------------------------------------------------- #

    def test_4_invoke_command_with_args(self):
        """The controller must correctly invoke a command with arguments."""
        sema = self._make_semaphore(threshold=3)
        self.controller.invoke(sema.id, "set_threshold", new_threshold=5)
        self.assertEqual(sema._threshold, 5)

    def test_5_invoke_query_command(self):
        """The controller should return values from invoked query commands."""
        sema = self._make_semaphore(threshold=1, reusable=False)
        is_spent_before = self.controller.invoke(sema.id, 'is_spent')
        sema.wait()
        is_spent_after = self.controller.invoke(sema.id, 'is_spent')

        self.assertFalse(is_spent_before)
        self.assertTrue(is_spent_after)

    def test_6_invoke_on_all_with_filter(self):
        """'invoke_on_all' should respect the name_filter argument."""
        sema_A = self._make_semaphore(threshold=5)
        sema_B = self._make_semaphore(threshold=5)

        # Manually rename one for the test
        self.controller._registry[sema_B.id]['name'] = 'special_semaphore'

        self.controller.invoke_on_all('notify_all_override', name_filter='special_semaphore')

        # FIX: Check the internal '_released' flag instead of a non-existent 'is_open' method.
        self.assertTrue(sema_B._released, "Filtered semaphore should be released")
        self.assertFalse(sema_A._released, "Non-filtered semaphore should NOT be released")

    # --------------------------------------------------------------------- #
    # Section 3: Wait State & Event Tracking
    # --------------------------------------------------------------------- #

    def test_7_wait_state_tracked_and_cleared_on_release(self):
        """Controller should track a waiting object and clear it on release."""
        sema = self._make_semaphore(threshold=2, manual_release=True)

        def worker():
            sema.wait(timeout=1.5)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()

        time.sleep(0.1)  # Let threads block and signal
        self.assertIn(sema.id, self.controller.get_waiting_objects(), "Semaphore should be in waiting list")

        # Manually release and trigger the "SEMAPHORE_RELEASED" event
        self.controller.invoke(sema.id, 'release')

        for t in threads:
            t.join()

        self.assertNotIn(sema.id, self.controller.get_waiting_objects(),
                         "Semaphore should be removed from waiting list")

    # --------------------------------------------------------------------- #
    # Section 4: Pub/Sub System
    # --------------------------------------------------------------------- #

    def test_8_subscribe_and_notify_threshold_met(self):
        """A subscriber should be correctly notified of the THRESHOLD_MET event."""
        sema = self._make_semaphore(threshold=1)
        callback = MagicMock()
        self.controller.subscribe(sema.id, "THRESHOLD_MET", callback)

        sema.wait()  # This meets the threshold

        callback.assert_called_once_with(sema.id, "THRESHOLD_MET", None)

    def test_9_subscriber_exception_is_logged(self):
        """An exception within a subscriber should be caught and logged, not crash."""
        sema = self._make_semaphore(threshold=1)

        def failing_subscriber(*args, **kwargs):
            raise ValueError("This subscriber is designed to fail")

        self.controller.subscribe(sema.id, "THRESHOLD_MET", failing_subscriber)

        # This will trigger the notification and the failing subscriber
        sema.wait()

        # Check that the controller logged the error instead of crashing
        self.mock_logger.error.assert_called_once()

        # FIX: Check for the exception's message, not its class name, to match the log format.
        log_call_str = str(self.mock_logger.error.call_args)
        self.assertIn("Subscriber callback failed", log_call_str)
        self.assertIn("This subscriber is designed to fail", log_call_str)

    # --------------------------------------------------------------------- #
    # Section 5: Controller Hooks
    # --------------------------------------------------------------------- #

    def test_10_pre_and_post_invoke_hooks_on_success(self):
        """Pre- and post-invoke hooks should fire correctly on a successful command."""
        sema = self._make_semaphore(threshold=3)
        pre_hook = MagicMock()
        post_hook = MagicMock()

        self.controller.add_pre_invoke_hook(pre_hook)
        self.controller.add_post_invoke_hook(post_hook)

        # Invoke a command that returns a value
        result = self.controller.invoke(sema.id, 'is_spent')

        # Verify pre-hook was called before the command
        pre_hook.assert_called_once_with(sema.id, 'is_spent')

        # Verify post-hook was called after with the correct result
        post_hook.assert_called_once_with(sema.id, 'is_spent', result, None)
        self.assertFalse(result)

    def test_11_post_invoke_hook_on_failure(self):
        """The post-invoke hook should fire with an exception object on command failure."""
        sema = self._make_semaphore(threshold=1)
        post_hook = MagicMock()
        self.controller.add_post_invoke_hook(post_hook)

        # set_threshold will raise a ValueError with a non-positive integer
        with self.assertRaises(ValueError):
            self.controller.invoke(sema.id, 'set_threshold', new_threshold=0)

        # Check that the post_hook was still called, but with an exception
        self.assertEqual(post_hook.call_count, 1)
        args, _ = post_hook.call_args

        self.assertEqual(args[0], sema.id)  # object_id
        self.assertEqual(args[1], 'set_threshold')  # command
        self.assertIsNone(args[2])  # result is None
        self.assertIsInstance(args[3], ValueError)  # exception is a ValueError

    # --------------------------------------------------------------------- #
    # Section 6: Error Handling
    # --------------------------------------------------------------------- #

    def test_12_invoke_invalid_command_raises_key_error(self):
        """Invoking a non-existent command should raise a helpful KeyError."""
        sema = self._make_semaphore(threshold=2)
        with self.assertRaisesRegex(KeyError, "has no command 'non_existent_command'"):
            self.controller.invoke(sema.id, 'non_existent_command')


if __name__ == "__main__":
    unittest.main()