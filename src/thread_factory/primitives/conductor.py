import inspect
import threading
import time
from typing import Optional, Callable, List, Union, Any
from thread_factory.utils import IDisposable


class Conductor(IDisposable):
    """A reusable, data-aware barrier for synchronizing threads.

    The Conductor blocks a group of threads until a specified threshold is met.
    Once the threshold is reached, it can optionally execute a series of tasks,
    capture their results and exceptions, and then release all waiting threads.

    It serves as a powerful synchronization primitive for scenarios like:
    - Ensuring N worker threads are ready before starting a computation.
    - Coordinating distinct phases of a multi-threaded operation.
    - Launching a set of dependent tasks only after setup is complete.

    Key Features:
    - **Data-Aware**: Executes tasks and captures their results or exceptions.
    - **Reusable**: Can be configured to reset itself automatically for use in loops.
    - **Manual Control**: Supports manual release for fine-grained control.
    - **Timeout Capable**: Can be configured with a global timeout to prevent deadlocks.
    - **Thread-Safe**: Designed for safe use in concurrent applications.

    Usage Example:
        def my_task():
            print("Threshold met, executing task!")
            return "Task Complete"

        # Create a conductor that waits for 3 threads and runs one task.
        conductor = Conductor(threshold=3, tasks=my_task)

        def worker(thread_id):
            print(f"Thread {thread_id} is ready and waiting.")
            was_released = conductor.wait(timeout=5)
            if was_released:
                print(f"Thread {thread_id} has been released.")
            else:
                print(f"Thread {thread_id} was not released (timeout/disposed).")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        print(f"Conductor results: {conductor.results}")
    """
    __slots__ = IDisposable.__slots__ + [
        "threshold", "tasks", "reusable", "manual_release",
        "_timeout", "_raise_on_timeout", "outcomes",
        "_lock", "_condition", "_count", "_released", "_broken", "_start_time"
    ]

    def __init__(
            self,
            threshold: int,
            tasks: Optional[Union[Callable, List[Callable]]] = None,
            reusable: bool = False,
            manual_release: bool = False,
            timeout: Optional[float] = None,
            raise_on_timeout: bool = False
    ):
        """Initializes the Conductor.

        Args:
            threshold (int): The number of threads required to trigger the release.
            tasks (Optional): A single function or a list of functions to be
                executed once the threshold is met.
            reusable (bool): If True, the conductor resets after all threads from
                a cycle have passed, allowing it to be used again. Defaults to False.
            manual_release (bool): If True, the conductor will not release threads
                automatically when the threshold is met. `release()` must be
                called explicitly. Defaults to False.
            timeout (Optional[float]): A global timeout in seconds. If the
                threshold is not met within this time from when the first thread
                arrives, the conductor will break and release all threads.
            raise_on_timeout (bool): If True, raises a `TimeoutError` when the
                global timeout is exceeded instead of returning False.
        """
        super().__init__()
        if threshold <= 0:
            raise ValueError("Threshold must be a positive integer.")

        self.threshold = threshold
        self.reusable = reusable
        self.manual_release = manual_release
        self._timeout = timeout
        self._raise_on_timeout = raise_on_timeout

        self.tasks: List[Callable] = []
        if tasks:
            task_list = [tasks] if callable(tasks) else tasks
            if not isinstance(task_list, list) or not all(callable(cb) for cb in task_list):
                raise TypeError("tasks must be a callable function or a list of callables.")

            # Ensure all provided tasks are synchronous.
            for task in task_list:
                if inspect.iscoroutinefunction(task):
                    raise TypeError("Coroutines are not supported; only synchronous callables are allowed.")
                self.tasks.append(task)
        self.outcomes = None
        self.create_outcomes()  # Initialize outcomes for tasks
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._count = 0
        self._released = False
        self._broken = False
        self._start_time = None

    def create_outcomes(self) -> None:
        """Creates Outcome objects for each task.

        This method is called internally to ensure that outcomes are created
        when the conductor is initialized or reset.
        """
        from thread_factory.utils import Outcome
        self.outcomes = [Outcome() for _ in self.tasks]

    def dispose(self):
        """Safely terminates the conductor, releasing all waiting threads.

        This method cleans up all internal resources, including any associated
        Outcome objects. Once disposed, the conductor cannot be used again.
        This operation is idempotent (safe to call multiple times).
        """
        if self._disposed: return
        with self._condition:
            self._disposed = True
            for outcome in self.outcomes: outcome.dispose()
            self.outcomes.clear()
            self._broken = True
            self._released = True
            self._condition.notify_all()

    def reset(self):
        """Resets the conductor to its initial state for reuse.

        This method is called internally by the `reusable` mode logic and should
        generally not be called publicly. It clears all previous outcomes.
        """
        for o in self.outcomes: o.dispose()
        self.create_outcomes()
        self._released = False
        self._broken = False
        self._start_time = None
        self._count = 0

    @property
    def results(self) -> List[Any]:
        """A convenience property to get a list of successful task results."""
        if self._disposed: return []
        return [o.result() for o in self.outcomes if o.done and o.exception() is None]

    @property
    def exceptions(self) -> List[Exception]:
        """A convenience property to get a list of captured task exceptions."""
        if self._disposed: return []
        return [o.exception() for o in self.outcomes if o.done and o.exception() is not None]

    def is_spent(self) -> bool:
        """Checks if the conductor has completed its run and is not reusable.

        Returns:
            bool: True if the conductor has been released and `reusable` is False.
        """
        return self._released and not self.reusable

    def release(self) -> None:
        """Manually releases waiting threads.

        This method is only effective when `manual_release=True` and the
        thread count has already met or exceeded the threshold.
        """
        with self._condition:
            if self._disposed: return
            if self.manual_release and self._count >= self.threshold and not self._released:
                self._released = True
                self._condition.notify_all()

    def notify_all_override(self) -> None:
        """Forcefully breaks the barrier and releases all waiting threads.

        This is an administrative override useful for shutdown or error handling.
        Waiting threads will receive a `False` return value from `wait()`.
        In reusable mode, the exiting threads are responsible for the reset.
        """
        with self._condition:
            if self._disposed or self._released: return
            self._released = True
            self._broken = True
            self._condition.notify_all()

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Blocks the calling thread until the conductor is released.

        Args:
            timeout (Optional[float]): A per-call timeout that can override
                the global timeout for this specific wait.

        Returns:
            bool: `True` for a successful release. `False` if the wait timed
                out, the conductor was disposed, or it was broken by an override.

        Raises:
            TimeoutError: If the global `raise_on_timeout` is True and the
                wait times out.
        """
        with self._condition:
            # Check for terminal states first.
            if self._disposed: return False
            if self._broken: return False
            # If a non-reusable conductor is already released, it acts as an open latch.
            if self._released and not self.reusable: return True

            if self._start_time is None: self._start_time = time.monotonic()

            self._count += 1

            # The thread that meets the threshold is responsible for execution.
            if self._count == self.threshold and not self._released:
                for i, task in enumerate(self.tasks):
                    outcome = self.outcomes[i]
                    try:
                        result = task()
                        outcome.set_result(result)
                    except Exception as e:
                        outcome.set_exception(e)

                if not self.manual_release:
                    self._released = True
                    self._condition.notify_all()

            # Calculate the remaining time to wait, considering the global timeout.
            effective_timeout = timeout if timeout is not None else self._timeout
            remaining = effective_timeout
            if self._start_time is not None and effective_timeout is not None:
                elapsed = time.monotonic() - self._start_time
                remaining = max(0, effective_timeout - elapsed)

            was_released = self._condition.wait_for(
                lambda: self._released or self._disposed, timeout=remaining
            )

            # Capture the state AT THIS MOMENT, before any reset logic runs.
            # This is the critical fix for the reusable/override race condition.
            is_broken_on_exit = self._broken

            # Handle the case where the wait ended due to timeout.
            if not was_released and not self._disposed:
                self._broken = True
                self._released = True  # Release any other waiting threads.
                self._condition.notify_all()
                if self._raise_on_timeout:
                    raise TimeoutError(f"Conductor wait timed out after {effective_timeout}s.")

            # In reusable mode, the last thread out resets the conductor.
            if self.reusable and self._released:
                self._count -= 1
                if self._count == 0:
                    self.reset()

            # The final return value depends on the captured "broken" state.
            return was_released and not self._disposed and not is_broken_on_exit