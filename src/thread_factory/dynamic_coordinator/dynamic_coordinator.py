from typing import Callable, Optional
import threading
from typing import Callable, Optional, List
from thread_factory.utils import IDisposable
from thread_factory.primitives.threshold_semaphore import ThresholdSemaphore


class DynamicCoordinator(IDisposable):
    """
    DynamicCoordinator
    ------------------
    A coordination primitive for dynamic thread groups.

    The calling thread *participates* as a worker.

    Threads join the coordinator via `run()`, which blocks until enough threads
    have arrived to meet the required `group_size`. Once the group is complete,
    the provided `callable` is executed by all participating threads (including the caller).

    Behavior:
    - Requires at least `group_size` threads to proceed.
    - If `strict=True`, throws if not enough threads are available.
    - If `strict=False`, allows partial groups and ensures initiator thread still runs the task.

    Parameters:
        group_size (int): Required number of threads.
        fn (Callable): The task to be executed by all participants.
        strict (bool): Whether to enforce exact group count (default: True).

    Example::

        def group_task():
            print(f"Thread running in group: {threading.current_thread().name}")

        coordinator = DynamicCoordinator(group_size=3, fn=group_task, strict=True)

        # Assume you have a pool, you'd do something like:
        for _ in range(2):
            pool.submit(coordinator.run)

        # And then the initiating thread calls:
        coordinator.run()
    """

    def __init__(self, group_size: int, fn: Callable, strict: bool = True):
        if group_size <= 0:
            raise ValueError("group_size must be positive")

        super().__init__()
        self.group_size = group_size
        self.fn = fn
        self.strict = strict

        self._lock = threading.Lock()
        self._barrier = ThresholdSemaphore(threshold=group_size, reusable=False, callback=self._trigger_execution)
        self._execution_ready = threading.Event()
        self._exceptions: List[BaseException] = []

    def _trigger_execution(self):
        """Called once threshold is met; sets event to release waiting threads."""
        self._execution_ready.set()

    def run(self):
        """
        Join the group and execute the shared task once the group is formed.
        The calling thread is part of the execution group.
        """
        if self._disposed:
            raise RuntimeError("Coordinator has been disposed.")

        released = self._barrier.wait()

        if not released:
            if self.strict:
                raise RuntimeError(f"DynamicCoordinator failed to form required group of {self.group_size}.")
            # Soft mode: just execute alone
            try:
                self.fn()
            except BaseException as e:
                with self._lock:
                    self._exceptions.append(e)
            return

        # Wait for signal
        self._execution_ready.wait()

        # Execute shared task
        try:
            self.fn()
        except BaseException as e:
            with self._lock:
                self._exceptions.append(e)

    def get_exceptions(self) -> List[BaseException]:
        """Returns any exceptions encountered by group members."""
        with self._lock:
            return list(self._exceptions)

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        self._barrier.dispose()
        self._execution_ready.set()

class GroupPlan:
    def __init__(
        self,
        required: int,
        task: Callable,
        synchronized: bool = True,         # Must get all N or throw
        allow_partial: bool = False,       # Try with fewer if needed
        fallback_fn: Optional[Callable] = None,  # Alternative work plan
        strict: bool = True,               # Whether to throw or ignore
        metadata: Optional[dict] = None,   # For tracing/debug/logging
    ):
        pass
