import unittest
from unittest.mock import Mock, patch
import threading
from datetime import datetime
from thread_factory.runtime import WorkerState
from thread_factory.runtime.orchestrator.monitoring.records.records import WorkStatus
from thread_factory.agent_thread_pool.agentic_worker.agentic_worker import AgenticWorker
from thread_factory.agent_thread_pool.help_request.help_request import HelpRequest
from ulid import ULID


class TestDynamicWorker(unittest.TestCase):

    def setUp(self):
        """Set up before each test."""
        # Initialize DynamicWorker with the factory_id explicitly defined
        self.worker = AgenticWorker(factory_id="worker1", factory=None)
        self.mock_value_work = Mock(spec=HelpRequest)

        # Mock the record attribute and its getter method to return it
        self.mock_value_work.record = Mock()
        self.mock_value_work.get_record.return_value = self.mock_value_work.record  # <-- This line is crucial

        # Set the return value for get_state
        self.mock_value_work.get_state.return_value = WorkStatus.PENDING

    def test_register_save_point(self):
        """Test registering a save point and its functionality."""
        save_point_name = "checkpoint"
        save_point_func = Mock()

        # Register save point
        self.worker.register_save_point(save_point_name, save_point_func)
        self.assertIn(save_point_name, self.worker.save_points)

        # Call the registered save point function
        self.worker.save_points[save_point_name]()
        save_point_func.assert_called_once()

    def test_register_location(self):
        """Test registering a location and its functionality."""
        location_name = "location1"
        location_func = Mock()

        # Register location
        self.worker.register_location(location_name, location_func)
        self.assertIn(location_name, self.worker.locations)

        # Call the registered location function
        self.worker.locations[location_name]()
        location_func.assert_called_once()

    def test_run_with_home_set(self):
        """Test running the worker when home function is set."""
        home_func = Mock()
        self.worker.set_home(home_func)

        # Start the worker in a separate thread
        thread = threading.Thread(target=self.worker.run)
        thread.start()

        # Allow some time for the thread to execute
        threading.Event().wait(0.1)

        # Check that home() was called
        home_func.assert_called()

        # Stop the worker gracefully
        self.worker.stop()
        thread.join()  # Ensure the thread has finished

    def test_run_without_home_set(self):
        """Test running the worker without a home function set."""
        with self.assertRaises(RuntimeError):
            self.worker.run()

    def test_stop(self):
        """Test stopping the worker."""
        self.worker.stop()
        self.assertTrue(self.worker.shutdown_flag.is_set())

    def test_dispose(self):
        """Test disposing the worker."""
        self.worker.dispose()
        self.assertTrue(self.worker._disposed)
        self.assertIsNone(self.worker.save_points)
        self.assertIsNone(self.worker.locations)
        self.assertIsNone(self.worker._event_loop)

    def test_dynamic_worker_repr(self):
        """Test the string representation of the worker."""
        self.worker.state = WorkerState.STARTING
        repr_str = repr(self.worker)
        self.assertIn("AgenticWorker", repr_str)
        self.assertIn("worker1", repr_str)
        self.assertIn("STARTING", repr_str)

    def test_worker_thread_lifecycle(self):
        """Test full worker lifecycle: start, run, stop, dispose."""
        self.worker.set_home(Mock())
        thread = threading.Thread(target=self.worker.run)

        # Start the worker
        thread.start()

        # Wait a bit and stop the worker
        threading.Event().wait(0.1)
        self.worker.stop()

        # Ensure the thread stops properly and exits gracefully
        thread.join()

        # Now, dispose of the worker and check for proper cleanup
        self.worker.dispose()
        self.assertTrue(self.worker.disposed)
        self.assertEqual(self.worker.state, WorkerState.DISPOSED)

    # --- New tests for ValueWork integration ---

    def test_bind_value_work(self):
        """Test binding a ValueWork instance to the worker."""
        # Directly set the _value_work attribute since there's no public method to bind it
        # This is a bit of a workaround, but it's how the DynamicWorker is designed to work
        self.worker._value_work = self.mock_value_work
        self.assertIs(self.worker._value_work, self.mock_value_work)

    def test_set_work_state(self):
        """Test setting the state of the bound ValueWork."""
        self.worker._value_work = self.mock_value_work
        self.worker.set_work_state(WorkStatus.IN_PROGRESS)
        self.mock_value_work.set_state.assert_called_once_with(WorkStatus.IN_PROGRESS)

    def test_get_work_state(self):
        """Test getting the state of the bound ValueWork."""
        self.worker._value_work = self.mock_value_work
        state = self.worker.get_work_state()
        self.assertEqual(state, WorkStatus.PENDING)
        self.mock_value_work.get_state.assert_called_once()

    def test_mark_work_in_progress(self):
        """Test marking the bound ValueWork as 'in progress'."""
        self.worker._value_work = self.mock_value_work
        self.worker.mark_work_in_progress()
        self.mock_value_work.mark_in_progress.assert_called_once()

    def test_mark_work_completed(self):
        """Test marking the bound ValueWork as 'completed'."""
        self.worker._value_work = self.mock_value_work
        self.worker.mark_work_completed()
        self.mock_value_work.mark_completed.assert_called_once()

    def test_mark_work_failed(self):
        """Test marking the bound ValueWork as 'failed'."""
        self.worker._value_work = self.mock_value_work
        self.worker.mark_work_failed()
        self.mock_value_work.mark_failed.assert_called_once()

    def test_mark_work_cancelled(self):
        """Test marking the bound ValueWork as 'cancelled'."""
        self.worker._value_work = self.mock_value_work
        self.worker.mark_work_cancelled()
        self.mock_value_work.mark_cancelled.assert_called_once()

    def test_reset_work(self):
        """Test resetting the bound ValueWork."""
        self.worker._value_work = self.mock_value_work
        self.worker.reset_work()
        self.mock_value_work.reset.assert_called_once()

    def test_get_work_record(self):
        """Test getting the record from the bound ValueWork."""
        self.worker._value_work = self.mock_value_work
        record = self.worker.get_work_record()
        self.assertIs(record, self.mock_value_work.record)
        self.mock_value_work.get_record.assert_called_once()

    def test_acquire_and_run_work(self):
        """Test acquiring and running the bound ValueWork."""
        self.worker._value_work = self.mock_value_work
        self.worker.acquire_and_run_work()
        self.mock_value_work.acquire_work.assert_called_once()

    def test_cancel_bound_job(self):
        """Test canceling the bound ValueWork job."""
        self.worker._value_work = self.mock_value_work
        self.worker.cancel_bound_job()
        self.mock_value_work.cancel_job.assert_called_once()

    def test_dispose_work(self):
        """Test disposing of the bound ValueWork."""
        self.worker._value_work = self.mock_value_work
        self.worker.dispose_work()
        self.mock_value_work.dispose.assert_called_once()
        self.assertIsNone(self.worker._value_work)

    def test_multiple_thread_disposal(self):
        """Test that multiple worker threads can be started and disposed of."""
        workers = []
        threads = []
        num_workers = 5

        # Create and start multiple workers in threads
        for i in range(num_workers):
            worker = AgenticWorker(factory_id=f"worker_{i}", factory=None)
            worker.set_home(Mock())
            thread = threading.Thread(target=worker.run)
            thread.start()
            workers.append(worker)
            threads.append(thread)

        # Allow some time for threads to start
        threading.Event().wait(0.2)

        # Stop all workers and join their threads
        for worker in workers:
            worker.stop()
        for thread in threads:
            thread.join()
            self.assertFalse(thread.is_alive())  # Ensure thread is no longer alive

        # Dispose of all workers and check their state
        for worker in workers:
            worker.dispose()
            self.assertTrue(worker.disposed)
            self.assertEqual(worker.state, WorkerState.DISPOSED)


if __name__ == "__main__":
    unittest.main()