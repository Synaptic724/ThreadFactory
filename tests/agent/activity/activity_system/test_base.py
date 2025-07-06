import unittest
import time
import logging
import threading
from unittest.mock import MagicMock, patch

# Assuming the following imports are correct based on your project structure
from thread_factory.agent.activity.base import BaseActivity, ActivityStatus
from thread_factory.agent.activity.job import JobActivity
from thread_factory.synchronization.controllers.signal_controller import SignalController
from thread_factory.agent.identity.types.agent import Agent

# Suppress all logging below CRITICAL for cleaner test output
logging.disable(logging.CRITICAL)


# --- Test Helper Classes ---

class DummyAgent(Agent):
    """A minimal Agent for testing purposes that doesn't require a full CommandCenter."""

    def __init__(self, *args, **kwargs):
        if 'command_center' not in kwargs:
            kwargs['command_center'] = MagicMock()
        super().__init__(*args, **kwargs)

    def deploy(self):
        # Mock the deploy method to avoid starting a real thread.
        pass


class DummyActivity(BaseActivity):
    """A minimal, concrete implementation of BaseActivity for testing its core features."""

    def __init__(self, **kwargs):
        # BaseActivity.__init__ only accepts kwargs.
        super().__init__(**kwargs)

    def perform_activity(self):
        # A concrete implementation is required by the ABC.
        pass


# --- Test Suites ---

class TestBaseActivity(unittest.TestCase):
    """
    Tests the core functionality defined in the abstract BaseActivity class,
    using a minimal DummyActivity implementation.
    """

    def setUp(self):
        """Create a fresh SignalController and DummyActivity before each test."""
        self.mock_controller = SignalController()
        self.activity = DummyActivity(signal_controller=self.mock_controller, key1="value1")

    def tearDown(self):
        """Dispose activity and controller after each test."""
        self.activity.dispose()
        self.mock_controller.dispose()

    def test_id_is_set(self):
        """Ensure activity ID is generated and non-empty."""
        self.assertIsNotNone(self.activity.id)
        self.assertIsInstance(self.activity.id, str)

    def test_metadata_is_stored_and_retrievable(self):
        """Test that metadata passed via kwargs is properly stored."""
        self.assertEqual(self.activity.get_metadata()["key1"], "value1")

    def test_dispose_is_idempotent(self):
        """Test that calling dispose multiple times is safe."""
        self.activity.dispose()
        self.activity.dispose()
        self.assertTrue(self.activity._disposed)

    def test_registered_with_signal_controller(self):
        """Ensure activity registers itself with SignalController on init."""
        listed_objects = self.mock_controller.list_objects()
        self.assertTrue(any(obj["id"] == self.activity.id for obj in listed_objects))

    def test_unregisters_on_dispose(self):
        """Ensure activity unregisters from SignalController on dispose."""
        self.activity.dispose()
        listed_objects = self.mock_controller.list_objects()
        self.assertFalse(any(obj["id"] == self.activity.id for obj in listed_objects))

    def test_register_and_unregister_agent_emits_events(self):
        """Test that agent registration and unregistration emit the correct events."""
        events = []

        def on_event(object_id, event_type, data):
            events.append(event_type)

        self.mock_controller.subscribe(self.activity.id, "AGENT_ASSIGNED", on_event)
        self.mock_controller.subscribe(self.activity.id, "AGENT_UNASSIGNED", on_event)

        mock_agent = DummyAgent(factory_id="agent-001")
        self.activity.register_agent(mock_agent)
        self.activity.unregister_agent(mock_agent)

        self.assertIn("AGENT_ASSIGNED", events)
        self.assertIn("AGENT_UNASSIGNED", events)

    def test_get_agent_details_with_thread_context(self):
        """Ensure _get_agent_details returns correct agent based on thread-local factory_id."""
        mock_agent = DummyAgent()
        mock_agent.factory_id = "agent-777"
        self.activity.register_agent(mock_agent)

        threading.current_thread().factory_id = "agent-777"
        try:
            agent = self.activity._get_agent_details()
            self.assertIs(agent, mock_agent)
        finally:
            del threading.current_thread().factory_id


