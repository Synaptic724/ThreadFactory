from __future__ import annotations
import ulid
from thread_factory.utils import IDisposable
import inspect
import threading
from thread_factory.synchronization.primitives import Dynaphore
from typing import Optional, Callable, List, Union, Any, Dict
from thread_factory.synchronization.coordinators.clock_barrier import ClockBarrier
from thread_factory.synchronization.primitives.signal_barrier import SignalBarrier
from thread_factory.synchronization.primitives.flow_regulator import FlowRegulator
from thread_factory.concurrency import ConcurrentDict, ConcurrentList # Import ConcurrentList
from thread_factory.utils.coordination.outcome import Outcome


class Conductor(IDisposable):
    """A reusable, data-aware synchronization point and work executor.

    The Conductor blocks a group of threads until a specified threshold is met.
    Once the threshold is reached, it can optionally execute a series of tasks,
    capture their results and exceptions, and then release all waiting threads.

    It effectively acts as a dynamic barrier that can also manage and collect
    outcomes from a coordinated execution phase, making it suitable for managing
    batches of work in a multi-threaded environment.

    It serves as a powerful synchronization primitive for scenarios like:
    - Ensuring N worker threads are ready before starting a computation.
    - Coordinating distinct phases of a multi-threaded operation.
    - Launching a set of dependent tasks only after setup is complete.

    Key Features:
    - **Data-Aware**: Executes tasks and robustly captures their results or exceptions, holding them until explicitly cleared.
    - **Reusable**: Designed for repeated use across multiple cycles of coordination. For reusable instances, results from a completed cycle persist until `reset()` is manually called by the user, allowing for thorough inspection and collection before the next cycle.
    - **Result Persistence**: Captured outcomes are held by the Conductor instance after a cycle completes until `reset()` is explicitly invoked or `dispose()` is called.
    - **Manual Control**: Supports explicit `release()` for fine-grained control when `manual_release` is enabled, allowing threads to proceed only when externally commanded.
    - **Timeout Capable**: Can be configured with a global timeout to prevent deadlocks if the threshold is not met within a specified duration.
    - **Thread-Safe**: Internally designed with robust synchronization primitives for safe concurrent use across multiple threads.
    """
    __slots__ = IDisposable.__slots__ + [
        "_threshold", "tasks", "reusable", "manual_release", "_timeout", "_raise_on_timeout",
        "_id", "outcomes", "_released", "_broken", "_create_field", "_multiple_outcomes_per_task",
        "_lock", "_clock_barrier", "_signal_barrier", "_dynaphore", "_internal_threshold_barrier", "_flow_regulator"
    ]

    def __init__(
            self,
            threshold: int,
            tasks: Optional[Union[Callable, List[Callable]]] = None,
            reusable: bool = False,
            manual_release: bool = False,
            timeout: Optional[float] = None,
            raise_on_timeout: bool = False,
            multiple_outcomes_per_task: bool = False # New flag
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
            multiple_outcomes_per_task (bool): If True, each task index can store
                multiple Outcome objects (e.g., if multiple threads attempt the same task).
                If False, only the first Outcome set for a given index is stored. Defaults to False.
        """
        super().__init__()
        if threshold <= 0:
            raise ValueError("Threshold must be a positive integer.")
        self._threshold = threshold
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
        self.reusable = reusable
        self.manual_release = manual_release
        self._timeout = timeout
        self._raise_on_timeout = raise_on_timeout
        self._multiple_outcomes_per_task = multiple_outcomes_per_task # Store the new flag

        # Outputs
        self._id = str(ulid.ULID())
        # Use ConcurrentDict for thread-safe dictionary operations
        # The type hint for outcomes is updated to reflect ConcurrentList
        self.outcomes: ConcurrentDict[int, Union[Outcome, ConcurrentList[Outcome]]] = ConcurrentDict()

        # Initialize internal state
        self._released = False
        self._broken = False
        self._create_field = False

        # Initialize synchronization primitives
        self._lock = threading.RLock()
        self._clock_barrier = None
        self._signal_barrier = None
        self._internal_threshold_barrier = None
        self._dynaphore = Dynaphore(self._threshold)
        self._flow_regulator = FlowRegulator(0)

        if timeout is not None:
            if timeout <= 0:
                raise ValueError("Timeout must be a positive number.")
            self._clock_barrier = ClockBarrier(
                threshold=self._threshold,
                timeout=timeout,
                on_broken=self.notify_all_override
            )
        else:
            self._signal_barrier = SignalBarrier(self._threshold, reusable=True)


    def dispose(self):
        """Safely terminates the conductor, releasing all waiting threads.

        This method cleans up all internal resources, including any associated
        Outcome objects. Once disposed, the conductor cannot be used again.
        This operation is idempotent (safe to call multiple times).
        """
        if self._disposed: return
        with self._lock: # Keep this lock for overall Conductor state
            self._disposed = True
            if self._clock_barrier:
                self._clock_barrier.dispose()
            if self._signal_barrier:
                self._signal_barrier.dispose()
            if self._internal_threshold_barrier:
                self._internal_threshold_barrier.dispose()
            if self._dynaphore:
                self._dynaphore.dispose()
            if self.outcomes:
                for key, value in self.outcomes.items():
                    if self._multiple_outcomes_per_task:
                        # value is ConcurrentList[Outcome]
                        for obj in value:
                            obj.dispose()
                    else: # value is single Outcome
                        value.dispose()
            self.outcomes.clear()
            self._broken = True
            self._released = True

    def reset(self):
        """Resets the conductor to its initial state for reuse.

        This method is called internally by the `reusable` mode logic and should
        generally not be called publicly. It clears all previous outcomes.
        """
        if self.reusable:
            if self.outcomes:
                for key, value in self.outcomes.items():
                    if self._multiple_outcomes_per_task:
                        # value is ConcurrentList[Outcome]
                        for obj in value:
                            obj.dispose()
                    else: # value is single Outcome
                        value.dispose()
            self.outcomes.clear()

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
        successful = []
        for key, value in self.outcomes.items():
            outcomes_to_check = value if self._multiple_outcomes_per_task else [value]
            for o in outcomes_to_check:
                if o.done and o.exception() is None:
                    try:
                        successful.append(o.result())
                    except Exception:
                        pass
        return successful

    @property
    def exceptions(self) -> List[Exception]:
        """A convenience property to get a list of captured task exceptions."""
        if self._disposed: return []
        errors = []
        for key, value in self.outcomes.items():
            outcomes_to_check = value if self._multiple_outcomes_per_task else [value]
            for o in outcomes_to_check:
                if o.done:
                    exc = o.exception()
                    if exc is not None and not (isinstance(exc, RuntimeError) and str(exc) == "Outcome was disposed."):
                        try:
                            errors.append(exc)
                        except Exception:
                            pass
        return errors

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
                raise TimeoutError(f"Conductor wait timed out after {self._timeout}s.")
            else:
                return True

    def _execute_operation(self, task: Callable, index: int) -> None:
        """
        Executes a single operation/task associated with the conductor.
        """
        try:
            print("Starting Task Execution")
            self._set_result(task(), index)
        except Exception as e:
            self._set_exception(e, index)
        print("Task Execution Completed")

    def _execute_operations(self):
        """
        Executes the tasks associated with the conductor once the threshold is met.
        """
        print("Tasks to execute:", len(self.tasks))
        for index, task in enumerate(self.tasks):
            self._execute_operation(task, index)
            self._internal_threshold_barrier.wait() # Still commented out, which is fine for single thread.
        print("Tasks to execute:", len(self.tasks))
        if not self.manual_release:
            self._released = True

    def _set_result(self, result: Any, index: int):
        """
        Sets the result of the callable execution.
        This method is called internally after the callable completes.
        It creates the Outcome object(s) for the given index.
        """
        print(index)
        if self._multiple_outcomes_per_task:
            # Get or create the ConcurrentList for this index
            # ConcurrentDict's setdefault is thread-safe for the dict operation
            outcome_list = self.outcomes.setdefault(index, ConcurrentList())
            # Now, append to the ConcurrentList (which is thread-safe)
            new_outcome = Outcome()
            new_outcome.set_result(result)
            outcome_list.append(new_outcome)
        else:
            # Use setdefault for idempotent creation of a single Outcome
            outcome_obj = self.outcomes.setdefault(index, Outcome())
            outcome_obj.set_result(result)


    def _set_exception(self, e: Exception, index: int):
        """
        Sets the exception of the callable execution.
        This method is called internally if the callable raises an exception.
        It creates the Outcome object(s) for the given index.
        """
        print(index)
        if self._multiple_outcomes_per_task:
            # Get or create the ConcurrentList for this index
            outcome_list = self.outcomes.setdefault(index, ConcurrentList())
            # Now, append to the ConcurrentList (which is thread-safe)
            new_outcome = Outcome()
            new_outcome.set_exception(e)
            outcome_list.append(new_outcome)
        else:
            # Use setdefault for idempotent creation of a single Outcome
            outcome_obj = self.outcomes.setdefault(index, Outcome())
            outcome_obj.set_exception(e)


    def _create_execute_operations_field(self):
        """Creates a field for executing operations.

        This method is used to ensure that the tasks are executed when the
        threshold is met. It can be overridden to customize the execution logic.
        """
        if not self.tasks:
            raise ValueError("No tasks provided to execute.")
        self._internal_threshold_barrier = SignalBarrier(self._threshold, reusable=True)  # THIS IS CAUSING THE THREAD TO BLOCK OR VANISH
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
            if not self._create_field:
                with self._lock:
                    if not self._create_field:
                        self._create_execute_operations_field()

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

        # Return whether the conductor was successfully released
        print("Ending 2")

        return was_released and not self._disposed and not self._broken