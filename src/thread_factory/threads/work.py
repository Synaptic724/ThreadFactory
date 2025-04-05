import time
import threading
from concurrent.futures import Future
from typing import Optional, Callable, List
from thread_factory.utils import Disposable
import asyncio

class Work(Future, Disposable):
    """
    Work represents a unit of execution within the ThreadFactory framework.
    It extends Python's concurrent.futures.Future and includes:
      - Execution metadata
      - Hook support before and after execution
      - Auto-disposal functionality
      - Clean cancellation support
    """

    def __init__(self, fn, *args, priority: int = 0, auto_dispose=True, metadata: Optional[dict] = None, **kwargs):
        """
        Initialize a new Work object.

        Args:
            fn (callable): The function to execute.
            *args: Positional arguments to pass to the function.
            priority (int): Optional priority (used by scheduling systems).
            auto_dispose (bool): If True, auto-clears data after execution.
            metadata (dict): Optional user metadata.
            **kwargs: Additional keyword arguments for the function.
        """
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.priority = priority
        self.disposed = False
        self._auto_dispose = auto_dispose

        # Execution tracking metadata
        self.task_id = id(self)
        self.worker_id = None
        self.queue_id = None
        self.retry_count = 0
        self.metadata = metadata or {}

        # Timing metrics
        self.timestamp_created = time.perf_counter_ns()
        self.timestamp_started = None
        self.timestamp_finished = None
        self.duration_ns = None

        # Synchronization object (inherited but overridden for internal locking)
        self._condition = threading.Condition()

        # Lifecycle hook containers
        self.pre_hooks: List[Callable[['Work', str], None]] = []
        self.post_hooks: List[Callable[['Work', str], None]] = []

    def run(self):
        """
        Execute the assigned function and set the result or exception.
        - Calls all pre-hooks
        - Executes the function
        - Calls all post-hooks
        - Disposes the work item if auto_dispose is enabled, and it wasn't already cancelled
        """
        if not self.set_running_or_notify_cancel():
            # Task was cancelled before execution; cancel() already handled dispose
            return

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

            if self._auto_dispose:
                self.dispose()

    def execute_pre_hooks(self):
        """
        Execute all registered pre-execution hooks.
        Raises RuntimeError if any pre-hook fails.
        """
        try:
            for hook in self.pre_hooks:
                hook(self, "before")
        except Exception as ex:
            self.set_exception(ex)

    def execute_post_hooks(self):
        """
        Execute all registered post-execution hooks.
        Raises RuntimeError if any post-hook fails.
        """
        try:
            for hook in self.post_hooks:
                hook(self, "after")
        except Exception as ex:
            self.set_exception(ex)

    def cancel(self):
        """
        Attempt to cancel the task. If cancellation is successful:
        - Marks cancel_requested
        - Injects CancelledError if the task hadn't started
        - Disposes the work object if auto_dispose is enabled

        Returns:
            bool: True if successfully cancelled, False otherwise.
        """
        with self._condition:
            # Ask the base class to cancel (this checks _state)
            success = super().cancel()

            if success:
                if self._auto_dispose:
                    self._result = None
                    self._exception = None
                    self.dispose()

            return success

    def status(self) -> str:
        """
        Returns a string representing the current internal state of the Work item.

        Returns:
            str: One of "cancelled", "completed", "running", or "pending".
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


    def add_hook(self, hook: Callable[['Work', str], None], phase: str = "both"):
        """
        Register a hook to run at a particular lifecycle phase.

        Args:
            hook (callable): Function accepting (work_instance, phase:str)
            phase (str): One of "before", "after", or "both"
        """
        if phase in ("before", "both"):
            self.pre_hooks.append(hook)
        if phase in ("after", "both"):
            self.post_hooks.append(hook)

    def result(self, timeout=None):
        """
        Override to provide automatic disposal after result retrieval.

        Args:
            timeout (float): Optional timeout in seconds.
        Returns:
            Any: The result of the function, if successful.
        """
        try:
            return super().result(timeout)
        finally:
            if self._auto_dispose:
                self._result = None  # Clear after retrieval
                self.dispose()

    def exception(self, timeout=None):
        """
        Override to provide automatic disposal after exception retrieval.

        Args:
            timeout (float): Optional timeout in seconds.
        Returns:
            Exception or None
        """
        try:
            return super().exception(timeout)
        finally:
            if self._auto_dispose:
                self._exception = None
                self.dispose()

    def __await__(self):
        """
        Make Work awaitable by wrapping it in an asyncio Future.
        Ensures there's an active event loop.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            raise RuntimeError("No running event loop; cannot await Work instance")

        return asyncio.wrap_future(self, loop=loop).__await__()

    def dispose(self):
        """
        Clear references and metadata. Safe to call multiple times.
        Ensures cleanup for memory-sensitive applications.
        """
        with self._condition:
            if self.disposed:
                return  # silently skip instead of raising

            self.disposed = True
            self.fn = None
            self.args = None
            self.kwargs = None
            self.metadata = None
            self.pre_hooks.clear()
            self.post_hooks.clear()
            self._done_callbacks.clear()

            self._condition.notify_all()

    def __repr__(self):
        """
        Pretty-print the Work object including internal Future state.
        """
        with self._condition:
            base_repr = super().__repr__()

        meta = f"id={self.task_id} priority={self.priority}"
        if self.disposed:
            meta += " disposed=True"

        return f"<Work {meta} base={base_repr}>"
