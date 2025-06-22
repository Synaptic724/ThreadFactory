import threading
from datetime import datetime
from ulid import ULID
from thread_factory.runtime.orchestrator.monitoring.records.records import Record, WorkStatus
from typing import Callable
from thread_factory.utils import IDisposable


class ValueWork(IDisposable):
    """
    A lightweight, thread-safe task tracking object that can be dynamically executed
    by workers. The task's lifecycle is tracked, and it provides hooks for handling
    work completion, cancellation, and execution.
    """

    def __init__(self, task_id: str, work_callable: Callable[['ValueWork'], None]):
        """
        Initializes the `ValueWork` object, creating an internal record for the task
        and accepting a callable function to execute the work.

        Args:
            task_id (str): Unique identifier for the task.
            work_callable (Callable): The function to be executed for the work.
        """
        super().__init__()
        self.task_id = task_id
        self._state = WorkStatus.PENDING  # Initial state is pending
        self._lock = threading.RLock()  # Thread-safe locking for state changes
        self._disposed = False  # Flag to mark if the object is disposed

        # Create an internal Record for this task, initialized with task details
        self.record = Record(
            task_id=ULID(),
            status=self._state,  # Corrected from work_status to status
            timestamp_creation_time=datetime.now()
        )

        # Store the callable to be executed (the actual work function)
        self._work_callable = work_callable

    def _update_record(self):
        """Internal API to update the record's status and timestamps."""
        self.record.work_status = self._state  # Update the record with the current state
        if self._state == WorkStatus.IN_PROGRESS and self.record.execution_time is None:
            # Set execution time when the task is in progress
            self.record.execution_time = datetime.now()
        elif self._state == WorkStatus.COMPLETED and self.record.completion_time is None:
            # Set completion time when the task is completed
            self.record.completion_time = datetime.now()

    def set_state(self, new_state: WorkStatus):
        """
        Set a new state for the task. Ensures thread-safe state changes and updates the record.

        Args:
            new_state (WorkStatus): The new state of the task.
        """
        with self._lock:
            self._state = new_state
            self._update_record()  # Update the internal record with the new state

    def get_state(self) -> WorkStatus:
        """
        Get the current state of the task, which reflects the record's status.

        Returns:
            WorkStatus: The current state of the task.
        """
        with self._lock:
            return self.record.status  # Return the state of the record

    def mark_in_progress(self):
        """Mark the task as in progress."""
        self.set_state(WorkStatus.IN_PROGRESS)

    def mark_completed(self):
        """Mark the task as completed, update the record, and dispose of the object."""
        with self._lock:
            self.set_state(WorkStatus.COMPLETED)  # Update the task state to COMPLETED
            self._update_record()  # Update the record with completion time

            # Dispose of the object and null out the record
            self.dispose()  # Dispose of the object, which will null out the record and callable
            self.record = None  # Null out the record to clean up any reference

    def mark_failed(self):
        """Mark the task as failed."""
        self.set_state(WorkStatus.FAILED)

    def mark_cancelled(self):
        """Mark the task as cancelled."""
        self.set_state(WorkStatus.CANCELLED)

    def reset(self):
        """Reset the task's state back to PENDING."""
        with self._lock:
            self.set_state(WorkStatus.PENDING)  # Reset state to PENDING

    def __repr__(self):
        """
        String representation of the task's state and record for debugging/logging purposes.
        """
        return f"<ValueWork task_id={self.task_id}, state={self.get_state().name}, record={self.record}>"

    def get_record(self) -> Record:
        """
        Expose the record for external use (e.g., for logging or auditing).
        """
        return self.record

    def dispose(self):
        """
        Dispose the ValueWork object, clearing references to the task record.
        This is intended for memory-sensitive environments where holding references is expensive.
        """
        with self._lock:
            if self._disposed:
                return

            # Clear references to the work callable and record
            self._work_callable = None
            self.record = None  # Clear the record to help with garbage collection
            self._disposed = True

            print(f"[ValueWork] {self.task_id} disposed of.")

    def acquire_work(self):
        """
        Internal method to acquire the work, marking the task as in progress,
        recording the start time, and then executing the work callable.
        This method is triggered when a worker becomes available and it processes the task.
        """
        if self._disposed:
            raise ValueError(f"[ValueWork] {self.task_id} has already been disposed.")

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
            print(f"[ValueWork] Error executing task {self.task_id}: {e}")

    def cancel_job(self):
        """
        Allows the user to cancel the job on their side, marking it as CANCELLED.
        This does not cancel the task in the thread pool, but allows users to
        cancel the job locally.
        """
        with self._lock:
            if self._disposed:
                raise ValueError(f"[ValueWork] {self.task_id} has already been disposed.")
            self.set_state(WorkStatus.CANCELLED)  # Mark the task as cancelled
            self._update_record()  # Update the record to reflect cancellation
            print(f"[ValueWork] {self.task_id} has been cancelled locally.")

    def wrap_callable(self, callable: Callable[['ValueWork'], None]) -> Callable[['ValueWork'], None]:
        """
        Wraps the user-provided callable with additional logic to execute the task,
        notifying the SwitchLock or other worker mechanisms when the task is ready.

        Args:
            callable (Callable): The original work function provided by the user.

        Returns:
            Callable: A new callable that integrates with the worker system.
        """

        def wrapped_callable(value_work: 'ValueWork'):
            """
            This is the wrapper that gets called when the task is executed.
            It ensures the task's state is correctly tracked and work is executed.
            """
            value_work.acquire_work()  # Acquire and process the task
            callable(value_work)  # Execute the original task logic

        return wrapped_callable
