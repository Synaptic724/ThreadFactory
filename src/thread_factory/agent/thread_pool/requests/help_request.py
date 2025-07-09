import threading
from datetime import datetime
from ulid import ULID
from typing import Callable, Union
from thread_factory.agent.thread_pool.records.records import WorkStatus, Record
from thread_factory.utils.interfaces.disposable import IDisposable
from thread_factory.utils.coordination.package import Pack

class HelpRequest(IDisposable):
    """
    HelpRequest
    -----------
    A thread-safe contract for agentic tasks, coordinating work execution within the thread system.

    This object represents an active task that requires assistance. It signals a callable
    is ready for execution and must be picked up by an Agent. It is tightly integrated
    with the Agent-based architecture, designed for intelligent, decentralized, and traceable
    thread orchestration.

    **Agent Contract & Lifecycle:**
    When an Agent receives a HelpRequest:
    - It inspects the task and executes the callable via `acquire_work()`.
    - It is responsible for marking the outcome: `mark_completed()`, `mark_failed()`, or `mark_cancelled()`.
    - Each HelpRequest tracks its full lifecycle state in an internal `Record`.
    - Agents should only work on tasks not in a terminal state (COMPLETED, CANCELLED, FAILED).

    **Responsibilities:**
    - **Dispatcher/User:** Issues the HelpRequest to the pool. Calls `cancel_job()` if no longer needed.
    - **Agent:** Explicitly invokes `acquire_work()`. Catches exceptions and calls `mark_failed()`.
      Manually calls `mark_completed()` if work finishes early (e.g., short-circuiting).

    **Disposal:**
    After a HelpRequest reaches a terminal state, it can be `dispose()`d to release resources.

    **Summary:**
    HelpRequest defines the core execution contract for autonomous Agents, ensuring clarity,
    safety, and observability in distributed work environments.
    """
    __slots__ = IDisposable.__slots__ + [
        "_work_state", "_lock", "record", "_work_callable", "_return_to_pool",
    ]
    def __init__(self, work_callable: Union[Callable[..., None], Pack]):
        """
        Initialize a new HelpRequest instance with a unique task ID and a callable to execute the work.

        Args:
            task_id (str): Unique identifier for the task.
            work_callable (Union[Callable[..., None], Pack]): A callable function to execute the task.
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
        self._work_state: WorkStatus = WorkStatus.PENDING  # Initial state is pending
        self._lock = threading.RLock()  # Thread-safe locking for state changes

        # Create an internal Record for this task, initialized with task details
        self.record: Record = Record(
            task_id=ULID(),
            status=self._work_state,  # Corrected from work_status to status
            timestamp_creation_time=datetime.now()
        )

        # Store the callable to be executed (the actual work function)
        if work_callable:
            work_callable = Pack(work_callable)
        self._work_callable = work_callable
        self._return_to_pool = False
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
            self._return_to_pool = True
            self._disposed = True

    @property
    def should_return(self) -> bool:
        """
        Alias for check_return_to_pool(), for expressive read-style use.
        """
        return self._return_to_pool

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
                self._return_to_pool = True
                if self.record.timestamp_completion_time is None:
                    self.record.timestamp_completion_time = datetime.now()

            elif self._work_state == WorkStatus.CANCELLED:
                self._return_to_pool = True
                if self.record.timestamp_completion_time is None:  # Cancelling without completion timestamp
                    self.record.timestamp_completion_time = datetime.now()

            elif self._work_state == WorkStatus.FAILED:
                self._return_to_pool = True
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
        return f"<HelpRequest task_id={self.record.task_id}, state={self.get_state().name}, record={self.record}>"

    def get_record(self) -> Record:
        """
        Exposes the task's record for external use.

        This is useful for logging or auditing the task's lifecycle and status.

        Returns:
            Record: The current record associated with the task.
        """
        if self._disposed:
            raise RuntimeError(f"[HelpRequest] {self.record.task_id} has been disposed and cannot return a record.")
        return self.record

        # Add this method within the HelpRequest class definition

    def is_terminal_state(self) -> bool:
        """
        Checks if the HelpRequest is in a terminal state (COMPLETED, CANCELLED, or FAILED).
        Tasks in a terminal state should not be worked on.

        Returns:
            bool: True if the task is in a terminal state, False otherwise.
        """
        with self._lock:  # Ensure thread-safe access to _work_state
            return self._work_state in {WorkStatus.COMPLETED, WorkStatus.CANCELLED, WorkStatus.FAILED}

    def acquire_work(self):
        """
        Acquire work doesn't bind the HelpRequest to the current thread, but executes the work callable.
        This method is intended to be called by an Agent to execute the work associated with this HelpRequest.
        It checks if the HelpRequest is in a valid state to be worked on, marks it as in progress,
        and then executes the work callable. If the task is already in a terminal state, it raises an error.

        Raises:
            ValueError: If the HelpRequest has already been disposed of.
            RuntimeError: If the HelpRequest is in a terminal state (COMPLETED, CANCELLED, or FAILED).
        """
        if self._disposed:
            raise ValueError(f"[HelpRequest] {self.record.task_id} has already been disposed.")
        if self.is_terminal_state():
            raise RuntimeError(f"[HelpRequest] {self.record.task_id} has already been terminated.")

        # Acquire lock for state-changing operations only (marking in progress, completion, failure)
        with self._lock:
            # Mark the task as in progress and set the execution timestamp
            self.mark_in_progress()
            self._update_record()  # Update the record with start time

        # Execute the provided callable (do the work) without the lock so it can be done concurrently
        try:
            self._work_callable()  # Perform the work
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
                raise ValueError(f"[HelpRequest] {self.record.task_id} has been disposed.")

            # Prevent cancellation if the task is already completed
            if self._work_state == WorkStatus.COMPLETED:
                return  # Exit early, do not change the state to CANCELLED

            self.set_state(WorkStatus.CANCELLED)
            self._update_record()

    def _check_work(self):
        """
        Internal method to check if the work callable is valid.

        This method ensures that the work callable is callable and sets the thread's `_help_request`
        attribute if the thread is a dynamic worker. It raises an error if the thread does not have
        a factory ID set.
        """
        if self._work_callable is None or not callable(self._work_callable):
            raise RuntimeError(f"[HelpRequest] {self.record.task_id} does not have a valid callable.")

    def bind_help_request(self) -> None:
        """
        Binds the HelpRequest to the current thread, allowing it to execute the work callable.
        This method checks if the current thread is an AgenticWorker and sets the `_help_request`
        attribute to this HelpRequest instance. It raises an error if the thread is not properly initialized
        or if the work callable is not callable.
        This method is intended to be called by the AgenticWorker to execute the work associated with this HelpRequest.

        Raises:
            RuntimeError: If the thread is not properly initialized as an AgenticWorker or if the work callable is not callable.
        """
        if self._work_state in (WorkStatus.COMPLETED, WorkStatus.CANCELLED, WorkStatus.FAILED):
            return
        if self._disposed or self._return_to_pool:
            return
        thread = threading.current_thread()
        if not hasattr(thread, '_worker_type'):
            raise RuntimeError("Thread is not properly initialized as an AgenticWorker.")
        if thread._worker_type != "agentic":
            return  # This is only for dynamic threads
        thread._help_request = self
        if not callable(self._work_callable): #TODO: Inspect this section here it might be broken
            raise RuntimeError("No callable has been assigned to this HelpRequest.")
        try:
            self.record.add_factory_id(thread.factory_id)
            self._work_callable()
        except Exception as e:
            self.mark_failed()
            # Optionally: print or log for debug mode
            # print(f"[HelpRequest] Task {self.task_id} failed with: {e}")
