import unittest
from unittest.mock import Mock
import threading
from datetime import datetime
from thread_factory.runtime import WorkerState
from thread_factory.runtime.orchestrator.monitoring.records.records import WorkStatus
from thread_factory.thread_pool.worker.dynamic_worker import DynamicWorker


class TestDynamicWorker(unittest.TestCase):

    def setUp(self):
        """Set up before each test."""
        # Initialize DynamicWorker with the factory_id explicitly defined
        self.worker = DynamicWorker(factory_id="worker1", factory=None)

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
        self.assertIsNone(self.worker.home)

    def test_dynamic_worker_repr(self):
        """Test the string representation of the worker."""
        self.worker.state = WorkerState.STARTING
        repr_str = repr(self.worker)
        self.assertIn("DynamicWorker", repr_str)
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
        self.assertTrue(self.worker._disposed)
        self.assertEqual(self.worker.state, WorkerState.DISPOSED)


if __name__ == "__main__":
    unittest.main()
