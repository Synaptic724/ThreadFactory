import ulid
from thread_factory.utils import IDisposable
import inspect
import threading
from thread_factory.synchronization.primitives import Dynaphore
from typing import Optional, Callable, List, Union, Any
from thread_factory.synchronization.coordinators.clock_barrier import ClockBarrier
from thread_factory.synchronization.primitives.signal_barrier import SignalBarrier
from thread_factory.synchronization.primitives.flow_regulator import FlowRegulator
from thread_factory.utils.coordination.outcome import Outcome


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
        "_min_threshold", "_max_threshold", "tasks", "reusable", "manual_release", "_timeout", "_raise_on_timeout",
        "_id", "outcomes", "_released", "_broken", "_create_field", "_outcome_set",
        "_index", "_index_updater", "_new_index", "_lock", "_clock_barrier", "_signal_barrier", "_dynaphore",
        "_entrance_sema", "_internal_threshold_sema", "_flow_regulator"
    ]

    def __init__(
            self,
            min_threads: int,
            max_threads: Optional[int] = None,
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
        if min_threads <= 0:
            raise ValueError("Threshold must be a positive integer.")
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

        # Settings and validations
        self._max_threshold = max_threads
        self._min_threshold = min_threads
        self.reusable = reusable
        self.manual_release = manual_release
        self._timeout = timeout
        self._raise_on_timeout = raise_on_timeout

        # Outputs
        self._id = str(ulid.ULID())
        self.outcomes: List[Outcome] | None = None
        self.create_outcomes()  # Initialize outcomes for tasks

        # Initialize internal state
        self._released = False
        self._broken = False
        self._create_field = False
        self._outcome_set = False
        self._index = 0

        # Initialize synchronization primitives
        self._lock = threading.RLock()
        self._clock_barrier = None
        self._signal_barrier = None
        self._dynaphore = Dynaphore(self._min_threshold)
        self._entrance_sema = None
        self._internal_threshold_sema = None
        self._flow_regulator = FlowRegulator(0)
        self._index_updater = False


        if timeout is not None:
            if timeout <= 0:
                raise ValueError("Timeout must be a positive number.")
            self._clock_barrier = ClockBarrier(
                threshold=self._min_threshold,
                timeout=timeout,
                on_broken=self.notify_all_override
            )
        else:
            self._signal_barrier = SignalBarrier(self._min_threshold, reusable=True)


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
        with self._lock:
            self._disposed = True
            for obj in self.outcomes:
                obj.dispose()
            self.outcomes.clear()
            self._broken = True
            self._released = True

    def reset(self):
        """Resets the conductor to its initial state for reuse.

        This method is called internally by the `reusable` mode logic and should
        generally not be called publicly. It clears all previous outcomes.
        """
        for o in self.outcomes:
            o.dispose()
        self.create_outcomes()
        self._released = False
        self._broken = False
        if self._timeout is not None:
            self._clock_barrier.reset()
        elif self._signal_barrier is not None:
            self._signal_barrier.reset()

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
        with self._lock:
            if self._disposed: return
            if self.manual_release and not self._released:
                self._released = True
                self._lock.release()

    def notify_all_override(self) -> None:
        """Forcefully breaks the barrier and releases all waiting threads.

        This is an administrative override useful for shutdown or error handling.
        Waiting threads will receive a `False` return value from `wait()`.
        In reusable mode, the exiting threads are responsible for the reset.
        """
        with self._lock:
            if self._disposed or self._released: return
            self._released = True
            self._broken = True
            # This is where you would normally notify all, but a lock doesn't have a notify_all.
            # The wait() method will need to be updated to handle this change.

    def _clock_barrier_wait(self) -> bool:
        """Internal method to handle waiting with the ClockBarrier.

        This method is used to wait for the conductor's threshold using a
        ClockBarrier, which provides timeout functionality.

        Args:
            timeout (Optional[float]): A per-call timeout that can override
                the global timeout for this specific wait.

        Returns:
            bool: True if the threshold was met and tasks executed, False if
                the wait timed out or was broken by an override.
        """
        if self._clock_barrier is None:
            raise RuntimeError("ClockBarrier is not initialized. Use wait() instead.")
        try:
            return self._clock_barrier.wait()
        except Exception as e:
            if self._raise_on_timeout:
                raise TimeoutError(f"Conductor wait timed out after {self._timeout}s.") from e
            else:
                return True

    def _execute_operation(self, task: Callable) -> None:
        """
        Executes a single operation/task associated with the conductor.
        """
        try:
            self._set_result(task())
        except Exception as e:
            self._set_exception(e)
        self._reset_update_flags()

    def _get_new_index(self, index:int) -> None:
        """
        Returns the current index of the task being executed.
        This is used to track which task is currently being processed.
        """
        with self._lock:
            if self._index_updater:
                return
            self._index_updater = True
            self._index = index

    def _reset_update_flags(self):
        """
        Resets the flags used for updating the index and outcome state.
        This is called after the tasks have been executed.
        """
        with self._lock:
            if not self._outcome_set:
                return
            self._index_updater = False
            self._outcome_set = False

    def _execute_operations(self):
        """
        Executes the tasks associated with the conductor once the threshold is met.
        """
        if not self._create_field:
            with self._lock:
                if not self._create_field:
                    self._create_execute_operations_field()

            self._entrance_sema.wait()
        for index, task in enumerate(self.tasks):
            self._get_new_index(index)
            self._execute_operation(task)
            self._internal_threshold_sema.wait()

        if not self.manual_release:
            self._released = True

    def _set_result(self, result: Any):
        """
        Sets the result of the callable execution.
        This method is called internally after the callable completes.
        """
        if self._outcome_set:
            return
        with self._lock:
            if self._outcome_set:
                return
            self._outcome_set = True
            self.outcomes[self._index].set_result(result)

    def _set_exception(self, e: Exception):
        """
        Sets the exception of the callable execution.
        This method is called internally if the callable raises an exception.
        """
        if self._outcome_set:
            return
        with self._lock:
            if self._outcome_set:
                return
            self._outcome_set = True
            self.outcomes[self._index].set_exception(e)

    def _create_execute_operations_field(self):
        """Creates a field for executing operations.

        This method is used to ensure that the tasks are executed when the
        threshold is met. It can be overridden to customize the execution logic.
        """
        if not self.tasks:
            raise ValueError("No tasks provided to execute.")
        self.entrance_sema = SignalBarrier(self._min_threshold, reusable=False)
        self.internal_threshold_sema = SignalBarrier(self._min_threshold, reusable=True)
        self._create_field = True

    def wait(self) -> bool:
        """Blocks the calling thread until the conductor is released.

        Returns:
            bool: `True` for a successful release. `False` if the wait timed
                  out, the conductor was disposed, or it was broken by an override.

        Raises:
            TimeoutError: If `raise_on_timeout` is True and the wait times out.
        """
        if self._disposed or self._broken:
            return False

        # If already released and not reusable, it acts like an open latch.
        if self._released and not self.reusable:
            return True
        print("Step 1: Waiting for threshold...")
        try:
            # Wait for threshold based on config
            if self._timeout:
                was_released = self._clock_barrier_wait()
            else:
                was_released = self._signal_barrier.wait()
            print("Step 2: Waiting for tasks to execute...")
            # Block further entry until operation finishes
            self._dynaphore.wait_for_permit()
            print("Step 3: Executing operations...")
            try:
                # 🔧 Inject your actual execution logic here
                self._execute_operations()
            finally:
                print("Step 4: Closing conductor...")
                self._dynaphore.release()
        except Exception as e:
            was_released = False
            if self._raise_on_timeout:
                raise TimeoutError(f"Conductor wait timed out after {self._timeout}s.") from e
        print("Ending 1")
        # If timeout or error occurred, break the barrier
        if not was_released and not self._disposed:
            with self._lock:
                self._broken = True
                self._released = True
                # No notify_all() equivalent on RLock, so threads will unblock when they can acquire the lock.

        # Reset if reusable and last thread out
        if self.reusable and was_released:
            with self._lock:
                self.reset()
        # Return whether the conductor was successfully released
        print("Ending 2")

        return was_released and not self._disposed and not self._broken