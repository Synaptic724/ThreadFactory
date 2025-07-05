import threading, ulid
from typing import Optional, Callable, Union, Any
from thread_factory.concurrency.concurrent_queue import ConcurrentQueue
from thread_factory.runtime.factory.operations.work.work import Work
from thread_factory.runtime.worker.worker.worker import Worker, WorkerState
from thread_factory.agent.thread_pool.help_request import HelpRequest
from thread_factory.runtime.orchestrator.monitoring.records.records import WorkStatus, Record
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.utils.coordination.package import Pack


class Agent(Worker):
    """
    Agent
    ---------
    An advanced, agentic thread object that serves as the base for all profiles.
    It combines identity, state, and execution logic, designed for sophisticated,
    long-lived operations within a dynamic execution pool.


    Key Features:
    - **Unique Identity**: Each instance is assigned a unique `factory_id` for precise identification and interaction.
    - **Bound Work Integration**: Seamlessly integrates with `HelpRequest` objects, allowing the agent to bind to, manage, and execute specific work units.
    - **Stateful Operations**: Manages both its own lifecycle state (`WorkerState`) and the status of its assigned work (`WorkStatus`).
    - **Dual Memory System**: Features a private, thread-local inventory (`_private_inventory`) for isolated data and a public inventory (`_public_inventory`) for shared data within the agent's context.
    - **Behavior Routing**: Supports a primary execution loop (`_event_loop`) and can be configured to return to this loop after task completion.
    - **Framework Integration**: Designed to operate within a larger framework, such as a `CommandCenter`, for resolving and interacting with other agents.

    Attributes:
        _factory_id (str): A unique ULID assigned to the agent instance upon creation.
        _command_center ('CommandCenter'): A reference to a central coordinating object, used for resolving other agents by their ID.
        _target (Optional[Pack]): The packaged callable that the worker executes if run as a standalone thread.
        _worker_type (str): An identifier for the worker type, hardcoded to "agentic".
        _pool_agent (bool): A flag indicating if the worker is part of a dynamic thread pool, which dictates the behavior of the `run()` method.
        _return_home (bool): A flag that controls whether the agent should return to its primary event loop after completing a task.
        _lock (threading.RLock): A reentrant lock to ensure thread-safe access to shared state within the agent.
        _event_loop (Optional[Pack]): The packaged callable that defines the agent's primary or "home" execution logic.
        _value_work (Optional[HelpRequest]): The `HelpRequest` object currently bound to this agent.
        _private_inventory (threading.local): A thread-local storage object containing a `ConcurrentDict` for data private to this agent's thread.
        _public_inventory (ConcurrentDict[str, Any]): A dictionary for storing data that is publicly accessible within the agent's scope.
    """

    def __init__(self, command_center: 'CommandCenter', target: Union[Callable[..., Any], Pack] = None, factory_id: Optional[str | int] = None,
                 factory: Any = None, work_queue: Optional[ConcurrentQueue[Work]] = None, *args, **kwargs):
        """
        Initializes the agentic profile, sets up all agentic state, and
        prepares the thread for execution. It extends the base `Worker`
        initialization with features for dynamic behavior, stateful operations,
        and flexible data management.

        Args:
            command_center ('CommandCenter'): A reference to the central coordinating entity,
                such as a thread pool or orchestrator, that can resolve agents by ID.
            target (Union[Callable[..., Any], Pack], optional): The target function or `Pack`
                to execute. This is primarily used if the agent is run as a standalone
                thread (`_pool_agent=False`). Defaults to None.
            *args: Arbitrary positional arguments passed to the base `Worker` constructor.
            **kwargs: Arbitrary keyword arguments passed to the base `Worker` constructor.

        Raises:
            TypeError: If the provided `target` is not a `Callable` or `Pack` instance.
        """
        # --- Initialize Base Classes ---
        super().__init__(command_center, target, factory_id=factory_id, factory=factory, work_queue=work_queue, *args, **kwargs)
        if target and (isinstance(target, Callable) or isinstance(target, Pack)):
            self._target = Pack.bundle(target)
        elif target is not None:
            raise TypeError("Target must be a Callable or Pack instance.")
        else:
            self._target = None

        # --- Identity & Framework Integration ---
        self._factory_id = str(ulid.ULID())
        self._command_center = command_center

        # --- Agentic Configuration ---
        self._worker_type = "agentic"
        self._pool_agent: bool = True
        self._return_home: bool = False
        self._lock = threading.RLock()

        # --- Behavior & Execution ---
        self._event_loop: Optional[Pack] = None
        self._value_work: Optional[HelpRequest] = None

        # --- Memory & State ---
        self._private_inventory = threading.local()
        self._private_inventory.data = ConcurrentDict()
        self._public_inventory: ConcurrentDict[str, Any] = ConcurrentDict()

    # --- Framework Integration & Identity ---
    @property
    def factory_id(self) -> str:
        """
        Returns the unique factory ID of this agent instance.

        Returns:
            str: The unique ULID identifier.
        """
        return self._factory_id

    def set_target(self, target: Union[Callable[..., Any], Pack]) -> None:
        """
        This method sets the target function or `Pack` for the agent.
        """
        if target and (isinstance(target, Callable) or isinstance(target, Pack)):
            self._target = Pack.bundle(target)
        elif target is not None:
            raise TypeError("Target must be a Callable or Pack instance.")
        else:
            self._target = None

    def get_name(self) -> str:
        """
        Retrieves the name of the agent profile.

        Returns:
            str: A string indicating this is a base profile.
        """
        return "This is a BaseProfile, and thus is nameless until specialized."

    def get_description(self) -> str:
        """
        Retrieves a description of the agent profile.

        Returns:
            str: A string describing the purpose of the base profile.
        """
        return "This is a BaseProfile, its purpose is to provide a base for agent profiles."

    def __repr__(self) -> str:
        """
        Provides a developer-friendly string representation of the agent.

        Returns:
            str: A string showing the agent's ID and current state.
        """
        return f"<AgenticProfile id={self.factory_id} state={self.state.name}>"

    def __str__(self) -> str:
        """
        Provides a user-friendly string representation of the agent.

        Returns:
            str: A string showing the agent's type and ID.
        """
        return f"AgenticProfile<{self.factory_id}>"

    def dispose(self):
        """
        Performs a comprehensive cleanup of the agent's state, clears
        all references, and then triggers the disposal process of its base class.
        This is safe to call multiple times.
        """
        if self._disposed:
            return

        # Dispose agent-specific resources
        self._dispose_work()
        self._private_inventory.data.dispose()
        self._private_inventory = None
        self._public_inventory.dispose()
        self._public_inventory = None

        self._event_loop = None
        self._command_center = None

        super().dispose()  # Call parent dispose if it exists

    def _dispose_work(self) -> None:
        """
        Disposes of the `HelpRequest` currently bound to this worker and
        detaches it, clearing the reference.

        This is typically called when a work item is no longer needed or after
        its completion/failure, allowing for resource cleanup.
        """
        if self._value_work:
            self._value_work.dispose()
            self._value_work = None

    def _set_work_state(self, new_state: WorkStatus) -> None:
        """
        Sets the status of the `HelpRequest` currently bound to this agent.

        Args:
            new_state (WorkStatus): The new status to apply to the bound work.
        """
        if self._value_work:
            self._value_work.set_state(new_state)

    def _get_work_state(self) -> Optional[WorkStatus]:
        """
        Retrieves the current status of the `HelpRequest` bound to this agent.

        Returns:
            Optional[WorkStatus]: The current status of the bound work, or `None`
                if no work is bound.
        """
        if self._value_work:
            return self._value_work.get_state()
        return None

    def _get_value_work(self) -> Optional[HelpRequest]:
        """
        Retrieves the `HelpRequest` instance currently bound to this agent.

        Returns:
            Optional[HelpRequest]: The bound `HelpRequest` object, or `None` if
                no work is currently assigned.
        """
        return self._value_work

    def _set_value_work(self, help_request: HelpRequest) -> None:
        """
        Binds a `HelpRequest` instance to this agent.

        Args:
            help_request (HelpRequest): The `HelpRequest` object to bind.
        """
        self._value_work = help_request

    def _mark_work_in_progress(self) -> None:
        """Convenience method to mark the bound work as 'in progress'."""
        if self._value_work:
            self._value_work.mark_in_progress()

    def _mark_work_completed(self) -> None:
        """Convenience method to mark the bound work as 'completed'."""
        if self._value_work:
            self._value_work.mark_completed()

    def _mark_work_failed(self) -> None:
        """Convenience method to mark the bound work as 'failed'."""
        if self._value_work:
            self._value_work.mark_failed()

    def _mark_work_cancelled(self) -> None:
        """Convenience method to mark the bound work as 'cancelled'."""
        if self._value_work:
            self._value_work.mark_cancelled()

    def _reset_work(self) -> None:
        """Resets the bound `HelpRequest` to its initial 'pending' state."""
        if self._value_work:
            self._value_work.reset()

    def _get_work_record(self) -> Optional[Record]:
        """
        Retrieves the `Record` object from the bound `HelpRequest`.

        Returns:
            Optional[Record]: The record associated with the work, or `None`.
        """
        if self._value_work:
            return self._value_work.get_record()
        return None

    def _acquire_and_run_work(self):
        """Initiates the execution of the `HelpRequest` bound to this agent."""
        if self._value_work:
            self._value_work.acquire_work()

    def _cancel_bound_job(self):
        """Cancels the job associated with the bound `HelpRequest`."""
        if self._value_work:
            self._value_work.cancel_job()

    # --- Behavior Routing & Execution ---
    def should_return_home(self) -> bool:
        """
        Checks if the agent is configured to return to its home event loop.

        Returns:
            bool: `True` if the agent should return home, `False` otherwise.

        Raises:
            RuntimeError: If the agent has been disposed.
        """
        with self._lock:
            if self._disposed:
                raise RuntimeError("Cannot check return home status after agent is disposed.")
            return self._return_home

    def set_return_home(self, return_home: bool) -> None:
        """
        Sets whether the agent should return to its home event loop.

        Args:
            return_home (bool): `True` to enable returning to the event loop.

        Raises:
            RuntimeError: If the agent has been disposed.
        """
        with self._lock:
            if self._disposed:
                raise RuntimeError("Cannot set return home status after agent is disposed.")
            self._return_home = return_home

    def _resolve_worker_by_id(self, factory_id: str) -> Optional['AgenticBase']:
        """
        Internal helper to resolve another agent instance by its factory ID.

        This method queries the `_command_center` or the worker's `factory`
        to find another worker, enabling inter-agent communication.

        Args:
            factory_id (str): The unique ID of the agent to resolve.

        Returns:
            Optional['AgenticBase']: The resolved agent instance, or `None` if not found.
        """
        if self._command_center and hasattr(self._command_center, "get_agent_by_id"):
            return self._command_center.get_agent_by_id(factory_id)
        # Fallback for pool-based resolution
        if self.factory and hasattr(self.factory, "get_worker_by_id"):
            return self.factory.get_worker_by_id(factory_id)
        return None

    def bind_to_inventory_by_id(self, factory_id: str, key: str, value: Any):
        """
        Binds a value to the private inventory of another agent, identified by its ID.

        Args:
            factory_id (str): The unique ID of the target agent.
            key (str): The key under which the value will be stored.
            value (Any): The data to be stored.
        """
        worker = self._resolve_worker_by_id(factory_id)
        if worker and hasattr(worker, 'bind_to_inventory'):
            # Assuming the target worker has a 'bind_to_inventory' method
            worker.bind_to_inventory(key, value)

    def get_from_inventory_by_id(self, factory_id: str, key: str, default=None) -> Any:
        """
        Retrieves a value from the private inventory of another agent by its ID.

        Args:
            factory_id (str): The unique ID of the target agent.
            key (str): The key of the item to retrieve.
            default (Any, optional): The value to return if the key is not found.
                Defaults to None.

        Returns:
            Any: The value from the target agent's inventory, or the default value.
        """
        worker = self._resolve_worker_by_id(factory_id)
        if worker and hasattr(worker, 'get_from_inventory'):
            # Assuming the target worker has a 'get_from_inventory' method
            return worker.get_from_inventory(key, default)
        return default

    def set_home(self, fn: Union[Callable[..., None], Pack]) -> None:
        """
        Sets the primary, default execution loop or "home behavior" for the agent.

        This function defines the agent's main operational loop, which is executed
        when `run()` is called for a pool-bound agent.

        Args:
            fn (Union[Callable[..., None], Pack]): A parameterless callable or `Pack`
                that represents the agent's main execution loop.
        """
        self._event_loop = Pack.bundle(fn) if fn else None

    def run(self):
        """
        Main execution entry point for the agentic thread.

        - If `self._pool_agent` is `True`, this thread executes the agentic event
          loop set via `set_home()`. This is the standard behavior for agents
          within a dynamic thread pool.
        - Otherwise, it falls back to the standard `threading.Thread.run()`
          behavior, executing the `_target` function if provided. This supports
          standalone thread logic outside the pool framework.

        Raises:
            RuntimeError: If the agent is a pool agent but `_event_loop` has not
                been set, or if it is a standalone agent but no `_target` is defined.
        """
        if not self._pool_agent:
            if self._target:
                return super().run()  # Executes the _target via Worker's run
            else:
                raise RuntimeError("No event loop or target function set for standalone thread.")

        # Default agentic behavior for pool-bound workers
        self._bind_factory_id()
        self.state = WorkerState.STARTING

        if self._event_loop is None:
            raise RuntimeError(f"[Worker {self.factory_id}] No home() set before thread start.")

        self._event_loop()
        self.death_event.set()

    def _validate_caller(self, factory_id: Optional[str] = None) -> None:
        """
        Internal method to validate the `factory_id` of the calling thread.

        This can be used as a security measure to ensure that certain methods are
        only called by authorized threads.

        Args:
            factory_id (Optional[str]): The expected `factory_id`. If `None`, this
                agent's own `factory_id` is used for the check.

        Raises:
            PermissionError: If the calling thread's `factory_id` does not match
                the expected ID.
        """
        expected = factory_id or self.factory_id
        current_id = getattr(threading.current_thread(), "factory_id", None)
        if current_id != expected:
            raise PermissionError(
                f"[Access Denied] Caller factory_id={current_id} does not match expected={expected}"
            )