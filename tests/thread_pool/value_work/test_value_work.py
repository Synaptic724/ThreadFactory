import unittest
from datetime import datetime
from unittest.mock import Mock
from ulid import ULID
from thread_factory.runtime.orchestrator.monitoring.records.records import WorkStatus, Record
from thread_factory.thread_pool.value_work.value_work import ValueWork

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

    def test_task_execution(self):
        """Test that the task executes and marks as completed."""
        self.value_work.wrap_callable(self.mock_callable)

        self.mock_callable.reset_mock()  # Reset any previous calls to the mock
        self.value_work.acquire_work()  # Trigger the task execution

        self.mock_callable.assert_called_once_with(self.value_work)
        self.assertEqual(self.value_work.get_state(), WorkStatus.COMPLETED)
        # Record should still exist here, disposal only happens in `test_dispose`
        self.assertIsNotNone(self.value_work.record)  # Record should not be nulled out in execution tests

    def test_task_execution_with_exception(self):
        """Test task execution with an exception."""
        self.mock_callable.side_effect = Exception("Test error")
        self.value_work.wrap_callable(self.mock_callable)

        self.value_work.acquire_work()

        self.assertEqual(self.value_work.get_state(), WorkStatus.FAILED)
        self.mock_callable.assert_called_once_with(self.value_work)

        # Record should still exist after failure
        self.assertIsNotNone(self.value_work.record)  # Record should not be nulled out in failure tests

    def test_dispose(self):
        """Test the dispose functionality."""
        self.value_work.mark_completed()  # Ensure it's in a state where dispose actually clears references
        self.value_work.dispose()  # Explicit dispose call

        self.assertTrue(self.value_work._disposed)
        self.assertIsNone(self.value_work._work_callable)
        self.assertIsNone(self.value_work.record)

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
