import threading
import time
import unittest
from unittest.mock import Mock
from ulid import ULID

from thread_factory import ConcurrentList, ConcurrentSet
from thread_factory.runtime.orchestrator.monitoring.records.records import WorkStatus, Record
from thread_factory.agentic_thread_pool.help_request.help_request import HelpRequest


class TestValueWork(unittest.TestCase):

    def setUp(self):
        """Set up before each test."""
        self.was_called = False

        # Callable that toggles flag so we can assert it was called
        def sample_callable():
            self.was_called = True

        self.sample_callable = sample_callable
        self.value_work = HelpRequest(work_callable=self.sample_callable)

    def test_initialization(self):
        """Test initialization of ValueWork."""
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
        self.value_work.mark_in_progress()
        self.value_work.mark_completed()
        self.assertEqual(self.value_work.get_state(), WorkStatus.COMPLETED)
        self.assertEqual(self.value_work.record.status, WorkStatus.COMPLETED)
        self.assertIsNotNone(self.value_work.record.timestamp_completion_time)

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
        self.assertIsNotNone(self.value_work.record)

    def test_reset(self):
        """Test resetting the task back to PENDING."""
        self.value_work.mark_in_progress()
        self.value_work.reset()
        self.assertEqual(self.value_work.get_state(), WorkStatus.PENDING)
        self.assertEqual(self.value_work.record.status, WorkStatus.PENDING)

    def test_dispose(self):
        """Test the dispose functionality."""
        self.value_work.mark_completed()
        self.value_work.dispose()
        self.assertTrue(self.value_work._disposed)
        self.assertIsNone(self.value_work._work_callable)
        self.assertIsNone(self.value_work.record)

    def test_bind_value_work_sets_thread_context(self):
        """Test that bind_value_work sets _value_work on the current thread."""
        thread = threading.current_thread()
        thread._worker_type = "agentic"
        thread._factory_id = ULID()

        self.value_work.bind_value_work()
        self.assertTrue(hasattr(thread, '_value_work'))
        self.assertIs(thread._value_work, self.value_work)

    def test_bind_value_work_invokes_callable(self):
        """Test that bind_value_work invokes the callable and sets 'called'."""
        thread = threading.current_thread()
        thread._worker_type = "agentic"
        thread._factory_id = ULID()

        result = {}

        def sample_callable():
            hr = threading.current_thread()._value_work
            assert isinstance(hr, HelpRequest)
            result["called"] = True

        value_work = HelpRequest(work_callable=sample_callable)
        value_work.bind_value_work()

        self.assertTrue(result.get("called", False))

    def test_bind_value_work_promotes_factory_id_to_list(self):
        """
        Calling `bind_value_work` from two threads with different factory_ids should
        promote the record.factory_id from ULID to ConcurrentList.
        """
        result = {}

        def test_callable():
            result["called"] = True

        help_request = HelpRequest(work_callable=test_callable)

        # Simulate first thread
        thread1 = threading.current_thread()
        thread1._worker_type = "agentic"
        thread1._factory_id = ULID()
        help_request.bind_value_work()

        # At this point, should still be a ULID
        self.assertIsInstance(help_request.record.factory_id, ULID)

        # Simulate second thread
        class DummyThread:
            _worker_type = "agentic"
            _factory_id = ULID()

        original_thread = threading.current_thread
        try:
            threading.current_thread = lambda: DummyThread
            help_request.reset()  # Reset to allow second call
            help_request.bind_value_work()
        finally:
            threading.current_thread = original_thread  # Restore

        # Now, factory_id should be a ConcurrentList with 2 entries
        factory_id = help_request.record.factory_id
        self.assertIsInstance(factory_id, ConcurrentSet)
        self.assertEqual(len(factory_id), 2)

    def test_bind_value_work_raises_without_worker_type(self):
        """Test that bind_value_work raises if thread lacks _worker_type."""
        thread = threading.current_thread()
        if hasattr(thread, '_worker_type'):
            del thread._worker_type

        with self.assertRaises(RuntimeError) as context:
            self.value_work.bind_value_work()

        self.assertIn("not properly initialized as an AgenticWorker", str(context.exception))

    def test_cancel_job(self):
        """Test cancelling the job locally."""
        self.value_work.cancel_job()
        self.assertEqual(self.value_work.get_state(), WorkStatus.CANCELLED)
        self.assertEqual(self.value_work.record.status, WorkStatus.CANCELLED)
        self.assertIsNotNone(self.value_work.record)

    def test_cancel_after_complete(self):
        """Test cancelling a completed task should not work."""
        self.value_work.mark_in_progress()
        self.value_work.mark_completed()
        self.value_work.cancel_job()

        self.assertEqual(self.value_work.get_state(), WorkStatus.COMPLETED)
        self.assertEqual(self.value_work.record.status, WorkStatus.COMPLETED)
        self.assertIsNotNone(self.value_work.record)


if __name__ == '__main__':
    unittest.main()
