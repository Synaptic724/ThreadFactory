import time
from concurrent.futures import Future
from typing import Optional, Callable


class Work(Future):
    """
    Work represents a unit of execution within the ThreadFactory framework.
    Extends concurrent.futures.Future with additional metadata and lifecycle management.
    """

    def __init__(self, fn, *args, priority: int = 0, metadata: Optional[dict] = None, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.priority = priority

        # Metadata
        self.task_id = id(self)
        self.worker_id = None
        self.queue_id = None
        self.retry_count = 0
        self.cancel_requested = False
        self.metadata = metadata or {}

        # Timing
        self.timestamp_created = time.perf_counter_ns()
        self.timestamp_started = None
        self.timestamp_finished = None
        self.duration_ns = None

        # Optional hooks
        self.hooks = []

    def run(self):
        """
        Execute the assigned function and set the result or exception.
        Records timing automatically.
        """
        if self.cancel_requested:
            self.set_exception(RuntimeError("Task was cancelled before execution"))
            return

        self.timestamp_started = time.perf_counter_ns()
        try:
            # Pre-hooks
            for hook in self.hooks:
                hook(self, "before")

            result = self.fn(*self.args, **self.kwargs)
            self.set_result(result)
        except Exception as e:
            self.set_exception(e)
        finally:
            self.timestamp_finished = time.perf_counter_ns()
            self.duration_ns = self.timestamp_finished - self.timestamp_started

            # Post-hooks
            for hook in self.hooks:
                hook(self, "after")

    def add_hook(self, hook: Callable[['Work', str], None]):
        """
        Register a pre- / post-hook for task lifecycle events.
        Hooks receive (self, phase) where phase is 'before' or 'after'.
        """
        self.hooks.append(hook)

    def __repr__(self):
        state = self._state if hasattr(self, '_state') else "UNKNOWN"
        return f"<Work id={self.task_id} priority={self.priority} state={state}>"
