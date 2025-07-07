import logging
import threading, ulid
from typing import Optional, Callable, Union, Any
from thread_factory.concurrency.concurrent_queue import ConcurrentQueue
from thread_factory.runtime.factory.operations.work.work import Work
from thread_factory.runtime.worker.worker.worker import Worker, WorkerState
from thread_factory.agent.thread_pool.help_request import HelpRequest
from thread_factory.runtime.orchestrator.monitoring.records.records import WorkStatus, Record
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.synchronization import SignalController
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

    def __init__(self, command_center: 'CommandCenter',
                 target: Union[Callable[..., Any], 'Pack'] = None, # Make sure 'Pack' is imported or defined
                 factory: Any = None,
                 work_queue: Optional[ConcurrentQueue[Work]] = None,
                 signal_controller: Optional[SignalController] = None, # Explicitly pass this through
                 logger: Optional[logging.Logger] = None,            # Explicitly pass this through
                 *args, **kwargs):
        """
        Initializes a new Agent thread instance, extending the Worker's capabilities.

        Args:
            command_center (CommandCenter): A reference to the central coordinating
                CommandCenter, essential for the agent to resolve and interact with
                other entities in the system.
            target (Union[Callable, Pack], optional): The callable object or Pack instance
                that the agent's thread will execute. Defaults to None.
            factory (Any, optional): A reference to the parent factory or manager.
                Defaults to None.
            work_queue (Optional[ConcurrentQueue[Work]], optional): A queue from which
                the agent continuously dequeues and executes Work units. Defaults to None.
            signal_controller (Optional[SignalController], optional): An optional
                SignalController instance for external management and event notification.
                Defaults to None.
            logger (Optional[logging.Logger], optional): A custom logger instance for the agent.
                If None, a default logger will be used. Defaults to None.
            *args: Positional arguments to be passed to the base `threading.Thread` constructor.
            **kwargs: Keyword arguments to be passed to the base `threading.Thread` constructor.
                      These can include `name`, `group`, etc., which are then
                      forwarded to `super().__init__`.
        """
        # Call the Worker (super) class's __init__ method
        # Pass through all relevant parameters that Worker expects
        super().__init__(
            group=kwargs.pop('group', None),  # Extract 'group' from kwargs if present
            name=kwargs.pop('name', None),    # Extract 'name' from kwargs if present
            target=target,
            args=args,
            kwargs=kwargs, # Pass remaining kwargs to super() if any are left
            factory=factory,
            work_queue=work_queue,
            signal_controller=signal_controller, # This is now explicitly passed from Agent's init
            logger=logger                        # This is now explicitly passed from Agent's init
        )

        # Agent-specific initializations
        self._command_center: 'CommandCenter' = command_center
        if isinstance(target, Pack):
            self._target = target # This is an agent-specific target, not the thread's main target.
        else:
            self._target = Pack.bundle(target) if target else None

        self._group_name = None
        self._group_id = None
        self._activity_name = None
        self._activity_id = None

        self._template_name = None  # This can be set to a specific template name if needed
        self._worker_type = "agentic" # Overrides Worker's default "mainpool"
        self._pool_agent: bool = False # This flag might be set by a pool manager
        self._return_home: bool = False # Controls behavior after task completion
        self._agent_reset: bool = False  # Indicates if the agent has been reset

        self._event_loop: Optional['Pack'] = None # Example: Pack for the main behavior loop
        self._value_work: Optional['HelpRequest'] = None # Example: For binding specific work

        self._private_inventory = ConcurrentDict()
        self.public_inventory: ConcurrentDict[str, Any] = ConcurrentDict()
        self._registered_activities: ConcurrentDict[str, 'BaseActivity'] = ConcurrentDict()

    def dispose(self):
        """
        Performs a comprehensive cleanup of the agent's state, clears
        all references, and then triggers the disposal process of its base class.
        This is safe to call multiple times.
        """
        if self._disposed:
            return

        self._unregister()
        # Dispose agent-specific resources
        self._dispose_work()
        if self._private_inventory:
            self._private_inventory.dispose()
            self._private_inventory = None
        if self.public_inventory:
            self.public_inventory.dispose()
            self.public_inventory = None

        # Unregister from all activities
        if self._registered_activities:
            for activity in list(self._registered_activities.values()):
                self.deregister_from_activity(activity)
            self._registered_activities.dispose()
            self._registered_activities = None

        self._event_loop = None

        super().dispose()  # Call parent dispose if it exists

    def reset(self) -> None:
        """
        Soft-reset the agent without disposing it.

        This clears:
        - All items from public and private inventories
        - Bound work reference and its status
        - Registered activities
        - Agent's current event loop and activity metadata
        - Internal state flags like `_return_home`
        - Execution state to `IDLE`

        This does NOT:
        - Dispose or delete any object
        - Shutdown the thread
        - Affect identity or registration with the CommandCenter
        """
        if self._disposed:
            raise RuntimeError("Cannot reset a disposed agent.")

        # Clear inventories without disposing
        if self._private_inventory:
            self._private_inventory.clear()
        if self.public_inventory:
            self.public_inventory.clear()

        # Unbind work and reset its state
        if self._value_work:
            self._value_work = None

        # Deregister from activities but keep the container alive
        if self._registered_activities:
            for activity in list(self._registered_activities.values()):
                self.deregister_from_activity(activity)
            self._registered_activities.clear()

        # Reset internal state
        self._activity_id = None
        self._activity_name = None
        self._agent_reset = True
        self.state = WorkerState.IDLE

    def apply_attributes_from_kwargs(self, **kwargs) -> None:
        """
        Applies the provided keyword arguments to existing attributes on the agent.

        This method dynamically updates the agent's attributes only if the attribute
        already exists on the object.

        Args:
            **kwargs: Arbitrary keyword arguments, where each key corresponds to an
                      attribute name, and the value is the value to assign.

        Example:
            agent.apply_attributes_from_kwargs(public_name="Alice", job_title="Commander")
        """
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self, key):
                    setattr(self, key, value)

    #region Signal Controller Methods
    def _get_object_details(self) -> ConcurrentDict[str, Any]:
        """
        Extends the base Worker's object details with high-level agent-specific commands and metadata.

        This method is crucial for exposing the Agent's unique capabilities and status
        to external orchestrators or monitoring systems via the SignalController.
        It provides a top-down interface for:

        - **Identification**: Retrieving the agent's profile name and description.
        - **Behavior Configuration**: Setting the agent's primary event loop (`set_home`)
          and controlling its post-task behavior (`set_return_home`).
        - **Lifecycle Management**: Initiating the agent's thread execution (`deploy`).
        - **Work Observation**: Querying the state and ID of any currently bound work.
        - **Data Inspection**: Providing a snapshot of the agent's public inventory.

        Returns:
            ConcurrentDict[str, Any]: A dictionary containing the worker's base details
                augmented with agent-specific commands and metadata.
        """
        details = super()._get_object_details()

        details["commands"].update({
            "get_name": self.get_name,
            "get_description": self.get_description,
            "set_home": self.set_home,
            "set_return_home": self.set_return_home,
            "get_bound_work_state": self._get_work_state,
            "get_bound_work_id": lambda: self._value_work.record.task_id if self._value_work else None,
            "list_registered_activities": self.list_registered_activities,
        })
        details["name"] = self.__class__.__name__
        return details

