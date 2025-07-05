import logging
from enum import Enum, auto
from typing import Any, Callable, Dict, Optional, List, Union
from thread_factory.synchronization.controllers.signal_controller import SignalController
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.agent.activity.base import BaseActivity
from thread_factory.utils.interfaces.disposable import IDisposable


class JobStatus(Enum):
    """
    Defines the lifecycle status of a Job.
    """
    PENDING = auto()
    RUNNING = auto()
    PAUSED = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


class JobActivity(BaseActivity, IDisposable):
    """
    A concrete implementation of BaseActivity for managing generic, controllable jobs.

    This class represents a standard job with a defined task, progress tracking,
    cancellation logic, and a final result. It inherits the core contract from
    BaseActivity and adds a rich set of features for job-like workflows.
    """

    def __init__(self,
                 job_id: str,
                 task_id: str,
                 signal_controller: Optional[SignalController] = None,
                 logger: Optional[logging.Logger] = None,
                 **kwargs):
        """
        Initializes the JobActivity.
        """
        super().__init__(signal_controller=signal_controller, logger=logger, job_id=job_id, task_id=task_id, **kwargs)

        # Job-specific state
        self.job_id: str = job_id  # Unique identifier for the job
        self.task_id: str = task_id  # Identifier for the task being executed
        self._status: JobStatus = JobStatus.PENDING
        self._progress: float = 0.0
        self._job_current_count: float = 0.0
        self._job_total: float = 0.0
        self._job_result: Any = None

    def dispose(self):
        """
        Disposes the JobActivity instance.

        This method cleans up internal job-specific state, including:
        - Resetting job progress and result fields
        - Clearing status and task IDs
        - Releasing any job-specific metadata (if added later)
        - Emitting a final disposal log

        Then it defers to the BaseActivity's dispose method to complete the standard
        unregistration and signal controller cleanup.

        This method is thread-safe and idempotent.
        """
        if self._disposed:
            self._logger.debug(f"JobActivity '{self.id}' already disposed.")
            return

        with self._lock:
            if self._disposed:
                return

            self._logger.info(f"Disposing JobActivity '{self.id}'.")

            # Clear job-specific state
            self._progress = 0.0
            self._job_current_count = 0.0
            self._job_total = 0.0
            self._job_result = None
            self._status = JobStatus.CANCELLED  # Final state
            self.job_id = None
            self.task_id = None

            # Delegate to BaseActivity / IDisposable cleanup
            super().dispose()

    # --- Overriding the contract to add more commands ---

    def _get_object_details(self) -> ConcurrentDict[str, Any]:
        """
        Extends the base activity's object details with job-specific commands and metadata.

        This method is part of the internal contract for `BaseActivity` and is typically
        used by agents or controlling mechanisms to discover available operations and
        information about the activity. It retrieves the base details and then adds
        references to the `JobActivity`'s control and reporting methods
        (e.g., cancel, pause, get_status) under the "commands" key.
        It also explicitly sets the "name" of this activity.

        Returns:
            ConcurrentDict[str, Any]: A dictionary containing comprehensive details
                                      about the JobActivity, including its ID, type,
                                      and a map of callable commands.
        """
        details = super()._get_object_details()
        details["commands"].update({
            "cancel": self.cancel,
            "pause": self.pause,
            "resume": self.resume,
            "get_status": self.get_status,
            "get_progress": self.get_progress,
            "get_job_result": self.get_job_result
        })
        details["name"] = "JobActivity"
        return details

    # --- Lifecycle & Control Methods ---

    def cancel(self):
        """
        Requests the cancellation of the job.

        If the job is not already completed, failed, or cancelled, its status
        will be updated to `JobStatus.CANCELLED`. This method is thread-safe.
        A "STATUS_CHANGED" notification is emitted upon a successful status change.

        The actual termination of the running task associated with this job
        depends on the task periodically checking `is_cancellation_requested()`.
        """
        with self._lock:
            if self._status not in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
                self._logger.info(f"JobActivity '{self.id}' cancelled.")
                self._status = JobStatus.CANCELLED
                self._notify("STATUS_CHANGED", {"status": self._status.name})
            else:
                self._logger.debug(
                    f"JobActivity '{self.id}' already in a terminal/cancelled state ({self._status.name}). Cancellation request ignored.")

    def pause(self):
        """
        Requests that the job be paused.

        The job can only be paused if its current status is `JobStatus.RUNNING`.
        Upon successful pausing, its status is updated to `JobStatus.PAUSED`.
        This method is thread-safe. A "STATUS_CHANGED" notification is emitted.

        The actual pausing of the running task associated with this job
        depends on the task implementing pause/resume logic based on status checks.
        """
        with self._lock:
            if self._status == JobStatus.RUNNING:
                self._logger.info(f"JobActivity '{self.id}' paused.")
                self._status = JobStatus.PAUSED
                self._notify("STATUS_CHANGED", {"status": self._status.name})
            else:
                self._logger.debug(
                    f"JobActivity '{self.id}' cannot be paused from current status: {self._status.name}.")

    def resume(self):
        """
        Resumes a paused job.

        The job can only be resumed if its current status is `JobStatus.PAUSED`.
        Upon successful resumption, its status is updated to `JobStatus.RUNNING`.
        This method is thread-safe. A "STATUS_CHANGED" notification is emitted.

        The actual continuation of the running task associated with this job
        depends on the task implementing pause/resume logic based on status checks.
        """
        with self._lock:
            if self._status == JobStatus.PAUSED:
                self._logger.info(f"JobActivity '{self.id}' resumed.")
                self._status = JobStatus.RUNNING
                self._notify("STATUS_CHANGED", {"status": self._status.name})
            else:
                self._logger.debug(
                    f"JobActivity '{self.id}' cannot be resumed from current status: {self._status.name}.")
    # --- Status, Reporting, and Agent-Facing Tools ---

    def get_status(self) -> JobStatus:
        """
        Retrieves the current lifecycle status of the job.

        This method provides a thread-safe way to access the job's
        internal status, reflecting its current state (e.g., PENDING, RUNNING, PAUSED).

        Returns:
            JobStatus: An enum member representing the current status of the job.
        """
        with self._lock:
            return self._status

    def is_cancellation_requested(self) -> bool:
        """
        Checks if a cancellation request has been made for the job.

        This method is primarily intended as a tool for the agent or the task
        being executed to periodically check if it should gracefully terminate.
        It directly queries the job's current status.

        Returns:
            bool: True if the job's status is JobStatus.CANCELLED, False otherwise.
        """
        # This method internally calls get_status(), which already handles the lock.
        # No need for an additional lock here, as get_status() provides the necessary
        # thread safety for accessing _status.
        return self.get_status() == JobStatus.CANCELLED

    def get_progress(self) -> float:
        """
        Returns the current percentage completion of the job.

        The progress is a float value between 0.0 and 100.0, inclusive.
        This value is calculated and updated by the `update_progress` method
        based on the `_job_current_count` and `_job_total`.

        Returns:
            float: The current progress as a percentage (0.0 to 100.0).
        """
        with self._lock:
            return self._progress

    def get_job_result(self) -> Any:
        """
        Retrieves the final result of the job.

        This method returns the value set as the job's outcome.
        It will typically be populated once the job reaches a `COMPLETED`
        or `FAILED` status. Until then, it is likely None.

        Returns:
            Any: The stored result of the job, or None if the job has not yet
                 completed or failed with a result.
        """
        with self._lock:
            return self._job_result

    def report_progress(self, progress_data: Dict[str, Any]):
        """
        Allows the running task to report arbitrary progress data.

        This method serves as a generic mechanism for the executing task
        to send detailed updates or intermediate results back to any
        observers. The `PROGRESS_UPDATE` signal is emitted with the
        provided data. This is distinct from the structured percentage
        progress updated by `update_progress`.

        Args:
            progress_data (Dict[str, Any]): A dictionary containing arbitrary
                                             data related to the job's progress.
        """
        # This method directly calls _notify, which handles its own internal locking/dispatch
        self._notify("PROGRESS_UPDATE", progress_data)

    # --- Agent-Facing Methods ---
    def set_status(self, status_str: str):
        """
        Sets the current status of the job from a string.

        Args:
            status_str: The string representation of the desired JobStatus.

        Raises:
            ValueError: If the provided string does not match any JobStatus enum member.
        """
        with self._lock:
            try:
                agent_id = self._get_agent_id()
                new_status = JobStatus[status_str.upper()]
                if self._status != new_status:
                    self._logger.info(
                        f"JobActivity '{self.id}' status changed from {self._status.name} to {new_status.name}.")
                    self._status = new_status
                    self._notify("STATUS_CHANGED", {"status": self._status.name, "agent_id": agent_id})
            except KeyError:
                raise ValueError(
                    f"Invalid job status string: '{status_str}'. Must be one of {[s.name for s in JobStatus]}.")

    def set_job_total(self, total: Union[int, float]):
        """
        Sets the total value or maximum iterations for the job's progress.

        Args:
            total: The total value against which progress will be measured.
                   Must be a positive number.

        Raises:
            ValueError: If the provided total is not positive.
        """
        with self._lock:
            if total <= 0:
                raise ValueError("Job total must be a positive number.")
            self._job_total = float(total)
            self._logger.debug(f"JobActivity '{self.id}' job total set to {self._job_total}.")
            # Optionally notify if the total changes, though less common
            # self._notify("JOB_TOTAL_SET", {"total": self._job_total})

    def update_progress(self, increment: Union[int, float]):
        """
        Updates the job's current progress by a given increment.

        This method adds the increment to the internal job count and
        calculates the current progress percentage based on the job's total.
        The current count will not exceed the job's total.

        Args:
            increment: The positive amount to add to the current progress count.

        Raises:
            ValueError: If the provided increment is not positive.
            RuntimeError: If called before a job total has been set.
        """
        with self._lock:
            if increment < 0:
                raise ValueError("Progress increment must be a positive number.")

            if self._job_total <= 0:
                raise RuntimeError("Job total has not been set or is zero. Cannot update progress.")

            self._job_current_count += increment
            # Ensure the current count does not exceed the total
            if self._job_current_count > self._job_total:
                self._job_current_count = self._job_total

            # Calculate the percentage and store it in _progress for get_progress()
            current_percentage = (self._job_current_count / self._job_total) * 100.0
            self._progress = current_percentage  # This now stores the 0.0-100.0 percentage
            agent_id = self._get_agent_id()
            self._logger.debug(
                f"JobActivity '{self.id}' progress updated: {self._job_current_count}/{self._job_total} ({self._progress:.2f}%).")
            self._notify("PROGRESS_UPDATE", {"current_count": self._job_current_count,
                                             "total_count": self._job_total,
                                             "percentage": self._progress,
                                             "agent_id": agent_id})

    def cancellation_confirmed(self):
        """
        Handles the confirmation of a cancellation request from an agent.

        This method is called when an agent confirms that it has received
        a cancellation request for this job activity. It updates the job's
        status to `JobStatus.CANCELLED` and logs the confirmation.
        """
        self.set_status("CANCELLED")
        agent = self._get_agent_id()
        self._notify("CANCELLATION_CONFIRMED", {"status": self._status.name,
                                                "agent_id": agent})
        self._logger.info(f"Cancellation request received from agent {agent} for JobActivity '{self.id}'.")