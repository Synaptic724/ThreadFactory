import unittest
from unittest.mock import MagicMock, patch
from typing import Any, Type, Optional
import threading  # Required for BaseActivity's _lock
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.agent.activity.base import BaseActivity
from thread_factory.agent.activity.job import JobActivity
from thread_factory.agent.activity.builder import ActivityBuilder


# --- Unit Tests for ActivityBuilder ---

class TestActivityBuilder(unittest.TestCase):

    def setUp(self):
        """Set up a fresh builder for each test."""
        # Patch the real ConcurrentDict's dispose method to track calls
        # This allows us to verify dispose is called on the registry
        self.patcher = patch('thread_factory.concurrency.concurrent_dictionary.ConcurrentDict.dispose')
        self.mock_concurrent_dict_dispose = self.patcher.start()

        self.builder = ActivityBuilder()

    def tearDown(self):
        """Dispose the builder after each test and stop patches."""
        self.builder.dispose()
        self.patcher.stop()

    def test_init_default_registration(self):
        """Test that 'job_activity' is registered on initialization."""
        self.assertTrue(self.builder._registered)
        self.assertIn("job_activity", self.builder._registry)
        self.assertEqual(self.builder._registry["job_activity"], JobActivity)  # Use real JobActivity

    def test_dispose_clears_registry_and_sets_disposed(self):
        """Test that dispose clears the registry and sets the disposed flag."""
        # Ensure something is in the registry before disposing
        self.builder.register_activity("test_activity", BaseActivity)  # Use real BaseActivity
        self.assertGreater(len(self.builder._registry), 0)

        self.builder.dispose()

        self.assertTrue(self.builder._disposed)
        # Verify dispose was called
        self.mock_concurrent_dict_dispose.assert_called_once()

    def test_dispose_idempotency(self):
        """Test that calling dispose multiple times has no further effect."""
        self.builder.dispose()
        initial_disposed_state = self.builder._disposed

        self.builder.dispose()  # Call again
        self.assertEqual(self.builder._disposed, initial_disposed_state)
        # Verify dispose was called only once on the underlying ConcurrentDict
        self.mock_concurrent_dict_dispose.assert_called_once()

    def test_register_custom_activity_class_success(self):
        """Test successful registration of a custom activity class."""

        class CustomActivity(BaseActivity):  # Use real BaseActivity
            def __init__(self, activity_name: str, signal_controller: Optional[Any] = None,
                         logger: Optional[Any] = None, **kwargs):
                super().__init__(signal_controller=signal_controller, logger=logger, **kwargs)
                self.activity_name = activity_name  # Renamed 'name' to 'activity_name' to avoid conflict
                self._logger = MagicMock()  # Mock logger for real BaseActivity

        self.builder.register_activity("custom_test", CustomActivity)
        self.assertIn("custom_test", self.builder._registry)
        self.assertEqual(self.builder._registry["custom_test"], CustomActivity)

    def test_register_activity_class_not_subclass_of_base(self):
        """Test that registering a non-BaseActivity subclass raises TypeError."""

        class NonActivity: pass

        with self.assertRaisesRegex(TypeError, "must be a subclass of BaseActivity"):  # Use real BaseActivity
            self.builder.register_activity("invalid_type", NonActivity)

    def test_register_activity_class_overwrites_existing(self):
        """Test that registering a class with an existing name overwrites it."""

        class OriginalActivity(BaseActivity):  # Use real BaseActivity
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self._logger = MagicMock()  # Mock logger for real BaseActivity

        class NewActivity(BaseActivity):  # Use real BaseActivity
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self._logger = MagicMock()  # Mock logger for real BaseActivity

        self.builder.register_activity("overwrite_me", OriginalActivity)
        self.assertEqual(self.builder._registry["overwrite_me"], OriginalActivity)

        self.builder.register_activity("overwrite_me", NewActivity)
        self.assertEqual(self.builder._registry["overwrite_me"], NewActivity)  # Should be overwritten

    def test_build_job_activity_success(self):
        """Test successful building of a 'job_activity' instance."""
        # Mock dependencies that JobActivity's __init__ expects
        mock_signal_controller = MagicMock()
        mock_logger = MagicMock()

        job_id = "test-job-1"
        task_id = "test-task-1"
        job = self.builder.build_activity(
            "job_activity",
            job_id=job_id,
            task_id=task_id,
            signal_controller=mock_signal_controller,
            logger=mock_logger,
            extra_arg="value"
        )
        self.assertIsInstance(job, JobActivity)  # Use real JobActivity
        # JobActivity's __init__ passes job_id to super().__init__(**kwargs)
        # BaseActivity stores all kwargs in _metadata.
        # So, job.id is the ULID, and job_id is in _metadata.
        self.assertEqual(job._metadata.get("job_id"), job_id)  # Access job_id from _metadata
        self.assertEqual(job._metadata.get("task_id"), task_id)  # task_id is in _metadata
        self.assertEqual(job._metadata.get("extra_arg"), "value")  # Access _metadata
        self.assertEqual(job._signal_controller, mock_signal_controller)
        self.assertEqual(job._logger, mock_logger)

    def test_build_activity_unknown_name_returns_none(self):
        """Test that building with an unregistered name returns None."""
        activity = self.builder.build_activity("non_existent_activity")
        self.assertIsNone(activity)

    def test_build_job_activity_missing_required_kwargs_raises_type_error(self):
        """Test that building JobActivity without required args raises TypeError."""
        # Mock dependencies that JobActivity's __init__ expects
        mock_signal_controller = MagicMock()
        mock_logger = MagicMock()

        with self.assertRaisesRegex(TypeError, "Failed to build activity 'job_activity'."):
            # Missing task_id
            self.builder.build_activity(
                "job_activity",
                job_id="missing_task_id",
                signal_controller=mock_signal_controller,
                logger=mock_logger
            )

    def test_build_job_activity_with_extra_kwargs(self):
        """Test that extra kwargs are passed to the activity constructor."""
        # Mock dependencies that JobActivity's __init__ expects
        mock_signal_controller = MagicMock()
        mock_logger = MagicMock()

        job = self.builder.build_activity(
            "job_activity",
            job_id="job-extra-kwargs",
            task_id="task-extra-kwargs",
            signal_controller=mock_signal_controller,
            logger=mock_logger,
            custom_setting=True,
            another_param=123
        )
        self.assertIsInstance(job, JobActivity)  # Use real JobActivity
        self.assertTrue(job._metadata.get("custom_setting"))  # Access _metadata
        self.assertEqual(job._metadata.get("another_param"), 123)  # Access _metadata

    def test_build_custom_activity_success(self):
        """Test registering and building a custom BaseActivity subclass."""
        # Mock dependencies that BaseActivity's __init__ expects
        mock_signal_controller = MagicMock()
        mock_logger = MagicMock()

        class MyCustomActivity(BaseActivity):  # Use real BaseActivity
            def __init__(self, activity_name: str, signal_controller: Optional[Any] = None,
                         logger: Optional[Any] = None, **kwargs):
                super().__init__(signal_controller=signal_controller, logger=logger, **kwargs)
                self.activity_name = activity_name  # Renamed 'name' to 'activity_name'

        self.builder.register_activity("my_custom_activity", MyCustomActivity)
        custom_act = self.builder.build_activity(
            "my_custom_activity",
            activity_name="AwesomeAct",  # Pass 'activity_name' here
            signal_controller=mock_signal_controller,
            logger=mock_logger,
            config_val=42
        )

        self.assertIsInstance(custom_act, MyCustomActivity)
        self.assertEqual(custom_act.activity_name, "AwesomeAct")
        self.assertEqual(custom_act._metadata.get("config_val"), 42)  # Access _metadata
        self.assertEqual(custom_act._signal_controller, mock_signal_controller)
        self.assertEqual(custom_act._logger, mock_logger)

    # The @patch decorator is moved to setUp/tearDown for consistency
    # as we are now patching a real class's method.
    def test_register_defaults_only_runs_once(self):
        """Test that _register_defaults only registers defaults once."""
        initial_registry_len = len(self.builder._registry)  # Should be 1 (job_activity)
        self.assertTrue(self.builder._registered)

        # Manually call _register_defaults again
        self.builder._registered = False  # Temporarily reset to allow it to run
        self.builder.register_activity("temp_test", BaseActivity)  # Use real BaseActivity, add something else
        self.assertEqual(len(self.builder._registry), initial_registry_len + 1)

        self.builder._registered = False  # Reset again
        self.builder._register_defaults()  # Should *not* re-add job_activity or remove temp_test
        self.assertEqual(len(self.builder._registry), initial_registry_len + 1)
        self.assertIn("job_activity", self.builder._registry)
        self.assertIn("temp_test", self.builder._registry)
        self.assertTrue(self.builder._registered)  # Should be set to True again

    def test_build_activity_after_dispose_returns_none(self):
        """Test that building an activity after builder is disposed returns None (due to empty registry)."""
        self.builder.dispose()
        # Mock dependencies for JobActivity's __init__ if it were called
        mock_signal_controller = MagicMock()
        mock_logger = MagicMock()
        with self.assertRaisesRegex(RuntimeError, "Activity Builder has been disposed."):
            self.builder.build_activity(
                "job_activity",
                job_id="x",
                task_id="y",
                signal_controller=mock_signal_controller,
                logger=mock_logger
            )

    def test_register_activity_class_with_none_class(self):
        """Test that registering None as an activity class raises TypeError."""
        with self.assertRaisesRegex(TypeError, "issubclass"):
            self.builder.register_activity("none_class", None)


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
