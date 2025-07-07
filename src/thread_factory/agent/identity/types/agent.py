import logging, ulid, ctypes, threading
from enum import Enum, auto
from datetime import datetime, timedelta
from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.agent.thread_pool.records.records import Records, Record, WorkStatus
from thread_factory.agent.thread_pool.requests.work import Work
from thread_factory.synchronization.controllers.signal_controller import SignalController
from typing import Optional, Callable, Union, Any
from thread_factory.agent.thread_pool.requests.help_request import HelpRequest
from thread_factory.agent.thread_pool.records.records import WorkStatus, Record
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.utils.coordination.package import Pack
from thread_factory.utils.interfaces.disposable import IDisposable

class AgentState(Enum):
    """
    Enum representing the lifecycle and behavioral states of a BaseAgent thread.
    """
    CREATED = auto()
    STARTING = auto()
    IDLE = auto()
    ACTIVE = auto()
    BLOCKED = auto()
    PAUSED = auto()
    KILLED = auto()
    DEAD = auto()
    DISPOSED = auto()

    #main pool only states
    REBALANCING = auto()
    TERMINATING = auto()
    SWITCHED = auto()


class AgentPoolType(Enum):
    """
    Enum representing the type of agent.
    """
    NOTSET = auto()  # Represents an agent that has not been set to a specific type
    DISPATCHER = auto()  # Represents a worker focused on dispatching tasks
    DISPATCHER_TARGETED = auto()  # Represents a worker focused on dispatching tasks where they can be claimed
    THROUGHPUT = auto()   # Represents a worker focused on high throughput
    THROUGHPUT_SLEEP = auto()  # Represents a worker focused on high throughput with sleep behavior