#endregion Signal Controller Methods
#region Generic Agent System Methods
#region Command Center Management Methods
    def _unregister(self) -> None:
        """
        Unregisters the agent from the command center, if applicable.
        This is typically called when the agent is no longer needed or is being disposed.
        """
        if self._command_center:
            self._command_center._unregister_agent(self)
            self._group_name = None
            self._group_id = None
            self._command_center = None

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
#endregion Command Center Management Methods
#region Activity Management Methods
    # Add these new methods to the Agent class

    def register_with_activity(self, activity: 'BaseActivity'):
        """
        Registers this agent with a given activity.

        This creates a two-way link: the agent tracks the activity,
        and the activity tracks the agent.
        """
        if activity and activity.id not in self._registered_activities:
            self._registered_activities[activity.id] = activity
            # This call completes the link and triggers the notification
            activity.register_agent(self)
            self._logger.info(f"Agent '{self.factory_id}' registered with Activity '{activity.id}'.")
            self._activity_id = activity._id
            self._activity_name = activity._name

    def deregister_from_activity(self, activity: 'BaseActivity'):
        """
        Deregisters this agent from a given activity.
        """
        if activity and self._registered_activities.pop(activity.id, None):
            # This call breaks the link from the activity's side
            activity.unregister_agent(self)
            self._logger.info(f"Agent '{self.factory_id}' deregistered from Activity '{activity.id}'.")
            self._activity_id = None
            self._activity_name = None


    def list_registered_activities(self) -> list:
        """
        Lists all activities that this agent is currently registered with.

        Returns:
            list: A list of activity IDs that this agent is registered with.
        """
        return list(self._registered_activities.keys())

