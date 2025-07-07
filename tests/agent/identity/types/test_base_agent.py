import unittest
import time
from datetime import datetime, timedelta
from thread_factory.concurrency.concurrent_queue import ConcurrentQueue
from thread_factory.agent.identity.types.base_agent import AgentState, BaseAgent
from thread_factory.agent.thread_pool.records import WorkStatus
from thread_factory.agent.thread_pool.work import Work  # This should be the corrected Work class above

def sample_work_function():
    """A simple function to simulate work."""
    time.sleep(0.001)
    return "work_done"

def failing_work_function():
    """A function that simulates work failure."""
    raise ValueError("Simulated work error")

class TestWorker(unittest.TestCase):

    def setUp(self):
        self.mock_work_queue = ConcurrentQueue()
        self.worker = BaseAgent(work_queue=self.mock_work_queue)
        self.worker._last_hourly_reset = datetime.now()

    def tearDown(self):
        if self.worker and not self.worker.is_disposed:
            if self.worker.is_alive():
                self.worker.stop()
                self.worker.join(timeout=1)
            self.worker.dispose()

    def _start_worker(self):
        self.worker.start()
        timeout = time.time() + 1
        while self.worker.state == AgentState.CREATED and time.time() < timeout:
            time.sleep(0.01)
        self.assertNotEqual(self.worker.state, AgentState.CREATED)
        time.sleep(0.05)

    def test_worker_initialization(self):
        self.assertEqual(self.worker.state, AgentState.CREATED)
        self.assertFalse(self.worker.shutdown_flag.is_set())
        self.assertFalse(self.worker.death_event.is_set())
        self.assertEqual(len(self.worker.records), 0)
        self.assertIsNone(self.worker.last_completed_work)
        self.assertEqual(self.worker.availability, 0.0)
        self.assertEqual(self.worker.units_per_minute, 0)
        self.assertEqual(self.worker.units_per_hour, [])
        self.assertEqual(self.worker.work_unit_counter, 0)
        self.assertIsNotNone(self.worker.start_time)
        self.assertFalse(self.worker.is_disposed)
        self.assertIsNotNone(self.worker._last_hourly_reset)

    def test_worker_starts_and_becomes_blocked(self):
        self._start_worker()
        time.sleep(0.1)
        self.assertEqual(self.worker.state, AgentState.BLOCKED)

    def test_worker_executes_single_task_successfully(self):
        work_instance = Work(fn=sample_work_function)
        self.mock_work_queue.enqueue(work_instance)
        self._start_worker()

        timeout = time.time() + 1
        while len(self.worker.records) == 0 and time.time() < timeout:
            time.sleep(0.01)

        self.assertEqual(len(self.worker.records), 1)
        first_record = next(iter(self.worker.records.records.values()))
        self.assertEqual(first_record.status, WorkStatus.COMPLETED)
        self.assertEqual(self.worker.last_completed_work, first_record)
        self.assertEqual(self.worker.units_per_minute, 1)
        self.assertEqual(self.worker.work_unit_counter, 1)
        self.assertGreater(self.worker.availability, 0)
        self.assertEqual(self.worker.state, AgentState.BLOCKED)

    def test_worker_handles_task_failure(self):
        work_instance = Work(fn=failing_work_function)
        self.mock_work_queue.enqueue(work_instance)
        self._start_worker()

        timeout = time.time() + 1
        while len(self.worker.records) == 0 and time.time() < timeout:
            time.sleep(0.01)

        self.assertEqual(len(self.worker.records), 1)
        first_record = next(iter(self.worker.records.records.values()))
        self.assertEqual(first_record.status, WorkStatus.FAILED)
        self.assertEqual(self.worker.units_per_minute, 1)
        self.assertEqual(self.worker.work_unit_counter, 1)
        self.assertEqual(self.worker.state, AgentState.BLOCKED)

    def test_worker_graceful_shutdown(self):
        self._start_worker()
        time.sleep(0.1)
        self.assertEqual(self.worker.state, AgentState.BLOCKED)

        # Stop the worker and immediately check flags BEFORE join()
        self.worker.stop()
        self.assertIsNotNone(self.worker.shutdown_flag)
        self.assertIsNotNone(self.worker.death_event)
        self.assertTrue(self.worker.shutdown_flag.is_set())
        self.assertFalse(self.worker.death_event.is_set())  # Not set yet until run() exits

        self.worker.join(timeout=1)

        # Now the worker has run dispose() internally
        self.assertFalse(self.worker.is_alive())
        self.assertTrue(self.worker.is_disposed)
        self.assertEqual(self.worker.state, AgentState.DISPOSED)
        self.assertIsNone(self.worker.shutdown_flag)
        self.assertIsNone(self.worker.death_event)

    def test_worker_disposal(self):
        self._start_worker()
        time.sleep(0.1)

        # Stop and join before calling dispose to ensure thread exits gracefully
        self.worker.stop()
        self.worker.join(timeout=1)

        self.worker.dispose()

        self.assertTrue(self.worker.is_disposed)
        self.assertEqual(self.worker.state, AgentState.DISPOSED)
        self.assertIsNone(self.worker.shutdown_flag)
        self.assertIsNone(self.worker.death_event)

    def test_worker_metrics_update(self):
        num_tasks = 5
        for _ in range(num_tasks):
            work_instance = Work(fn=sample_work_function)
            self.mock_work_queue.enqueue(work_instance)
        self._start_worker()

        timeout = time.time() + 2
        while len(self.worker.records) < num_tasks and time.time() < timeout:
            time.sleep(0.01)

        self.assertEqual(self.worker.units_per_minute, num_tasks)
        self.assertEqual(self.worker.work_unit_counter, num_tasks)
        self.assertAlmostEqual(self.worker.availability, num_tasks / 60.0, places=5)
        self.assertEqual(self.worker.state, AgentState.BLOCKED)

    def test_worker_hourly_metrics_reset(self):
        tasks_in_first_hour = 10

        for _ in range(tasks_in_first_hour):
            self.mock_work_queue.enqueue(Work(fn=sample_work_function))

        self._start_worker()

        timeout = time.time() + 2
        while self.worker.units_per_minute < tasks_in_first_hour and time.time() < timeout:
            time.sleep(0.01)

        self.worker._last_hourly_reset -= timedelta(hours=1, seconds=1)
        self.worker._check_and_reset_hourly_metrics()

        self.assertEqual(len(self.worker.units_per_hour), 1)
        self.assertEqual(self.worker.units_per_hour[0], tasks_in_first_hour)
        self.assertEqual(self.worker.units_per_minute, 0)

        self.worker._last_hourly_reset -= timedelta(hours=1, seconds=1)
        self.mock_work_queue.enqueue(Work(fn=sample_work_function))
        timeout = time.time() + 1
        while self.worker.units_per_minute == 0 and time.time() < timeout:
            time.sleep(0.01)

        self.worker._check_and_reset_hourly_metrics()

        self.assertEqual(len(self.worker.units_per_hour), 2)
        self.assertEqual(self.worker.units_per_hour[1], 1)
        self.assertEqual(self.worker.units_per_minute, 0)
        self.assertEqual(self.worker.work_unit_counter, tasks_in_first_hour + 1)

    def test_worker_remains_blocked_with_empty_queue(self):
        self._start_worker()
        time.sleep(0.5)
        self.assertEqual(self.worker.state, AgentState.BLOCKED)
        self.assertEqual(len(self.mock_work_queue), 0)
        self.assertEqual(self.worker.work_unit_counter, 0)

    @unittest.skip("Hard kill test is problematic for unit testing due to OS-level thread termination.")
    def test_worker_hard_kill(self):
        self._start_worker()
        time.sleep(0.1)

        try:
            self.worker.hard_kill()
        except (ValueError, SystemError) as e:
            self.fail(f"Hard kill failed: {e}")

        self.worker.join(timeout=1)
        self.assertFalse(self.worker.is_alive())
        self.assertEqual(self.worker.state, AgentState.KILLED)

if __name__ == '__main__':
    unittest.main()
