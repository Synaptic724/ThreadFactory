from __future__ import annotations
import ulid
from thread_factory.utils import IDisposable
import inspect
import threading
from thread_factory.synchronization.primitives import Dynaphore
from typing import Optional, Callable, List, Union, Any, Dict, Iterable
from thread_factory.synchronization.coordinators.clock_barrier import ClockBarrier
from thread_factory.synchronization.primitives.signal_barrier import SignalBarrier
from thread_factory.concurrency import ConcurrentDict, ConcurrentList
from thread_factory.utils.coordination.outcome import Outcome


# Assuming SignalController is available for import
# from .signal_controller import SignalController

class Conductor(IDisposable):
    """A reusable, data-aware synchronization point and work executor."""
    __slots__ = IDisposable.__slots__ + [
        "_threshold", "tasks", "reusable", "manual_release", "_timeout", "_raise_on_timeout",
        "_id", "outcomes", "_released", "_broken", "_multiple_outcomes_per_task",
        "_lock", "_clock_barrier", "_signal_barrier", "_dynaphore", "_internal_threshold_barrier",
        "_manual_release_gate",
        "_controller", "_callback",
        "_callback_executed_flags", "_barrier_passed_notified", "_execution_started_notified",
        "_execution_completed_notified",  # New flag for completion event
        "_main_barrier",
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

        self._clock_barrier = None
        self._signal_barrier = None

        self._threshold = threshold
        self.tasks: List[Callable] = []
        self._internal_threshold_barrier = None

        self._callback = callback
        self._callback_executed_flags: List[bool] = []

        if tasks:
            task_list = [tasks] if callable(tasks) else tasks
            if not isinstance(task_list, list) or not all(callable(cb) for cb in task_list):
                raise TypeError("tasks must be a callable function or a list of callables.")

            for task in task_list:
                if inspect.iscoroutinefunction(task):
                    raise TypeError("Coroutines are not supported.")
                self.tasks.append(task)

            self._internal_threshold_barrier = SignalBarrier(self._threshold, reusable=True)
            if self._callback:
                if not callable(callback): raise TypeError("Callback must be a callable function.")
                self._callback_executed_flags = [False for _ in self.tasks]

        self.reusable = reusable
        self.manual_release = manual_release
        self._timeout = timeout
        self._raise_on_timeout = raise_on_timeout
        self._multiple_outcomes_per_task = multiple_outcomes_per_task

        self._id = str(ulid.ULID())
        self.outcomes: ConcurrentDict[int, Union[Outcome, ConcurrentList[Outcome]]] = ConcurrentDict()

        self._released = False
        self._broken = False
        self._barrier_passed_notified = False
        self._execution_started_notified = False
        self._execution_completed_notified = False
        self._main_barrier = None

        self._lock = threading.RLock()
        self._dynaphore = Dynaphore(self._threshold)
        self._manual_release_gate = threading.Event() if self.manual_release else None

        self._controller = controller
        if self._controller:
            try:
                self._controller.register(self)
            except Exception:
                pass

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

    # ... (Controller contract methods remain the same) ...
    @property
    def id(self) -> str:
        return self._id

    def _get_object_details(self) -> Dict[str, Any]:
        return {
            'name': 'conductor',
            'commands': {
                'dispose': self.dispose, 'reset': self.reset, 'release': self.release,
                'notify_all_override': self.notify_all_override, 'is_spent': self.is_spent,
            }
        }

    def dispose(self):
        if self._disposed: return
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
            if self.outcomes:
                for value in self.outcomes.values():
                    outcomes_to_dispose = value if self._multiple_outcomes_per_task else [value]
                    for obj in outcomes_to_dispose: obj.dispose()
            self.outcomes.clear()
            self._broken = True
            self._released = True

    def reset(self):
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
        """Return every successful .result() gathered so far."""
        if self._disposed:
            return []

        successful: List[Any] = []

        # helper: flatten any container that is **not** an Outcome itself
        def _iter_outcomes(val):
            if hasattr(val, "done"):  # a single Outcome
                yield val
            elif isinstance(val, Iterable):  # list / ConcurrentList / tuple …
                yield from val
            else:  # should never happen, but safe-guard
                return

        for bucket in self.outcomes.values():
            for o in _iter_outcomes(bucket):
                if o.done and o.exception() is None:
                    try:
                        successful.append(o.result())
                    except Exception:
                        pass  # ignore retrieval failures

        return successful

    @property
    def exceptions(self) -> List[Exception]:
        """Return every non-disposed exception captured so far."""
        if self._disposed:
            return []

        errors: List[Exception] = []

        def _iter_outcomes(val):
            if hasattr(val, "done"):  # single Outcome
                yield val
            elif isinstance(val, Iterable):  # list / ConcurrentList
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
        return self._released and not self.reusable

    def release(self) -> None:
        with self._lock:
            if self._disposed or not self.manual_release or self._released: return
            self._released = True
            if self._manual_release_gate: self._manual_release_gate.set()
            if self._controller: self._controller.notify(self.id, "MANUALLY_RELEASED")

    def notify_all_override(self) -> None:
        with self._lock:
            if self._disposed or self._released:
                return
            self._broken = True
            self._released = True

            # 1️⃣ Wake whichever main barrier we’re using
            if self._main_barrier:
                try:
                    if hasattr(self._main_barrier, "notify_all_override"):
                        self._main_barrier.notify_all_override()
                    else:  # ClockBarrier
                        self._main_barrier.release()
                except Exception:
                    pass  # don't let a bad barrier keep others stuck

            # 2️⃣ Wake any follow-on gates so `start()` can bail early
            if self._dynaphore:
                self._dynaphore.release_all()
            if self._manual_release_gate:
                self._manual_release_gate.set()

            # 3️⃣ Tell the controller **once**
            if self._controller and not self._barrier_passed_notified:
                self._barrier_passed_notified = True
                self._controller.notify(self.id, "BARRIER_BROKEN")

    def _execute_operation(self, task: Callable, index: int) -> None:
        self._internal_threshold_barrier.wait()
        try:
            self._set_result(task(), index)
        except Exception as e:
            self._set_exception(e, index)

    def _execute_operations(self):
        """Executes tasks and callbacks, ensuring manual release gate is checked."""
        # --- FIX: Moved task execution into its own block ---
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
        new_outcome = Outcome()
        new_outcome.set_result(result)
        if self._multiple_outcomes_per_task:
            outcome_list = self.outcomes.setdefault(index, ConcurrentList())
            outcome_list.append(new_outcome)
        else:
            self.outcomes.setdefault(index, new_outcome)

    def _set_exception(self, e: Exception, index: int):
        new_outcome = Outcome()
        new_outcome.set_exception(e)
        if self._multiple_outcomes_per_task:
            outcome_list = self.outcomes.setdefault(index, ConcurrentList())
            outcome_list.append(new_outcome)
        else:
            self.outcomes.setdefault(index, new_outcome)

    def _set_main_barrier(self) -> None:
        """Sets the main barrier for synchronization."""
        self._main_barrier = self._clock_barrier or self._signal_barrier

    def start(self, timeout: float = None) -> None:
        """Blocks the calling thread until the threshold is met, then executes tasks."""
        if self._disposed or self._broken or self.is_spent():
            return
        try:
            self._main_barrier.wait()
            if self._broken:  # override hit while we were waiting
                return
            with self._lock:
                if self._controller and not self._barrier_passed_notified:
                    self._barrier_passed_notified = True
                    self._controller.notify(self.id, "BARRIER_PASSED")

            if not self._dynaphore.wait_for_permit(timeout): #This locks out additional threads until the threshold is met
                return

            if self._broken:
                return
            try:
                self._execute_operations()
            finally:
                pass

        except Exception as e:
            # --- FIX: Correctly handle BrokenBarrierError on timeout ---
            if self._raise_on_timeout and isinstance(e, threading.BrokenBarrierError):
                raise TimeoutError("Conductor wait timed out.") from e

            self.notify_all_override()