import logging
from typing import Any, Callable, Dict, Optional, List, Union
from thread_factory.concurrency.concurrent_queue import ConcurrentQueue
from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.synchronization.controllers.signal_controller import SignalController
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.agent.activity.base import BaseActivity, ActivityStatus
from thread_factory.utils.coordination.package import Pack
from thread_factory.utils.interfaces.disposable import IDisposable


class JobActivity(BaseActivity, IDisposable):
    """
    A concrete implementation of BaseActivity for managing generic, controllable jobs.

    This class represents a standard job with a defined task, progress tracking,
    cancellation logic, and a final result. It inherits the core contract from
    BaseActivity and adds a rich set of features for job-like workflows.

    **Features**:
    - **Lifecycle Management**: Tracks job states such as `PENDING`, `RUNNING`, `PAUSED`, `COMPLETED`, `FAILED`, and `CANCELLED`.
    - **Progress Tracking**: Monitors and updates progress based on the number of items processed.
    - **Cancellation Logic**: Allows jobs to be cancelled gracefully during execution.
    - **Result Handling**: Stores the final result of the job upon completion or failure.
    - **Thread Safety**: Ensures safe state transitions and progress updates in concurrent environments.

    **Usage**:
    This class is designed for scenarios where a job needs to process a collection of items
    with a specific function, while providing robust lifecycle and progress management.
    """

    def __init__(self,
                 job_id: str,
                 task_id: str,
                 collection: Optional[List[Any]] = None,
                 work_function: Optional[Callable[[Any], None]] = None,
                 signal_controller: Optional[SignalController] = None,
                 logger: Optional[logging.Logger] = None,
                 **kwargs):
        """
        Initializes the JobActivity instance.

        **Args**:
        - `job_id` (str): Unique identifier for the job.
        - `task_id` (str): Identifier for the task being executed.
        - `collection` (Optional[List[Any]]): A list of items to process. Defaults to None.
        - `work_function` (Optional[Callable[[Any], None]]): Function to apply to each item in the collection. Defaults to None.
        - `signal_controller` (Optional[SignalController]): Controller for managing signals. Defaults to None.
        - `logger` (Optional[logging.Logger]): Logger instance for logging job activity. Defaults to None.
        - `**kwargs`: Additional arguments for extended functionality.

        **Behavior**:
        - Initializes job-specific state such as progress, status, and result.
        - If a collection is provided, sets the total number of items for progress tracking.
        - Logs an error if the collection does not have a determinable length.

        **Raises**:
        - `TypeError`: If the provided collection is not iterable or lacks a determinable length.
        """
        super().__init__(signal_controller=signal_controller, logger=logger, job_id=job_id, task_id=task_id, **kwargs)

        # Job-specific state
        self.job_id: str = job_id  # Unique identifier for the job
        self.task_id: str = task_id  # Identifier for the task being executed

        # Internal state for progress tracking
        self._progress: float = 0.0
        self._job_current_count: float = 0.0
        self._job_total: float = 0.0
        self._job_result: Any = None
        self._job_completed = False

        # Store the work and data
        self._collection = ConcurrentQueue(collection) if collection else ConcurrentQueue()
        self._work_function = Pack.bundle(work_function) if work_function else None

        # If a collection is provided, set the total immediately
        if self._collection:
            try:
                total_items = len(self._collection)
                self.set_job_total(total_items)
            except TypeError:
                self._logger.error("Provided collection does not have a determinable length.")
                # You might want to set status to FAILED here

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
            "load_work": self.load_work,
            "reset": self.reset,
            "perform_activity": self.perform_activity,
            "get_job_result": self.get_job_result,
            "get_progress": self.get_progress,
            "report_progress": self.report_progress,
        })
        details["name"] = "JobActivity"
        return details

    # --- Lifecycle & Control Methods ---
    # In the JobActivity class

    def reset(self):
        """
        Resets the job to its initial PENDING state, clearing progress and results.

        This allows the job to be re-configured with load_work() and run again.
        The work collection is cleared and must be reloaded.
        """
        with self._lock:
            self._logger.info(f"Resetting JobActivity '{self.id}'.")
            self.set_status("PENDING")
            self._progress = 0.0
            self._job_current_count = 0.0
            self._job_result = None
            self._job_completed = False

            # Clear the work queue for reloading
            if self._collection:
                self._collection.clear()

            # The job total is implicitly reset because the collection is empty.
            # A new call to load_work() or re-initialization is required.

            self._notify("JOB_RESET")

    # And modify the existing perform_activity method:

    def perform_activity(self):
        """
        An agent calls this method to start working on the job's collection.
        The agent will only perform work if the job's status is RUNNING.
        """
        # This is the crucial change: The method is now a work loop for an
        # already-activated job.
        if self._disposed:
            self._logger.warning(f"JobActivity '{self.id}' is disposed. Cannot perform activity.")
            raise RuntimeError("JobActivity is disposed and cannot perform activity.")

        if self._job_completed:
            self._logger.warning(f"JobActivity '{self.id}' is already completed. No further activity will be performed.")
            raise RuntimeError("JobActivity is already completed. Please reset job and reinitialize.")

        if self.get_status() != ActivityStatus.RUNNING:
            return

        # Call the internal loop
        self._perform_job_activity()

        # After the loop, check if the job is finished
        with self._lock:
            if self._collection.is_empty() and not self._job_completed:
                self.set_status("COMPLETED")
                self._job_completed = True


    # --- Status, Reporting, and Agent-Facing Tools ---


    def load_work(self, collection: List[Any], work_function: Callable[[Any], None]):
        """
        Loads the collection and work function into the job after initialization.

        This allows the job to be configured for "Managed Execution" at a later time.
        This can only be done while the job is in a PENDING state.

        Args:
            collection (List[Any]): A list of items to iterate over.
            work_function (Callable[[Any], None]): A function to be called for each item.
        """
        if work_function:
            work_function = Pack.bundle(work_function)  # Ensure the work function is a Pack instance
        if self.get_status() != ActivityStatus.PENDING:
            self._logger.error(f"Job '{self.id}' is not PENDING. Cannot load new work.")
            return

        self._collection = ConcurrentQueue(collection)
        self._work_function = work_function

        # Set the job total, which also notifies the SignalController
        try:
            total_items = len(self._collection)
            self.set_job_total(total_items)
        except TypeError:
            self._logger.error("Provided collection does not have a determinable length.")
            self.set_status("FAILED")


    def _perform_job_activity(self):
        """
        This is the internal method that performs the actual work for each item
        in the collection using the provided work function.
        """
        while not self._collection.is_empty():
            # Check for cancellation BEFORE taking an item from the queue
            if self.is_cancellation_requested():
                self._logger.info(f"Cancellation detected for job '{self.id}'. Halting execution.")
                break

            # Now it's safe to get the next item
            item = self._collection.dequeue()

            # Execute the user's work
            self._work_function(item)

            # The progress increment is now implicitly 1 per loop
            self.update_progress(1)

    def is_cancellation_requested(self) -> bool:
        """
        Checks if a cancellation request has been made for the job.

        This method is primarily intended as a tool for the agent or the task
        being executed to periodically check if it should gracefully terminate.
        It directly queries the job's current status.

        Returns:
            bool: True if the job's status is ActivityStatus.CANCELLED, False otherwise.
        """
        # This method internally calls get_status(), which already handles the lock.
        # No need for an additional lock here, as get_status() provides the necessary
        # thread safety for accessing _status.
        return self.get_status() == ActivityStatus.CANCELLED

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
    def set_job_total(self, total: Union[int, float]):
        """
        Sets the total value or maximum iterations for the job's progress.
        """
        with self._lock:
            if total <= 0:
                raise ValueError("Job total must be a positive number.")
            self._job_total = float(total)
        self._logger.debug(f"JobActivity '{self.id}' job total set to {self._job_total}.")
        # Notify that the total has been set
        self._notify("JOB_TOTAL_SET", {"total": self._job_total})

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
        if increment < 0:
            raise ValueError("Progress increment must be a positive number.")

        if self._job_total <= 0:
            raise RuntimeError("Job total has not been set or is zero. Cannot update progress.")

        with self._lock:
            self._job_current_count += increment
            # Ensure the current count does not exceed the total
            if self._job_current_count > self._job_total:
                self._job_current_count = self._job_total

        # Calculate the percentage and store it in _progress for get_progress()
        current_percentage = (self._job_current_count / self._job_total) * 100.0
        self._progress = current_percentage  # This now stores the 0.0-100.0 percentage

        agent_id = self._get_agent_id()
        self._logger.info(
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
        status to `ActivityStatus.CANCELLED` and logs the confirmation.
        """
        self.set_status("CANCELLED")
        agent = self._get_agent_id()
        self._notify("CANCELLATION_CONFIRMED", {"status": self._status.name,
                                                "agent_id": agent})
        self._logger.info(f"Cancellation request received from agent {agent} for JobActivity '{self.id}'.")