class TestJobActivity(unittest.TestCase):
    """
    Tests the specific implementation and features of the JobActivity class.
    """

    def setUp(self):
        """Set up a JobActivity with required arguments for each test."""
        self.mock_controller = SignalController()
        self.activity = JobActivity(
            job_id="job-1",
            task_id="task-1",
            signal_controller=self.mock_controller
        )

    def tearDown(self):
        """Dispose of resources after each test."""
        # Ensure any running threads from tests are handled
        if not self.activity._disposed:
            self.activity.cancel()  # Cancel to unblock threads
            self.activity.resume()  # Unpause to let them exit
            self.activity.dispose()
        if not self.mock_controller._disposed:
            self.mock_controller.dispose()

    def test_initial_status_is_pending(self):
        """Verify the initial status of a new job is PENDING."""
        self.assertEqual(self.activity.get_status(), ActivityStatus.PENDING)

    def test_start_changes_status_to_running(self):
        """Test that the start() method correctly changes status from PENDING to RUNNING."""
        self.activity.start()
        self.assertEqual(self.activity.get_status(), ActivityStatus.RUNNING)

    def test_cancel_sets_cancelled_status(self):
        """Test that the cancel() method correctly sets the status to CANCELLED."""
        self.activity.start()
        self.activity.cancel()
        self.assertEqual(self.activity.get_status(), ActivityStatus.CANCELLED)

    def test_load_work_and_set_job_total(self):
        """Test loading a collection and work function into the job."""
        work_items = [1, 2, 3, 4]
        self.activity.load_work(work_items, lambda item: None)
        self.assertEqual(self.activity._job_total, 4)

    def test_update_progress_calculates_correctly(self):
        """Test that progress is calculated correctly after updates."""
        self.activity.set_job_total(10)
        self.activity.update_progress(2)
        self.assertEqual(self.activity.get_progress(), 20.0)
        self.activity.update_progress(3)
        self.assertEqual(self.activity.get_progress(), 50.0)

    def test_update_progress_emits_notification(self):
        """Verify that updating progress sends a notification through the SignalController."""
        event_data = None

        def on_progress(object_id, event_type, data):
            nonlocal event_data
            event_data = data

        self.mock_controller.subscribe(self.activity.id, "PROGRESS_UPDATE", on_progress)
        self.activity.set_job_total(10)
        self.activity.update_progress(5)

        self.assertIsNotNone(event_data)
        self.assertEqual(event_data['percentage'], 50.0)

    def test_perform_activity_processes_collection(self):
        """Verify that perform_activity processes all items and updates progress."""
        processed_items = []

        def work_function(item):
            processed_items.append(item)

        self.activity.load_work([10, 20, 30], work_function)
        self.activity.start()
        self.activity.perform_activity()

        self.assertEqual(len(processed_items), 3)
        self.assertListEqual(processed_items, [10, 20, 30])
        self.assertEqual(self.activity.get_progress(), 100.0)
        self.assertEqual(self.activity.get_status(), ActivityStatus.COMPLETED)

    # --- Pause, Resume, and Concurrency Tests ---

    def test_pause_and_resume_with_threading(self):
        """Ensure pause and resume work correctly with a live worker thread."""
        processed_items = []

        def work_function(item):
            time.sleep(0.1)  # Simulate work
            processed_items.append(item)

        self.activity.load_work([1, 2, 3, 4], work_function)
        self.activity.start()

        worker_thread = threading.Thread(target=self.activity.perform_activity)
        worker_thread.start()

        time.sleep(0.12)  # Let the first item be processed
        self.activity.pause()
        self.assertEqual(self.activity.get_status(), ActivityStatus.PAUSED)

        # At this point, the worker thread should be blocked on the gate.
        # The number of processed items should be 1.
        time.sleep(0.05)  # Give time to ensure no more items are processed
        self.assertEqual(len(processed_items), 1)

        self.activity.resume()
        self.assertEqual(self.activity.get_status(), ActivityStatus.RUNNING)

        worker_thread.join(timeout=5)  # Wait for the thread to finish
        self.assertFalse(worker_thread.is_alive(), "Worker thread did not finish after resume.")

        self.assertEqual(len(processed_items), 4)
        self.assertEqual(self.activity.get_status(), ActivityStatus.COMPLETED)

    def test_cancel_unblocks_paused_worker(self):
        """Verify that cancelling a paused job unblocks the worker thread."""
        self.activity.load_work([1, 2, 3], lambda item: time.sleep(0.75))
        self.activity.start()

        worker_thread = threading.Thread(target=self.activity.perform_activity)
        worker_thread.start()

        time.sleep(0.2)  # Let the thread start and enter the loop
        self.activity.pause()
        print(self.activity.get_status())
        time.sleep(0.2)  # Ensure it's paused and waiting
        self.assertEqual(self.activity.get_status(), ActivityStatus.PAUSED)

        self.activity.cancel()  # This should open the gate and set status

        # The worker thread should now see the gate is open, check for cancellation, and exit.
        worker_thread.join(timeout=1)
        self.assertFalse(worker_thread.is_alive(), "Worker thread did not exit after cancel.")
        self.assertEqual(self.activity.get_status(), ActivityStatus.CANCELLED)

    # --- Edge Case and State Management Tests ---

    def test_pause_is_ignored_when_not_running(self):
        """Verify that pause() has no effect on a PENDING or COMPLETED job."""
        self.activity.pause()
        self.assertEqual(self.activity.get_status(), ActivityStatus.PENDING)

        self.activity.set_status("COMPLETED")
        self.activity.pause()
        self.assertEqual(self.activity.get_status(), ActivityStatus.COMPLETED)

    def test_resume_is_ignored_when_not_paused(self):
        """Verify that resume() has no effect on a RUNNING job."""
        self.activity.start()
        self.activity.resume()
        self.assertEqual(self.activity.get_status(), ActivityStatus.RUNNING)

    def test_cancel_is_ignored_on_terminal_state(self):
        """Test that cancel() has no effect if the job is already completed or cancelled."""
        self.activity.set_status("COMPLETED")
        self.activity.cancel()
        self.assertEqual(self.activity.get_status(), ActivityStatus.COMPLETED)

        self.activity.set_status("CANCELLED")
        self.activity.cancel()  # Should not change status
        self.assertEqual(self.activity.get_status(), ActivityStatus.CANCELLED)

    def test_reset_clears_state_and_allows_rerun(self):
        """Test that reset() clears progress and status, allowing a job to be re-run."""
        self.activity.load_work([1, 2], lambda item: None)
        self.activity.start()
        self.activity.perform_activity()
        self.assertEqual(self.activity.get_status(), ActivityStatus.COMPLETED)

        self.activity.reset()
        self.assertEqual(self.activity.get_status(), ActivityStatus.PENDING)
        self.assertEqual(self.activity.get_progress(), 0.0)
        self.assertIsNone(self.activity.get_job_result())
        self.assertTrue(self.activity._pause_event.is_open(), "Reset should open the pause gate.")

        # Can be re-run
        self.activity.load_work([3, 4, 5], lambda item: None)
        self.activity.start()
        self.activity.perform_activity()
        self.assertEqual(self.activity.get_status(), ActivityStatus.COMPLETED)
        self.assertEqual(self.activity.get_progress(), 100.0)

    def test_load_work_with_empty_collection_raises_error(self):
        """Test that loading an empty collection raises a ValueError."""
        with self.assertRaises(ValueError):
            self.activity.load_work([], lambda item: None)

    def test_update_progress_raises_error_before_total_is_set(self):
        """Verify that calling update_progress before setting a total raises an error."""
        with self.assertRaises(RuntimeError):
            self.activity.update_progress(1)

    def test_load_work_fails_when_not_pending(self):
        """Test that load_work is ignored if the job is not in a PENDING state."""
        self.activity.start()  # Status is now RUNNING
        initial_total = self.activity._job_total
        self.activity.load_work([1, 2, 3], lambda x: None)
        # The total should not have changed
        self.assertEqual(self.activity._job_total, initial_total)

    def test_set_and_get_job_result(self):
        """Test that a job's result can be set and retrieved."""
        # In a real scenario, the work_function or perform_activity would set this.
        # For this test, we set the internal attribute directly.
        self.activity._job_result = {"status": "success", "data": [1, 2]}
        result = self.activity.get_job_result()
        self.assertDictEqual(result, {"status": "success", "data": [1, 2]})

    def test_deploy_all_agents_calls_deploy_on_each_agent(self):
        """Verify that deploy_all_agents calls the deploy method on every registered agent."""
        agents = [DummyAgent(factory_id=f"agent-{i}") for i in range(3)]
        for agent in agents:
            agent.deploy = MagicMock()
            self.activity.register_agent(agent)

        self.activity.deploy_all_agents()

        for agent in agents:
            agent.deploy.assert_called_once()

    def test_is_cancellation_requested_returns_correctly(self):
        """Test the is_cancellation_requested helper method."""
        self.assertFalse(self.activity.is_cancellation_requested())
        self.activity.cancel()
        self.assertTrue(self.activity.is_cancellation_requested())


if __name__ == "__main__":
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
