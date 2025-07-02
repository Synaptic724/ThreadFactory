from __future__ import annotations
import threading, inspect, ulid
from typing import Optional, Callable, List, Union, Any, Dict
from thread_factory.utils import IDisposable
from thread_factory.concurrency import ConcurrentDict, ConcurrentList
from thread_factory.utils.coordination.outcome import Outcome
from thread_factory.synchronization.primitives import Dynaphore
from thread_factory.synchronization.coordinators.clock_barrier import ClockBarrier
from thread_factory.synchronization.primitives.signal_barrier import SignalBarrier


class Conductor(IDisposable):
    """
    Conductor
    ---------
    A reusable, data-aware synchronization point and work executor.
    Designed to coordinate a set of threads that must wait until a shared threshold is reached,
    then optionally execute one or more registered tasks with result tracking and callbacks.

    ✅ Integrated with SignalController:
       - Registers itself on creation
       - Exposes commands: release, reset, notify_all_override, is_spent, dispose
       - Emits events: BARRIER_PASSED, EXECUTION_STARTED, EXECUTION_COMPLETED, BARRIER_BROKEN, RESET, DISPOSED
       - Responds to controller-issued `.invoke()` commands

    Usage Scenarios:
    ----------------
    - Group-based thread coordination
    - Manual release control (e.g., pausing groups)
    - Task execution after threshold
    - Integration with orchestration logic via SignalController
    """

    __slots__ = IDisposable.__slots__ + [
        "_threshold", "tasks", "reusable", "manual_release",
        "_timeout", "_raise_on_timeout", "_multiple_outcomes_per_task", "_callback",
        "_controller", "_id", "_released", "_broken", "_main_barrier",
        "_lock", "_dynaphore", "_manual_release_gate", "_callback_executed_flags",
        "_barrier_passed_notified", "_execution_started_notified", "_execution_completed_notified",
        "_clock_barrier", "_signal_barrier", "_internal_threshold_barrier", "outcomes"
    ]

    def __init__(
        self,
        threshold: int,
        tasks: Optional[Union[Callable, List[Callable]]] = None,
        reusable: bool = False,
        manual_release: bool = False,
        timeout: Optional[float] = None,
        raise_on_timeout: bool = False,
        multiple_outcomes_per_task: bool = False,
        callback: Optional[Callable[[], None]] = None,
        controller: Optional['SignalController'] = None
    ):
        """
        Initializes a new Conductor instance.

        Args:
            threshold (int): The number of threads that must arrive before the barrier is passed.
            tasks (Optional[Union[Callable, List[Callable]]]): A single callable or a list of callables
                                                                to be executed once the barrier is passed.
            reusable (bool): If True, the Conductor can be reset and reused after its barrier is passed.
            manual_release (bool): If True, the tasks will only execute and the barrier will fully release
                                   after `release()` is explicitly called.
            timeout (Optional[float]): The maximum time in seconds to wait for the barrier to be passed.
                                       If None, the wait is indefinite.
            raise_on_timeout (bool): If True, a TimeoutError will be raised if the barrier times out.
            multiple_outcomes_per_task (bool): If True, each task can store multiple outcomes (e.g., if
                                               the task is executed multiple times or by multiple threads).
            callback (Optional[Callable[[], None]]): A callable to be invoked after each task completes
                                                     its execution.
            controller (Optional['SignalController']): An optional SignalController instance for
                                                       event notification and command invocation.

        Raises:
            ValueError: If `threshold` is not a positive integer or `timeout` is not positive.
            TypeError: If `tasks` is not a callable or a list of callables, or if a coroutine is provided.
        """
        super().__init__()
        if threshold <= 0:
            raise ValueError("Threshold must be a positive integer.")

        # ----------------- Basic Fields -----------------
        self._threshold = threshold
        self.reusable = reusable
        self.manual_release = manual_release
        self._timeout = timeout
        self._raise_on_timeout = raise_on_timeout
        self._multiple_outcomes_per_task = multiple_outcomes_per_task
        self._callback = callback
        self._controller = controller
        self._id = str(ulid.ULID())  # Generate a unique ID for the Conductor
        self.outcomes = ConcurrentDict()  # Stores the outcomes (results/exceptions) of executed tasks
        self._released = False  # Flag indicating if the Conductor has been released
        self._broken = False  # Flag indicating if the barrier has been forcibly broken

        # ----------------- Threading Primitives -----------------
        self._lock = threading.RLock()  # Reentrant lock for internal state management
        self._dynaphore = Dynaphore(threshold)  # Dynaphore to manage permits for task execution
        self._manual_release_gate = threading.Event() if manual_release else None # Event for manual release

        # ----------------- Barrier Selection -----------------
        self._clock_barrier = None
        self._signal_barrier = None
        self._internal_threshold_barrier = None
        self._main_barrier = None

        # ----------------- Notification Flags -----------------
        self._barrier_passed_notified = False
        self._execution_started_notified = False
        self._execution_completed_notified = False
        self._callback_executed_flags = []

        # ----------------- Task Validation -----------------
        self.tasks: List[Callable] = []
        if tasks:
            task_list = [tasks] if callable(tasks) else tasks
            if not isinstance(task_list, list) or not all(callable(cb) for cb in task_list):
                raise TypeError("tasks must be a callable or list of callables.")
            for task in task_list:
                if inspect.iscoroutinefunction(task):
                    raise TypeError("Coroutines are not supported.")
                self.tasks.append(task)
            # Internal barrier for coordinating task completion
            self._internal_threshold_barrier = SignalBarrier(threshold, reusable=True)
            if callback:
                self._callback_executed_flags = [False for _ in self.tasks]

        # ----------------- Main Barrier Init -----------------
        if timeout is not None:
            if timeout <= 0:
                raise ValueError("Timeout must be positive.")
            # Use ClockBarrier if a timeout is specified
            self._clock_barrier = ClockBarrier(
                threshold=threshold, timeout=timeout,
                on_broken=self.notify_all_override, controller=controller
            )
        else:
            # Otherwise, use SignalBarrier for indefinite waiting
            self._signal_barrier = SignalBarrier(threshold, reusable=reusable, controller=controller)

        self._set_main_barrier()

        # ----------------- Controller Registration -----------------
        if self._controller:
            try:
                self._controller.register(self)
            except Exception:
                pass  # soft failure; registration is optional

    def dispose(self):
        """
        Cleanly disposes the Conductor instance.
        This method wakes all internal barriers and gates, clears internal data structures,
        and notifies the associated SignalController (if any) of the disposal.
        It makes the Conductor unusable after calling.
        """
        if self._disposed:
            return
        with self._lock:
            self._disposed = True
            if self._controller:
                self._controller.notify(self.id, "DISPOSED")
                self._controller = None # Dereference the controller

            # Dispose of all internal threading primitives
            if self._clock_barrier: self._clock_barrier.dispose()
            if self._signal_barrier: self._signal_barrier.dispose()
            if self._internal_threshold_barrier: self._internal_threshold_barrier.dispose()
            if self._dynaphore: self._dynaphore.dispose()
            if self._manual_release_gate: self._manual_release_gate.set() # Set the event to unblock waiters

            # Dispose of all outcome objects and clear the outcomes dictionary
            for v in self.outcomes.values():
                outcomes = v if self._multiple_outcomes_per_task else [v]
                for o in outcomes: o.dispose()
            self.outcomes.clear()

            self._released = True # Mark as released
            self._broken = True # Mark as broken to prevent further operations

    # ============================================================
    #  Controller Integration – Contract Exposure
    # ============================================================
    @property
    def id(self) -> str:
        """
        Returns:
            str: The unique identifier for this Conductor instance.
        """
        return self._id

    def _get_object_details(self) -> Dict[str, Any]:
        """
        Provides metadata for SignalController integration, including exposed commands and the conductor's name.

        Returns:
            Dict[str, Any]: A dictionary containing the conductor's name and a mapping of command names
                            to their respective callable methods.
        """
        return {
            'name': 'conductor',
            'commands': {
                'dispose': self.dispose,
                'reset': self.reset,
                'release': self.release,
                'notify_all_override': self.notify_all_override,
                'is_spent': self.is_spent,
            }
        }

    # ============================================================
    #  Public Lifecycle / Entry Points
    # ============================================================

    def start(self, timeout: float = None) -> None:
        """
        Blocks the calling thread until the defined threshold of participants is met,
        and then optionally executes the registered tasks.

        If `manual_release` is True, tasks will only execute after `release()` is called.

        Args:
            timeout (float, optional): The maximum time to wait for the barrier.
                                       Overrides the `timeout` set during initialization if provided.
        Raises:
            TimeoutError: If `raise_on_timeout` is True and the barrier times out.
        """
        # If disposed, broken, or spent (not reusable and already used), return immediately.
        if self._disposed or self._broken or self.is_spent():
            return
        try:
            # Wait for the main barrier to be passed by the required number of threads.
            self._main_barrier.wait()
            if self._broken: # Check if the barrier was broken while waiting
                return

            with self._lock:
                # Notify the controller that the barrier has been passed, if not already notified.
                if self._controller and not self._barrier_passed_notified:
                    self._barrier_passed_notified = True
                    self._controller.notify(self.id, "BARRIER_PASSED")

            # Acquire a permit from the dynaphore before executing operations.
            if not self._dynaphore.wait_for_permit(timeout):
                return

            try:
                self._execute_operations() # Execute the registered tasks.
            finally:
                self._dynaphore.decrease_permits() # Release the permit after execution.

        except Exception as e:
            # Handle timeout exceptions if configured to raise them.
            if self._raise_on_timeout and isinstance(e, threading.BrokenBarrierError):
                raise TimeoutError("Conductor wait timed out.") from e
            self.notify_all_override() # Forcibly unblock if an unexpected exception occurs.

    def reset(self):
        """
        Resets the Conductor to its initial state, allowing it to be reused if `reusable` is True.
        This clears all collected outcomes, resets internal flags, and resets the underlying
        threading primitives.

        Raises:
            RuntimeError: If the Conductor has already been disposed.
        """
        if self._disposed:
            raise RuntimeError("Cannot reset a disposed Conductor.")
        if not self.reusable: # Only reset if the Conductor is designed for reuse
            return

        with self._lock:
            # Clear all stored outcomes and dispose of them
            for v in self.outcomes.values():
                outcomes = v if self._multiple_outcomes_per_task else [v]
                for o in outcomes: o.dispose()
            self.outcomes.clear()

            # Reset internal state flags
            self._released = False
            self._broken = False
            self._barrier_passed_notified = False
            self._execution_started_notified = False
            self._execution_completed_notified = False
            self._callback_executed_flags = [False for _ in self.tasks]

            # Reset all internal threading primitives
            if self._clock_barrier: self._clock_barrier.reset()
            if self._signal_barrier: self._signal_barrier.reset()
            if self._internal_threshold_barrier: self._internal_threshold_barrier.reset()
            if self._manual_release_gate: self._manual_release_gate.clear() # Clear the event for manual release

            self._dynaphore.set_permits(self._threshold) # Reset dynaphore permits to threshold

            if self._controller:
                self._controller.notify(self.id, "RESET") # Notify controller of reset

    def release(self):
        """
        Manually releases the Conductor when `manual_release` is True.
        This unblocks any threads waiting on the `_manual_release_gate` and allows tasks to proceed.
        """
        with self._lock:
            # Only release if not disposed, manual_release is enabled, and not already released
            if self._disposed or not self.manual_release or self._released:
                return
            self._released = True
            if self._manual_release_gate:
                self._manual_release_gate.set() # Set the event to unblock waiting threads
            if self._controller:
                self._controller.notify(self.id, "MANUALLY_RELEASED") # Notify controller

    def notify_all_override(self):
        """
        Forcibly unblocks all waiting threads and effectively "breaks" the barrier.
        This method is typically used to handle timeouts or exceptional conditions,
        preventing threads from being indefinitely blocked.
        """
        with self._lock:
            # Only break if not disposed or already released
            if self._disposed or self._released:
                return
            self._broken = True # Mark the barrier as broken
            self._released = True # Mark as released

            # 1. Wake main barrier
            if self._main_barrier:
                try:
                    # Attempt to call a specific override method if available, otherwise general release
                    if hasattr(self._main_barrier, "notify_all_override"):
                        self._main_barrier.notify_all_override()
                    else:
                        self._main_barrier.release()
                except Exception:
                    pass

            # 2. Wake follow-on gates (dynaphore and manual release gate)
            if self._dynaphore:
                self._dynaphore.release_all() # Release all permits in the dynaphore
            if self._manual_release_gate:
                self._manual_release_gate.set() # Set the event to unblock any manual release waiters

            # 3. Notify controller once that the barrier was broken
            if self._controller and not self._barrier_passed_notified:
                self._barrier_passed_notified = True
                self._controller.notify(self.id, "BARRIER_BROKEN")

    # ============================================================
    #  Execution Pipeline
    # ============================================================
    def _execute_operations(self):
        """
        Executes the registered tasks sequentially and triggers the per-task callback if defined.
        Handles notification of task execution lifecycle events to the controller.
        """
        if self.tasks:
            with self._lock:
                # Notify controller that task execution has started
                if self._controller and not self._execution_started_notified:
                    self._execution_started_notified = True
                    self._controller.notify(self.id, "EXECUTION_STARTED")

            for index, task in enumerate(self.tasks):
                # Stop execution if the conductor is broken or disposed
                if self._broken or self._disposed:
                    break
                self._execute_operation(task, index) # Execute a single task
                try:
                    self._internal_threshold_barrier.wait()
                except threading.BrokenBarrierError:
                    pass  # D

                if self._callback:
                    with self._lock:
                        # Execute callback if it hasn't been executed for this task yet
                        if not self._callback_executed_flags[index]:
                            self._callback_executed_flags[index] = True
                            try:
                                self._callback()
                            except Exception as e:
                                # Log errors in callback execution if a logger is available
                                if self._controller and self._controller._logger:
                                    self._controller._logger.error(
                                        f"Error in Conductor callback: {e}", exc_info=True
                                    )

            with self._lock:
                # Notify controller that task execution has completed, if not broken or disposed
                if self._controller and not self._execution_completed_notified and not (self._broken or self._disposed):
                    self._execution_completed_notified = True
                    self._controller.notify(self.id, "EXECUTION_COMPLETED")
            self._internal_threshold_barrier.wait()  # Wait for all threads to complete the current task

        # Wait on manual release gate if manual_release is enabled, otherwise mark as released
        if self.manual_release:
            self._manual_release_gate.wait()
        else:
            self._released = True

    def _execute_operation(self, task: Callable, index: int):
        """
        Executes a single task and records its outcome (result or exception).

        Args:
            task (Callable): The task (callable) to execute.
            index (int): The index of the task in the `tasks` list.
        """
        try:
            self._set_result(task(), index) # Execute task and store its result
        except Exception as e:
            self._set_exception(e, index) # Store any exception raised by the task

    def _set_result(self, result: Any, index: int):
        """
        Stores the successful result of a task.

        Args:
            result (Any): The result returned by the executed task.
            index (int): The index of the task to which this result belongs.
        """
        outcome = Outcome()
        outcome.set_result(result)
        # Store outcome based on whether multiple outcomes per task are allowed
        if self._multiple_outcomes_per_task:
            self.outcomes.setdefault(index, ConcurrentList()).append(outcome)
        else:
            self.outcomes.setdefault(index, outcome)

    def _set_exception(self, e: Exception, index: int):
        """
        Stores an exception that occurred during task execution.

        Args:
            e (Exception): The exception raised by the executed task.
            index (int): The index of the task to which this exception belongs.
        """
        outcome = Outcome()
        outcome.set_exception(e)
        # Store outcome based on whether multiple outcomes per task are allowed
        if self._multiple_outcomes_per_task:
            self.outcomes.setdefault(index, ConcurrentList()).append(outcome)
        else:
            self.outcomes.setdefault(index, outcome)

    def _set_main_barrier(self):
        """
        Internal method to determine and set the primary barrier for the Conductor.
        It prioritizes the ClockBarrier if a timeout is specified, otherwise uses the SignalBarrier.
        """
        self._main_barrier = self._clock_barrier or self._signal_barrier

    # ============================================================
    #  Properties
    # ============================================================
    @property
    def results(self) -> List[Any]:
        """
        Returns a list of successful results from all executed tasks.
        Disposed outcomes and outcomes with exceptions are excluded.

        Returns:
            List[Any]: A list containing the results of successfully completed tasks.
        """
        if self._disposed:
            return []
        successful = []
        for value in self.outcomes.values():
            values = value if isinstance(value, list) else [value]
            for o in values:
                # Check if the outcome is done and has no exception
                if o.done and o.exception() is None:
                    try:
                        successful.append(o.result())
                    except Exception:
                        pass # Ignore exceptions during result retrieval if already marked as no exception
        return successful

    def get_outcomes(self, as_concurrent_dict: bool = True) -> Union[Dict, ConcurrentDict]:
        """
        Returns the collected outcomes of all executed tasks.

        Args:
            as_concurrent_dict (bool): If True (default), returns the outcomes as a ConcurrentDict.
                                       If False, returns the outcomes as a standard Python dictionary.

        Returns:
            Union[Dict, ConcurrentDict]: A dictionary containing the outcomes, where keys are task indices
                                         and values are either single Outcome objects or ConcurrentLists of Outcomes.
        """
        if as_concurrent_dict:
            return self.outcomes
        else:
            # Convert ConcurrentDict to a regular dict for standard dictionary behavior
            return dict(self.outcomes)


    @property
    def exceptions(self) -> List[Exception]:
        """
        Returns a list of exceptions from all executed tasks.
        Disposed outcomes and `RuntimeError` instances indicating disposal are filtered out.

        Returns:
            List[Exception]: A list containing the exceptions raised by tasks.
        """
        if self._disposed:
            return []
        errors = []
        for value in self.outcomes.values():
            values = value if isinstance(value, list) else [value]
            for o in values:
                if o.done: # Check if the outcome is complete
                    exc = o.exception()
                    # Add exception to list if it exists and is not a "disposed" RuntimeError
                    if exc is not None and not (isinstance(exc, RuntimeError) and "disposed" in str(exc)):
                        errors.append(exc)
        return errors

    def is_spent(self) -> bool:
        """
        Checks if the Conductor has completed its lifecycle and cannot be reused.

        Returns:
            bool: True if the Conductor is released and not reusable, False otherwise.
        """
        return self._released and not self.reusable