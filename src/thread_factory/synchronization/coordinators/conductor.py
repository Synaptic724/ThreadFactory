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
        self._id = str(ulid.ULID())
        self.outcomes = ConcurrentDict()
        self._released = False
        self._broken = False

        # ----------------- Threading Primitives -----------------
        self._lock = threading.RLock()
        self._dynaphore = Dynaphore(threshold)
        self._manual_release_gate = threading.Event() if manual_release else None

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
            self._internal_threshold_barrier = SignalBarrier(threshold, reusable=True)
            if callback:
                self._callback_executed_flags = [False for _ in self.tasks]

        # ----------------- Main Barrier Init -----------------
        if timeout is not None:
            if timeout <= 0:
                raise ValueError("Timeout must be positive.")
            self._clock_barrier = ClockBarrier(
                threshold=threshold, timeout=timeout,
                on_broken=self.notify_all_override, controller=controller
            )
        else:
            self._signal_barrier = SignalBarrier(threshold, reusable=reusable, controller=controller)

        self._set_main_barrier()

        # ----------------- Controller Registration -----------------
        if self._controller:
            try:
                self._controller.register(self)
            except Exception:
                pass  # soft failure; registration is optional

    # ============================================================
    #  Controller Integration – Contract Exposure
    # ============================================================
    @property
    def id(self) -> str:
        return self._id

    def _get_object_details(self) -> Dict[str, Any]:
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
        """Blocks the calling thread until threshold is met, then runs tasks."""
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

            try:
                self._execute_operations()
            finally:
                self._dynaphore.decrease_permits()

        except Exception as e:
            if self._raise_on_timeout and isinstance(e, threading.BrokenBarrierError):
                raise TimeoutError("Conductor wait timed out.") from e
            self.notify_all_override()

    def dispose(self):
        if self._disposed:
            return
        with self._lock:
            self._disposed = True
            if self._controller:
                self._controller.notify(self.id, "DISPOSED")
                self._controller = None

            if self._clock_barrier: self._clock_barrier.dispose()
            if self._signal_barrier: self._signal_barrier.dispose()
            if self._internal_threshold_barrier: self._internal_threshold_barrier.dispose()
            if self._dynaphore: self._dynaphore.dispose()
            if self._manual_release_gate: self._manual_release_gate.set()

            for v in self.outcomes.values():
                outcomes = v if self._multiple_outcomes_per_task else [v]
                for o in outcomes: o.dispose()
            self.outcomes.clear()

            self._released = True
            self._broken = True

    def reset(self):
        """Reset for reuse — clears state and resets internal barriers."""
        if self._disposed:
            raise RuntimeError("Cannot reset a disposed Conductor.")
        if not self.reusable:
            return

        with self._lock:
            for v in self.outcomes.values():
                outcomes = v if self._multiple_outcomes_per_task else [v]
                for o in outcomes: o.dispose()
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

    def release(self):
        """Manual release — used when manual_release=True."""
        with self._lock:
            if self._disposed or not self.manual_release or self._released:
                return
            self._released = True
            if self._manual_release_gate:
                self._manual_release_gate.set()
            if self._controller:
                self._controller.notify(self.id, "MANUALLY_RELEASED")

    def notify_all_override(self):
        """Break the barrier — forcibly unblocks waiting threads."""
        with self._lock:
            if self._disposed or self._released:
                return
            self._broken = True
            self._released = True

            # 1. Wake main barrier
            if self._main_barrier:
                try:
                    if hasattr(self._main_barrier, "notify_all_override"):
                        self._main_barrier.notify_all_override()
                    else:
                        self._main_barrier.release()
                except Exception:
                    pass

            # 2. Wake follow-on gates
            if self._dynaphore:
                self._dynaphore.release_all()
            if self._manual_release_gate:
                self._manual_release_gate.set()

            # 3. Notify once
            if self._controller and not self._barrier_passed_notified:
                self._barrier_passed_notified = True
                self._controller.notify(self.id, "BARRIER_BROKEN")

    # ============================================================
    #  Execution Pipeline
    # ============================================================
    def _execute_operations(self):
        """Executes tasks and triggers callback per-task."""
        if self.tasks:
            with self._lock:
                if self._controller and not self._execution_started_notified:
                    self._execution_started_notified = True
                    self._controller.notify(self.id, "EXECUTION_STARTED")

            for index, task in enumerate(self.tasks):
                if self._broken or self._disposed:
                    break
                self._execute_operation(task, index)
                self._internal_threshold_barrier.wait()

                if self._callback:
                    with self._lock:
                        if not self._callback_executed_flags[index]:
                            self._callback_executed_flags[index] = True
                            try:
                                self._callback()
                            except Exception as e:
                                if self._controller and self._controller._logger:
                                    self._controller._logger.error(
                                        f"Error in Conductor callback: {e}", exc_info=True
                                    )

            with self._lock:
                if self._controller and not self._execution_completed_notified and not (self._broken or self._disposed):
                    self._execution_completed_notified = True
                    self._controller.notify(self.id, "EXECUTION_COMPLETED")

        if self.manual_release:
            self._manual_release_gate.wait()
        else:
            self._released = True

    def _execute_operation(self, task: Callable, index: int):
        try:
            self._set_result(task(), index)
        except Exception as e:
            self._set_exception(e, index)

    def _set_result(self, result: Any, index: int):
        outcome = Outcome()
        outcome.set_result(result)
        if self._multiple_outcomes_per_task:
            self.outcomes.setdefault(index, ConcurrentList()).append(outcome)
        else:
            self.outcomes.setdefault(index, outcome)

    def _set_exception(self, e: Exception, index: int):
        outcome = Outcome()
        outcome.set_exception(e)
        if self._multiple_outcomes_per_task:
            self.outcomes.setdefault(index, ConcurrentList()).append(outcome)
        else:
            self.outcomes.setdefault(index, outcome)

    def _set_main_barrier(self):
        """Internal: Determines whether clocked or signal-based barrier is primary."""
        self._main_barrier = self._clock_barrier or self._signal_barrier

    # ============================================================
    #  Properties
    # ============================================================
    @property
    def results(self) -> List[Any]:
        if self._disposed:
            return []
        successful = []
        for value in self.outcomes.values():
            values = value if isinstance(value, list) else [value]
            for o in values:
                if o.done and o.exception() is None:
                    try:
                        successful.append(o.result())
                    except Exception:
                        pass
        return successful

    @property
    def exceptions(self) -> List[Exception]:
        if self._disposed:
            return []
        errors = []
        for value in self.outcomes.values():
            values = value if isinstance(value, list) else [value]
            for o in values:
                if o.done:
                    exc = o.exception()
                    if exc is not None and not (isinstance(exc, RuntimeError) and "disposed" in str(exc)):
                        errors.append(exc)
        return errors

    def is_spent(self) -> bool:
        return self._released and not self.reusable
