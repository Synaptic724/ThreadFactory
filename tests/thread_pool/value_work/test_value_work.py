import threading
import unittest
from datetime import datetime
from unittest.mock import Mock
from ulid import ULID
from thread_factory.runtime.orchestrator.monitoring.records.records import WorkStatus, Record
from thread_factory.dynamic_thread_pool.value_work.value_work import ValueWork

class TestValueWork(unittest.TestCase):

    def setUp(self):
        """Set up before each test."""
        self.task_id = str(ULID())
        self.mock_callable = Mock()  # Mock work callable
        self.value_work = ValueWork(task_id=self.task_id, work_callable=self.mock_callable)

    def test_initialization(self):
        """Test initialization of ValueWork."""
        self.assertEqual(self.value_work.task_id, self.task_id)
        self.assertEqual(self.value_work.get_state(), WorkStatus.PENDING)
        self.assertIsInstance(self.value_work.record, Record)
        self.assertEqual(self.value_work.record.status, WorkStatus.PENDING)

    def test_mark_in_progress(self):
        """Test marking the task as in progress."""
        self.value_work.mark_in_progress()
        self.assertEqual(self.value_work.get_state(), WorkStatus.IN_PROGRESS)
        self.assertEqual(self.value_work.record.status, WorkStatus.IN_PROGRESS)

    def test_mark_completed(self):
        """Test marking the task as completed."""
        self.value_work.mark_in_progress()  # Mark in progress first
        self.value_work.mark_completed()  # Mark as completed
        self.assertEqual(self.value_work.get_state(), WorkStatus.COMPLETED)
        self.assertEqual(self.value_work.record.status, WorkStatus.COMPLETED)
        self.assertIsNotNone(self.value_work.record.timestamp_completion_time)  # Check completion time
        # Record should be nulled out only when dispose() is explicitly called
        self.assertIsNotNone(self.value_work.record)  # Do not null it out here.

    def test_mark_failed(self):
        """Test marking the task as failed."""
        self.value_work.mark_failed()
        self.assertEqual(self.value_work.get_state(), WorkStatus.FAILED)
        self.assertEqual(self.value_work.record.status, WorkStatus.FAILED)

    def test_mark_cancelled(self):
        """Test marking the task as cancelled."""
        self.value_work.mark_cancelled()
        self.assertEqual(self.value_work.get_state(), WorkStatus.CANCELLED)
        self.assertEqual(self.value_work.record.status, WorkStatus.CANCELLED)

        # Check that the record is not null here, it will be nulled when dispose() is explicitly called
        self.assertIsNotNone(self.value_work.record)

    def test_reset(self):
        """Test resetting the task back to PENDING."""
        self.value_work.mark_in_progress()  # Mark as in progress
        self.value_work.reset()  # Reset to PENDING
        self.assertEqual(self.value_work.get_state(), WorkStatus.PENDING)
        self.assertEqual(self.value_work.record.status, WorkStatus.PENDING)

    def test_dispose(self):
        """Test the dispose functionality."""
        self.value_work.mark_completed()  # Ensure it's in a state where dispose actually clears references
        self.value_work.dispose()  # Explicit dispose call

        self.assertTrue(self.value_work._disposed)
        self.assertIsNone(self.value_work._work_callable)
        self.assertIsNone(self.value_work.record)

    def test_bind_value_work_sets_thread_context(self):
        """Test that bind_value_work sets _value_work on the current thread."""
        thread = threading.current_thread()
        thread._worker_type = "dynamic"  # Simulate valid thread setup

        self.value_work.bind_value_work()

        self.assertTrue(hasattr(thread, '_value_work'))
        self.assertIs(thread._value_work, self.value_work)

    def test_bind_value_work_invokes_callable(self):
        """Test that bind_value_work invokes the _work_callable."""
        thread = threading.current_thread()
        thread._worker_type = "dynamic"

        self.value_work.bind_value_work()

        self.mock_callable.assert_called_once()

    def test_bind_value_work_raises_without_worker_type(self):
        """Test that bind_value_work raises if thread lacks _worker_type."""
        thread = threading.current_thread()
        if hasattr(thread, '_worker_type'):
            del thread._worker_type  # Ensure _worker_type is missing

        with self.assertRaises(RuntimeError) as context:
            self.value_work.bind_value_work()

        self.assertIn("Thread does not have a factory_id", str(context.exception))

    def test_cancel_job(self):
        """Test cancelling the job locally."""
        self.value_work.cancel_job()
        self.assertEqual(self.value_work.get_state(), WorkStatus.CANCELLED)
        self.assertEqual(self.value_work.record.status, WorkStatus.CANCELLED)

        # Check that the record is not null here, it will be nulled when dispose() is explicitly called
        self.assertIsNotNone(self.value_work.record)

    def test_cancel_after_complete(self):
        """Test cancelling a completed task should not work."""
        # Mark task as in progress, then complete it
        self.value_work.mark_in_progress()  # Mark as in progress
        self.value_work.mark_completed()  # Mark as completed

        # Attempt to cancel after completion
        self.value_work.cancel_job()

        # Ensure the state does not change to CANCELLED
        self.assertEqual(self.value_work.get_state(), WorkStatus.COMPLETED,
                         "State should remain COMPLETED after cancellation attempt.")

        # Ensure the record status remains COMPLETED
        self.assertEqual(self.value_work.record.status, WorkStatus.COMPLETED,
                         "Record status should remain COMPLETED after cancellation attempt.")

        # Ensure the record is still valid, should not be nulled
        self.assertIsNotNone(self.value_work.record, "Record should not be nulled after completion.")


if __name__ == '__main__':
    unittest.main()