class Agent(threading.Thread, IDisposable):
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

    def __init__(self,
                 command_center: 'CommandCenter',
                 group: Optional[threading.Thread] = None,
                 name: Optional[str] = None,
                 target: Union[Callable[..., Any], 'Pack'] = None, # Make sure 'Pack' is imported or defined
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
        super().__init__(group, target, name, args, kwargs, daemon=True)
        IDisposable.__init__(self)                  # This is now explicitly passed from Agent's init

        self._lock = threading.RLock() # Thread-safe lock for internal state management
        self.factory_id: str = str(ulid.ULID())
        self._logger = logger or logging.getLogger(__name__)
        self._signal_controller: Optional[SignalController] = signal_controller # Optional SignalController for external management

        # State management
        self.state = AgentState.CREATED
        self.shutdown_flag = threading.Event()
        self.death_event = threading.Event()
        self.worker_type = None
        self._data_center = None

        # Activity Management
        self._group_name = None
        self._group_id = None
        self._activity_name = None
        self._activity_id = None
        self._registered_activities: ConcurrentDict[str, 'BaseActivity'] = ConcurrentDict()

        # Metrics tracking
        self.records = Records() # Stores historical records of completed work units
        self.last_completed_work: Optional[Record] = None # The most recently completed work record
        self.availability: float = 0.0 # Estimated utilization or availability percentage
        self.units_per_minute: int = 0 # Work units processed in the current minute
        self.units_per_hour: ConcurrentList[int] = ConcurrentList() # History of units processed per hour
        self.work_unit_counter: int = 0 # Total number of work units processed by this worker
        self.start_time: datetime = datetime.now() # Timestamp of when the worker instance was created

        # Work queue for continuous task processing.
        self._last_hourly_reset: datetime = datetime.now() # Tracks the start of the current hourly aggregation period

        # Agent-specific initializations
        self._command_center: 'CommandCenter' = command_center
        if isinstance(target, Pack):
            self._target = target # This is an agent-specific target, not the thread's main target.
        else:
            self._target = Pack.bundle(target) if target else None

        # Internal State Management
        self._template_name = None  # This can be set to a specific template name if needed
        self._worker_type = "agentic" # Overrides Worker's default "mainpool"
        self._pool_agent: bool = False # This flag might be set by a pool manager
        self._return_home: bool = False # Controls behavior after task completion
        self._agent_reset: bool = False  # Indicates if the agent has been reset recently
        # Loop and Event Pool Management
        self._dismiss_agent: bool = False # Flag to indicate if the agent should be dismissed
        self._pool_type = AgentPoolType.NOTSET
        self._value_work: Optional['HelpRequest'] = None # Example: For binding specific work


        # Auto-register with controller (best-effort)
        if self._signal_controller:
            try:
                self._signal_controller.register(self)
                self._logger.debug(f"BaseAgent '{self.id}' auto-registered with SignalController.")
            except Exception as e:
                self._logger.warning(
                    f"Failed to auto-register BaseAgent '{self.id}' with SignalController: {e}", exc_info=True)

    def dispose(self):
        """
        Disposes of the BaseAgent's resources, halts the thread, and unregisters itself.

        This method ensures a clean shutdown by signaling the thread to stop,
        releasing owned IDisposable resources, and unregistering from the
        SignalController. It is designed to be thread-safe and idempotent.

        This method does NOT call `super().dispose()` as per design.
        """
        if self._disposed:
            return

        with self._lock:
            if self._disposed: # Re-check inside the lock for race conditions
                return
            self._logger.info(f"Initiating disposal for BaseAgent '{self.id}'.")
            self._disposed = True
            self._unregister()
            # Dispose agent-specific resources
            self._dispose_work()

            # Unregister from all activities
            if self._registered_activities:
                for activity in list(self._registered_activities.values()):
                    self.deregister_from_activity(activity)
                self._registered_activities.dispose()
                self._registered_activities = None

            # Signal thread termination
            self.shutdown_flag.set()
            self.death_event.set()
            self.set_worker_state("DISPOSED")

            # Dispose and nullify owned IDisposable objects
            if self.units_per_hour:
                self.units_per_hour.dispose()
            self.units_per_hour = None

            if self.records:
                self.records.dispose()
            self.records = None

            # Unregister from SignalController and nullify its reference
            if self._signal_controller:
                try:
                    # Prevent recursive dispose call
                    self._signal_controller.unregister(self.factory_id, dispose_object=False)
                except Exception as e:
                    # Log error during unregistration
                    if hasattr(self, '_logger') and self._logger:
                        self._logger.warning(
                            f"Error unregistering BaseAgent '{self.id}' from SignalController: {e}",
                            exc_info=True
                        )
                finally:
                    self._signal_controller = None

            # Nullify remaining references
            self.last_completed_work = None
            self.shutdown_flag = None
            self.death_event = None

            # Log final disposal message, then nullify logger
            if hasattr(self, '_logger') and self._logger: # Check before using/nullifying
                self._logger.info(f"BaseAgent '{self.id}' disposal complete.")
            self._logger = None

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

        # Deregister from activities but keep the container alive
        if self._registered_activities:
            for activity in list(self._registered_activities.values()):
                self.deregister_from_activity(activity)
            self._registered_activities.clear()

        # Unbind work and reset its state
        if self._value_work:
            self._value_work = None

        # Reset internal state
        self._activity_id = None
        self._activity_name = None
        self._agent_reset = True
        self.state = AgentState.IDLE

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
        return ConcurrentDict({
            "name": self.__class__.__name__,
            "commands": ConcurrentDict({
                "get_name": self.get_name,
                "get_description": self.get_description,
                "set_return_home": self.set_return_home,
                "get_bound_work_state": self._get_work_state,
                "get_bound_work_id": lambda: self._value_work.record.task_id if self._value_work else None,
                "list_registered_activities": self.list_registered_activities,
                "stop": self.stop,
                "hard_kill": self.hard_kill,
                "get_worker_state": self.get_state,  # Need to add this getter
                "get_units_per_minute": self.get_units_per_minute,  # Need to add this getter
                "get_total_processed": self.get_work_unit_counter,  # Need to add this getter
            })
        })

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
        The main execution method for the agent.
        """
        raise NotImplementedError(
            "The run method must be implemented by subclasses of Agent. "
            "This method defines the primary execution logic for the agent."
        )


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

#region Signal Controller
#region Signal Controller Integration
    def set_external_controller(self, controller: SignalController):
        """
        Sets an external SignalController to manage or observe this BaseAgent.

        This allows the BaseAgent to register with a controller even after construction,
        enabling remote monitoring, status updates, or lifecycle awareness.

        Args:
            controller (SignalController): The controller to attach.

        Raises:
            TypeError: If the provided object is not a SignalController.
        """
        if not isinstance(controller, SignalController):
            raise TypeError("Expected a SignalController instance.")

        self._signal_controller = controller
        try:
            self._signal_controller.register(self)
        except Exception:
            pass  # Safe fail; controller may choose not to accept

    @property
    def id(self) -> str:
        """
        The unique identifier for this BaseAgent instance, conforming to SignalController's contract.
        """
        return self.factory_id

    # Revised set_status (renamed to set_worker_state for clarity)
    def set_worker_state(self, state_str: str):
        """
        Sets the current state of the worker from a string.

        Args:
            state_str: The string representation of the desired AgentState.

        Raises:
            ValueError: If the provided string does not match any AgentState enum member.
        """
        with self._lock:
            try:
                new_state = AgentState[state_str.upper()]
                if self.state != new_state:
                    self._logger.info(
                        f"BaseAgent '{self.id}' state changed from {self.state.name} to {new_state.name}.")
                    self.state = new_state
                    self._notify("WORKER_STATE_CHANGED", {"state": self.state.name})
                else:
                    self._logger.debug(f"BaseAgent '{self.id}' state is already {new_state.name}.")
            except KeyError:
                # self._logger might not be initialized if an exception occurs during init and then set_status is called
                # It's good practice to ensure self._logger exists before using it
                logger_to_use = getattr(self, '_logger', logging.getLogger(__name__))
                logger_to_use.error(
                    f"Invalid worker state string: '{state_str}'. Must be one of {[s.name for s in AgentState]}.")
                raise ValueError(
                    f"Invalid worker state string: '{state_str}'. Must be one of {[s.name for s in AgentState]}.")

    def _notify(self, event_type: str, data: Optional[dict] = None):
        """
        Notify the connected SignalController (if any) of an event.

        This is a lightweight way for the BaseAgent to report state or activity
        to external systems like the Command Center without being tightly coupled.

        Args:
            event_type (str): A short string describing the event type.
            data (Optional[dict]): Additional contextual data for the event.
        """
        if self._signal_controller is not None:
            self._signal_controller.notify(
                object_id=self.factory_id,
                event_type=event_type,
                data=data or {}
            )


#endregion Signal Controller Integration
    # Add simple getters for metrics that you expose in _get_object_details
    def get_state(self) -> AgentState:
        """
        Retrieves the worker's current operational state.

        Returns:
            AgentState: The current state of the worker.
        """
        with self._lock:
            return self.state

    def get_units_per_minute(self) -> int:
        """
        Retrieves the number of work units processed in the current minute.

        Returns:
            int: The count of units processed within the last minute.
        """
        with self._lock:
            return self.units_per_minute

    def get_work_unit_counter(self) -> int:
        """
        Retrieves the total number of work units processed by this worker.

        Returns:
            int: The cumulative count of all work units processed.
        """
        with self._lock:
            return self.work_unit_counter


    def _execute_task(self, task: 'Work'):
        """
        Executes a unit of work. Updates the worker's metrics and collects the task's final record.
        This method is now fully responsible for managing the Work object's disposal.
        """
        # Get a reference to the task's record BEFORE it runs.
        # This reference will persist even if the Work object's internal `record` is later nulled by Work.dispose().
        task_record_reference = task.record

        try:
            task.run() # This executes the work function and updates task.record.status internally.

        except Exception as e:
            # This 'except' block catches *any* exception that propagates out of task.run().
            # This includes the "Future in unexpected state" error.
            self._logger.error(f"[BaseAgent {self.factory_id}] Critical worker-level error during task execution: {e}")
            self._notify("CRITICAL_WORKER_ERROR", {"error": str(e)})
            # If Work.run() failed in a way that its own internal set_exception/set_result
            # didn't finalize the record, we force it to FAILED here.
            if task_record_reference and not task.done(): # Check if Future itself wasn't marked done
                 task_record_reference.status = WorkStatus.FAILED
                 if not task_record_reference.timestamp_completion_time:
                     task_record_reference.timestamp_completion_time = datetime.now()


        finally:
            self.units_per_minute += 1
            self.work_unit_counter += 1
            self._check_and_reset_hourly_metrics()

            # Add the (now finalized) record to the worker's collection using the stored reference.
            # We check task.done() to ensure the Work object itself finished its Future lifecycle.
            # The record should have the correct status set by Work.set_result/set_exception.
            if task_record_reference and task.done():
                self.records.add(task_record_reference)
                self.last_completed_work = task_record_reference
            else:
                # This indicates a problem where Work.run() did not complete its Future lifecycle properly.
                self._logger.error(f"[BaseAgent {self.factory_id}] Warning: Task Future did not complete its lifecycle or record not finalized.")
                # Force add if not done but record has a state
                if task_record_reference and task_record_reference.status != WorkStatus.PENDING:
                    self.records.add(task_record_reference)
                    self.last_completed_work = task_record_reference

            self.update_metrics()

    def stop(self) -> None:
        """
        Signals the worker thread to gracefully stop its execution.

        This method sets an internal shutdown flag (`shutdown_flag`) which the
        worker's `run()` loop periodically checks. Upon detecting the flag,
        the `run()` method will complete its current task (if any), exit its loop,
        and proceed to dispose of its resources.

        This is the preferred method for terminating a worker thread as it allows
        for orderly cleanup and prevents data corruption. It does not immediately
        terminate the thread but requests its cooperation in shutting down.
        """
        self.shutdown_flag.set()

    def hard_kill(self) -> None:
        """
        Forcefully terminates the worker thread using low-level ctypes.

        This method is a drastic measure and should be used with extreme caution
        and only when graceful shutdown (`stop()`) is not feasible or effective.
        It injects an exception (SystemExit) into the target thread, which can
        cause unpredictable behavior, resource leaks, or data corruption if
        the thread is in the middle of a critical operation.

        This method should only be called if the worker is currently alive.
        After calling `hard_kill`, the worker's state is immediately set to `AgentState.KILLED`.

        Raises:
            ValueError: If the thread ID is invalid or the target thread cannot be found.
            SystemError: If multiple exceptions are set for the target thread (indicates an issue).
        """
        if not self.is_alive():
            self._logger.debug(f"Attempted hard_kill on non-alive worker '{self.id}'. No action taken.")
            return

        res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_long(self.ident),
            ctypes.py_object(SystemExit)
        )
        if res == 0:
            if hasattr(self, '_logger') and self._logger:
                self._logger.error(f"Failed to hard_kill worker '{self.id}': Invalid thread ID.")
            raise ValueError(f"Invalid thread ID for hard kill: {self.ident}.")
        elif res > 1:
            ctypes.pythonapi.PyThreadState_SetAsyncExc(self.ident, None) # Clear pending exceptions
            if hasattr(self, '_logger') and self._logger:
                self._logger.error(f"Failed to hard_kill worker '{self.id}': Multiple exceptions already set.")
                self._notify("CRITICAL_WORKER_ERROR", {
                    "error": f"Multiple exceptions set for thread {self.ident}."
                })
            raise SystemError(f"Multiple exceptions set for thread {self.ident}.")

        self.state = AgentState.KILLED
        self._logger.warning(f"BaseAgent '{self.id}' forcefully terminated (hard_kill).")

    def update_metrics(self) -> None:
        """
        Updates all composite performance metrics for the worker.

        This method serves as a consolidated entry point to recalculate various
        metrics, such as availability. It is typically called internally after
        a unit of work is completed or when new metric data becomes available.
        """
        self.update_availability()

    def update_availability(self) -> None:
        """
        Calculates and updates the worker's estimated availability or utilization.

        Availability is derived from `units_per_minute` (work units processed in the
        current minute) as a percentage relative to a theoretical maximum (60 units/minute).
        The value is capped at 1.0 (100%) to ensure it doesn't exceed full utilization.

        This metric provides an indication of how busy the worker is.
        """
        # Ensure units_per_minute does not exceed 60 to prevent availability > 1.0
        # If units_per_minute represents work in a given minute, max is 60.0 assuming 1 unit/sec.
        # If it represents theoretical max, this calculation might need adjustment based on context.
        # Assuming 60.0 is the baseline for 100% utilization.
        self.availability = min(1.0, self.units_per_minute / 60.0)

    def _check_and_reset_hourly_metrics(self):
        """
        Checks if a new hour has elapsed since the last hourly metric reset.
        Also, removes records older than an hour to keep the data manageable.
        """
        current_time = datetime.now()
        hours_elapsed = (current_time - self._last_hourly_reset).total_seconds() / 3600.0

        # Clean up records older than 1 hour from self.records.records (now a dict)
        self.records.records = ConcurrentDict({
            k: v for k, v in self.records.records.items()
            if (current_time - v.timestamp_creation_time).total_seconds() < 3600
        })

        while hours_elapsed >= 1.0:
            self.units_per_hour.append(self.units_per_minute)
            self.units_per_minute = 0
            self._last_hourly_reset += timedelta(hours=1)
            hours_elapsed -= 1.0


#endregion Signal Controller
#endregion