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
    A thread-safe, agentic task signal used to coordinate execution within a DynamicPool.

    This object represents an active help-call — a formal contract between the dispatcher and
    the thread system, signaling that a callable is ready for execution and must be picked up
    by a DynamicWorker. It is tightly integrated with the DynamicPool/DynamicWorker architecture,
    and is designed to enable intelligent, decentralized, and traceable thread orchestration.

    System Role:
    ------------
    HelpRequest is the mechanism through which tasks signal for assistance. It emits an intent
    to execute, and the DynamicPool responds by dispatching a DynamicWorker to fulfill the contract.

    When a DynamicWorker receives a HelpRequest:
    - It inspects the task.
    - It executes the callable by invoking `acquire_work()`.
    - It is responsible for properly marking the outcome:
      • `mark_completed()` if successful.
      • `mark_failed()` if an error occurred.
      • `mark_cancelled()` if the task was aborted or unnecessary.

    Agentic Threading Contract:
    ---------------------------
    • Threads are agents — they choose to act based on the contract state.
    • Execution is not automatic; it must be explicitly invoked (`acquire_work()`).
    • Each HelpRequest includes a full task lifecycle state, tracked in a `Record`.
    • Threads must call a finalizing method if work completes early or is skipped.
    • No blocking or waiting: all execution is observable and controlled.

    Dispatcher and User Responsibilities:
    -------------------------------------
    • The dispatcher issues a HelpRequest and passes it to the DynamicPool.
    • DynamicWorkers are expected to obey contract lifecycle logic.
    • If the task finishes early (e.g., by condition short-circuiting), the worker
      must call `mark_completed()` manually to finalize the state.
    • If a HelpRequest is no longer needed before execution, `cancel_job()` should be called.
    • Threads must inspect task state before acting — executing an already completed
      or cancelled task may introduce race conditions or logic errors.

    Exception Handling:
    -------------------
    Exceptions during callable execution do not need to be propagated.
    Instead, threads should catch and respond by calling `mark_failed()` or `cancel_job()`.
    This separates logical failure from thread-crashing exceptions and allows
    external systems to observe lifecycle outcomes via state inspection.

    Disposal:
    ---------
    After a HelpRequest has been completed, failed, or cancelled, it can be disposed
    via `dispose()` to release memory and signal that the contract is closed.

    Summary:
    --------
    HelpRequest is the core execution contract for agentic thread systems using
    DynamicPools. It provides clarity, safety, and observability in environments where
    threads operate as autonomous responders to distributed work requests.
    """

    def __init__(self, work_callable: Callable):
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

    def set_return_to_pool(self, should_return: bool = True):
        """
        Signals that the current worker intends to return to the pool after task execution.

        This method can be called from within the task's callable to indicate that the thread
        has completed its duty and does not require further chaining, context retention, or
        special cleanup logic.

        Args:
            should_return (bool): Whether to mark this task for return to pool. Defaults to True.
        """
        with self._lock:
            self._return_to_pool = should_return


    def check_return_to_pool(self) -> bool:
        """
        Signals whether the worker should return to the pool after responding to this HelpRequest.

        This flag is set by either the HelpRequest itself (e.g., after `mark_completed()`),
        or by the user thread explicitly using `set_return_to_pool(True)` or `return_home()`.

        Philosophical Model:
        --------------------
        Agentic threads do not assume ownership blindly — they verify whether help is still needed.
        If this method returns True, it indicates the thread should gracefully release itself
        from this contract and return to the pool.

        This mechanism supports cooperative execution:
        - Threads act only when help is truly needed.
        - User threads retain final ownership of task state.
        - Threads honor intent, not just availability.

        Returns:
            bool: True if this thread should return to the pool and not continue execution.
        """
        return self._return_to_pool

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
            raise RuntimeError(f"[HelpRequest] {self.task_id} does not have a valid callable.")

    def bind_value_work(self) -> None:
        """
        Executes the bound work callable for dynamic threads.

        Binds this HelpRequest instance to the current dynamic thread and executes the
        associated callable, tracking factory ID and ensuring failure reporting.
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
        thread._value_work = self
        if not callable(self._work_callable):
            raise RuntimeError("No callable has been assigned to this HelpRequest.")
        try:
            self.record.add_factory_id(thread._factory_id)
            self._work_callable()
        except Exception as e:
            self.mark_failed()
            # Optionally: print or log for debug mode
            # print(f"[HelpRequest] Task {self.task_id} failed with: {e}")
