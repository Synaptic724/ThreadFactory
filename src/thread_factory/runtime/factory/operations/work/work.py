import inspect
import time
from concurrent.futures import Future
from typing import Optional, Callable, List, Any
from thread_factory.utils import IDisposable

class Work(Future, IDisposable):
    """
    Work represents a self-contained unit of execution in the ThreadFactory ecosystem.

    It extends `concurrent.futures.Future`, providing:
    - Lifecycle-aware execution with pre/post hooks
    - Execution tracking metadata and timing metrics
    - Manual resource disposal support
    - Restriction against coroutine usage to maintain thread safety and determinism

    This is the core abstraction around "what gets done" in ThreadFactory.
    """

    def __init__(self, fn: Callable, *args, priority: int = 0, metadata: Optional[dict] = None, **kwargs):
        """
        Create a new Work item wrapping the given function and arguments.

        Args:
            fn (Callable): A regular function to be executed (no coroutine support).
            *args: Positional arguments for the function.
            priority (int): Optional scheduling priority for queue-aware systems.
            metadata (dict): Optional dictionary to attach contextual data.
            **kwargs: Keyword arguments for the function.

        Raises:
            TypeError: If `fn` is not a callable or is a coroutine function.
        """
        super().__init__()
        IDisposable.__init__(self)
        if not callable(fn):
            raise TypeError(f"Expected a callable, got type '{type(fn).__name__}' instead.")
        if inspect.iscoroutinefunction(fn):
            raise TypeError("Async coroutine functions are not supported in Work. Use regular functions.")

        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.priority = priority

        # Internal execution metadata
        self.task_id = id(self)
        self.worker_id = None
        self.queue_id = None
        self.retry_count = 0
        self.metadata = metadata or {}

        # Timing fields
        self.timestamp_created = time.perf_counter_ns()
        self.timestamp_started = None
        self.timestamp_finished = None
        self.duration_ns = None

        # Hook containers
        self.pre_hooks: List[Callable[['Work', str], None]] = []
        self.post_hooks: List[Callable[['Work', str], None]] = []

    def run(self):
        """
        Run the task logic with full lifecycle tracking.

        - Marks the task as running (thread-safe).
        - Executes all registered pre-hooks.
        - Executes the user-supplied function.
        - Captures exceptions if any arise.
        - Executes all post-hooks regardless of outcome.
        - Records execution timing and metadata.
        """
        if not self.set_running_or_notify_cancel():
            return  # Task was already cancelled

        self.timestamp_started = time.perf_counter_ns()

        try:
            self.execute_pre_hooks()
            result = self.fn(*self.args, **self.kwargs)
            self.set_result(result)
        except Exception as e:
            self.set_exception(e)
        finally:
            self.timestamp_finished = time.perf_counter_ns()
            self.duration_ns = self.timestamp_finished - self.timestamp_started
            self.execute_post_hooks()

    def add_done_callback(self, fn):
        """
        Attach a callback to be invoked once the task completes.

        Notes:
        - Callbacks will run in the same thread that completes the task.
        - Cannot register coroutine functions as callbacks.
        - Callbacks are triggered in order of registration.

        Args:
            fn (Callable): Function accepting a single argument — the Work instance.

        Raises:
            TypeError: If the callback is a coroutine function.
        """
        if inspect.iscoroutinefunction(fn):
            raise TypeError("Async coroutine functions are not supported in Work. Use a regular function.")
        super().add_done_callback(fn)

    def add_hook(self, hook: Callable[['Work', str], None], phase: str = "both"):
        """
        Register a lifecycle hook to execute before or after the task.

        Args:
            hook (Callable): A regular function accepting (work_instance, phase:str).
            phase (str): One of "before", "after", or "both".

        Raises:
            TypeError: If hook is a coroutine function.
        """
        if inspect.iscoroutinefunction(hook):
            raise TypeError("Async coroutine hooks are not supported in Work.")

        if phase in ("before", "both"):
            self.pre_hooks.append(hook)
        if phase in ("after", "both"):
            self.post_hooks.append(hook)

    def execute_pre_hooks(self):
        """
        Execute all registered pre-execution hooks.
        Any exception raised will be captured as task failure.
        """
        for hook in self.pre_hooks:
            try:
                hook(self, "before")
            except Exception as ex:
                self.set_exception(ex)

    def execute_post_hooks(self):
        """
        Execute all registered post-execution hooks.
        Any exception raised will be captured as task failure.
        """
        for hook in self.post_hooks:
            try:
                hook(self, "after")
            except Exception as ex:
                self.set_exception(ex)

    def status(self) -> str:
        """
        Get a human-readable status string for the Work item.

        Returns:
            str: One of "cancelled", "completed", "running", "pending", or "unknown(...)"
        """
        with self._condition:
            if self._state in {"CANCELLED", "CANCELLED_AND_NOTIFIED"}:
                return "cancelled"
            elif self._state == "FINISHED":
                return "completed"
            elif self._state == "RUNNING":
                return "running"
            elif self._state == "PENDING":
                return "pending"
            else:
                return f"unknown({self._state})"

    def __enter__(self):
        """
        Allow Work to be used in a `with` statement for deterministic disposal.
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Automatically dispose Work object on exit from context manager.
        """
        self.dispose()

    def dispose(self):
        """
        Manually clear internal references and state.

        Safe to call multiple times. This does NOT clear result or exception.
        Intended for memory-sensitive systems where holding references is expensive.
        """
        with self._condition:
            if self.disposed:
                return
            self.disposed = True

            self.fn = None
            self.args = None
            self.kwargs = None
            self.metadata = None
            self.pre_hooks.clear()
            self.post_hooks.clear()
            self._done_callbacks.clear()
            self._result = None
            self._exception = None

            self._condition.notify_all()

    def __repr__(self):
        """
        Render a concise summary of the Work unit's metadata and state.
        """
        with self._condition:
            base_repr = super().__repr__()

        meta = f"id={self.task_id} priority={self.priority}"
        if self.disposed:
            meta += " disposed=True"

        return f"<Work {meta} base={base_repr}>"
