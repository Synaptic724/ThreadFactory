from __future__ import annotations
import threading, inspect, ulid, time
from typing import Optional, Callable, List, Union, Any, Dict
from thread_factory.utils import IDisposable, Group
from thread_factory.concurrency import ConcurrentDict, ConcurrentList
from thread_factory.utils.coordination.outcome import Outcome
from thread_factory.synchronization.primitives import Dynaphore
from thread_factory.synchronization.coordinators.clock_barrier import ClockBarrier
from thread_factory.synchronization.primitives.signal_barrier import SignalBarrier


class MultiConductor(IDisposable):
    """
    MultiConductor
    --------------------------
    A reusable, data-aware synchronization point that executes tasks organized into groups.
    This class maintains the exact execution schema of the Conductor: all participating
    threads wait at a single barrier. Once the threshold is met, ALL threads are released
    and proceed to execute ALL tasks from ALL groups in lock-step synchronization.

    This ensures that if 50 threads arrive, all 50 threads will execute task 1 (of group 1),
    then synchronize, then all 50 execute task 2 (of group 1), and so on for all tasks in
    all groups.
    """

    # Define all instance attributes in __slots__ for memory optimization.
    __slots__ = IDisposable.__slots__ + [
        "_threshold", "groups", "reusable", "manual_release",
        "_timeout", "_raise_on_timeout", "_multiple_outcomes_per_task", "_callback",
        "_controller", "_id", "_released", "_broken", "_main_barrier",
        "_lock", "_dynaphore", "_manual_release_gate", "_callback_executed_flags",
        "_barrier_passed_notified", "_execution_started_notified", "_execution_completed_notified",
        "_clock_barrier", "_signal_barrier", "_internal_threshold_barrier", "outcomes", "_enabled"
    ]

    def __init__(
            self,
            threshold: int,
            groups: Optional[List[Group]] = None,
            reusable: bool = False,
            manual_release: bool = False,
            timeout: Optional[float] = None,
            raise_on_timeout: bool = False,
            multiple_outcomes_per_task: bool = False,
            callback: Optional[Callable[[], None]] = None,
            controller: Optional['SignalController'] = None
    ):
        super().__init__()
        # The overall number of threads that must call start() before execution begins.
        if threshold <= 0:
            raise ValueError("Threshold must be a positive integer.")

        # --- Core Fields ---
        self._threshold = threshold
        self.groups = ConcurrentList()
        self.reusable = reusable
        self.manual_release = manual_release
        self._timeout = timeout
        self._raise_on_timeout = raise_on_timeout
        self._multiple_outcomes_per_task = multiple_outcomes_per_task
        self._callback = callback
        self._controller = controller
        self._id = str(ulid.ULID())
        self._enabled = False  # A flag to prevent adding groups after starting.

        # This dictionary will map group names to their respective outcome lists.
        self.outcomes = ConcurrentDict()

        # If groups are provided at initialization, add them.
        if groups:
            for group in groups:
                self.add_group(group)

        # --- State and Primitives (Identical to Conductor) ---
        self._released = False  # True when the conductor has finished its cycle.
        self._broken = False  # True if the conductor is forcibly broken (e.g., by timeout).
        self._lock = threading.RLock()  # A reentrant lock for managing internal state.
        self._dynaphore = Dynaphore(threshold)  # Manages permits for threads to execute tasks.
        self._manual_release_gate = threading.Event() if manual_release else None  # An event to hold threads if manual_release is True.
        self._internal_threshold_barrier = SignalBarrier(threshold,
                                                         reusable=True)  # Barrier to sync threads BETWEEN tasks.

        # --- Notification Flags ---
        self._barrier_passed_notified = False
        self._execution_started_notified = False
        self._execution_completed_notified = False
        self._callback_executed_flags = {}  # Tracks if the callback for a specific task has run.

        # --- Main Barrier Initialization (Identical to Conductor) ---
        # Selects the appropriate barrier type based on whether a timeout is specified.
        if timeout is not None:
            if timeout <= 0: raise ValueError("Timeout must be positive.")
            self._clock_barrier = ClockBarrier(threshold, timeout, self.notify_all_override, controller)
        else:
            self._signal_barrier = SignalBarrier(threshold, reusable, controller)
        self._main_barrier = self._clock_barrier or self._signal_barrier

        # --- Controller Registration ---
        # If a SignalController is provided, register this MultiConductor instance with it.
        if self._controller:
            try:
                self._controller.register(self)
            except Exception:
                pass  # Registration is optional, so we fail silently.

    def add_group(self, group: Group):
        """Adds a group to the conductor. Must be called before the conductor is active."""
        if self._enabled:
            raise RuntimeError("Cannot add groups after MultiConductor is active.")
        if not isinstance(group, Group):
            raise TypeError("Only Group objects can be added.")
        self.groups.append(group)
        # Map the group's name to its list of outcomes for easy lookup.
        self.outcomes[group.name] = group.outcomes
        # If a callback is used, initialize tracking flags for this group's tasks.
        if self._callback:
            self._callback_executed_flags[group.name] = [False for _ in group.tasks]

    def remove_group(self, group: Group):
        """Removes a group from the conductor. Must be called before the conductor is active."""
        if self._enabled:
            raise RuntimeError("Cannot remove groups after MultiConductor is active.")
        try:
            self.groups.remove(group)
            del self.outcomes[group.name]
            if self._callback:
                del self._callback_executed_flags[group.name]
        except (ValueError, KeyError):
            pass  # Ignore if the group is not found.

    def enable(self):
        """Locks the configuration, preparing the conductor for use and preventing further changes."""
        self._enabled = True

    # ============================================================
    #  Entry Point - Identical to Conductor
    # ============================================================
    def start(self, timeout: float = None) -> None:
        """The main entry point for threads. Blocks until the threshold is met."""
        if not self._enabled: self.enable()
        if self._disposed or self._broken or self.is_spent():
            return
        try:
            # 1. All threads wait here until `_threshold` threads have arrived.
            self._main_barrier.wait()
            if self._broken: return

            # 2. Notify the controller that the barrier has been passed.
            with self._lock:
                if self._controller and not self._barrier_passed_notified:
                    self._barrier_passed_notified = True
                    self._controller.notify(self.id, "BARRIER_PASSED")

            # 3. Acquire a permit to proceed with task execution.
            if not self._dynaphore.wait_for_permit(timeout): return

            # 4. Execute the main operation pipeline.
            try:
                self._execute_operations()
            finally:
                # 5. Release the permit after execution is complete.
                self._dynaphore.decrease_permits()

        except Exception as e:
            # Handle timeouts and other exceptions.
            if self._raise_on_timeout and isinstance(e, threading.BrokenBarrierError):
                raise TimeoutError("MultiConductor wait timed out.") from e
            self.notify_all_override()

    # ============================================================
    #  Execution Pipeline - Modified for Groups
    # ============================================================
    def _execute_operations(self):
        """
        Iterates through all groups and their tasks, executing each one
        and synchronizing all threads after every single task.
        """
        if self.groups:
            with self._lock:
                if self._controller and not self._execution_started_notified:
                    self._execution_started_notified = True
                    self._controller.notify(self.id, "EXECUTION_STARTED")

            # THE CRITICAL DOUBLE FOR-LOOP for lock-step execution.
            for group in self.groups:
                for task_index, task in enumerate(group.tasks):
                    if self._broken or self._disposed: break

                    # All threads execute the same task concurrently.
                    self._execute_operation(task, group, task_index)

                    # All threads wait here. No thread proceeds to the next task
                    # until all have finished the current one.
                    self._internal_threshold_barrier.wait()

                    # If a callback is defined, execute it (only one thread will succeed).
                    if self._callback:
                        self._execute_callback(group, task_index)

                if self._broken or self._disposed: break

            with self._lock:
                if self._controller and not self._execution_completed_notified and not (self._broken or self._disposed):
                    self._execution_completed_notified = True
                    self._controller.notify(self.id, "EXECUTION_COMPLETED")

            self._internal_threshold_barrier.wait()  # Wait for all threads to complete the current task

        # After all tasks are done, wait for a manual release if configured.
        if self.manual_release:
            self._manual_release_gate.wait()
        else:
            self._released = True

    def _execute_callback(self, group: Group, task_index: int):
        """Executes the shared callback, ensuring it runs only once per task."""
        with self._lock:
            # Check if the callback for this specific task has already been run.
            if not self._callback_executed_flags[group.name][task_index]:
                self._callback_executed_flags[group.name][task_index] = True
                try:
                    self._callback()
                except Exception as e:
                    # Log any errors in the callback via the controller's logger.
                    if self._controller and hasattr(self._controller, '_logger'):
                        self._controller._logger.error(f"Error in MultiConductor callback: {e}", exc_info=True)

    def _execute_operation(self, task: Callable, group: Group, task_index: int):
        """Executes a single task and records its outcome in the correct group."""
        try:
            result = task()
            # Store the successful result.
            self._set_result(result, group, task_index)
        except Exception as e:
            # Store the exception.
            self._set_exception(e, group, task_index)

    def _set_result(self, result: Any, group: Group, task_index: int):
        """Stores a successful task result in the group's outcomes."""
        outcome = Outcome()
        outcome.set_result(result)
        if self._multiple_outcomes_per_task:
            # Append the new outcome if multiple are allowed.
            group.outcomes[task_index].append(outcome)
        else:
            # Otherwise, overwrite the existing outcome for that task.
            group.outcomes[task_index] = outcome

    def _set_exception(self, e: Exception, group: Group, task_index: int):
        """Stores a task exception in the group's outcomes."""
        outcome = Outcome()
        outcome.set_exception(e)
        if self._multiple_outcomes_per_task:
            group.outcomes[task_index].append(outcome)
        else:
            group.outcomes[task_index] = outcome

    # ============================================================
    #  Lifecycle & Properties - Adapted for Groups
    # ============================================================
    def reset(self):
        """Resets the conductor and all its groups for another cycle."""
        if self._disposed: raise RuntimeError("Cannot reset a disposed MultiConductor.")
        if not self.reusable: return

        with self._lock:
            # Cascade the reset call to each individual group.
            for group in self.groups:
                group.reset()
            # Re-link the main outcomes dictionary after groups are reset.
            self.outcomes = ConcurrentDict({g.name: g.outcomes for g in self.groups})

            # Reset all state flags and primitives to their initial state.
            self._released = False
            self._broken = False
            self._barrier_passed_notified = False
            self._execution_started_notified = False
            self._execution_completed_notified = False
            self._callback_executed_flags = {g.name: [False] * len(g.tasks) for g in self.groups if self._callback}

            if self._clock_barrier: self._clock_barrier.reset()
            if self._signal_barrier: self._signal_barrier.reset()
            self._internal_threshold_barrier.reset()
            if self._manual_release_gate: self._manual_release_gate.clear()
            self._dynaphore.set_permits(self._threshold)

            if self._controller: self._controller.notify(self.id, "RESET")

    def dispose(self):
        """Fully disposes the conductor and cascades the disposal to all groups."""
        if self._disposed: return
        with self._lock:
            self._disposed = True
            if self._controller:
                self._controller.notify(self.id, "DISPOSED")
                self._controller = None

            # Cascade the dispose call to each group.
            for group in self.groups:
                group.dispose()
            self.groups.clear()
            self.outcomes.clear()

            # Dispose all internal synchronization primitives.
            if self._clock_barrier: self._clock_barrier.dispose()
            if self._signal_barrier: self._signal_barrier.dispose()
            if self._internal_threshold_barrier: self._internal_threshold_barrier.dispose()
            if self._dynaphore: self._dynaphore.dispose()
            if self._manual_release_gate: self._manual_release_gate.set()

            self._released = True
            self._broken = True

    def get_all_outcomes(self, as_concurrent_dict: bool = True) -> Union[Dict, ConcurrentDict]:
        """Returns all outcomes from all groups, keyed by group name."""
        return self.outcomes if as_concurrent_dict else dict(self.outcomes)

    @property
    def results(self) -> List[Any]:
        """Returns a flat list of all successful results from all tasks in all groups."""
        if self._disposed: return []
        # List comprehension to gather results from every group.
        return [res for group in self.groups for res in group.results]

    @property
    def exceptions(self) -> List[Exception]:
        """Returns a flat list of all exceptions from all tasks in all groups."""
        if self._disposed: return []
        # List comprehension to gather exceptions from every group.
        return [exc for group in self.groups for exc in group.exceptions]

    def is_spent(self) -> bool:
        """Checks if the conductor has completed its cycle and is not reusable."""
        return self._released and not self.reusable

    # --- Unchanged methods from Conductor ---

    def release(self):
        """Manually releases the conductor when `manual_release` is True."""
        with self._lock:
            if self._disposed or not self.manual_release or self._released: return
            self._released = True
            if self._manual_release_gate: self._manual_release_gate.set()
            if self._controller: self._controller.notify(self.id, "MANUALLY_RELEASED")

    def notify_all_override(self):
        """Forcibly unblocks all waiting threads and breaks the conductor."""
        with self._lock:
            if self._disposed or self._released: return
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
            if self._dynaphore: self._dynaphore.release_all()
            if self._manual_release_gate: self._manual_release_gate.set()
            if self._controller and not self._barrier_passed_notified:
                self._barrier_passed_notified = True
                self._controller.notify(self.id, "BARRIER_BROKEN")

    @property
    def id(self) -> str:
        """The unique identifier for this MultiConductor instance."""
        return self._id

    def _get_object_details(self) -> Dict[str, Any]:
        """Provides metadata for SignalController integration, exposing commands."""
        return {
            'name': 'multiconductor',
            'commands': {
                'dispose': self.dispose, 'reset': self.reset, 'release': self.release,
                'notify_all_override': self.notify_all_override, 'is_spent': self.is_spent,
            }
        }