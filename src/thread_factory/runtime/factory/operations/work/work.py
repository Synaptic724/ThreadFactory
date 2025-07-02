import inspect
from concurrent.futures import Future
from datetime import datetime
from typing import Optional, Callable, List
from ulid import ULID
from thread_factory.utils.interfaces.disposable import IDisposable # Assumed to raise NotImplementedError for dispose()
from thread_factory.runtime.orchestrator.monitoring.records.records import Record, WorkStatus
import threading

class Work(Future, IDisposable):
    """
    Work represents a self-contained unit of execution in the ThreadFactory ecosystem.
    (Existing docstring and attributes remain)
    """

    def __init__(self, fn: Callable, *args, priority: int = 0, metadata: Optional[dict] = None, **kwargs):
        super().__init__()
        IDisposable.__init__(self)
        # IDisposable.__init__(self) # No need to call if IDisposable is just an interface

        if not callable(fn):
            raise TypeError(f"Expected a callable, got type '{type(fn).__name__}' instead.")
        if inspect.iscoroutinefunction(fn):
            raise TypeError("Async coroutine functions are not supported in Work. Use regular functions.")

        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.priority = priority
        self.metadata = metadata or {}

        # Internal execution metadata
        self.task_id = id(self)
        self.worker_id = None
        self.queue_id = None
        self.retry_count = 0

        # State management
        self._work_state: WorkStatus = WorkStatus.PENDING # Renamed from _state to _work_state
        self._lock = threading.RLock()

        # Record object for task details
        self.record = Record(
            task_id=ULID(),
            status=self._work_state, # Use _work_state here
            timestamp_creation_time=datetime.now()
        )

        # Hook containers
        self.pre_hooks: List[Callable[['Work', str], None]] = []
        self.post_hooks: List[Callable[['Work', str], None]] = []

    def dispose(self):
        """
        Manually clear internal references and state for this Work object.
        This implementation does NOT call super().dispose() as per design.
        """
        with self._lock:
            if self._disposed:
                return
            self._disposed = True  # Manually set disposed flag

            # Clear resources specific to Work
            self.fn = None
            self.args = None
            self.kwargs = None
            self.metadata = None
            self.pre_hooks.clear()
            self.post_hooks.clear()
            self._done_callbacks = None

    def set_result(self, result):
        """Set the result of the Future and update Work's custom state."""
        super().set_result(result)
        self._set_custom_state(WorkStatus.COMPLETED)

    def set_exception(self, exception):
        """Set the exception of the Future and update Work's custom state."""
        super().set_exception(exception)
        self._set_custom_state(WorkStatus.FAILED)

    def cancel(self):
        """Cancel the Future and update Work's custom state."""
        if super().cancel():
            self._set_custom_state(WorkStatus.CANCELLED)
            return True
        return False

    def _set_custom_state(self, new_state: WorkStatus):
        """Internal helper to set Work's custom state and update the record."""
        with self._lock:
            self._work_state = new_state # Use _work_state here
            self.record.status = new_state
            # Update timestamps in record based on state change
            if new_state == WorkStatus.IN_PROGRESS and not self.record.timestamp_execution_time:
                self.record.timestamp_execution_time = datetime.now()
            elif new_state in [WorkStatus.COMPLETED, WorkStatus.FAILED, WorkStatus.CANCELLED] and not self.record.timestamp_completion_time:
                self.record.timestamp_completion_time = datetime.now()

    def run(self):
        """
        Run the task logic with full lifecycle tracking.
        This method relies on set_result/set_exception to update its custom state.
        """
        # Set to IN_PROGRESS via custom state
        if not self.set_running_or_notify_cancel():
            # If set_running_or_notify_cancel returns False, it means the Future was already cancelled.
            # In this case, ensure the Work's custom state is also CANCELLED.
            self._set_custom_state(WorkStatus.CANCELLED)
            return  # Task was already cancelled

        # Set Work's custom state to IN_PROGRESS AFTER Future's state has transitioned
        # (set_running_or_notify_cancel implicitly puts Future in RUNNING)
        self._set_custom_state(WorkStatus.IN_PROGRESS)


        try:
            self.execute_pre_hooks()
            result = self.fn(*self.args, **self.kwargs)
            self.set_result(result) # This will call _set_custom_state(COMPLETED)
        except Exception as e:
            self.set_exception(e) # This will call _set_custom_state(FAILED)
        finally:
            self.execute_post_hooks()
            # IMPORTANT: DO NOT call self.dispose() here or set self.record = None.
            # The Worker's _execute_task will handle calling dispose on this Work object
            # and collecting its record once Work.run() completes.

    def add_done_callback(self, fn: Callable[['Work'], None]):
        """
        Add a callback to be executed when the Work is done.
        This callback will receive the Work instance itself.
        """
        if not callable(fn):
            raise TypeError(f"Expected a callable, got type '{type(fn).__name__}' instead.")
        super().add_done_callback(fn)

    def add_hook(self, hook: Callable[['Work', str], None], phase: str):
        """
        Register a hook to be executed before or after the task execution.

        Args:
            hook (Callable[['Work', str], None]): The hook function to register.
            phase (str): Either "before" for pre-execution or "after" for post-execution hooks.

        Raises:
            ValueError: If phase is not "before" or "after".
        """
        if not callable(hook):
            raise TypeError(f"Expected a callable, got type '{type(hook).__name__}' instead.")
        if phase == "before":
            self.pre_hooks.append(hook)
        elif phase == "after":
            self.post_hooks.append(hook)
        else:
            raise ValueError("Phase must be either 'before' or 'after'.")

    def execute_pre_hooks(self):
        """
        Execute all registered pre-execution hooks.
        """
        for hook in self.pre_hooks:
            try:
                hook(self, "before")
            except Exception as ex:
                # If a pre-hook fails, the task should be marked as failed.
                self.set_exception(ex) # Set Future exception, which updates custom state to FAILED
                raise # Re-raise to stop main function execution

    def execute_post_hooks(self):
        """
        Execute all registered post-execution hooks.
        """
        for hook in self.post_hooks:
            try:
                hook(self, "after")
            except Exception as ex:
                # Post-hook failures are typically logged but don't change task status.
                print(f"Warning: Post-hook failed for task {self.task_id}: {ex}")

    def status(self) -> str:
        """
        Get a human-readable status string for the Work item based on its custom state.
        """
        with self._lock:
            # Use _work_state here
            if self._work_state == WorkStatus.CANCELLED:
                return "cancelled"
            elif self._work_state == WorkStatus.COMPLETED:
                return "completed"
            elif self._work_state == WorkStatus.IN_PROGRESS:
                return "running"
            elif self._work_state == WorkStatus.PENDING:
                return "pending"
            elif self._work_state == WorkStatus.FAILED:
                return "failed"
            else:
                return f"unknown({self._work_state})"

    def __enter__(self):
        """Enable Work to be used with a `with` statement."""
        return self

    def __repr__(self):
        """Provide a concise summary of the Work unit's metadata and state."""
        with self._lock:
            base_repr = super().__repr__()
        meta = f"id={self.task_id} priority={self.priority}"
        if self._disposed:
            meta += " disposed=True"
        return f"<Work {meta} state={self._work_state.name} base={base_repr}>" # Use _work_state here