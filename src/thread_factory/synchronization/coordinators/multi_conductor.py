from __future__ import annotations
import threading, ulid
from typing import Optional, Callable, List, Union, Any, Dict
from thread_factory.utils.interfaces.disposable import IDisposable
from thread_factory.utils.coordination.group import Group
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.utils.coordination.outcome import Outcome
from thread_factory.synchronization.primitives import Dynaphore
from thread_factory.synchronization.coordinators.clock_barrier import ClockBarrier
from thread_factory.synchronization.primitives.signal_barrier import SignalBarrier
from thread_factory.synchronization.dispatchers.fork import Fork
from thread_factory.synchronization.dispatchers.sync_fork import SyncFork


class MultiConductor(IDisposable):
    """A reusable, data-aware synchronization point that executes tasks in groups.

    The MultiConductor extends the Conductor's pattern to manage multiple, named
    groups of tasks. It acts as a single, overarching barrier that synchronizes
    all participating threads. Once the specified `threshold` of threads arrives,
    all threads are released to execute every task from every group in a
    lock-step, synchronized manner.

    This ensures that if 50 threads arrive at a MultiConductor with two groups
    of tasks, all 50 threads will execute task 1 of group 1, then synchronize,
    then execute task 2 of group 1, synchronize, and then proceed to execute
    all tasks of group 2 in the same fashion.

    It supports the same features as the Conductor, including reusability,
    manual release, timeouts, and SignalController integration.
    """
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
            task_concurrent_execution: bool = False,
            parallel_sync_execution: bool = False,
            callback: Optional[Callable[[], None]] = None,
            controller: Optional['SignalController'] = None
    ):
        """Initializes a new MultiConductor instance.

        Args:
            threshold (int):
                The number of threads that must call `start()` before the barrier
                is passed and tasks are executed. Must be a positive integer.
            groups (Optional[List[Group]]):
                An optional initial list of `Group` objects, each containing its
                own set of tasks.
            reusable (bool):
                If True, the conductor can be reset for subsequent synchronization
                cycles. Defaults to False.
            manual_release (bool):
                If True, the conductor will wait for an explicit call to `release()`
                after all tasks are complete. Defaults to False.
            timeout (Optional[float]):
                The maximum time in seconds to wait for the threshold to be met.
                Must be a positive number if provided.
            raise_on_timeout (bool):
                If True, raises a `TimeoutError` when a timeout occurs.
                Defaults to False.
            multiple_outcomes_per_task (bool):
                If True, allows each task to store multiple results in a list,
                useful for reusable cycles. Defaults to False.
            callback (Optional[Callable[[], None]]):
                An optional function to be called after each task in every group
                completes its execution.
            controller (Optional['SignalController']):
                An optional `SignalController` for receiving state change
                notifications.
        """
        super().__init__()
        if threshold <= 0:
            raise ValueError("Threshold must be a positive integer.")

        self._parallel = task_concurrent_execution
        self._parallel_sync_execution = parallel_sync_execution
        self._threshold = threshold
        self.groups = []
        self.reusable = reusable
        self.manual_release = manual_release
        self._timeout = timeout
        self._raise_on_timeout = raise_on_timeout
        self._multiple_outcomes_per_task = multiple_outcomes_per_task
        self._callback = callback
        self._controller = controller
        self._id = str(ulid.ULID())
        self._enabled = False

        self.outcomes = ConcurrentDict()
        if groups:
            for group in groups:
                # ✅ This check ensures the Group and MultiConductor configurations match.
                if group._multiple_outcomes_per_task != self._multiple_outcomes_per_task:
                    raise ValueError(
                        f"Mismatch in 'multiple_outcomes_per_task' setting between "
                        f"MultiConductor and Group '{group.name}'."
                    )
                self.add_group(group)

        self._released = False
        self._broken = False
        self._lock = threading.RLock()
        self._dynaphore = Dynaphore(threshold)
        self._manual_release_gate = threading.Event() if manual_release else None
        self._internal_threshold_barrier = SignalBarrier(threshold, reusable=True)
        self._barrier_passed_notified = False
        self._execution_started_notified = False
        self._execution_completed_notified = False
        self._callback_executed_flags = {}
        self._clock_barrier = None
        self._signal_barrier = None

        if timeout is not None:
            if timeout <= 0:
                raise ValueError("Timeout must be positive.")
            self._clock_barrier = ClockBarrier(
                threshold, timeout, self.notify_all_override, controller
            )
        else:
            self._signal_barrier = SignalBarrier(
                threshold=threshold, reusable=reusable, controller=controller
            )

        self._main_barrier = self._clock_barrier or self._signal_barrier
        if self._controller:
            try: self._controller.register(self)
            except Exception: pass


    def dispose(self):
        """
        Disposes of the MultiConductor and all its associated resources.
        """
        if self._disposed:
            return

        with self._lock:
            if self._disposed:  # Double-check inside lock
                return

            self._disposed = True
            self._broken = True
            self._released = True

            # --- Step 1: Immediately release all possible waiters ---
            # This is the most critical step to prevent deadlocks during shutdown.
            # It ensures any thread waiting on THIS object is unblocked before
            # we proceed with any other cleanup.
            if self._clock_barrier:
                self._clock_barrier.dispose()
            if self._signal_barrier:
                self._signal_barrier.dispose()
            if self._internal_threshold_barrier:
                self._internal_threshold_barrier.dispose()
            if self._dynaphore:
                self._dynaphore.dispose()
            if self._manual_release_gate:
                self._manual_release_gate.set()

            # --- Step 2: Perform secondary cleanup of child objects and data ---
            # This is now safe to do because no threads are stuck waiting on us.
            if self._controller:
                self._controller.notify(self.id, "DISPOSED")
                self._controller = None

            for group in self.groups:
                group.dispose()

            self.groups.clear()
            self.outcomes.clear()

    def add_group(self, group: Group):
        """Adds a group of tasks to the conductor.

        This method must be called before the conductor is first used (i.e.,
        before the first call to `start()`).

        Args:
            group (Group): The `Group` object to add.

        Raises:
            RuntimeError: If called after the conductor has been enabled.
            TypeError: If the object provided is not an instance of `Group`.
        """
        if self._enabled:
            raise RuntimeError("Cannot add groups after MultiConductor is active.")
        if not isinstance(group, Group):
            raise TypeError("Only Group objects can be added.")
        self.groups.append(group)
        self.outcomes[group.name] = group.outcomes
        if self._callback:
            self._callback_executed_flags[group.name] = [False for _ in group.tasks]

    def remove_group(self, group: Group):
        """Removes a group of tasks from the conductor.

        This method must be called before the conductor is first used.

        Args:
            group (Group): The `Group` object to remove.

        Raises:
            RuntimeError: If called after the conductor has been enabled.
        """
        if self._enabled:
            raise RuntimeError("Cannot remove groups after MultiConductor is active.")
        try:
            self.groups.remove(group)
            del self.outcomes[group.name]
            if self._callback:
                del self._callback_executed_flags[group.name]
        except (ValueError, KeyError):
            pass

    def enable(self):
        """Locks the conductor's configuration.

        After this method is called (which happens automatically on the first
        call to `start()`), no more groups can be added or removed.
        """
        self._enabled = True

    def start(self, timeout: float = None) -> None:
        """Blocks the calling thread until the threshold is met, then executes tasks.

        This is the primary entry point for threads. Each call blocks until the
        `threshold` number of threads has arrived. Once the barrier passes,
        the thread acquires a permit to participate in the synchronized execution
        of all tasks across all groups.

        Args:
            timeout (float, optional):
                A timeout for the permit acquisition phase. If a permit cannot
                be acquired in time, the method returns.

        Raises:
            TimeoutError:
                If `raise_on_timeout` is True and the main barrier wait times out.
        """
        if not self._enabled:
            self.enable()
        if self._disposed or self._broken or self.is_spent():
            return
        try:
            self._main_barrier.wait()
            if self._broken: return

            with self._lock:
                if self._controller and not self._barrier_passed_notified:
                    self._barrier_passed_notified = True
                    self._controller.notify(self.id, "BARRIER_PASSED")

            if self._dynaphore.wait_for_permit(timeout):
                try:
                    if self._broken:
                        return
                    self._execute_operations()
                finally:
                    if not self._disposed:
                        self._dynaphore.release_permit()

        except Exception as e:
            if self._raise_on_timeout and isinstance(e, threading.BrokenBarrierError):
                raise TimeoutError("MultiConductor wait timed out.") from e
            self.notify_all_override()

    def _general_execution_loop(self):
        """
        The main execution loop that iterates through all groups and their tasks.
        """
        for group in self.groups:
            for task_index, task in enumerate(group.tasks):

                if self._broken or self._disposed: break

                self._execute_operation(task, group, task_index)
                self._internal_threshold_barrier.wait()

                if self._callback:
                    self._execute_callback(group, task_index)

            if self._broken or self._disposed: break

    def _parallel_execution_loop(self):
        pass


    def _parallel_sync_execution_loop(self):
        pass

    def _execute_operations(self):
        """Orchestrates the entire task execution sequence across all groups.

        This method is the control loop for all post-barrier work. It iterates
        through each group, and for each task within that group, it coordinates
        all participating threads to execute the task and then synchronize at a
        barrier before any thread can proceed to the next task.
        """
        if self.groups:
            with self._lock:
                if self._controller and not self._execution_started_notified:
                    self._execution_started_notified = True
                    self._controller.notify(self.id, "EXECUTION_STARTED")

            self._execution_loop()

            with self._lock:
                if self._controller and not self._execution_completed_notified and not (self._broken or self._disposed):
                    self._execution_completed_notified = True
                    self._controller.notify(self.id, "EXECUTION_COMPLETED")

        if self.manual_release:
            self._manual_release_gate.wait()
        else:
            self._released = True

    def _execute_callback(self, group: Group, task_index: int):
        """Executes the shared callback, ensuring it runs only once per task.

        This method uses a lock and a flag to guarantee that, even though all
        threads will call it, the callback function is only executed by the
        first thread to acquire the lock for a given task.

        Args:
            group (Group): The group to which the completed task belongs.
            task_index (int): The index of the completed task within the group.
        """
        with self._lock:
            if not self._callback_executed_flags[group.name][task_index]:
                self._callback_executed_flags[group.name][task_index] = True
                try:
                    self._callback()
                except Exception as e:
                    if self._controller and hasattr(self._controller, '_logger'):
                        self._controller._logger.error(f"Error in MultiConductor callback: {e}", exc_info=True)

    def _execute_operation(self, task: Callable, group: Group, task_index: int):
        """Executes a single task and records its outcome in the correct group.

        Args:
            task (Callable): The task function to execute.
            group (Group): The group that owns the task.
            task_index (int): The index of the task, used for storing the outcome.
        """
        try:
            result = task()
            self._set_result(result, group, task_index)
        except Exception as e:
            self._set_exception(e, group, task_index)

    def _set_result(self, result: Any, group: Group, task_index: int):
        """
        Stores a successful task result in the group's Outcome object(s).
        """
        if self._multiple_outcomes_per_task:
            # When multiple outcomes are allowed, we create a new Outcome
            # for each result and append it to the list for that task.
            new_outcome = Outcome()
            new_outcome.set_result(result)
            group.outcomes[task_index].append(new_outcome)
        else:
            # ✅ REFINED LOGIC: Get the *existing* Outcome object from the
            # group and set its result. This leverages the write-once
            # safety of the Outcome object itself.
            try:
                # The first thread to call this will succeed.
                group.outcomes[task_index].set_result(result)
            except RuntimeError:
                # Subsequent threads will fail with a RuntimeError, which is expected.
                pass


    def _set_exception(self, e: Exception, group: Group, task_index: int):
        """
        Stores a task exception in the group's Outcome object(s).
        """
        if self._multiple_outcomes_per_task:
            # Create a new Outcome for each exception and append it.
            new_outcome = Outcome()
            new_outcome.set_exception(e)
            group.outcomes[task_index].append(new_outcome)
        else:
            # ✅ REFINED LOGIC: Get the *existing* Outcome object and set
            # its exception.
            try:
                group.outcomes[task_index].set_exception(e)
            except RuntimeError:
                # This is expected if another thread already set the outcome.
                pass

    def reset(self):
        """Resets the conductor and all its groups for another cycle.

        This method is only effective if the MultiConductor was initialized with
        `reusable=True`. It cascades the reset to all contained `Group` objects,
        clears all state flags, and reinitializes synchronization primitives.

        Raises:
            RuntimeError: If the MultiConductor has already been disposed.
        """
        if self._disposed: raise RuntimeError("Cannot reset a disposed MultiConductor.")
        if not self.reusable: return
        with self._lock:
            for group in self.groups:
                group.reset()
            self.outcomes = ConcurrentDict({g.name: g.outcomes for g in self.groups})
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


    def get_all_outcomes(self, as_concurrent_dict: bool = True) -> Union[Dict, ConcurrentDict]:
        """Returns all outcomes from all groups, keyed by group name.

        Args:
            as_concurrent_dict (bool): If True, returns the internal
                `ConcurrentDict`. If False, returns a standard `dict` copy.

        Returns:
            Union[Dict, ConcurrentDict]: A dictionary of all group outcomes.
        """
        return self.outcomes if as_concurrent_dict else dict(self.outcomes)

    @property
    def results(self) -> List[Any]:
        """A flat list of all successful results from all tasks in all groups."""
        if self._disposed: return []
        return [res for group in self.groups for res in group.results]

    @property
    def exceptions(self) -> List[Exception]:
        """A flat list of all exceptions from all tasks in all groups."""
        if self._disposed: return []
        return [exc for group in self.groups for exc in group.exceptions]

    def is_spent(self) -> bool:
        """Checks if the conductor has completed its cycle and is not reusable."""
        return self._released and not self.reusable

    def release(self):
        """Manually releases the conductor from its final wait state.

        If the conductor was initialized with `manual_release=True`, calling this
        method will allow the `start()` method to finally complete. It has no
        effect otherwise.
        """
        with self._lock:
            if self._disposed or not self.manual_release or self._released: return
            self._released = True
            if self._manual_release_gate: self._manual_release_gate.set()
            if self._controller: self._controller.notify(self.id, "MANUALLY_RELEASED")

    def notify_all_override(self):
        """Forcibly breaks the barrier and releases all waiting threads."""
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
        """The unique, time-sortable identifier for this MultiConductor."""
        return self._id

    def _get_object_details(self) -> Dict[str, Any]:
        """Prepares a summary of the instance for controller registration."""
        return {
            'name': 'multiconductor',
            'commands': {
                'dispose': self.dispose, 'reset': self.reset, 'release': self.release,
                'notify_all_override': self.notify_all_override, 'is_spent': self.is_spent,
            }
        }

    class ExecutionStrategies:
        pass