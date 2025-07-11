import threading
import time
import unittest
from typing import Any

# Import the new, refactored SignalLatch
from thread_factory import SignalLatch, TransitCondition, Pack


# Assuming a placeholder IDisposable for testing context
class IDisposable:
    def __init__(self):
        self._disposed = False
    def dispose(self):
        self._disposed = True

# A mock controller that aligns with the final Controller design
class MockController(IDisposable):
    def __init__(self):
        super().__init__()
        self.registry = {}
        self.notifications = []
        self.notification_event = threading.Event()

    def register(self, registrant: Any):
        details = registrant._get_object_details()
        self.registry[registrant.id] = {
            'name': details['name'],
            'commands': details['commands']
        }

    def on_wait_starting(self, object_id: str):
        self.notifications.append({'id': object_id, 'event': 'WAIT_STARTING'})
        self.notification_event.set()

    # FIX: Add the missing 'notify' method
    def notify(self, object_id: str, event_type: str, *args, **kwargs):
        """Mocks the notification mechanism of the real controller."""
        self.notifications.append({
            'id': object_id,
            'event': event_type,
            'args': args,
            'kwargs': kwargs
        })
        self.notification_event.set()

    def invoke(self, object_id: str, command: str, *args, **kwargs):
        if object_id not in self.registry:
            raise KeyError(f"Object {object_id} not registered.")
        if command not in self.registry[object_id]['commands']:
            raise KeyError(f"Command {command} not found for object {object_id}.")
        return self.registry[object_id]['commands'][command](*args, **kwargs)