#endregion Activity Management Methods
#region Agent Execution Methods
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
        with self._lock:
            if self._disposed:
                raise RuntimeError("Cannot activate a disposed agent.")
            self.state = WorkerState.ACTIVE

        try:
            if self._target:
                return self._target()  # Run the target if it's a standalone agent

            if self._event_loop:
                self._event_loop()
        except Exception as e:
            # Optionally, log the exception if needed
            pass
        finally:
            # Ensure agent is disposed properly even after an exception
            self.dispose()

    def deploy(self):
        """
        Deploys the agent by starting its thread. This method is typically called
        by the `CommandCenter` or similar orchestrator to activate the agent.

        Raises:
            RuntimeError: If the agent has been disposed or if it is already running.
        """
        if self._disposed:
            raise RuntimeError("Cannot deploy a disposed agent.")
        if self.is_alive():
            raise RuntimeError("Agent is already running.")
        self.start()

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
#endregion Agent Execution Methods
#endregion
#region Queue Pool Management Methods
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
        """
        Convenience method to mark the bound work as 'in progress'.
        """
        if self._value_work:
            self._value_work.mark_in_progress()

    def _mark_work_completed(self) -> None:
        """
        Convenience method to mark the bound work as 'completed'.
        """
        if self._value_work:
            self._value_work.mark_completed()

    def _mark_work_failed(self) -> None:
        """
        Convenience method to mark the bound work as 'failed'.
        """
        if self._value_work:
            self._value_work.mark_failed()

    def _mark_work_cancelled(self) -> None:
        """
        Convenience method to mark the bound work as 'cancelled'.
        """
        if self._value_work:
            self._value_work.mark_cancelled()

    def _reset_work(self) -> None:
        """
        Resets the bound `HelpRequest` to its initial 'pending' state.
        """
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
        """
        Initiates the execution of the `HelpRequest` bound to this agent.
        """
        if self._value_work:
            self._value_work.acquire_work()

    def _cancel_bound_job(self):
        """
        Cancels the job associated with the bound `HelpRequest`.
        """
        if self._value_work:
            self._value_work.cancel_job()
#endregion
#region Agentic Behavior Control Methods
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

        Raises:
            ValueError: If no agent with the given `factory_id` is found.
        """
        if self._command_center and hasattr(self._command_center, "get_agent_by_id"):
            agent = self._command_center.get_agent_by_id(factory_id)
            if agent is None:
                raise ValueError(f"No agent found with factory_id: {factory_id}")
            return agent
        raise ValueError(f"Command center is not available or does not support get_agent_by_id.")

    def bind_to_inventory_by_id(self, factory_id: str, key: str, value: Any):
        """
        Binds a value to the public inventory of another agent, identified by its ID.

        Args:
            factory_id (str): The unique ID of the target agent.
            key (str): The key under which the value will be stored.
            value (Any): The data to be stored.
        """
        worker = self._resolve_worker_by_id(factory_id)
        if worker and hasattr(worker, 'public_inventory'):
            # Use public inventory instead of private inventory
            worker.public_inventory[key] = value

    def get_from_inventory_by_id(self, factory_id: str, key: str, default=None) -> Any:
        """
        Retrieves a value from the public inventory of another agent by its ID.

        Args:
            factory_id (str): The unique ID of the target agent.
            key (str): The key of the item to retrieve.
            default (Any, optional): The value to return if the key is not found.
                Defaults to None.

        Returns:
            Any: The value from the target agent's inventory, or the default value.
        """
        worker = self._resolve_worker_by_id(factory_id)
        if worker and hasattr(worker, 'public_inventory'):
            # Access public inventory instead of private inventory
            return worker.public_inventory.get(key, default)
        return default

    def _validate_caller(self) -> None:
        """
        Internal method to validate the `factory_id` of the calling thread.

        Compares the `factory_id` of the calling thread with the agent's own `factory_id`
        to ensure that the correct thread is accessing or modifying the agent's data.

        Raises:
            PermissionError: If the calling thread's `factory_id` does not match
                the agent's `factory_id`.
        """
        current_id = getattr(threading.current_thread(), "factory_id", None)

        # Compare the calling thread's factory_id with the agent's factory_id
        if current_id != self.factory_id:
            raise PermissionError(
                f"[Access Denied] Caller factory_id={current_id} does not match agent's factory_id={self.factory_id}"
            )

    def get_from_private_inventory(self, key: str, default=None) -> Any:
        """
        Retrieves a value from the private inventory of this agent, only if the calling thread has the
        correct `factory_id`.

        Args:
            key (str): The key of the item to retrieve.
            default (Any, optional): The value to return if the key is not found. Defaults to None.

        Returns:
            Any: The value from the inventory, or the default value if not found.
        """
        self._validate_caller()  # Validate caller using the existing method
        return self._private_inventory.get(key, default)

    def put_in_private_inventory(self, key: str, value: Any) -> None:
        """
        Puts a value in the private inventory of this agent, only if the calling thread has the
        correct `factory_id`.

        Args:
            key (str): The key under which to store the value.
            value (Any): The value to store in the inventory.
        """
        self._validate_caller()  # Validate caller using the existing method
        self._private_inventory[key] = value
#endregion