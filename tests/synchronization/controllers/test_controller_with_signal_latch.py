# test_controller_latch.py
import logging
import threading
import time
import unittest
from typing import List
from unittest.mock import MagicMock, call  # Import 'call' for a more robust check
from thread_factory.synchronization.controllers.signal_controller import Controller
from thread_factory.synchronization.primitives.signal_latch import SignalLatch
from thread_factory.concurrency import ConcurrentDict


class TestControllerWithLatch(unittest.TestCase):
    """Integration-style tests for Controller using real SignalLatch objects."""

    # --------------------------------------------------------------------- #
    # Helpers
    # --------------------------------------------------------------------- #
    def _make_latch(self) -> SignalLatch:
        """Create a SignalLatch already wired to this test's controller."""
        return SignalLatch(
            controller=self.controller,
            signal_callback=self.controller.on_wait_starting,  # event handshake
        )

    # --------------------------------------------------------------------- #
    # Framework plumbing
    # --------------------------------------------------------------------- #
    def setUp(self):
        self.mock_logger = MagicMock(spec=logging.Logger)
        # Apply your corrected Controller class from the previous step
        self.controller = Controller(logger=self.mock_logger)
        self.temp_controller = None

    def tearDown(self):
        # Dispose main controller if still alive
        if self.controller and not self.controller._disposed:
            self.controller.dispose()
        # Dispose any secondary controller
        if self.temp_controller and not self.temp_controller._disposed:
            self.temp_controller.dispose()
        self.controller = None
        self.temp_controller = None

    # --------------------------------------------------------------------- #
    # 1 – Initialization
    # --------------------------------------------------------------------- #
    def test_initialization_defaults(self):
        self.assertIsInstance(self.controller._registry, ConcurrentDict)
        self.assertFalse(self.controller._disposed)
        self.assertIs(self.controller._logger, self.mock_logger)

        # Create controller with default logger
        self.temp_controller = Controller()
        self.assertIsInstance(self.temp_controller._logger, logging.Logger)
        self.assertNotEqual(self.temp_controller._logger, self.mock_logger)
        self.assertTrue(self.temp_controller._logger.handlers)
        self.assertEqual(self.temp_controller._logger.level, logging.DEBUG)

    # --------------------------------------------------------------------- #
    # 2 – Successful registration
    # --------------------------------------------------------------------- #
    def test_register_latch_success(self):
        latch = self._make_latch()
        self.assertIn(latch.id, self.controller._registry)
        self.mock_logger.debug.assert_called_with(
            f"Registered object: ID='{latch.id}', Name='latch'"
        )

    # --------------------------------------------------------------------- #
    # 3 – Duplicate registration failure
    # --------------------------------------------------------------------- #
    def test_register_duplicate_fails(self):
        latch = self._make_latch()
        with self.assertRaisesRegex(ValueError, "already registered"):
            self.controller.register(latch)

    # --------------------------------------------------------------------- #
    # 4 – Unregister disposes object
    # --------------------------------------------------------------------- #
    def test_unregister_disposes_latch(self):
        latch = self._make_latch()
        self.controller.unregister(latch.id)
        self.assertTrue(latch._disposed)
        self.assertNotIn(latch.id, self.controller._registry)

    # --------------------------------------------------------------------- #
    # 5 – Unregister WITHOUT dispose
    # --------------------------------------------------------------------- #
    def test_unregister_without_dispose_flag(self):
        latch = self._make_latch()
        self.controller.unregister(latch.id, dispose_object=False)
        self.assertFalse(latch._disposed)

    # --------------------------------------------------------------------- #
    # 6 – Invoke: open command works
    # --------------------------------------------------------------------- #
    def test_invoke_open(self):
        latch = self._make_latch()
        self.assertFalse(latch.is_open())
        self.controller.invoke(latch.id, "open")
        self.assertTrue(latch.is_open())

    # --------------------------------------------------------------------- #
    # 7 – Invoke: reset command works
    # --------------------------------------------------------------------- #
    def test_invoke_reset(self):
        latch = self._make_latch()
        self.controller.invoke(latch.id, "open")
        self.assertTrue(latch.is_open())
        self.controller.invoke(latch.id, "reset")
        self.assertFalse(latch.is_open())

    # --------------------------------------------------------------------- #
    # 8 – Invoke: is_open query
    # --------------------------------------------------------------------- #
    def test_invoke_is_open(self):
        latch = self._make_latch()
        result_before = self.controller.invoke(latch.id, "is_open")
        self.controller.invoke(latch.id, "open")
        result_after = self.controller.invoke(latch.id, "is_open")
        self.assertEqual((result_before, result_after), (False, True))

    # --------------------------------------------------------------------- #
    # 9 – Broadcast open to ALL objects
    # --------------------------------------------------------------------- #
    def test_invoke_on_all_open(self):
        latches = [self._make_latch() for _ in range(3)]
        self.controller.invoke_on_all("open")
        self.assertTrue(all(l.is_open() for l in latches))

        # FIX: Change assert_called_with to assert_any_call.
        # This checks if the call was made at all, not if it was the *last* call.
        self.mock_logger.info.assert_any_call(
            f"Broadcasting command 'open' to 3 objects."
        )

    # --------------------------------------------------------------------- #
    # 10 – Broadcast with name_filter
    # --------------------------------------------------------------------- #
    def test_invoke_on_all_with_filter(self):
        latch1 = self._make_latch()
        latch2 = self._make_latch()

        # Rename the second latch to “special”
        latch2_name_patch = {'name': 'special'}
        self.controller._registry[latch2.id]['name'] = 'special'  # quick patch

        self.controller.invoke_on_all("open", name_filter="special")
        self.assertFalse(latch1.is_open())
        self.assertTrue(latch2.is_open())

    # --------------------------------------------------------------------- #
    # 11 – Concurrent wait blocks then releases
    # --------------------------------------------------------------------- #
    def test_concurrent_wait_and_open(self):
        latch = self._make_latch()
        wait_results: List[bool] = []

        def waiter():
            wait_results.append(latch.wait(timeout=1.0))

        t = threading.Thread(target=waiter, daemon=True)
        t.start()
        time.sleep(0.1)  # ensure thread is blocking
        self.assertFalse(wait_results)  # nothing appended yet
        self.controller.invoke(latch.id, "open")
        t.join(timeout=2)
        self.assertEqual(wait_results, [True])

    # --------------------------------------------------------------------- #
    # 12 – WAIT_STARTING and DISPOSED_BY_CONTROLLER events
    # --------------------------------------------------------------------- #
    def test_event_tracking_wait_and_dispose(self):
        latch = self._make_latch()
        self.controller.on_wait_starting(latch.id)
        self.assertEqual(self.controller.get_waiting_objects(), [latch.id])

        # invoke("dispose") triggers DISPOSED_BY_CONTROLLER
        self.controller.invoke(latch.id, "dispose")

        # Check that the expected event was logged at some point
        expected_event_call = call(f"Controller Event: ID='{latch.id}', Event='DISPOSED_BY_CONTROLLER'")
        self.assertIn(expected_event_call, self.mock_logger.info.call_args_list)

        self.assertEqual(list(self.controller.get_waiting_objects()), [])

    # --------------------------------------------------------------------- #
    # 13 – Subscribe & notify WAIT_STARTING
    # --------------------------------------------------------------------- #
    def test_subscribe_wait_starting(self):
        latch = self._make_latch()
        callback = MagicMock()
        self.controller.subscribe(latch.id, "WAIT_STARTING", callback)
        self.controller.on_wait_starting(latch.id)
        callback.assert_called_once_with(latch.id, "WAIT_STARTING", None)

    # --------------------------------------------------------------------- #
    # 14 – Subscriber receives custom event
    # --------------------------------------------------------------------- #
    def test_subscribe_custom_event(self):
        latch = self._make_latch()
        callback = MagicMock()
        self.controller.subscribe(latch.id, "MY_EVENT", callback)
        self.controller.notify(latch.id, "MY_EVENT", data={"x": 1})
        callback.assert_called_once_with(latch.id, "MY_EVENT", {"x": 1})

    # --------------------------------------------------------------------- #
    # 15 – Controller.dispose disposes all latches
    # --------------------------------------------------------------------- #
    def test_controller_dispose_disposes_everything(self):
        latches = [self._make_latch() for _ in range(2)]
        self.controller.dispose()
        self.assertTrue(self.controller._disposed)
        for l in latches:
            self.assertTrue(l._disposed)

    # --------------------------------------------------------------------- #
    # 16 – list_objects filtering
    # --------------------------------------------------------------------- #
    def test_list_objects(self):
        latch1 = self._make_latch()
        latch2 = self._make_latch()
        self.controller._registry[latch2.id]['name'] = 'printer'  # rename

        all_objs = self.controller.list_objects()
        self.assertEqual(len(all_objs), 2)

        printers = self.controller.list_objects(name_filter='printer')
        self.assertEqual(len(printers), 1)
        self.assertEqual(printers[0]['id'], latch2.id)

    # --------------------------------------------------------------------- #
    # 17 – get_waiting_objects accuracy
    # --------------------------------------------------------------------- #
    def test_waiting_objects_set(self):
        latch = self._make_latch()
        self.controller.on_wait_starting(latch.id)
        self.assertEqual(self.controller.get_waiting_objects(), [latch.id])
        self.controller.notify(latch.id, "DISPOSED_BY_CONTROLLER")
        self.assertEqual(list(self.controller.get_waiting_objects()), [])

    # --------------------------------------------------------------------- #
    # 18 – Invalid command error
    # --------------------------------------------------------------------- #
    def test_invoke_invalid_command(self):
        latch = self._make_latch()
        with self.assertRaisesRegex(KeyError, "has no command 'nope'"):
            self.controller.invoke(latch.id, "nope")

    # --------------------------------------------------------------------- #
    # 19 – Unregistered object error
    # --------------------------------------------------------------------- #
    def test_invoke_unregistered_object(self):
        with self.assertRaisesRegex(KeyError, "No object registered with ID 'ghost'"):
            self.controller.invoke("ghost", "open")

    # --------------------------------------------------------------------- #
    # 20 – Subscriber exception is swallowed and logged
    # --------------------------------------------------------------------- #
    def test_subscriber_exception_handled(self):
        latch = self._make_latch()

        def boom(*_):
            raise RuntimeError("boom")

        self.controller.subscribe(latch.id, "WAIT_STARTING", boom)
        self.controller.on_wait_starting(latch._id)

        # Controller should log an error but NOT raise
        self.mock_logger.error.assert_called_once()
        self.assertIn("Subscriber callback failed", self.mock_logger.error.call_args[0][0])


if __name__ == "__main__":
    unittest.main()