class TestSignalLatch(unittest.TestCase):

    def setUp(self):
        """Set up a clean state for each test."""
        self.mock_signal_callback_called = False
        self.mock_signal_callback_id = None
        self.mock_controller = MockController()

    def mock_signal_callback(self, latch_id: str):
        """A simple callback for testing standalone functionality."""
        self.mock_signal_callback_called = True
        self.mock_signal_callback_id = latch_id

    def test_initialization_defaults(self):
        """Test latch initializes with default values."""
        latch = SignalLatch()
        self.assertIsInstance(latch.id, str)
        self.assertFalse(latch.is_open())
        self.assertIsInstance(latch._cond, TransitCondition)
        self.assertIsNone(latch._signal_callback)
        self.assertIsNone(latch._controller)

    def test_initialization_with_args(self):
        """Test latch initializes with provided arguments."""
        mock_cond = TransitCondition()
        latch = SignalLatch(
            signal_callback=self.mock_signal_callback,
            cond=mock_cond,
            controller=self.mock_controller
        )

        self.assertIsInstance(latch.id, str)
        self.assertFalse(latch.is_open())
        self.assertIs(latch._cond, mock_cond)

        # ✅ Confirm the callback is wrapped in a Pack and matches expected func by name/module
        self.assertIsInstance(latch._signal_callback, Pack)
        self.assertEqual(
            latch._signal_callback._func.__name__,
            self.mock_signal_callback.__name__
        )
        self.assertEqual(
            latch._signal_callback._func.__module__,
            self.mock_signal_callback.__module__
        )

        self.assertIs(latch._controller, self.mock_controller)

        # ✅ Confirm the latch was registered with the controller
        self.assertIn(latch.id, self.mock_controller.registry)

    def test_get_object_details_contract(self):
        """Test that the latch provides the correct details for the controller."""
        latch = SignalLatch()
        details = latch._get_object_details()
        self.assertEqual(details['name'], 'latch')
        self.assertIn('open', details['commands'])
        self.assertIn('reset', details['commands'])
        self.assertTrue(callable(details['commands']['open']))

    def test_wait_blocks_until_open(self):
        """Test that wait() blocks a thread until open() is called."""
        latch = SignalLatch()
        thread_finished = threading.Event()

        def worker():
            latch.closed()
            thread_finished.set()

        thread = threading.Thread(target=worker)
        thread.start()
        time.sleep(0.05)
        self.assertFalse(thread_finished.is_set())
        latch.open()
        self.assertTrue(thread_finished.wait(timeout=0.5))
        thread.join()

    def test_wait_does_not_block_if_already_open(self):
        """Test that wait() does not block if the latch is already open."""
        latch = SignalLatch()
        latch.open()
        thread_finished = threading.Event()

        def worker():
            latch.closed()
            thread_finished.set()

        thread = threading.Thread(target=worker)
        thread.start()
        self.assertTrue(thread_finished.wait(timeout=0.1))
        thread.join()

    def test_wait_timeout(self):
        """Test that wait() returns False on timeout."""
        latch = SignalLatch()
        result = [None]
        def worker():
            result[0] = latch.closed(timeout=0.05)
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        self.assertFalse(result[0])
        self.assertFalse(latch.is_open())

    def test_wait_raises_runtime_error_if_disposed(self):
        """Test that wait() raises an error if the latch is disposed."""
        latch = SignalLatch()
        latch.dispose()
        with self.assertRaisesRegex(RuntimeError, "disposed"):
            latch.closed()

    def test_wait_invokes_signal_callback(self):
        """Test that wait() correctly invokes the standalone signal_callback."""
        latch = SignalLatch(signal_callback=self.mock_signal_callback)
        def worker():
            latch.closed()
        thread = threading.Thread(target=worker)
        thread.start()
        time.sleep(0.05)
        self.assertTrue(self.mock_signal_callback_called)
        self.assertEqual(self.mock_signal_callback_id, latch.id)
        latch.open()
        thread.join()

    def test_wait_invokes_controller_callback(self):
        """Test that wait() invokes the controller's callback when wired up."""
        latch = SignalLatch(
            controller=self.mock_controller,
            signal_callback=self.mock_controller.on_wait_starting
        )
        def worker():
            latch.closed()
        thread = threading.Thread(target=worker)
        thread.start()
        self.assertTrue(self.mock_controller.notification_event.wait(timeout=0.5))
        self.assertEqual(len(self.mock_controller.notifications), 1)
        self.assertEqual(self.mock_controller.notifications[0]['id'], latch.id)
        self.assertEqual(self.mock_controller.notifications[0]['event'], 'WAIT_STARTING')
        latch.open()
        thread.join()

    def test_wait_handles_signal_callback_exception(self):
        """Test that a faulty callback does not crash the latch."""
        def bad_callback(latch_id):
            raise ValueError("Callback error")
        latch = SignalLatch(signal_callback=bad_callback)
        try:
            latch.closed(timeout=0.01)
        except Exception as e:
            self.fail(f"wait() raised an unexpected exception: {e}")
        self.assertFalse(latch.is_open())

    def test_open_releases_waiting_threads(self):
        """Test that open() releases all waiting threads."""
        latch = SignalLatch()
        count = 5
        threads = []
        events = [threading.Event() for _ in range(count)]
        for i in range(count):
            def worker(idx=i):
                latch.closed()
                events[idx].set()
            t = threading.Thread(target=worker)
            threads.append(t)
            t.start()
        time.sleep(0.1)
        latch.open()
        for i in range(count):
            self.assertTrue(events[i].wait(timeout=0.5))
        for t in threads:
            t.join()
        self.assertTrue(latch.is_open())

    def test_reset_closes_latch(self):
        """Test that reset() closes an open latch and makes it block again."""
        latch = SignalLatch()
        latch.open()
        self.assertTrue(latch.is_open())
        latch.reset()
        self.assertFalse(latch.is_open())

        # Verify it blocks again
        thread_finished = threading.Event()
        def worker():
            latch.closed()
            thread_finished.set()
        thread = threading.Thread(target=worker)
        thread.start()
        time.sleep(0.05)
        self.assertFalse(thread_finished.is_set())
        latch.open()
        thread.join()

    def test_dispose_releases_waiting_threads(self):
        """Test that dispose() unblocks waiting threads."""
        latch = SignalLatch()
        thread_finished = threading.Event()
        def worker():
            latch.closed()
            thread_finished.set()
        thread = threading.Thread(target=worker)
        thread.start()
        time.sleep(0.05)
        self.assertFalse(thread_finished.is_set())
        latch.dispose()
        self.assertTrue(thread_finished.wait(timeout=0.5))
        thread.join()
        self.assertTrue(latch.is_open())

    def test_dispose_clears_references(self):
        """Test that dispose() clears internal references."""
        latch = SignalLatch(
            signal_callback=self.mock_signal_callback,
            controller=self.mock_controller
        )
        latch.dispose()
        self.assertIsNone(latch._signal_callback)
        self.assertIsNone(latch._controller)

    def test_wait_does_not_signal_if_already_open(self):
        """Verify wait() does not signal if the latch is already open."""
        latch = SignalLatch(
            signal_callback=self.mock_signal_callback,
            controller=self.mock_controller
        )
        latch.open()
        latch.closed(timeout=0.01)
        self.assertFalse(self.mock_signal_callback_called)

    def test_race_condition_open_during_wait_call(self):
        """Test for race condition where open() is called concurrently with wait()."""
        latch = SignalLatch()
        ready_to_open = threading.Event()
        ready_to_wait = threading.Event()
        thread_finished = threading.Event()
        def worker():
            ready_to_open.set()
            ready_to_wait.wait(timeout=0.5)
            latch.closed()
            thread_finished.set()
        thread = threading.Thread(target=worker)
        thread.start()
        self.assertTrue(ready_to_open.wait(timeout=0.5))
        ready_to_wait.set()
        latch.open()
        self.assertTrue(thread_finished.wait(timeout=0.5))
        thread.join()
        self.assertTrue(latch.is_open())

if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)