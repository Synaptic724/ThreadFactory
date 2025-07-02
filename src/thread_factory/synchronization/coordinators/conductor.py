from __future__ import annotations
import ulid
from thread_factory.utils import IDisposable
import inspect
import threading
from thread_factory.synchronization.primitives import Dynaphore
from typing import Optional, Callable, List, Union, Any
from thread_factory.synchronization.coordinators.clock_barrier import ClockBarrier
from thread_factory.synchronization.primitives.signal_barrier import SignalBarrier
from thread_factory.concurrency import ConcurrentDict, ConcurrentList
from thread_factory.utils.coordination.outcome import Outcome


class Conductor(IDisposable):
    """A reusable, data-aware synchronization point and work executor.

    The Conductor blocks a group of threads until a specified threshold is met.
    Once the threshold is reached, it executes a series of tasks on all
    participating threads in a synchronized, lock-step manner.

    This is designed for scenarios where N threads must perform the same sequence
    of operations together, waiting for the entire group to complete each step
    before proceeding to the next.

    Key Features:
    - **Lock-Step Execution**: Ensures that all participating threads execute
      the same task concurrently and wait for each other before moving to the next task.
    - **Data-Aware**: Executes tasks and robustly captures their results or exceptions.
    - **Reusable**: Can be reset for multiple cycles of coordination.
    - **Timeout Capable**: A global timeout prevents deadlocks if the threshold is not met.
    - **Thread-Safe**: Designed with robust synchronization primitives for concurrent use.
    """
    __slots__ = IDisposable.__slots__ + [
        "_threshold", "tasks", "reusable", "manual_release", "_timeout", "_raise_on_timeout",
        "_id", "outcomes", "_released", "_broken", "_multiple_outcomes_per_task",
        "_lock", "_clock_barrier", "_signal_barrier", "_dynaphore", "_internal_threshold_barrier",
    ]

    def __init__(
            self,
            threshold: int,
            tasks: Optional[Union[Callable, List[Callable]]] = None,
            reusable: bool = False,
            manual_release: bool = False,
            timeout: Optional[float] = None,
            raise_on_timeout: bool = False,
            multiple_outcomes_per_task: bool = False
    ):
        """Initializes the Conductor.

        Args:
            threshold (int): The number of threads required to trigger the release.
            tasks (Optional): A function or list of functions to be executed by
                all participating threads once the threshold is met.
            reusable (bool): If True, the conductor can be reset for another cycle.
            manual_release (bool): If True, threads are not released automatically.
            timeout (Optional[float]): A global timeout in seconds.
            raise_on_timeout (bool): If True, raises TimeoutError on timeout.
            multiple_outcomes_per_task (bool): If True, each task can store
                multiple outcomes (one from each participating thread).
        """
        super().__init__()
        if threshold <= 0:
            raise ValueError("Threshold must be a positive integer.")
        self._threshold = threshold
        self.tasks: List[Callable] = []
        self._internal_threshold_barrier = None

        if tasks:
            task_list = [tasks] if callable(tasks) else tasks
            if not isinstance(task_list, list) or not all(callable(cb) for cb in task_list):
                raise TypeError("tasks must be a callable function or a list of callables.")

            for task in task_list:
                if inspect.iscoroutinefunction(task):
                    raise TypeError("Coroutines are not supported; only synchronous callables are allowed.")
                self.tasks.append(task)

            # Eagerly initialize the internal barrier used for lock-step execution if tasks exist.
            self._internal_threshold_barrier = SignalBarrier(self._threshold, reusable=reusable)

        # Settings and validations
        self.reusable = reusable
        self.manual_release = manual_release
        self._timeout = timeout
        self._raise_on_timeout = raise_on_timeout
        self._multiple_outcomes_per_task = multiple_outcomes_per_task

        # Outputs
        self._id = str(ulid.ULID())
        self.outcomes: ConcurrentDict[int, Union[Outcome, ConcurrentList[Outcome]]] = ConcurrentDict()

        # State
        self._released = False
        self._broken = False

        # Synchronization Primitives
        self._lock = threading.RLock()
        self._dynaphore = Dynaphore(self._threshold)
        self._clock_barrier = None
        self._signal_barrier = None

        if timeout is not None:
            if timeout <= 0:
                raise ValueError("Timeout must be a positive number.")
            self._clock_barrier = ClockBarrier(
                threshold=self._threshold,
                timeout=timeout,
                on_broken=self.notify_all_override
            )
        else:
            self._signal_barrier = SignalBarrier(self._threshold, reusable=reusable)

    def dispose(self):
        """Safely terminates the conductor, releasing all waiting threads and resources."""
        if self._disposed: return
        with self._lock:
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
                for value in self.outcomes.values():
                    outcomes_to_dispose = value if self._multiple_outcomes_per_task else [value]
                    for obj in outcomes_to_dispose:
                        obj.dispose()
            self.outcomes.clear()

            self._broken = True
            self._released = True

    def reset(self):
        """Resets the conductor to its initial state for reuse."""
        if self._disposed:
            raise RuntimeError("Cannot reset a disposed Conductor.")
        if not self.reusable:
            return

        with self._lock:
            if self.outcomes:
                for value in self.outcomes.values():
                    outcomes_to_dispose = value if self._multiple_outcomes_per_task else [value]
                    for obj in outcomes_to_dispose:
                        obj.dispose()
            self.outcomes.clear()

            self._released = False
            self._broken = False

            if self._clock_barrier:
                self._clock_barrier.reset()
            if self._signal_barrier:
                self._signal_barrier.reset()
            if self._internal_threshold_barrier:
                self._internal_threshold_barrier.reset()

            # Reset the dynaphore permits to the original threshold for the next cycle
            self._dynaphore.set_permits(self._threshold)

    @property
    def results(self) -> List[Any]:
        """A convenience property to get a list of successful task results."""
        if self._disposed: return []
        successful = []
        for value in self.outcomes.values():
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
        for value in self.outcomes.values():
            outcomes_to_check = value if self._multiple_outcomes_per_task else [value]
            for o in outcomes_to_check:
                if o.done:
                    exc = o.exception()
                    if exc is not None and not (isinstance(exc, RuntimeError) and "disposed" in str(exc)):
                        errors.append(exc)
        return errors

    def is_spent(self) -> bool:
        """Checks if the conductor has completed its run and is not reusable."""
        return self._released and not self.reusable

    def release(self) -> None:
        """Manually releases waiting threads when manual_release=True."""
        with self._lock:
            if self._disposed or not self.manual_release or self._released:
                return
            self._released = True
            # In manual mode, we assume the main barrier is what needs signaling.
            if self._signal_barrier:
                self._signal_barrier.release()

    def notify_all_override(self) -> None:
        """Forcefully breaks the barriers and releases all waiting threads."""
        with self._lock:
            if self._disposed or self._released: return
            self._broken = True
            self._released = True
            # Break all potential waiting points
            if self._clock_barrier: self._clock_barrier.release()
            if self._signal_barrier: self._signal_barrier.release()
            if self._internal_threshold_barrier: self._internal_threshold_barrier.release()
            if self._dynaphore: self._dynaphore.release_all()

    def _clock_barrier_wait(self) -> bool:
        """Internal method to wait on the ClockBarrier."""
        if self._clock_barrier is None: return False
        try:
            return self._clock_barrier.wait()
        except Exception:
            # The on_broken callback handles state change. Here we translate the outcome.
            if self._raise_on_timeout:
                raise TimeoutError(f"Conductor wait timed out after {self._timeout}s.")
            return False  # Return False on timeout if not raising

    def _execute_operation(self, task: Callable, index: int) -> None:
        """Executes a single task and records its outcome."""
        try:
            self._set_result(task(), index)
        except Exception as e:
            self._set_exception(e, index)

    def _execute_operations(self):
        """Executes all tasks in a synchronized, lock-step manner across all threads."""
        if not self.tasks:
            return

        for index, task in enumerate(self.tasks):
            if self._broken or self._disposed: break
            self._execute_operation(task, index)
            # Wait for all threads to finish the current task before starting the next one.
            self._internal_threshold_barrier.wait()

        if not self.manual_release:
            self._released = True

    def _set_result(self, result: Any, index: int):
        """Sets the result for a given task index."""
        new_outcome = Outcome()
        new_outcome.set_result(result)
        if self._multiple_outcomes_per_task:
            outcome_list = self.outcomes.setdefault(index, ConcurrentList())
            outcome_list.append(new_outcome)
        else:
            # Only the first thread to set the result for this index wins.
            self.outcomes.setdefault(index, new_outcome)

    def _set_exception(self, e: Exception, index: int):
        """Sets the exception for a given task index."""
        new_outcome = Outcome()
        new_outcome.set_exception(e)
        if self._multiple_outcomes_per_task:
            outcome_list = self.outcomes.setdefault(index, ConcurrentList())
            outcome_list.append(new_outcome)
        else:
            self.outcomes.setdefault(index, new_outcome)

    def start(self, timeout: float = None) -> None:
        """Blocks the calling thread until the threshold is met, then executes tasks."""
        if self._disposed or self._broken:
            return
        if self.is_spent():
            return

        was_released = False
        try:
            if self._timeout:
                was_released = self._clock_barrier_wait()
            else:
                # Assuming signal_barrier.wait() returns bool or raises
                was_released = self._signal_barrier.wait()

            # If the main barrier was broken or timed out, exit early.
            if not was_released:
                # State is set by on_broken or _clock_barrier_wait exception path
                return

            # Let the designated number of threads proceed to the execution phase.
            if not self._dynaphore.wait_for_permit(timeout):
                # Could not get a permit in time, might happen in complex scenarios
                return

            try:
                self._execute_operations()
            finally:
                # Each thread consumes a permit for the cycle.
                # Important for making 'reusable' mode work correctly.
                self._dynaphore.decrease_permits()

        except Exception as e:
            if self._raise_on_timeout and isinstance(e, TimeoutError):
                raise
            # For other unexpected exceptions, break the conductor.
            self.notify_all_override()

        # This handles cases where the barrier timed out but didn't raise.
        if not was_released and not self._disposed:
            self.notify_all_override()