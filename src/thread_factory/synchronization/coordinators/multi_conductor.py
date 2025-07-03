from __future__ import annotations
import threading, ulid
from typing import Optional, Callable, List, Union, Any, Dict, Tuple
from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.synchronization.dispatchers.fork import Fork
from thread_factory.synchronization.dispatchers.sync_fork import SyncFork
from thread_factory.utils.coordination.package import Pack
from thread_factory.utils.interfaces.disposable import IDisposable
from thread_factory.utils.coordination.group import Group
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.utils.coordination.outcome import Outcome
from thread_factory.synchronization.primitives import Dynaphore
from thread_factory.synchronization.coordinators.clock_barrier import ClockBarrier
from thread_factory.synchronization.primitives.signal_barrier import SignalBarrier
from thread_factory.concurrency.sync_types.sync_bool import SyncBool


class MultiConductor(IDisposable):
    """
    MultiConductor
    --------------
    A reusable, data-aware synchronization point that manages multiple groups of tasks.

    The `MultiConductor` extends the functionality of a traditional `Conductor` to manage multiple,
    named groups of tasks, ensuring they are executed in a synchronized and lock-step manner. This
    means that once the required threshold of threads has arrived, each thread will execute every task
    from every group sequentially, synchronizing between tasks. If there are multiple groups, all tasks
    in a group will be executed before moving on to the next group.

    Features:
    ----------
    - **Task Synchronization**: Ensures that multiple tasks across groups are executed in lock-step.
    - **Manual Release**: Supports manual release to ensure threads only proceed when explicitly instructed.
    - **Timeout Handling**: Includes optional timeout behavior, raising a `TimeoutError` if tasks don't complete in time.
    - **Reusability**: The conductor can be reset to synchronize tasks across multiple cycles.
    - **Multiple Outcomes per Task**: Allows tracking of multiple results per task, useful for reusable cycles.
    - **Concurrent and Parallel Execution**: Supports both concurrent and parallel execution modes, allowing for flexible task management.

    This class is particularly useful in scenarios where a large number of threads need to execute tasks
    across multiple groups while maintaining synchronization at each stage of execution.

    Attributes:
    -----------
    - `threshold`: The number of threads required to execute tasks.
    - `groups`: The list of task groups to be executed by threads.
    - `reusable`: If True, the conductor can be reused after completing a cycle.
    - `manual_release`: If True, threads will only proceed when manually released.
    - `timeout`: The timeout duration for waiting on threads to arrive.
    - `callback`: An optional callback to be executed after each task.
    - `controller`: An optional signal controller for managing state changes.


    # NOTE #: Syncfork and Fork Operations:
    - If `sync_distributed_execution` is True, the conductor will use a `SyncFork` to manage task execution.
    - If `distributed_execution` is True, the conductor will use a `Fork` to manage task execution.
    - If both are True, a `ValueError` is raised, as they are mutually exclusive.
    - If neither is True, tasks will in parallel but sequentially across tasks.

    Example:
    --------
    >>> conductor = MultiConductor(threshold=5, groups=[group1, group2])
    >>> conductor.start()
    """
    __slots__ = IDisposable.__slots__ + [
        "_threshold", "groups", "reusable", "manual_release",
        "_timeout", "_raise_on_timeout", "_multiple_outcomes_per_task", "_callback",
        "_controller", "_id", "_released", "_broken", "_main_barrier",
        "_lock", "_dynaphore", "_manual_release_gate", "_callback_executed_flags",
        "_barrier_passed_notified", "_execution_started_notified", "_execution_completed_notified",
        "_clock_barrier", "_signal_barrier", "_internal_threshold_barrier", "outcomes", "_enabled",
        "_distributed_execution", "_sync_distributed_execution", "_create_fork", "_fork_processor",

    ]
    def __init__(
            self,
            threshold: int,
            groups: Optional[Union[List[Group], ConcurrentList[Group]]] = None,
            reusable: bool = False,
            manual_release: bool = False,
            timeout: Optional[float] = None,
            raise_on_timeout: bool = False,
            multiple_outcomes_per_task: bool = False,
            distributed_execution: bool = False,
            sync_distributed_execution: bool = False,
            callback: Optional[Union[Callable[..., None], Pack]] = None,
            controller: Optional['SignalController'] = None
    ):
        """
        Initializes the MultiConductor with the provided configuration.

        Args:
            threshold (int):
                The number of threads required to meet the synchronization point. Must be positive.
            groups (Optional[List[Group]]):
                A list of `Group` objects, each representing a set of tasks to be executed in parallel.
            reusable (bool):
                If True, the conductor can be reused for multiple cycles.
            manual_release (bool):
                If True, threads will only proceed when manually released via `release()`.
            timeout (Optional[float]):
                The maximum time to wait for the threshold to be met, in seconds. If None, no timeout.
            raise_on_timeout (bool):
                If True, raises a `TimeoutError` if the timeout occurs.
            multiple_outcomes_per_task (bool):
                If True, allows storing multiple outcomes per task in a list.
            concurrent_execution (bool):
                If True, the tasks will be executed concurrently across threads.
            parallel_execution (bool):
                If True, the tasks will be executed in parallel, with each task assigned to a different thread.
            callback (Optional[Callable[[], None]]):
                A callback function to be executed after each task is completed.
            controller (Optional['SignalController']):
                An optional controller that can notify state changes during the execution.

        Raises:
            ValueError: If `threshold` is not a positive integer.
        """
        super().__init__()
        if threshold <= 0:
            raise ValueError("Threshold must be a positive integer.")
        if not isinstance(threshold, int):
            raise TypeError("Threshold must be an integer.")

        # --- Initialize outcomes storage ---
        self.outcomes: ConcurrentDict = ConcurrentDict()

        # --- Initialization of internal state ---
        self._id: str = str(ulid.ULID())
        self._enabled: bool = False
        self._distributed_execution: bool = distributed_execution
        self._sync_distributed_execution: bool = sync_distributed_execution
        self._threshold: int = threshold
        self.reusable: bool = reusable
        self.manual_release: bool = manual_release
        self._timeout: float = timeout
        self._raise_on_timeout:bool  = raise_on_timeout
        self._multiple_outcomes_per_task: bool = multiple_outcomes_per_task
        self._released: bool = False
        self._broken: bool = False
        self._barrier_passed_notified: bool = False
        self._execution_started_notified: bool = False
        self._execution_completed_notified: bool = False
        self._create_fork: SyncBool = SyncBool(False)
        self._fork_processor: Optional[SyncFork, Fork] = None

        # --- Callback Management ---
        self.groups: Optional[Group] | ConcurrentList[Group] = ConcurrentList[Group]()
        self._callback: Union[Callable[..., None], Pack] = Pack.bundle(callback) if callback else None
        if groups:
            for group in groups:
                # ✅ This check ensures the Group and MultiConductor configurations match.
                if group._multiple_outcomes_per_task != self._multiple_outcomes_per_task:
                    raise ValueError(
                        f"Mismatch in 'multiple_outcomes_per_task' setting between "
                        f"MultiConductor and Group '{group.name}'."
                    )
                self.add_group(group)
        self._callback_executed_flags = {}

        # --- Synchronization primitives ---
        self._lock: threading.RLock = threading.RLock()
        self._dynaphore: Dynaphore = Dynaphore(threshold)
        self._manual_release_gate: threading.Event | None = threading.Event() if manual_release else None
        self._internal_threshold_barrier: SignalBarrier = SignalBarrier(threshold, reusable=True)
        self._clock_barrier: ClockBarrier | None = None
        self._signal_barrier: SignalBarrier | None = None

        # --- Initialize the main barrier based on timeout ---
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

        # --- Initialize the controller if provided ---
        self._controller: 'Controller' = controller
        if self._controller:
            try: self._controller.register(self)
            except Exception: pass

        if self._distributed_execution and self._sync_distributed_execution:
            raise ValueError("Cannot set both concurrent_execution and parallel_execution to True. Choose one.")
        if self._sync_distributed_execution:
            self._check_if_eligible_for_sync_fork()

    def dispose(self):
        """
        Disposes of the MultiConductor and all associated resources.

        This method releases all synchronization primitives, disposes of any barriers and groups,
        and marks the conductor as disposed. Once disposed, the conductor is no longer usable.

        The following actions occur:
        - Releases all waiters to prevent deadlocks.
        - Notifies the controller (if provided) that the conductor has been disposed.
        - Disposes of any internal barriers such as the `ClockBarrier`, `SignalBarrier`, and `Dynaphore`.
        - Clears the groups and outcomes data structures, ensuring no references remain.

        If called multiple times, this method will safely exit without performing any additional work.
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

    def _check_if_eligible_for_sync_fork(self) -> bool:
        """
        Check if the current thread is eligible to use SyncFork.

        This method is used to ensure that the current thread is not already
        blocked by another SyncFork instance or has not exceeded its usage cap.
        """
        counter = 0

        for group in self.groups:
            counter += len(group)

        if self._threshold >= counter:
            raise RuntimeError(
                f"MultiConductor threshold ({self._threshold}) does not match the total number of tasks "
                f"({counter}) across all groups. SyncFork cannot be used as it requires a consistent number of tasks "
                "to worker ratio 1:1.  Please adjust your workload and use less callables with queues or use a Fork instead."
            )

        if not self._multiple_outcomes_per_task:
            raise RuntimeError(
                "SyncFork requires multiple outcomes per task to be enabled. "
                "Please set 'multiple_outcomes_per_task=True' when initializing the MultiConductor."
                "This operation is threadsafe and will not cause any issues. You have more workers than tasks and"
                " therefore either reduce your worker count or increase the number of tasks per group."
            )
        return True

    def add_group(self, group: Group):
        """
        Adds a group of tasks to the conductor.

        This method allows you to add a new `Group` to the MultiConductor. The group can then be included
        in the synchronization process, and its tasks will be executed in order once the threshold of threads
        has been reached.

        Args:
            group (Group): The `Group` object containing tasks to be executed.

        Raises:
            RuntimeError: If this method is called after the conductor has been enabled (i.e., after the first `start()`).
            TypeError: If the provided object is not an instance of `Group`.
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
        """
        Locks the conductor's configuration.

        After this method is called (which happens automatically on the first
        call to `start()`), no more groups can be added or removed.
        """
        self._enabled = True

    def start(self, timeout: float = None) -> None:
        """
        Blocks the calling thread until the threshold is met, then executes tasks in lock-step.

        This is the primary method for starting the execution of tasks across all groups in the MultiConductor.
        The method will block until the `threshold` number of threads has arrived at the barrier. Once the barrier
        is passed, all threads will execute tasks across groups in a synchronized manner.

        Args:
            timeout (float, optional):
                The maximum time in seconds to wait for the threshold to be met. If not provided or set to `None`,
                the conductor will wait indefinitely until the threshold is reached.

        Raises:
            TimeoutError: If `raise_on_timeout` is True and the wait times out before the threshold is met.
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

                # if self._callback:
                #     self._execute_callback(group, task_index)

            if self._broken or self._disposed: break


    def _execute_operation(self, task: Union[Callable[..., None], Pack], group: Group, task_index: int):
        """Executes a single task and records its outcome in the correct group.

        Args:
            task (Callable): The task function to execute.
            group (Group): The group that owns the task.
            task_index (int): The index of the task, used for storing the outcome.
        """
        try:
            result = task() # Should already be a Pack
            self._set_result(result, group, task_index)
        except Exception as e:
            self._set_exception(e, group, task_index)

        # If a callback is set, execute it after the task completes
        if self._callback:
             self._execute_callback(group, task_index)

    def _create_fork_processor(self, group: Group, sync: bool = None) -> Fork | SyncFork:
        """
        Calculates how the threshold workers are distributed among the tasks of a group
        for a non-synchronizing Fork processor.

        Args:
            group (Group): The group containing tasks to be processed.

        Returns:
            Fork: The configured Fork object with worker distribution. # <-- Docstring return type changed to Fork
        """
        if sync is None:
            raise ValueError("Sync parameter must be explicitly set to True or False.")

        number_of_tasks = len(group.tasks)
        if number_of_tasks == 0:
            raise ValueError("Cannot create Fork processor for a group with no tasks.")

        # Prepare data for worker distribution: use lists for usage_cap to allow modification
        fork_units_config: list[list[Union[int, Pack]]] = []  # Type hint for list of lists

        # Initialize each task with an initial usage_cap of 0
        for task_index, task in enumerate(group.tasks):
            # ***CRITICAL FIX: Append a LIST here, NOT a tuple***
            fork_units_config.append([0, Pack(self._execute_operation, task, group, task_index)])

        # Initialize counter to 0 for standard round-robin distribution
        current_task_index: int = 0

        # Distribute all 'self._threshold' workers across the tasks in a round-robin fashion
        for _ in range(self._threshold):
            # Increase worker count (usage_cap) for the current task
            fork_units_config[current_task_index][0] += 1
            # Move to the next task in a circular fashion
            current_task_index = (current_task_index + 1) % number_of_tasks

        # Convert the list-based config to tuple-based for the Fork/SyncFork constructor
        final_fork_callables = [(cap, fn) for cap, fn in fork_units_config]

        # Return the correct Fork or SyncFork type based on the 'sync' parameter
        if sync:
            return SyncFork(number_of_tasks, final_fork_callables)
        else:
            return Fork(number_of_tasks, final_fork_callables, rotate_selectors=False)

    def _calculate_fork_processor(self, group: Group) -> Optional[Fork, SyncFork]:
        """
        Determines the appropriate fork processor based on the conductor's configuration.
        """
        if self._sync_distributed_execution and not self._distributed_execution:
            return self._create_fork_processor(group, sync=True)
        elif self._distributed_execution:
            return self._create_fork_processor(group, sync=False)
        else:
            raise ValueError(
                "Unknown Error, please check your MultiConductor configuration. "
            )

    def _fork_execution_loop(self):
        """
        Executes tasks in a forked manner, using the Fork or SyncFork processor.
        """
        for group in self.groups:
            if self._broken or self._disposed: break
            if not self._create_fork:
                self._fork_processor = self._calculate_fork_processor(group)
            self._fork_processor.use_fork()
            self._internal_threshold_barrier.wait()
            self._create_fork = False

    def _execute_operations(self):
        """
        Orchestrates the task execution across all groups.

        This method is responsible for coordinating the execution of tasks within each group once the threshold
        has been met. It synchronizes the execution of tasks, ensuring that all threads execute the tasks in the
        correct order, and waits at barriers between each task.

        The method also ensures that the appropriate callbacks are executed after each task completes.

        If concurrent or parallel execution is enabled, it will modify the execution flow accordingly to achieve
        the desired behavior.

        The method ensures that the task execution continues until all tasks from all groups have been executed,
        or the conductor is disposed or broken.
        """
        if self.groups:
            with self._lock:
                if self._controller and not self._execution_started_notified:
                    self._execution_started_notified = True
                    self._controller.notify(self.id, "EXECUTION_STARTED")

            if self._sync_distributed_execution or self._distributed_execution:
                self._fork_execution_loop()
            else:
                self._general_execution_loop()

            with self._lock:
                if self._controller and not self._execution_completed_notified and not (self._broken or self._disposed):
                    self._execution_completed_notified = True
                    self._controller.notify(self.id, "EXECUTION_COMPLETED")

        if self.manual_release:
            self._manual_release_gate.wait()
        else:
            self._released = True

    def _execute_callback(self, group: Group, task_index: int = None, ignore_task_id: bool = False):
        """Executes the shared callback, ensuring it runs only once per task.

        This method uses a lock and a flag to guarantee that, even though all
        threads will call it, the callback function is only executed by the
        first thread to acquire the lock for a given task.

        Args:
            group (Group): The group to which the completed task belongs.
            task_index (int): The index of the completed task within the group.
        """
        with self._lock:
            if ignore_task_id:
                try:
                    self._callback()
                except Exception as e:
                    if self._controller and hasattr(self._controller, '_logger'):
                        self._controller._logger.error(f"Error in MultiConductor callback: {e}", exc_info=True)
            else:
                if not self._callback_executed_flags[group.name][task_index]:
                    self._callback_executed_flags[group.name][task_index] = True
                try:
                    self._callback()
                except Exception as e:
                    if self._controller and hasattr(self._controller, '_logger'):
                        self._controller._logger.error(f"Error in MultiConductor callback: {e}", exc_info=True)


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
        """
        Returns all outcomes from all groups, keyed by group name.

        This method aggregates the outcomes from all tasks within each group and returns them as a dictionary
        (either `ConcurrentDict` or standard Python `dict`, based on the `as_concurrent_dict` flag). Outcomes
        include both results and exceptions that occurred during task execution.

        Args:
            as_concurrent_dict (bool): If True, returns the internal `ConcurrentDict` that stores the outcomes.
                                       If False, returns a standard Python `dict` containing a copy of the outcomes.

        Returns:
            Union[Dict, ConcurrentDict]: A dictionary containing the outcomes for each group. The outcomes
                                         are grouped by the group name (keys), with the values being a list
                                         of the results and exceptions for the respective tasks.
        """
        return self.outcomes if as_concurrent_dict else dict(self.outcomes)

    @property
    def results(self) -> List[Any]:
        """
        A flat list of all successful results from all tasks in all groups.

        This property extracts and returns all successful task results from every task in every group, concatenated
        into a single, flat list. If the `MultiConductor` has been disposed, it will return an empty list.

        Returns:
            List[Any]: A list of all successful results collected from the tasks across all groups.
        """
        if self._disposed: return []
        return [res for group in self.groups for res in group.results]

    @property
    def exceptions(self) -> List[Exception]:
        """
        A flat list of all exceptions from all tasks in all groups.

        This property extracts and returns all exceptions that occurred during the execution of tasks across all groups,
        concatenated into a single, flat list. If the `MultiConductor` has been disposed, it will return an empty list.

        Returns:
            List[Exception]: A list of all exceptions collected from the tasks across all groups.
        """
        if self._disposed: return []
        return [exc for group in self.groups for exc in group.exceptions]

    def is_spent(self) -> bool:
        """
        Checks if the conductor has completed its cycle and is not reusable.

        This method checks whether the conductor has been released (i.e., its cycle has been completed) and if
        the conductor is not reusable. It is used to determine whether the conductor can be reused for another cycle
        or if it has reached its end.

        Returns:
            bool: True if the conductor has completed its cycle and is not reusable, False otherwise.
        """
        return self._released and not self.reusable

    def release(self):
        """
        Manually releases the conductor from its final wait state.

        This method is used to manually release the conductor from its waiting state, allowing all threads to proceed.
        It is only effective if the `manual_release` flag was set to `True` during initialization. This will trigger
        the conductor to notify the controller (if any) and proceed with task execution.

        If `manual_release` is not set to `True`, calling this method will have no effect.

        Raises:
            RuntimeError: If the conductor is already disposed or broken, or if it's not in a manual release state.
        """
        with self._lock:
            if self._disposed or not self.manual_release or self._released: return
            self._released = True
            if self._manual_release_gate: self._manual_release_gate.set()
            if self._controller: self._controller.notify(self.id, "MANUALLY_RELEASED")

    def notify_all_override(self):
        """
        Forcibly breaks the barrier and releases all waiting threads.

        This method immediately releases all waiting threads, bypassing the normal synchronization process. It is
        intended for emergency situations or when an external event requires immediate intervention. Calling this
        method will break the barrier and release all threads regardless of whether the threshold is met.

        If the conductor has been disposed or is already released, this method has no effect.

        Raises:
            RuntimeError: If the conductor is disposed or broken, preventing the barrier from being forcibly released.
        """
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
        """
        The unique, time-sortable identifier for this MultiConductor.

        This property returns the unique identifier (ULID) assigned to the MultiConductor instance. The identifier
        is time-sortable, meaning that lexicographically sorting the IDs will result in a chronological order.

        Returns:
            str: The unique identifier for this MultiConductor.
        """
        return self._id

    def _get_object_details(self) -> ConcurrentDict[str, Any]:
        """
        Prepares a summary of the instance for controller registration.

        This method returns a dictionary containing key metadata about the `MultiConductor` instance. It provides
        details such as the name of the component and a set of commands that can be executed by the controller.

        Returns:
            ConcurrentDict[str, Any]: A dictionary containing the name of the instance and the commands that can be triggered
                             by the controller.
        """
        return ConcurrentDict({
            'name': 'multiconductor',
            'commands': ConcurrentDict({
                'dispose': self.dispose, 'reset': self.reset, 'release': self.release,
                'notify_all_override': self.notify_all_override, 'is_spent': self.is_spent,
            })
        })