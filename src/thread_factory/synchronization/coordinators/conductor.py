from __future__ import annotations
import ulid, threading
from thread_factory.utilities.coordination.package import Pack
from thread_factory.utilities.interfaces.disposable import IDisposable
from thread_factory.synchronization.primitives import Dynaphore
from typing import Optional, Callable, List, Union, Any, Dict, Iterable
from thread_factory.synchronization.coordinators.clock_barrier import ClockBarrier
from thread_factory.synchronization.primitives.signal_barrier import SignalBarrier
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.utilities.coordination.outcome import Outcome

class Conductor(IDisposable):
    """
    A reusable, data-aware synchronization point and work executor.

    The Conductor acts as an advanced, thread-safe barrier that orchestrates the
    synchronization of multiple threads. It blocks callers of its `start` method
    until a specified `threshold` of threads has been reached.

    Once the threshold is met, it can optionally execute a series of predefined
    tasks in a controlled manner. It is designed for complex synchronization
    scenarios, offering features like reusability for cyclical operations,
    manual release triggers for fine-grained control, timeouts to prevent
    indefinite blocking, and centralized, thread-safe management of task outcomes
    (both results and exceptions).

    It can integrate with a `SignalController` to emit lifecycle events, enabling
    monitoring and external coordination based on its internal state, such as when
    the barrier is passed, when task execution begins, or when it is reset or
    disposed.
    """
    __slots__ = IDisposable.__slots__ + [
        "_threshold", "tasks", "reusable", "manual_release", "_timeout", "_raise_on_timeout",
        "_id", "outcomes", "_released", "_broken", "_multiple_outcomes_per_task",
        "_lock", "_clock_barrier", "_signal_barrier", "_dynaphore", "_internal_threshold_barrier",
        "_manual_release_gate", "_controller", "_callback",
        "_callback_executed_flags", "_barrier_passed_notified", "_execution_started_notified",
        "_execution_completed_notified","_main_barrier",
    ]
    def __init__(
            self,
            threshold: int,
            tasks: Optional[Union[Union[Callable[..., None], Pack], List[Union[Callable[..., None], Pack]]]] = None,
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

        This constructor sets up the synchronization primitives and configuration
        for the Conductor based on the provided parameters.

        Args:
            threshold (int):
                The number of threads that must call `start()` before the barrier
                is passed and tasks (if any) are executed. Must be a positive integer.
            tasks (Optional[Union[Callable, List[Callable]]]):
                A single callable or a list of callables to be executed after the
                threshold is met. Coroutines are not supported and will raise a
                TypeError.
            reusable (bool):
                If True, the conductor can be reset to its initial state using the
                `reset()` method, allowing it to be used for subsequent
                synchronization cycles. Defaults to False.
            manual_release (bool):
                If True, the conductor, after executing its tasks, will not fully
                release and will wait for an explicit call to `release()`. This is
                useful for holding a final state until an external condition is met.
                Defaults to False.
            timeout (Optional[float]):
                The maximum time in seconds to wait for the threshold to be met.
                If the timeout is reached, the barrier is considered "broken," and
                all waiting threads are released. Must be a positive number if provided.
            raise_on_timeout (bool):
                If True, a `TimeoutError` is raised in the `start` method when a
                timeout occurs. Otherwise, the method simply returns. Defaults to False.
            multiple_outcomes_per_task (bool):
                If True, allows each task to store multiple results in a list. This
                is primarily useful when a conductor is `reusable` and a single task
                index might be associated with outcomes from multiple cycles.
                Defaults to False.
            callback (Optional[Callable[[], None]]):
                An optional function to be called immediately after each task in the
                `tasks` list completes its execution.
            controller (Optional['SignalController']):
                An optional `SignalController` instance to which this Conductor will
                register. The controller will receive notifications about the
                conductor's state changes (e.g., "DISPOSED", "RESET", "BARRIER_PASSED").
        """
        super().__init__()
        if threshold <= 0:
            raise ValueError("Threshold must be a positive integer.")

        # Callback Management
        if tasks is None:
            self.tasks: ConcurrentList[Pack] = ConcurrentList()
        else:
            packified_result = Pack.bundle(tasks)
            if isinstance(packified_result, Pack):
                # If bundle returned a single Pack, put it into a list
                self.tasks = ConcurrentList([packified_result])
            else:
                # If bundle returned a ConcurrentList (for iterables), use it directly
                self.tasks = packified_result
        self._callback: Union[Callable[..., None], Pack] = callback
        self._callback_executed_flags: List[bool] = []
        if self._callback:
            Pack.bundle(self._callback)
            self._callback_executed_flags = [False for _ in self.tasks]

        # State management
        self._id: str = str(ulid.ULID())
        self._threshold: int = threshold
        self._released: bool = False
        self._broken: bool = False
        self._barrier_passed_notified: bool = False
        self._execution_started_notified: bool = False
        self._execution_completed_notified: bool = False
        self.reusable: bool = reusable
        self.manual_release: bool = manual_release
        self._timeout: float = timeout
        self._raise_on_timeout: float = raise_on_timeout
        self._multiple_outcomes_per_task: bool = multiple_outcomes_per_task

        # Synchronization primitives
        self._clock_barrier: Optional[ClockBarrier] = None
        self._signal_barrier: Optional[SignalBarrier]  = None
        self._main_barrier: Optional[Union[SignalBarrier, ClockBarrier]] = None
        self._internal_threshold_barrier: Optional[SignalBarrier] = None
        self._internal_threshold_barrier = SignalBarrier(self._threshold, reusable=True)
        self._lock: threading.RLock = threading.RLock()
        self._dynaphore: Dynaphore = Dynaphore(self._threshold)
        self._manual_release_gate: Optional[threading.Event] = threading.Event() if self.manual_release else None

        # Controller management
        self._controller: 'Controller' = controller
        if self._controller:
            try:
                self._controller.register(self)
            except Exception:
                pass

        # Set up the main barrier based on timeout
        if timeout is not None:
            if timeout <= 0: raise ValueError("Timeout must be a positive number.")
            self._clock_barrier = ClockBarrier(
                threshold=self._threshold, timeout=timeout,
                on_broken=self.notify_all_override, controller=self._controller
            )
        else:
            self._signal_barrier = SignalBarrier(
                self._threshold, reusable=reusable, controller=self._controller
            )
        self._set_main_barrier()

        # Outcomes management
        self.outcomes: ConcurrentDict[int, Union[Outcome, ConcurrentList[Outcome]]] = ConcurrentDict()

    def dispose(self):
        """
        Disposes of the Conductor, cleaning up all associated resources.

        This method performs a full teardown of the Conductor. It marks the
        instance as disposed, notifies the controller (if any), and releases all
        internal synchronization primitives (barriers, locks, events). This action
        effectively unblocks any threads currently waiting on the Conductor.

        Once disposed, a Conductor cannot be used or reset. Any subsequent calls
        to its methods will have no effect or raise a `RuntimeError`. This method
        is thread-safe.
        """
        if self._disposed: return
        with self._lock:
            self._disposed = True
            if self._clock_barrier:
                self._clock_barrier.dispose()
                self._clock_barrier = None
            if self._signal_barrier:
                self._signal_barrier.dispose()
                self._signal_barrier = None
            if self._internal_threshold_barrier:
                self._internal_threshold_barrier.dispose()
                self._internal_threshold_barrier = None
            if self._dynaphore:
                self._dynaphore.dispose()
                self._dynaphore = None
            if self._manual_release_gate:
                self._manual_release_gate.set()
                self._manual_release_gate = None
            if self.outcomes:
                for value in self.outcomes.values():
                    outcomes_to_dispose = value if self._multiple_outcomes_per_task else [value]
                    for obj in outcomes_to_dispose: obj.dispose()

            self.outcomes.dispose()
            self.outcomes = None
            if isinstance(self.tasks, list):
                self.tasks.clear()
            elif isinstance(self.tasks, ConcurrentList):
                    self.tasks.dispose()
            self.tasks = None
            self._broken = True
            self._released = True
            if self._controller:
                self._controller.notify(self.id, "DISPOSED")
            if self._controller and hasattr(self._controller, 'unregister'):
                try:
                    self._controller.unregister(self.id)
                except Exception:
                    pass
                self._controller = None

    @property
    def id(self) -> str:
        """
        The unique, time-sortable identifier for this Conductor instance.

        This property returns a ULID (Universally Unique Lexicographically
        Sortable Identifier) generated when the Conductor is initialized. This ID
        serves as a primary key for this specific instance, used for tracking,
        logging, and uniquely identifying it when communicating with a
        `SignalController`.

        Returns:
            str: The unique ULID string.
        """
        return self._id

    def _get_object_details(self) -> ConcurrentDict[str, Any]:
        """
        Prepares a summary of the instance for controller registration.

        This internal method provides a structured dictionary containing key
        information about the Conductor. It is part of the contract used by the
        `SignalController` during registration.

        The dictionary includes the object's name ('conductor') and a map of
        publicly invokable command methods. This allows the controller (or a
        downstream system) to dynamically discover and interact with the
        Conductor's core functionalities.

        Returns:
            Dict[str, Any]: A dictionary containing the object's name and
                            callable command methods.
        """
        return ConcurrentDict({
            'name': 'conductor',
            'commands': ConcurrentDict({
                'dispose': self.dispose, 'reset': self.reset, 'release': self.release,
                'notify_all_override': self.notify_all_override, 'is_spent': self.is_spent,
            })
        })

    def reset(self):
        """
        Resets the Conductor to its initial state for reuse.

        This method is only effective if the Conductor was initialized with
        `reusable=True`. It clears all previously collected outcomes, resets
        internal barriers and gates to their initial counts and states, and
        notifies the controller that a "RESET" event has occurred.

        This allows the Conductor to be used for another complete synchronization
        cycle. If the Conductor is not reusable, this method does nothing.

        Raises:
            RuntimeError: If the Conductor has already been disposed.
        """
        if self._disposed: raise RuntimeError("Cannot reset a disposed Conductor.")
        if not self.reusable: return
        with self._lock:
            if self.outcomes:
                for value in self.outcomes.values():
                    outcomes_to_dispose = value if self._multiple_outcomes_per_task else [value]
                    for obj in outcomes_to_dispose: obj.dispose()
            self.outcomes.clear()
            self._released = False
            self._broken = False
            self._barrier_passed_notified = False
            self._execution_started_notified = False
            self._execution_completed_notified = False
            self._callback_executed_flags = [False for _ in self.tasks]
            if self._clock_barrier: self._clock_barrier.reset()
            if self._signal_barrier: self._signal_barrier.reset()
            if self._internal_threshold_barrier: self._internal_threshold_barrier.reset()
            if self._manual_release_gate: self._manual_release_gate.clear()
            self._dynaphore.set_permits(self._threshold)
            if self._controller:
                self._controller.notify(self.id, "RESET")

    @property
    def results(self) -> List[Any]:
        """List[Any]: A list of all successful results from executed tasks.

        This property iterates through all collected outcomes and returns the
        actual result data for each task that completed successfully (i.e., did
        not raise an exception). The returned list is a snapshot of the results
        at the time of the call.

        If the Conductor is disposed, it returns an empty list.
        """
        if self._disposed:
            return []

        successful: List[Any] = []

        def _iter_outcomes(val):
            if hasattr(val, "done"):
                yield val
            elif isinstance(val, Iterable):
                yield from val
            else:
                return

        for bucket in self.outcomes.values():
            for o in _iter_outcomes(bucket):
                if o.done and o.exception() is None:
                    try:
                        successful.append(o.result())
                    except Exception:
                        pass

        return successful

    @property
    def exceptions(self) -> List[Exception]:
        """List[Exception]: A list of all exceptions captured from executed tasks.

        This property iterates through all collected outcomes and returns the
        exception objects for each task that failed. It filters out disposal-related
        `RuntimeError` exceptions to only report on application-level errors.

        The returned list is a snapshot of the exceptions at the time of the call.
        If the Conductor is disposed, it returns an empty list.
        """
        if self._disposed:
            return []

        errors: List[Exception] = []

        def _iter_outcomes(val):
            if hasattr(val, "done"):
                yield val
            elif isinstance(val, Iterable):
                yield from val

        for bucket in self.outcomes.values():
            for o in _iter_outcomes(bucket):
                if o.done:
                    exc = o.exception()
                    if exc and not (
                            isinstance(exc, RuntimeError) and "disposed" in str(exc)
                    ):
                        errors.append(exc)

        return errors

    def is_spent(self) -> bool:
        """Checks if the Conductor has completed its cycle and is not reusable.

        Returns:
            bool:
                True if the Conductor has been released (either manually or
                automatically) and was not configured to be reusable. This indicates
                that its lifecycle is complete. Returns False otherwise.
        """
        return self._released and not self.reusable

    def release(self) -> None:
        """Manually releases the Conductor from its final wait state.

        If the Conductor was initialized with `manual_release=True`, calling this
        method will set the internal event that allows the `start()` method to
        finally complete and threads to be released. If `manual_release` is False,
        or if the Conductor is already released or disposed, this method has no
        effect.

        This is primarily used to signal that post-task cleanup or verification
        is complete and the synchronized operation can be considered fully finished.
        """
        with self._lock:
            if self._disposed or not self.manual_release or self._released: return
            self._released = True
            if self._manual_release_gate: self._manual_release_gate.set()
            if self._controller: self._controller.notify(self.id, "MANUALLY_RELEASED")

    def notify_all_override(self) -> None:
        """
        Forcibly breaks the barrier and releases all waiting threads.

        This method immediately puts the Conductor into a "broken" state. It
        releases all internal barriers and gates, ensuring that any thread currently
        blocked in a call to `start()` will be unblocked.

        This is typically used for external cancellation or error conditions, such
        as a timeout detected by the `ClockBarrier`. It ensures that the system
        does not hang indefinitely.
        """
        with self._lock:
            if self._disposed or self._released:
                return
            self._broken = True
            self._released = True

            if self._main_barrier:
                try:
                    if hasattr(self._main_barrier, "notify_all_override"):
                        self._main_barrier.notify_all_override()
                    else:
                        self._main_barrier.release()
                except Exception:
                    pass

            if self._dynaphore:
                self._dynaphore.release_all()
            if self._manual_release_gate:
                self._manual_release_gate.set()

            if self._controller and not self._barrier_passed_notified:
                self._barrier_passed_notified = True
                self._controller.notify(self.id, "BARRIER_BROKEN")

    def _execute_operation(self, task: Callable, index: int) -> None:
        """
        Executes a single task and captures its outcome.

        This method serves as the direct executor for an individual task. It first
        waits on an internal barrier, which ensures that all participating threads
        execute tasks in a synchronized, step-by-step manner.

        It then calls the provided task within a try/except block. If the task
        completes successfully, its return value is passed to `_set_result`. If it
        raises an exception, the exception object is passed to `_set_exception`.
        This ensures that every task execution results in a recorded outcome.

        Args:
            task (Callable): The function to execute.
            index (int): The index of the task, used for storing the outcome.
        """
        try:
            self._set_result(task(), index)
        except Exception as e:
            self._set_exception(e, index)

    def _execute_operations(self):
        """
        Orchestrates the entire task execution and callback sequence.

        This method is the control loop for all post-barrier work. It first checks
        if any tasks are defined. If so, it notifies the controller that execution
        has started.

        It then iterates through the list of tasks, calling `_execute_operation`
        for each one. The loop includes a check to terminate early if the
        Conductor has been broken or disposed. After each task, it handles the
        execution of the optional, shared callback, ensuring the callback is
        invoked only once per task completion.

        After all tasks are processed, it notifies the controller that execution
        is complete. Finally, it handles the release logic: it either blocks until
        `release()` is called (if `manual_release` is True) or immediately marks
        the Conductor as released.
        """
        if self.tasks:
            with self._lock:
                if self._controller and not self._execution_started_notified:
                    self._execution_started_notified = True
                    self._controller.notify(self.id, "EXECUTION_STARTED")

            for index, task in enumerate(self.tasks):
                if self._broken or self._disposed: break

                self._execute_operation(task, index)
                self._internal_threshold_barrier.wait()

                if self._callback:
                    with self._lock:
                        if not self._callback_executed_flags[index]:
                            self._callback_executed_flags[index] = True
                            try:
                                self._callback()
                            except Exception as e:
                                logger = self._controller._logger if self._controller else None
                                if logger: logger.error(f"Error in Conductor callback: {e}", exc_info=True)


            with self._lock:
                if self._controller and not self._execution_completed_notified and not (self._broken or self._disposed):
                    self._execution_completed_notified = True
                    self._controller.notify(self.id, "EXECUTION_COMPLETED")


        if self.manual_release:
            self._manual_release_gate.wait()
        else:
            self._released = True

    def _set_result(self, result: Any, index: int):
        """
        Creates and stores a successful Outcome for a given task.

        This internal helper method wraps the successful result of a task in an
        `Outcome` object. It then stores this outcome in the `self.outcomes`
        dictionary, using the task's original index as the key.

        If `_multiple_outcomes_per_task` is True, the outcome is appended to a
        list at that index, allowing for multiple results per task across
        different cycles of a reusable Conductor. Otherwise, it overwrites any
        existing outcome for that index.

        Args:
            result (Any): The successful return value from the executed task.
            index (int): The zero-based index of the task that produced the result.
        """
        new_outcome = Outcome()
        new_outcome.set_result(result)
        if self._multiple_outcomes_per_task:
            outcome_list = self.outcomes.setdefault(index, ConcurrentList())
            outcome_list.append(new_outcome)
        else:
            self.outcomes.setdefault(index, new_outcome)

    def _set_exception(self, e: Exception, index: int):
        """
        Creates and stores a failure Outcome for a given task.

        This internal helper method captures an exception from a failed task and
        wraps it in an `Outcome` object. It then stores this outcome in the
        `self.outcomes` dictionary, using the task's original index as the key.

        If `_multiple_outcomes_per_task` is True, the failure outcome is appended
        to a list at that index. Otherwise, it overwrites any existing outcome.
        This ensures that task failures are properly recorded.

        Args:
            e (Exception): The exception object caught during task execution.
            index (int): The zero-based index of the task that failed.
        """
        new_outcome = Outcome()
        new_outcome.set_exception(e)
        if self._multiple_outcomes_per_task:
            outcome_list = self.outcomes.setdefault(index, ConcurrentList())
            outcome_list.append(new_outcome)
        else:
            self.outcomes.setdefault(index, new_outcome)

    def _set_main_barrier(self) -> None:
        """
        Internal: Selects the primary barrier based on configuration.

        This method is called during initialization to set `self._main_barrier`.
        It defaults to using the `_clock_barrier` if a timeout was specified,
        enabling time-limited waiting. If no timeout was configured, it falls
        back to the standard `_signal_barrier`.

        This abstraction allows the `start()` method to interact with a single,
        consistent barrier interface regardless of the chosen synchronization mode.
        """
        self._main_barrier = self._clock_barrier or self._signal_barrier

    def start(self, timeout: float = None) -> None:
        """
        Blocks the calling thread until the threshold is met or an override occurs.

        This is the primary entry point for threads synchronizing on the Conductor.
        Each call to `start()` decrements the main barrier's count. The calling
        thread will block until the number of callers reaches the `threshold`
        defined during initialization.

        Once the threshold is met, the barrier passes, and this method proceeds to
        acquire a permit to execute the defined `tasks`. After task execution, it
        may block again if `manual_release` is enabled, waiting for a call to
        `release()`.

        Args:
            timeout (float, optional):
                A timeout specific to the permit acquisition phase. If a permit
                cannot be acquired within this time, the method will return.

        Raises:
            TimeoutError:
                If the Conductor was initialized with `raise_on_timeout=True` and
                the main barrier wait times out. This is raised from the underlying
                `BrokenBarrierError`.
        """
        if self._disposed or self._broken or self.is_spent():
            return
        try:
            self._main_barrier.wait()
            if self._broken:
                return
            with self._lock:
                if self._controller and not self._barrier_passed_notified:
                    self._barrier_passed_notified = True
                    self._controller.notify(self.id, "BARRIER_PASSED")

            if not self._dynaphore.wait_for_permit(timeout):
                return

            if self._broken:
                return
            try:
                self._execute_operations()
            finally:
                pass

        except Exception as e:
            if self._raise_on_timeout and isinstance(e, threading.BrokenBarrierError):
                raise TimeoutError("Conductor wait timed out.") from e

            self.notify_all_override()
