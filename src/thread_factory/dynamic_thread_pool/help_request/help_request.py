import threading
from datetime import datetime
from ulid import ULID
from thread_factory.runtime.orchestrator.monitoring.records.records import WorkStatus, Record
from typing import Callable
from thread_factory.utils import IDisposable


class HelpRequest(IDisposable):
    """
    HelpRequest
    -----------
    A thread-safe, agentic task signal designed to coordinate thread behavior through explicit lifecycle control.

    This object represents a directed help-call — a request for thread assistance at a specific callable site.
    It is purpose-built for systems using agentic threading, where threads operate with autonomy and intention,
    often coordinated by a scheduler or dispatcher that routes these HelpRequests to appropriate workers.

    Conceptual Role:
    ----------------
    Think of HelpRequest as a dynamic thread contract — a beacon raised by a task site requesting help.
    When issued, it contains everything a thread needs to arrive, perform the task, and update the system
    about what happened. This design is ideal for distributed, autonomous thread orchestration where
    threads operate in multiple locations and are activated by incoming requests, not passive queues.

    Agentic Threading Design:
    -------------------------
    • Threads are active agents, not passive workers.
    • Threads receive a HelpRequest and decide how to engage with the callable.
    • Execution must be explicitly triggered via `acquire_work()`.
    • Lifecycle state (e.g. `IN_PROGRESS`, `COMPLETED`, `FAILED`, `CANCELLED`) must be correctly maintained
      by the user or the thread executing the task.
    • State transitions are thread-safe and backed by an internal `Record` object with timestamps.

    Responsibilities:
    -----------------
    - The **caller** is responsible for issuing the HelpRequest and defining the callable.
    - The **worker thread** is responsible for executing the callable, and must call `mark_completed()`,
      `mark_failed()`, or `mark_cancelled()` if the task ends early or is aborted.
    - If the task is no longer needed, the dispatcher or thread must call `cancel_job()`.
    - If a thread attempts to execute an already completed task, it may introduce logical errors or
      side effects; such scenarios should be avoided by proper state inspection before thread dispatch.

    Design Philosophy:
    ------------------
    HelpRequest is part of a broader agentic execution model where control and responsibility
    are shared between the system and the worker threads. It avoids the passive, opaque
    behavior of standard Future/Promise abstractions in favor of visibility, control, and contract-driven
    delegation.

    Error Handling:
    ---------------
    - Exceptions raised during execution do not need to be propagated — threads should handle
      failures by calling `mark_failed()` or `cancel_job()` as appropriate.
    - This decouples execution from exception propagation and allows external systems to inspect
      task outcomes purely through lifecycle state.

    Disposal:
    ---------
    Call `dispose()` when the HelpRequest is no longer needed. This clears internal references
    and indicates that the contract has been resolved or abandoned.

    Summary:
    --------
    HelpRequest is a precise, agent-ready task signal for thread orchestration systems.
    It allows tasks to be dynamically issued, cleanly tracked, and cooperatively completed by threads
    operating across distinct execution contexts.
    """
    def __init__(self, task_id: str, work_callable: Callable):
        """
        Initialize a new HelpRequest instance with a unique task ID and a callable to execute the work.

        Args:
            task_id (str): Unique identifier for the task.
            work_callable (Callable[['HelpRequest'], None]): A callable function to execute the task.
                The callable will receive the HelpRequest instance itself as an argument.

        Initializes:
            - `task_id`: Stores the task's unique identifier.
            - `record`: A `Record` object to track task lifecycle events and timestamps.
            - `_work_state`: The current state of the task (initially `PENDING`).
            - `_lock`: A reentrant lock for thread-safe state changes.
            - `_work_callable`: The function that performs the actual work.
            - `_disposed`: Flag to indicate whether the object has been disposed of to prevent further interaction.
        """
        super().__init__()
        self.task_id = task_id
        self._work_state = WorkStatus.PENDING  # Initial state is pending
        self._lock = threading.RLock()  # Thread-safe locking for state changes

        # Create an internal Record for this task, initialized with task details
        self.record = Record(
            task_id=ULID(),
            status=self._work_state,  # Corrected from work_status to status
            timestamp_creation_time=datetime.now()
        )

        # Store the callable to be executed (the actual work function)
        self._work_callable = work_callable

        self._check_work()

    def dispose(self):
        """
        Disposes of the HelpRequest object, clearing references to the task record and other resources.

        This method is intended to be used in memory-sensitive environments to free up resources
        once the task has been completed, cancelled, or failed.
        """
        with self._lock:
            if self._disposed:
                return
            self.record = None
            self._work_state = None
            self._work_callable = None
            self._disposed = True

    def _update_record(self):
        """
        Internal method to update the task's record with the latest state and timestamp information.
        This method ensures that the record is updated whenever the task's state changes.

        If the state is `IN_PROGRESS`, it updates the `timestamp_execution_time`.
        If the state is `COMPLETED`, it updates the `timestamp_completion_time`.
        If the state is `CANCELLED` or `FAILED`, it ensures the completion timestamp is updated.

        This method is called whenever the task's state changes to reflect the new state in the record.
        """
        if self.record:  # Ensure the record is not None before updating

            # Only update the record's status if it's different
            if self.record.status != self._work_state:
                self.record.status = self._work_state  # Update the record with the current state

            # Update the timestamps based on the state transition
            if self._work_state == WorkStatus.IN_PROGRESS:
                if self.record.timestamp_execution_time is None:
                    self.record.timestamp_execution_time = datetime.now()

            elif self._work_state == WorkStatus.COMPLETED:
                if self.record.timestamp_completion_time is None:
                    self.record.timestamp_completion_time = datetime.now()

            elif self._work_state == WorkStatus.CANCELLED:
                if self.record.timestamp_completion_time is None:  # Cancelling without completion timestamp
                    self.record.timestamp_completion_time = datetime.now()

            elif self._work_state == WorkStatus.FAILED:
                if self.record.timestamp_completion_time is None:  # Failed task won't complete
                    self.record.timestamp_completion_time = datetime.now()

    def set_state(self, new_state: WorkStatus):
        """
        Safely updates the state of the task to a new state and updates the record.

        This method ensures that any state change is thread-safe and the record is updated with the latest state.

        Args:
            new_state (WorkStatus): The new state to transition to.
        """
        if new_state == self._work_state:
            return
        with self._lock:
            self._work_state = new_state
            self._update_record()  # Update the internal record with the new state

    def get_state(self) -> WorkStatus:
        """
        Retrieves the current state of the task.

        This method provides the current task state, reflecting the state in the `record`.

        Returns:
            WorkStatus: The current state of the task.

        Raises:
            RuntimeError: If the task has been disposed of and should no longer be interacted with.
            ValueError: If the task does not have a valid record.
        """
        with self._lock:
            if self._disposed:
                raise RuntimeError("HelpRequest object is disposed")
            if self.record is None:
                raise ValueError(f"[HelpRequest] {self.task_id} has no record.")
            return self.record.status  # Return the state of the record

    def mark_in_progress(self):
        """
        Marks the task as in progress, updating the state and record.

        This method transitions the task from `PENDING` to `IN_PROGRESS` and updates the record.
        """
        if WorkStatus.IN_PROGRESS == self._work_state:
            return
        self.set_state(WorkStatus.IN_PROGRESS)

    def mark_completed(self):
        """
        Marks the task as completed, updating the state and record with the completion time.

        This method ensures the task state transitions to `COMPLETED` and reflects the completion timestamp
        in the record.
        """
        if self._work_state == WorkStatus.CANCELLED:
            return
        with self._lock:
            self.set_state(WorkStatus.COMPLETED)  # Update the task state to COMPLETED
            self._update_record()  # Update the record with completion time

    def mark_failed(self):
        """
        Marks the task as failed, updating the state and record.

        This method transitions the task to the `FAILED` state and updates the record with the failure timestamp.
        """
        if self._work_state == WorkStatus.FAILED:
            return
        self.set_state(WorkStatus.FAILED)

    def mark_cancelled(self):
        """
        Marks the task as cancelled, updating the state and record.

        This method transitions the task to the `CANCELLED` state, but only if the task has not already been completed.
        """
        if self._work_state == WorkStatus.CANCELLED or self._work_state == WorkStatus.COMPLETED:
            return
        with self._lock:
            self.set_state(WorkStatus.CANCELLED)  # Mark the task as cancelled
            self._update_record()  # Update the record to reflect cancellation

    def reset(self):
        """
        Resets the task back to the `PENDING` state.

        This method transitions the task back to the `PENDING` state, allowing it to be retried or re-executed.
        """
        if self._work_state == WorkStatus.PENDING:
            return
        with self._lock:
            self.set_state(WorkStatus.PENDING)  # Reset state to PENDING

    def __repr__(self):
        """
        Returns a string representation of the task for debugging and logging purposes.

        This includes the task ID, current state, and a reference to the task's record.

        Returns:
            str: A string representation of the HelpRequest instance.
        """
        return f"<HelpRequest task_id={self.task_id}, state={self.get_state().name}, record={self.record}>"

    def get_record(self) -> Record:
        """
        Exposes the task's record for external use.

        This is useful for logging or auditing the task's lifecycle and status.

        Returns:
            Record: The current record associated with the task.
        """
        if self._disposed:
            raise RuntimeError(f"[HelpRequest] {self.task_id} has been disposed and cannot return a record.")
        return self.record

    def acquire_work(self):
        """
        Acquires the task and begins execution.

        This method marks the task as `IN_PROGRESS`, updates the record, and then executes the provided
        work callable. If the work is completed or fails, the task is marked accordingly.
        """
        if self._disposed:
            raise ValueError(f"[HelpRequest] {self.task_id} has already been disposed.")

        # Acquire lock for state-changing operations only (marking in progress, completion, failure)
        with self._lock:
            # Mark the task as in progress and set the execution timestamp
            self.mark_in_progress()
            self._update_record()  # Update the record with start time

        # Execute the provided callable (do the work) without the lock so it can be done concurrently
        try:
            self._work_callable(self)  # Perform the work
            # Lock again to mark completion
            with self._lock:
                self.mark_completed()
        except Exception as e:
            # Lock again to mark failure
            with self._lock:
                self.mark_failed()

    def cancel_job(self):
        """
        Allows the user to cancel the job locally, marking it as `CANCELLED`.

        If the task is already completed, cancellation will not proceed.
        """
        if self._work_state == WorkStatus.CANCELLED:
            return
        with self._lock:
            if self._disposed:
                raise ValueError(f"[HelpRequest] {self.task_id} has been disposed.")

            # Prevent cancellation if the task is already completed
            if self._work_state == WorkStatus.COMPLETED:
                return  # Exit early, do not change the state to CANCELLED

            self.set_state(WorkStatus.CANCELLED)
            self._update_record()

    def _check_work(self):
        """
        Internal method to check if the work callable is valid.

        This method ensures that the work callable is callable and sets the thread's `_value_work`
        attribute if the thread is a dynamic worker. It raises an error if the thread does not have
        a factory ID set.
        """
        if self._work_callable is None or not callable(self._work_callable):
            raise RuntimeError(f"[HelpRequest] {self.task_id} has not been disposed.")


    def bind_value_work(self) -> None:
        """
        Wraps a user-provided callable for task execution.

        This method allows a callable to be wrapped so that when it's executed, it receives the `HelpRequest`
        instance as an argument. This ensures that the lifecycle management (e.g., in-progress, completed)
        is properly handled through the `acquire_work()` method.

        Args:
            original_callable (Callable[['HelpRequest'], None]): The callable that will perform the task.

        Returns:
            Callable[['HelpRequest'], None]: A wrapped version of the original callable that manages lifecycle state.
        """
        if self._work_state == WorkStatus.COMPLETED or self._work_state == WorkStatus.CANCELLED or self._disposed or self._work_state == WorkStatus.FAILED:
            return
        thread = threading.current_thread()
        if not hasattr(thread, '_worker_type'):
            raise RuntimeError("Thread does not have a factory_id set. Ensure the thread is properly initialized.")
        if thread._worker_type == "dynamic":
            thread._value_work = self  # Set the HelpRequest instance on the thread for dynamic workers
            try:
                self._work_callable()
            except Exception as e:
                self.mark_failed()