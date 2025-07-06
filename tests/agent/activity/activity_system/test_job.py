import unittest
from unittest.mock import MagicMock
from thread_factory.agent.activity.job import JobActivity
from thread_factory.agent.activity.base import ActivityStatus
from thread_factory.synchronization.controllers.signal_controller import SignalController


class TestJobActivity(unittest.TestCase):
    """Unit tests for the JobActivity class."""

    def setUp(self):
        """Create a new JobActivity instance before each test."""
        self.signal_controller = SignalController()
        self.activity = JobActivity(
            job_id="job-123",
            task_id="task-456",
            signal_controller=self.signal_controller
        )

    def tearDown(self):
        """Dispose the activity and signal controller after each test."""
        self.activity.dispose()
        self.signal_controller.dispose()

    def test_initial_status_is_pending(self):
        """Ensure the job starts in PENDING state."""
        self.assertEqual(self.activity.get_status(), ActivityStatus.PENDING)

    def test_cancel_transitions_to_cancelled(self):
        """Test that cancel() updates the status correctly."""
        self.activity.cancel()
        self.assertEqual(self.activity.get_status(), ActivityStatus.CANCELLED)

    def test_cancel_does_nothing_if_already_completed(self):
        """Cancel is ignored if the job is in a terminal state."""
        self.activity.set_status("COMPLETED")
        self.activity.cancel()
        self.assertEqual(self.activity.get_status(), ActivityStatus.COMPLETED)

    def test_pause_and_resume_work_correctly(self):
        """Test pause and resume transitions."""
        self.activity.set_status("RUNNING")
        self.activity.pause()
        self.assertEqual(self.activity.get_status(), ActivityStatus.PAUSED)

        self.activity.resume()
        self.assertEqual(self.activity.get_status(), ActivityStatus.RUNNING)

    def test_pause_when_not_running_is_ignored(self):
        """Pause should be ignored if not in RUNNING state."""
        self.activity.pause()
        self.assertEqual(self.activity.get_status(), ActivityStatus.PENDING)

    def test_resume_when_not_paused_is_ignored(self):
        """Resume should be ignored if not paused."""
        self.activity.resume()
        self.assertEqual(self.activity.get_status(), ActivityStatus.PENDING)

    def test_is_cancellation_requested(self):
        """Ensure the flag returns True only when cancelled."""
        self.assertFalse(self.activity.is_cancellation_requested())
        self.activity.cancel()
        self.assertTrue(self.activity.is_cancellation_requested())

    def test_progress_tracking(self):
        """Test that progress updates and calculates percentage correctly."""
        self.activity.set_job_total(100)
        self.activity.update_progress(25)
        self.assertAlmostEqual(self.activity.get_progress(), 25.0)

        self.activity.update_progress(50)
        self.assertAlmostEqual(self.activity.get_progress(), 75.0)

        self.activity.update_progress(100)  # should cap at 100
        self.assertEqual(self.activity.get_progress(), 100.0)

    def test_update_progress_raises_without_total(self):
        """Ensure update_progress() fails if total isn't set."""
        with self.assertRaises(RuntimeError):
            self.activity.update_progress(5)

    def test_set_job_total_negative_raises(self):
        """Reject invalid job total values."""
        with self.assertRaises(ValueError):
            self.activity.set_job_total(-10)

    def test_update_progress_negative_raises(self):
        """Reject invalid progress increments."""
        self.activity.set_job_total(100)
        with self.assertRaises(ValueError):
            self.activity.update_progress(-1)

    def test_get_job_result_initially_none(self):
        """Job result should default to None."""
        self.assertIsNone(self.activity.get_job_result())

    def test_cancellation_confirmed_sets_status_and_emits(self):
        events = []

        def handler(obj_id, event_type, data):
            events.append((event_type, data))

        self.signal_controller.subscribe(self.activity.id, "CANCELLATION_CONFIRMED", handler)
        self.activity.cancellation_confirmed()

        self.assertEqual(self.activity.get_status(), ActivityStatus.CANCELLED)
        self.assertTrue(any(evt[0] == "CANCELLATION_CONFIRMED" for evt in events))

    def test_report_progress_emits_data(self):
        events = []

        def handler(obj_id, event_type, data):
            events.append(data)

        self.signal_controller.subscribe(self.activity.id, "PROGRESS_UPDATE", handler)
        self.activity.report_progress({"foo": "bar"})

        self.assertIn({"foo": "bar"}, events)

    def test_set_status_accepts_valid_enum_strings(self):
        """Ensure set_status works for valid ActivityStatus strings."""
        self.activity.set_status("running")
        self.assertEqual(self.activity.get_status(), ActivityStatus.RUNNING)

    def test_set_status_invalid_string_raises(self):
        """Ensure invalid statuses raise ValueError."""
        with self.assertRaises(ValueError):
            self.activity.set_status("banana")

    def test_status_change_emits_event(self):
        received = []

        def callback(obj_id, event_type, data):
            received.append((event_type, data))

        self.signal_controller.subscribe(self.activity.id, "STATUS_CHANGED", callback)
        self.activity.set_status("running")
        self.assertTrue(any(evt[0] == "STATUS_CHANGED" for evt in received))


    def test_dispose_resets_state(self):
        """Dispose clears internal job state properly."""
        self.activity.set_job_total(50)
        self.activity.update_progress(25)
        self.activity.cancel()
        self.activity.dispose()

        self.assertEqual(self.activity.get_status(), ActivityStatus.DISPOSED)
        self.assertEqual(self.activity.get_progress(), 0.0)
        self.assertEqual(self.activity._job_current_count, 0.0)
        self.assertEqual(self.activity._job_total, 0.0)
        self.assertIsNone(self.activity.get_job_result())


if __name__ == "__main__":
    unittest.main()
