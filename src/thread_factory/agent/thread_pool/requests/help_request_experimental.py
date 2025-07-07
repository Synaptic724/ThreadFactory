import threading
import logging
from datetime import datetime
from ulid import ULID
from typing import Callable, Optional, TypeVar, Generic
from thread_factory.agent.thread_pool.records import WorkStatus, Record
from thread_factory.utils.interfaces.disposable import IDisposable
from thread_factory.utils.coordination.package import Pack

# Define a TypeVar for generic result handling, allowing HelpRequest to be typed
T = TypeVar('T')

class HelpRequest(IDisposable, Generic[T]):
    """
    HelpRequest (Enhanced Dual-Mode)
    ----------------------------------
    A future-like, thread-safe, agentic task contract designed to be the
    universal unit of work for a dual-mode (Throughput vs. Dispatch) thread pool.

    This object functions as a "future," providing:
    - Typed result handling via Generics.
    - Fluent task chaining with .then().
    - Built-in resilience (retries, timeouts).
    - Metadata for intelligent, resource-aware dispatching.

    It is the single, consistent interface for submitting work, regardless of
    the pool's operational mode.
    """
    __slots__ = IDisposable.__slots__ + [
        "_work_state", "_lock", "record", "_work_callable", "_return_to_pool",
        "_result", "_exception", "_completion_event", "metadata", "_timeout",
        "_retries", "_attempt"
    ]

    def __init__(self,
                 work_callable: Callable[..., T],
                 timeout: Optional[float] = None,
                 retries: int = 0,
                 metadata: Optional[dict] = None):
        """
        Initializes an enhanced HelpRequest.

        Args:
            work_callable (Callable[..., T]): The function to execute. It should return a result of type T.
            timeout (Optional[float]): Optional timeout in seconds. A monitoring system can use this
                                       to identify and cancel stale tasks.
            retries (int): Number of times to automatically retry the task upon failure.
            metadata (Optional[dict]): A dictionary for resource requirements or other metadata
                                       to aid in dispatching (e.g., {'gpu_required': True}).
        """
        super().__init__()
        self._work_state: WorkStatus = WorkStatus.PENDING
        self._lock = threading.RLock()
        self._completion_event = threading.Event()

        # --- Core Payload ---
        # Ensure the callable is wrapped for consistent execution
        if work_callable and not isinstance(work_callable, Pack):
            work_callable = Pack(work_callable)
        self._work_callable = work_callable

        # --- Future-like Result Handling ---
        self._result: Optional[T] = None
        self._exception: Optional[Exception] = None

        # --- Resilience and Metadata ---
        self._timeout = timeout
        self._retries = retries
        self._attempt = 0
        self.metadata = metadata or {}

        # --- Agentic Control ---
        self._return_to_pool = False

        # --- Observability ---
        self.record: Record = Record(
            task_id=ULID(),
            status=self._work_state,
            timestamp_creation_time=datetime.now()
        )
        self._check_work()

    def dispose(self):
        """Disposes of the HelpRequest, releasing all resources."""
        with self._lock:
            if self._disposed:
                return
            self.record = None
            self._work_callable = None
            self._result = None
            self._exception = None
            self._completion_event = None
            self._return_to_pool = True
            self._disposed = True

    def _update_record(self):
        """Internal method to synchronize the Record with the current state."""
        if not self.record:
            return

        self.record.status = self._work_state
        now = datetime.now()

        if self._work_state == WorkStatus.IN_PROGRESS:
            if not self.record.timestamp_execution_time:
                self.record.timestamp_execution_time = now
        # Any terminal state sets the completion time and signals the event
        elif self._work_state in (WorkStatus.COMPLETED, WorkStatus.CANCELLED, WorkStatus.FAILED):
            self._return_to_pool = True
            if not self.record.timestamp_completion_time:
                self.record.timestamp_completion_time = now
            if self._completion_event:
                self._completion_event.set()

    def set_state(self, new_state: WorkStatus):
        """Thread-safely sets the state of the request."""
        with self._lock:
            if self._disposed or self._work_state == new_state:
                return
            self._work_state = new_state
            self._update_record()

    def get_state(self) -> WorkStatus:
        """Returns the current state of the request."""
        with self._lock:
            if self._disposed:
                raise RuntimeError("HelpRequest is disposed")
            return self.record.status

    def mark_completed(self):
        """Marks the request as COMPLETED, unless it was cancelled."""
        if self._work_state != WorkStatus.CANCELLED:
            self.set_state(WorkStatus.COMPLETED)

    def mark_failed(self):
        """Marks the request as FAILED."""
        self.set_state(WorkStatus.FAILED)

    def mark_cancelled(self):
        """Marks the request as CANCELLED, unless it already completed."""
        if self._work_state != WorkStatus.COMPLETED:
            self.set_state(WorkStatus.CANCELLED)

    def acquire_work(self):
        """
        The primary execution method called by a worker thread.

        It handles the full lifecycle: running the callable, storing the result
        or exception, and managing retries.
        """
        if self._disposed:
            raise RuntimeError(f"Cannot acquire disposed HelpRequest: {self.record.task_id}")

        with self._lock:
            # Prevent re-execution if already started, completed, or cancelled
            if self._work_state != WorkStatus.PENDING:
                return
            self.set_state(WorkStatus.IN_PROGRESS)
            self._attempt += 1

        try:
            # Execute the work and store the result
            self._result = self._work_callable()
            self.mark_completed()
        except Exception as e:
            # If retries are available, reset for another attempt. Otherwise, fail permanently.
            with self._lock:
                if self._attempt <= self._retries:
                    logging.warning(f"Task {self.record.task_id} failed on attempt "
                                    f"{self._attempt}/{self._retries}, will be retried.")
                    # Reset to PENDING so it can be picked up again
                    self.set_state(WorkStatus.PENDING)
                else:
                    self._exception = e
                    self.mark_failed()

    def get_result(self, timeout: Optional[float] = None) -> T:
        """
        Waits for the task to complete and returns its result, making this a "future".

        If the task resulted in an exception, that exception will be raised here.

        Args:
            timeout (Optional[float]): Max seconds to wait for a result.

        Returns:
            T: The result of the work callable.
        """
        if self._disposed:
            raise RuntimeError("Cannot get result from a disposed HelpRequest.")

        # Wait for the completion event to be set
        if self._completion_event.wait(timeout=timeout):
            with self._lock:
                if self._exception:
                    raise self._exception
                return self._result
        else:
            raise TimeoutError(f"Timed out waiting for result of task {self.record.task_id}")

    def then(self, next_callable: Callable[[T], 'T']) -> 'HelpRequest[T]':
        """
        Chains a new task to be executed after this one completes successfully.
        The result of this task is passed as the argument to the next task.

        Args:
            next_callable (Callable[[T], 'T']): The next function to execute.

        Returns:
            A new HelpRequest representing the chained task.
        """
        def chained_work() -> 'T':
            # This will block until the first task is complete and get its result
            prior_result = self.get_result()
            # Pass the result to the next function
            return next_callable(prior_result)

        # Return a new HelpRequest for the chained operation, inheriting metadata
        return HelpRequest(chained_work, metadata=self.metadata)

    def _check_work(self):
        """Ensures the provided work item is a valid callable."""
        if not callable(self._work_callable):
            raise TypeError("Provided work_callable must be a callable function.")

    def __repr__(self):
        """Provides a clean representation for logging and debugging."""
        with self._lock:
            state = "DISPOSED" if self._disposed else self.get_state().name
            return f"<HelpRequest task_id={self.record.task_id}, state={state}>"
