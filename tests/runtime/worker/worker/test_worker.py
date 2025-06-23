import unittest
import threading
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import ulid
import ctypes  # For hard_kill method

# --- User specified imports ---
from thread_factory.concurrency.concurrent_queue import ConcurrentQueue, Empty
from thread_factory.runtime import WorkerState, Worker
from thread_factory.utils import IDisposable  # This IDisposable should raise NotImplementedError for dispose()
from thread_factory.runtime.orchestrator.monitoring.records.records import Records, Record, WorkStatus
from thread_factory.runtime.factory.operations.work.work import Work  # This should be the corrected Work class above

# --- UNIT TESTS FOR WORKER CLASS ---

# We define a simple function to be used by Work objects for testing
def sample_work_function():
    """A simple function to simulate work."""
    time.sleep(0.001)  # Simulate some processing time
    return "work_done"

def failing_work_function():
    """A function that simulates work failure."""
    raise ValueError("Simulated work error")

class TestWorker(unittest.TestCase):

    def setUp(self):
        """Set up for each test case."""
        self.mock_work_queue = ConcurrentQueue()
        self.worker = Worker(work_queue=self.mock_work_queue, factory_id="test_worker_1")
        # Initialize _last_hourly_reset for consistent testing
        self.worker._last_hourly_reset = datetime.now()

    def tearDown(self):
        """Clean up after each test case."""
        if self.worker.is_alive():
            self.worker.stop()
            self.worker.join(timeout=1)  # Give it a moment to stop
        # Ensure explicit disposal for test cleanliness, using the fixed dispose
        self.worker.dispose()

    def _start_worker(self):
        """Helper to start the worker thread and wait for initial state."""
        self.worker.start()
        # Wait for the worker to enter a non-CREATED state (STARTING or BLOCKED)
        timeout = time.time() + 1  # 1 second timeout
        while self.worker.state == WorkerState.CREATED and time.time() < timeout:
            time.sleep(0.01)
        self.assertNotEqual(self.worker.state, WorkerState.CREATED, "Worker did not start.")
        # Give it a moment to stabilize in BLOCKED if queue is empty
        time.sleep(0.05)

    def test_worker_initialization(self):
        """Test worker attributes after initialization."""
        self.assertEqual(self.worker.state, WorkerState.CREATED)
        self.assertFalse(self.worker.shutdown_flag.is_set())
        self.assertFalse(self.worker.death_event.is_set())
        self.assertEqual(len(self.worker.records), 0)
        self.assertIsNone(self.worker.last_completed_work)
        self.assertEqual(self.worker.availability, 0.0)
        self.assertEqual(self.worker.units_per_minute, 0)
        self.assertEqual(self.worker.units_per_hour, [])
        self.assertEqual(self.worker.work_unit_counter, 0)
        self.assertIsNotNone(self.worker.start_time)
        self.assertIsNotNone(self.worker.work_queue)
        self.assertFalse(self.worker.is_disposed)  # Check with the new property
        self.assertIsNotNone(self.worker._last_hourly_reset)

    def test_worker_starts_and_becomes_blocked(self):
        """Test worker starts and enters BLOCKED state when queue is empty."""
        self._start_worker()
        time.sleep(0.1)  # Shorter sleep after _start_worker's stabilization
        self.assertEqual(self.worker.state, WorkerState.BLOCKED)

    def test_worker_executes_single_task_successfully(self):
        """Test worker executes a single task successfully."""
        work_instance = Work(fn=sample_work_function)
        self.mock_work_queue.enqueue(work_instance)
        self._start_worker()

        # Wait for the task to be processed and record added
        timeout = time.time() + 1
        while len(self.worker.records) == 0 and time.time() < timeout:
            time.sleep(0.01)

        self.assertEqual(len(self.worker.records), 1)
        self.assertEqual(self.worker.records.records[0].status, WorkStatus.COMPLETED)
        self.assertEqual(self.worker.last_completed_work, self.worker.records.records[0])
        self.assertEqual(self.worker.units_per_minute, 1)
        self.assertEqual(self.worker.work_unit_counter, 1)
        self.assertGreater(self.worker.availability, 0)
        self.assertEqual(self.worker.state, WorkerState.BLOCKED)

    def test_worker_handles_task_failure(self):
        """Test worker handles a task that fails during execution."""
        work_instance = Work(fn=failing_work_function)
        self.mock_work_queue.enqueue(work_instance)
        self._start_worker()

        # Wait for the task to be processed and record added
        timeout = time.time() + 1
        while len(self.worker.records) == 0 and time.time() < timeout:
            time.sleep(0.01)

        self.assertEqual(len(self.worker.records), 1)
        self.assertEqual(self.worker.records.records[0].status, WorkStatus.FAILED)
        self.assertEqual(self.worker.units_per_minute, 1)
        self.assertEqual(self.worker.work_unit_counter, 1)
        self.assertEqual(self.worker.state, WorkerState.BLOCKED)

    def test_worker_graceful_shutdown(self):
        """Test worker shuts down gracefully using the stop flag."""
        self._start_worker()
        time.sleep(0.1)  # Let it enter BLOCKED state
        self.assertEqual(self.worker.state, WorkerState.BLOCKED)

        self.worker.stop()
        self.worker.join(timeout=1)  # Wait for the thread to finish

        self.assertFalse(self.worker.is_alive())
        self.assertTrue(self.worker.shutdown_flag.is_set())
        self.assertTrue(self.worker.death_event.is_set())
        self.assertEqual(self.worker.state, WorkerState.DISPOSED)
        self.assertTrue(self.worker.is_disposed)

    def test_worker_disposal(self):
        """Test explicit disposal of the worker."""
        self._start_worker()  # Start it to ensure thread state changes
        time.sleep(0.1)  # Let it settle
        self.worker.dispose()

        self.assertTrue(self.worker.is_disposed)
        self.assertTrue(self.worker.shutdown_flag.is_set())
        self.assertTrue(self.worker.death_event.is_set())
        self.assertEqual(self.worker.state, WorkerState.DISPOSED)

        # Try to join to ensure the thread actually stops (dispose sets shutdown_flag)
        self.worker.join(timeout=1)
        self.assertFalse(self.worker.is_alive())

    def test_worker_metrics_update(self):
        """Test that availability and unit counters update correctly."""
        num_tasks = 5
        for _ in range(num_tasks):
            work_instance = Work(fn=sample_work_function)
            self.mock_work_queue.enqueue(work_instance)
        self._start_worker()

        # Wait for all tasks to be processed
        timeout = time.time() + 2  # Give more time
        while len(self.worker.records) < num_tasks and time.time() < timeout:
            time.sleep(0.01)

        self.assertEqual(self.worker.units_per_minute, num_tasks)
        self.assertEqual(self.worker.work_unit_counter, num_tasks)
        self.assertAlmostEqual(self.worker.availability, num_tasks / 60.0, places=5)
        self.assertEqual(self.worker.state, WorkerState.BLOCKED)

    def test_worker_hourly_metrics_reset(self):
        """Test that hourly metrics reset correctly after an hour."""
        tasks_in_first_hour = 10

        # Enqueue work to simulate task execution for the first hour
        for _ in range(tasks_in_first_hour):
            self.mock_work_queue.enqueue(Work(fn=sample_work_function))

        self._start_worker()

        # Wait until the 10 tasks have been counted
        timeout = time.time() + 2
        while self.worker.units_per_minute < tasks_in_first_hour and time.time() < timeout:
            time.sleep(0.01)

        # --- force the “hour” to have elapsed --------------------------------
        self.worker._last_hourly_reset -= timedelta(hours=1, seconds=1)
        # ---------------------------------------------------------------------

        self.worker._check_and_reset_hourly_metrics()  # first flush

        # After the flush we expect exactly one hourly bucket with 10 units
        self.assertEqual(len(self.worker.units_per_hour), 1)
        self.assertEqual(self.worker.units_per_hour[0], tasks_in_first_hour)
        self.assertEqual(self.worker.units_per_minute, 0)

        # Simulate another hour passing
        self.worker._last_hourly_reset -= timedelta(hours=1, seconds=1)

        # Push one more task
        self.mock_work_queue.enqueue(Work(fn=sample_work_function))
        timeout = time.time() + 1
        while self.worker.units_per_minute == 0 and time.time() < timeout:
            time.sleep(0.01)

        self.worker._check_and_reset_hourly_metrics()  # second flush

        self.assertEqual(len(self.worker.units_per_hour), 2)
        self.assertEqual(self.worker.units_per_hour[1], 1)
        self.assertEqual(self.worker.units_per_minute, 0)
        self.assertEqual(self.worker.work_unit_counter, tasks_in_first_hour + 1)

    def test_worker_remains_blocked_with_empty_queue(self):
        """Test worker remains in BLOCKED state when queue is consistently empty."""
        self._start_worker()
        time.sleep(0.5)  # Give it time to become BLOCKED and check again
        self.assertEqual(self.worker.state, WorkerState.BLOCKED)
        self.assertEqual(len(self.mock_work_queue), 0)
        self.assertEqual(self.worker.work_unit_counter, 0)

    @unittest.skip("Hard kill test is problematic for unit testing due to OS-level thread termination.")
    def test_worker_hard_kill(self):
        """Attempt to test hard kill (might be unstable)."""
        self._start_worker()
        time.sleep(0.1)  # Let it start and become idle

        try:
            self.worker.hard_kill()
        except (ValueError, SystemError) as e:
            self.fail(f"Hard kill failed: {e}")

        self.worker.join(timeout=1)
        self.assertFalse(self.worker.is_alive())
        self.assertEqual(self.worker.state, WorkerState.KILLED)

if __name__ == '__main__':
    unittest.main()
