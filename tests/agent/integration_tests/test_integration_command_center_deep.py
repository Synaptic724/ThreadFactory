import unittest
import time
import logging
import threading
from unittest.mock import MagicMock

# Assuming the following imports are correct based on your project structure
from thread_factory.agent.command_center import CommandCenter
from thread_factory.agent.identity.types.general import General
from thread_factory.agent.activity.job import JobActivity
from thread_factory.agent.activity.base import ActivityStatus
from thread_factory.synchronization.controllers.signal_controller import SignalController

# Suppress all logging below CRITICAL for cleaner test output
logging.disable(logging.CRITICAL)


class TestFullSystemIntegration(unittest.TestCase):
    """
    A deep integration test suite that verifies the entire system workflow,
    from remote control via a SignalController to agent-based activity execution.
    """

    def setUp(self):
        """Set up a fully integrated environment for each test."""
        # The external controller used by the test to send commands
        self.remote_control = SignalController()

        # The main application component
        self.cc = CommandCenter(
            total_max_workers=10,
            external_signal_controller=self.remote_control  # CommandCenter registers itself
        )

        # Register real templates for agents and activities
        self.cc.register_template("general_agent", General)
        self.cc.register_activity_template("job_activity", JobActivity)

        # Create a dedicated group for our mission
        self.group_name = "mission_group"
        self.cc.create_command_group(self.group_name, max_workers=5)
        self.group = self.cc.get_command_group(self.group_name)

        # Register the group with the remote so we can command it
        self.remote_control.register(self.group)

    def tearDown(self):
        """Clean up all components after each test."""
        self.cc.dispose()
        self.remote_control.dispose()

    def test_full_lifecycle_remotely_controlled(self):
        """
        Test the complete lifecycle of creating, running, and monitoring a job
        entirely through the external SignalController.
        """
        # --- 1. Remotely Create the Activity ---
        # We invoke the 'add_activity' command on our command group
        activity = self.remote_control.invoke(
            self.group.id,
            'add_activity',
            name='job_activity',
            job_id='remote_job_1',
            task_id='remote_task_1'
        )
        self.assertIsInstance(activity, JobActivity)
        self.assertIn(activity.id, self.group.list_activities())

        # --- 2. Remotely Configure the Activity ---
        work_items = list(range(5))
        processed_items = []

        def work_function(item):
            time.sleep(0.01)
            processed_items.append(item)

        # Use the remote to load work into the activity
        self.remote_control.invoke(activity.id, 'load_work', collection=work_items, work_function=work_function)

        # --- 3. Remotely Start and Deploy ---
        # Start the activity, changing its status to RUNNING
        self.remote_control.invoke(activity.id, 'start')
        status = self.remote_control.invoke(activity.id, 'get_status')
        self.assertEqual(status, ActivityStatus.RUNNING)

        # Deploy agents via the CommandCenter (as a user would)
        self.cc.deploy_activity(activity, worker_count=2, command_group_name=self.group_name)

        # --- 4. Remotely Monitor Completion ---
        # Wait for the job to complete
        timeout = time.time() + 5  # 5 second timeout
        final_status = None
        while time.time() < timeout:
            final_status = self.remote_control.invoke(activity.id, 'get_status')
            if final_status == ActivityStatus.COMPLETED:
                break
            time.sleep(0.1)

        self.assertEqual(final_status, ActivityStatus.COMPLETED)
        self.assertEqual(len(processed_items), len(work_items))

        # After the job, ephemeral agents should be gone
        time.sleep(0.1)  # Give time for agents to dispose
        self.assertEqual(len(self.group.list_agents()), 0)

    def test_remote_pause_resume_and_cancel(self):
        """
        Test remote pause, resume, and cancel commands on a running activity.
        """
        processed_items = []
        work_items = list(range(10))  # A longer job

        def work_function(item):
            time.sleep(0.05)
            processed_items.append(item)

        # --- Setup: Create and deploy the activity ---
        activity = self.group.add_activity('job_activity', job_id='remote_job_2', task_id='remote_task_2')
        self.remote_control.invoke(activity.id, 'load_work', collection=work_items, work_function=work_function)
        self.remote_control.invoke(activity.id, 'start')

        # Run the deployment in a separate thread so our test can interact with it
        deploy_thread = threading.Thread(
            target=self.cc.deploy_activity,
            args=(activity, 2, self.group_name)
        )
        deploy_thread.start()

        # --- 1. Test Pause ---
        time.sleep(0.12)  # Let a couple of items get processed
        self.remote_control.invoke(activity.id, 'pause')

        # Wait until the status is confirmed as PAUSED
        timeout = time.time() + 2
        while self.remote_control.invoke(activity.id, 'get_status') != ActivityStatus.PAUSED:
            time.sleep(0.01)
            if time.time() > timeout:
                self.fail("Activity did not enter PAUSED state in time.")

        # Now that status is PAUSED, allow a moment for in-flight tasks to finish
        time.sleep(0.1)

        # Capture the state AFTER the system has settled into the paused state.
        items_processed_after_pause = len(processed_items)
        self.assertGreater(items_processed_after_pause, 0)
        self.assertLess(items_processed_after_pause, 10)

        # Wait again to ensure no *new* items are processed
        time.sleep(0.2)
        self.assertEqual(len(processed_items), items_processed_after_pause,
                         "Items were processed after the activity was paused.")

        # --- 2. Test Resume ---
        self.remote_control.invoke(activity.id, 'resume')
        status = self.remote_control.invoke(activity.id, 'get_status')
        self.assertEqual(status, ActivityStatus.RUNNING)

        # Wait for the deploy thread to finish (it should be quick)
        deploy_thread.join(timeout=1)

        # Now, poll for the activity's completion status, since the agents run separately.
        timeout = time.time() + 5  # 5 second timeout
        final_status = None
        while time.time() < timeout:
            final_status = self.remote_control.invoke(activity.id, 'get_status')
            if final_status == ActivityStatus.COMPLETED:
                break
            time.sleep(0.1)

        self.assertEqual(final_status, ActivityStatus.COMPLETED, "Activity did not complete after resume.")
        self.assertEqual(len(processed_items), 10)

        # --- 3. Test Cancel ---
        # Reset and run again to test cancellation
        self.remote_control.invoke(activity.id, 'reset')
        processed_items.clear()

        self.remote_control.invoke(activity.id, 'load_work', collection=work_items, work_function=work_function)
        self.remote_control.invoke(activity.id, 'start')

        deploy_thread_2 = threading.Thread(
            target=self.cc.deploy_activity,
            args=(activity, 2, self.group_name)
        )
        deploy_thread_2.start()

        time.sleep(0.12)  # Let some work happen
        self.remote_control.invoke(activity.id, 'cancel')

        deploy_thread_2.join(timeout=5)
        final_status = self.remote_control.invoke(activity.id, 'get_status')
        self.assertEqual(final_status, ActivityStatus.CANCELLED)
        self.assertLess(len(processed_items), 10)


if __name__ == '__main__':
    unittest.main(verbosity=2)
