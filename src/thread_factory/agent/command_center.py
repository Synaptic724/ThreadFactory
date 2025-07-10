import threading, warnings, logging, ulid
from logging import Logger
from typing import Optional, List, Callable, Any, Union, Dict, Type
from thread_factory.agent.activity.builder import ActivityBuilder
from thread_factory.agent.activity.base import BaseActivity, ActivityStatus
from thread_factory.agent.identity.agent_builder import AgentBuilder
from thread_factory.agent.identity.types.agent import Agent
from thread_factory.synchronization.controllers.signal_controller import SignalController
from thread_factory.utilities.coordination.package import Pack
from thread_factory.utilities.interfaces.disposable import IDisposable
from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.concurrency.sync_types.sync_int import SyncInt
from thread_factory.agent.thread_pool.agent_pool import AgentPool

#region CommandGroup
class CommandGroup(IDisposable):
    """
    CommandGroup
    ------------
    A container object that encapsulates a logical group of agents and activities under a single name,
    with its own lifecycle limits, registries, and behavior.

    It supports lifecycle operations like start, pause, cancel, deploy, and shutdown across all
    managed agents and activities. Integrates with the CommandCenter and SignalController for orchestration.

    Parameters:
    -----------
    command_center : CommandCenter
        The orchestrator that owns this group and handles agent/activity creation.
    group_name : str
        A unique name for identifying this group within the system.
    max_workers : int
        The maximum number of agents allowed to operate simultaneously within this group.
    group_type : Optional[str]
        An optional classification for the group (e.g., "ETL", "Modeling", etc.).
    """

    def __init__(self, command_center: 'CommandCenter', group_name: str, max_workers: int, agents_per_container: int = 30, logger: Optional[logging.Logger] = None, group_type: str = None):
        """
        Initializes a new CommandGroup instance.

        A CommandGroup is a container that manages a coordinated group of agents and activities.
        It enforces its own maximum worker count (`max_workers`) and provides lifecycle operations
        and centralized control for orchestration, diagnostics, and shutdown.

        Parameters:
        -----------
        command_center : CommandCenter
            The controlling CommandCenter instance responsible for creating agents and activities.
            This reference is retained for future delegation of creation or orchestration tasks.

        group_name : str
            A unique name for this group, used for identification and lookup in higher-level registries.

        max_workers : int
            The maximum number of concurrent agents that can operate under this group.
            Acts as an internal quota to prevent overload and manage concurrency.

        group_type : Optional[str]
            An optional tag or label that classifies this group (e.g., "etl", "analytics", "simulation").
            Can be used for filtering, scheduling preferences, or display purposes.


        Attributes:
        -----------
        id : str
            A ULID-based unique identifier for this group instance.

        _worker_count : SyncInt
            A thread-safe counter tracking the number of active agents currently in the group.

        _max_workers : int
            The ceiling on agent count; enforced via `add_agent()` and respected during orchestration.

        _active_agents : ConcurrentDict[str, Agent]
            Thread-safe dictionary of all currently registered agents by ID.

        _active_activities : ConcurrentDict[str, BaseActivity]
            Thread-safe dictionary of all registered activities by ID.

        _signal_controllers : ConcurrentDict[str, SignalController]
            Registry of all signal controllers used by activities or agents in this group.
        """
        super().__init__()
        self._lock = threading.RLock()
        self.id = str(ulid.ULID())
        self.name = group_name
        self.type = group_type
        self._logger: Logger = logger or logging.getLogger(__name__)
        self._command_center = command_center  # Reference to its creator

        # --- Internal Components ---
        # Pool Internals
        self._worker_count = SyncInt(0)
        self._agents_per_container = SyncInt(agents_per_container)
        self._max_workers = SyncInt(max_workers)

        # Create Agent Pool Container
        self._group_pool_container: 'CommandGroupContainer' = command_center._agent_pool.create_command_group_container(self.id, self._logger)

        # Internal registries for its members
        self._active_agents: ConcurrentDict[str, Agent] = ConcurrentDict()
        self._signal_controllers: ConcurrentDict[str, SignalController] = ConcurrentDict()
        self._active_activities: ConcurrentDict[str, BaseActivity] = ConcurrentDict()

    def dispose(self):
        # Logic to shut down all agents and dispose all activities
        with self._lock:
            self._disposed = True
            self._command_center = None
            self._logger.warning(f"Disposing CommandGroup '{self.name}'...")
            self._group_pool_container.dispose()
            self._group_pool_container = None

            # Dispose all SignalControllers
            for controller in list(self._signal_controllers.values()):
                try:
                    controller.dispose()
                except Exception as e:
                    logging.error(f"Error disposing SignalController '{controller.id}': {e}", exc_info=True)
            self._signal_controllers.dispose()

            # Dispose all active agents
            for agent in list(self._active_agents.values()):
                try:
                    agent.dispose()
                except Exception as e:
                    logging.error(f"Error disposing Agent '{agent.factory_id}': {e}", exc_info=True)
            self._active_agents.dispose()

            # Dispose all active activities
            for activity in list(self._active_activities.values()):
                try:
                    activity.dispose()
                except Exception as e:
                    logging.error(f"Error disposing Activity '{activity.id}': {e}", exc_info=True)
            self._active_activities.dispose()

            self._worker_count = None
            self._max_workers = None
            self._logger.info(f"CommandGroup '{self.name}' disposed.")
            self._logger = None

            # region CommandGroup Methods
    def add_agent(self, template_name: str = "default", reset_agent: bool = False, *args, **kwargs) -> Optional[Agent]:
        """
        Creates and registers a new agent under this CommandGroup.

        This method respects the group's max worker count, and will refuse to create agents
        if the limit is reached.

        Parameters:
        -----------
        template_name : str
            The agent template to use when creating the new agent.
        reset_agent : bool
            If True, the agent will be reset before deployment.
        *args : Any
            Positional arguments to pass to the CommandCenter's agent creation logic.
        **kwargs : Any
            Additional arguments to pass to the CommandCenter's agent creation logic.

        Returns:
        --------
        Optional[Agent]
            The created Agent object, or None if the group is at max capacity.
        """
        if self._worker_count >= self._max_workers:
            logging.warning(f"CommandGroup '{self.name}' has reached its max worker limit of {self._max_workers}.")
            return None

        # The command_center's create_agent method already handles registration and worker count.
        # We just need to call it with this group's name.
        agent = self._command_center.create_agent(
            template_name=template_name,
            command_group_name=self.name,
            reset_agent=reset_agent,
            *args,
            **kwargs
        )
        return agent

    def add_activity(self, name: str, **kwargs) -> Optional[BaseActivity]:
        """
        Creates and registers a new activity under this CommandGroup.

        This delegates to the CommandCenter for the actual creation logic.

        Parameters:
        -----------
        name : str
            The name/type of the activity to create.
        **kwargs : Any
            Arguments passed to the CommandCenter’s `create_activity`.

        Returns:
        --------
        Optional[BaseActivity]
            The created activity, or None if creation fails.
        """
        # The command_center's create_activity method handles registration.
        activity = self._command_center.create_activity(
            name=name,
            command_group_name=self.name,
            **kwargs
        )
        return activity

    def remove_agent(self, agent_id: str, dispose: bool = True):
        """
        Removes an agent from the group’s registry and optionally disposes it.

        Parameters:
        -----------
        agent_id : str
            The ID of the agent to remove.
        dispose : bool
            If True, the agent will also be disposed and cleaned up.

        Returns:
        --------
        bool
            True if the agent was found and removed; False otherwise.
        """
        agent = self._active_agents.get(agent_id)
        if agent:
            # The command_center's _unregister_agent handles decrementing worker count.
            self._command_center._unregister_agent(agent)
            if dispose:
                agent.dispose()
            return True
        return False

    def remove_activity(self, activity_id: str, dispose: bool = True):
        """
        Removes an activity from the group’s registry and optionally disposes it.

        Parameters:
        -----------
        activity_id : str
            The ID of the activity to remove.
        dispose : bool
            If True, the activity will also be disposed.

        Returns:
        --------
        bool
            True if the activity was found and removed; False otherwise.
        """
        activity = self._active_activities.pop(activity_id, None)
        if activity:
            if dispose:
                activity.dispose()
            return True
        return False

    # endregion
    # region Lifecycle Control
    def start_all_activities(self):
        """
        Starts all PENDING activities within the group.

        Activities already in a non-pending state are ignored.
        """

        for activity in list(self._active_activities.values()):
            if activity.get_status() == ActivityStatus.PENDING:
                activity.start()

    def deploy_all_agents(self):
        """
        Deploys all agents in the group that are not currently alive.

        This allows for a one-shot trigger to wake all agent threads
        that haven’t started yet.
        """
        for agent in list(self._active_agents.values()):
            try:
                if not agent.is_alive():
                    agent.deploy()
            except Exception as e:
                logging.error(f"Failed to deploy agent {agent.factory_id} in group {self.name}: {e}")

    def pause_all_activities(self):
        """
        Pauses all RUNNING activities in the group.

        Only activities currently in a RUNNING state will be affected.
        """
        for activity in list(self._active_activities.values()):
            if activity.get_status() == ActivityStatus.RUNNING:
                activity.pause()

    def cancel_all_activities(self):
        """
        Cancels all activities that are in a non-terminal state.

        Terminal states include: COMPLETED, FAILED, CANCELLED, DISPOSED.
        Only activities not in these states will be canceled.
        """

        terminal_states = {ActivityStatus.COMPLETED, ActivityStatus.FAILED, ActivityStatus.CANCELLED,
                           ActivityStatus.DISPOSED}
        for activity in list(self._active_activities.values()):
            if activity.get_status() not in terminal_states:
                activity.cancel()

    def shutdown_all_members(self, dispose: bool = True):
        """
        Stops all agents and activities in the group, and optionally disposes them.

        This method guarantees group-wide shutdown in a single call.

        Parameters:
        -----------
        dispose : bool
            Whether to dispose of the members after stopping them.
        """
        # Shutdown agents first
        for agent in list(self._active_agents.values()):
            try:
                self.remove_agent(agent.factory_id, dispose=dispose)
            except Exception as e:
                logging.error(f"Error shutting down Agent '{agent.factory_id}': {e}", exc_info=True)

        # Then shutdown activities
        for activity in list(self._active_activities.values()):
            try:
                self.remove_activity(activity.id, dispose=dispose)
            except Exception as e:
                logging.error(f"Error shutting down Activity '{activity.id}': {e}", exc_info=True)

    # endregion

    # region Introspection & Reporting

    def get_status_summary(self) -> Dict[str, int]:
        """
        Returns a count of activities grouped by their current status.

        Returns:
        --------
        Dict[str, int]
            A dictionary with status names as keys and their occurrence counts as values.
        """
        summary = {status.name: 0 for status in ActivityStatus}
        for activity in list(self._active_activities.values()):
            status_name = activity.get_status().name
            if status_name in summary:
                summary[status_name] += 1
        return summary

    def get_worker_utilization(self) -> Dict[str, Union[int, float]]:
        """
        Provides a report of worker usage within the group.

        Returns:
        --------
        Dict[str, Union[int, float]]
            Includes 'active' (current count), 'max' (allowed workers), and 'utilization' (percentage).
        """
        active = self._worker_count
        max_w = self._max_workers
        utilization = (active / max_w * 100) if max_w > 0 else 0
        return {'active': active, 'max': max_w, 'utilization': utilization}

    def list_agents(self) -> List[str]:
        """
        Lists all agent IDs currently active in this group.

        Returns:
        --------
        List[str]
            A list of agent ULID strings.
        """
        return list(self._active_agents.keys())

    def list_activities(self) -> List[str]:
        """
        Lists all activity IDs currently tracked in this group.

        Returns:
        --------
        List[str]
            A list of activity ULID strings.
        """
        return list(self._active_activities.keys())

    # endregion

    # region SignalController Integration
    # This section is for exposing the group's methods to a SignalController.
    # It's good practice to keep this for remote management capabilities.
    def _get_object_details(self) -> ConcurrentDict[str, Any]:
        """
        Exposes the CommandGroup's introspectable commands for use by SignalController.

        Returns:
        --------
        ConcurrentDict[str, Any]
            A structured dictionary mapping command names to callable handlers.
        """
        return ConcurrentDict({
            "name": "CommandGroup",
            "commands": ConcurrentDict({
                # --- Member Management ---
                'add_agent': self.add_agent,
                'add_activity': self.add_activity,
                'remove_agent': self.remove_agent,
                'remove_activity': self.remove_activity,
                'list_agents': self.list_agents,
                'list_activities': self.list_activities,

                # --- Group Lifecycle Control ---
                'start_all_activities': self.start_all_activities,
                'deploy_all_agents': self.deploy_all_agents,
                'pause_all_activities': self.pause_all_activities,
                # 'resume_all_activities' would need to be implemented similarly
                'cancel_all_activities': self.cancel_all_activities,
                'shutdown_all_members': self.shutdown_all_members,

                # --- Group-Level Reporting ---
                'get_status_summary': self.get_status_summary,
                'get_worker_utilization': self.get_worker_utilization,
            })
        })
# endregion
# endregion
#endregion

#endregion CommandGroup

#region CommandCenter
class CommandCenter(IDisposable):
    """
    CommandCenter
    --------------
    A centralized control unit responsible for creating, deploying, and managing agent threads and
    activities. It enforces both global and per-group worker limits, coordinates SignalController
    registrations, and acts as the main interface for orchestrating multithreaded workflows.

    Key Responsibilities:
    ---------------------
    • Manage all `Agent` instances created under its control.
    • Enforce a global worker limit (`total_max_workers`) and per-group limits (`group_max_workers`).
    • Provide lifecycle methods for agent/thread creation, reset, and disposal.
    • Create and manage CommandGroups for scoping related agents and activities.
    • Optionally connect to an external `SignalController` for remote management.

    Design Notes:
    -------------
    • Fully thread-safe using internal locking and concurrent structures.
    • Supports disposal of all registered objects and resources.
    • Acts as the root registry for agents, activities, and SignalControllers.
    • Integrates threadpool logic (soon to be refactored into a separate main pool and agent pool
      for more precise control over resource usage).
    • Compatible with remote orchestration systems via external signal control injection.

    """

    def __init__(self,
                 group_max_workers: int = 60,
                 agents_per_container: int = 30,
                 total_max_workers: int = 300,
                 command_group_name: str = "default",
                 command_group_type: Optional[str] = None,
                 logger: Optional[logging.Logger] = None,
                 external_signal_controller: Optional[SignalController] = None,
                 agent_pool_singleton: bool = True):
        """
        Initializes a new CommandCenter instance.

        This constructor sets up the internal worker limits, logging, default command group name,
        and optionally integrates with an external SignalController for remote command dispatch.

        Parameters:
        -----------
        group_max_workers : int, default=10
            The preset maximum number of workers that any single CommandGroup can run concurrently.
            This limit applies per group and is enforced internally by each group.

        total_max_workers : int, default=30
            The preset maximum number of concurrent agents allowed across all groups managed
            by this CommandCenter. This ensures overall system load is bounded.

        command_group_name : str, default="default"
            The name of the default command group created when the CommandCenter initializes.
            Other groups can be created dynamically via public APIs.

        logger : Optional[logging.Logger], default=None
            An optional logger instance for structured logging. If not provided, internal logs
            may fallback to `print` or remain silent depending on implementation.

        external_signal_controller : Optional[SignalController], default=None
            An optional remote SignalController to register this CommandCenter with.
            This allows it to be invoked or manipulated by external orchestrators.

        agent_pool_singleton : bool, default=True
            If True, uses a singleton AgentPool instance for managing agents.
            This allows for shared state and resource management across multiple CommandCenters.


        Behavior:
        ---------
        • Automatically creates a default CommandGroup on initialization.
        • Registers itself and its components with the SignalController if provided.
        • Prepares internal registries for agent and activity management.

        Raises:
        -------
        None
        """
        super().__init__()
        # --- Core Components ---
        self._logger: Logger = logger or logging.getLogger(__name__)
        self._id = str(ulid.ULID())
        self._lock = threading.RLock()
        self._builder = AgentBuilder()
        self._activity_builder = ActivityBuilder()
        self._singleton_agent_pool = agent_pool_singleton
        # --- Pool Management ---

        if self._singleton_agent_pool:
            try:
                self._agent_pool = AgentPool.get_instance()
                self._logger.debug("Reusing AgentPool singleton.")
            except RuntimeError:
                self._agent_pool = AgentPool.initialize_singleton(command_center=self, logger=self._logger)
                self._logger.debug("Initialized new AgentPool singleton.")
        else:
            self._agent_pool = AgentPool(command_center=self, logger=self._logger)
            self._logger.debug("Initialized standalone AgentPool instance.")


        if not isinstance(group_max_workers, int) or group_max_workers < 1:
            raise ValueError("group_max_workers must be a positive integer.")
        self._total_max_workers = SyncInt(total_max_workers)

        # --- Group Management ---
        self._command_groups: ConcurrentDict[str, CommandGroup] = ConcurrentDict()
        self.create_command_group(command_group_name=command_group_name, max_workers=group_max_workers, agents_per_container=agents_per_container, logger=logger, command_group_type=command_group_type) # creates initial command group

        # --- External Controller Integration ---
        self._id: str = str(ulid.ULID())
        self._external_signal_controller = external_signal_controller
        if self._external_signal_controller:
            try:
                self._external_signal_controller.register(self)
                self._logger.info(f"CommandCenter '{self.id}' registered with external SignalController.")
            except Exception as e:
                self._logger.warning(f"Failed to register CommandCenter with external SignalController: {e}", exc_info=True)


#region Destructor
    def dispose(self):
        """
        Disposes of the CommandCenter, cleaning up all resources, agents, activities,
        """
        with self._lock:
            if self._disposed:
                return
            self._disposed = True
            self._logger.info(f"Disposing CommandCenter '{self.id}'...")

            # --- Dispose all CommandGroups ---
            if self._command_groups:
                for group in list(self._command_groups.values()):
                    group.dispose()
                self._command_groups.dispose()
                self._command_groups = None

            # --- Dispose Builders ---
            if self._activity_builder:
                self._activity_builder.dispose()
            if self._builder:
                self._builder.dispose()

            self._agent_pool.dispose()
            self._agent_pool = None
            self._total_max_workers = None
            if self._external_signal_controller:
                self._external_signal_controller.notify(self.id, "DISPOSED")
            if self._external_signal_controller and hasattr(self._external_signal_controller, 'unregister'):
                try:
                    self._external_signal_controller.unregister(self.id)
                except Exception:
                    pass
                self._external_signal_controller = None

            self._logger.info(f"CommandCenter '{self.id}' disposed.")
            self._logger = None

    @property
    def id(self) -> str:  # noqa: D401
        """
        ULID that uniquely identifies this latch.
        """
        return self._id

    def shutdown(self):
        """
        Alias for .dispose(). Provides semantic clarity when intentionally
        terminating the CommandCenter.
        """
        self.dispose()

    def _check_disposed(self):
        """
        Internal helper to raise a RuntimeError if the instance is disposed.
        """
        if self._disposed:
            raise RuntimeError(f"CommandCenter '{self.id}' has been disposed.")

#endregion Destructor
#region Command Group Management
    # Add these methods to the CommandCenter class

    def get_total_max_workers(self) -> int:
        """
        Calculates and returns the total number of active workers across all command groups.
        """
        self._check_disposed()
        total = 0
        for group in self._command_groups.values():
            total += group._max_workers
        return total

    def get_total_active_workers(self) -> int:
        """
        Calculates and returns the total number of active workers across all command groups.
        """
        self._check_disposed()
        total = 0
        for group in self._command_groups.values():
            total += group._worker_count
        return total

    # Add this method to the CommandCenter class
    # In the CommandCenter class:

    def adjust_global_limit(self, new_global_limit: int):
        """
        Adjusts the global maximum worker limit. This method can only be used
        to increase the total limit. To decrease, individual command group
        limits must be reduced first using 'decrease_max_workers'.

        Args:
            new_global_limit (int): The new desired global maximum for all workers.

        Raises:
            ValueError: If the new limit is less than the current global max limit.
        """
        self._check_disposed()

        with self._lock:
            if new_global_limit < self._total_max_workers:
                raise ValueError(
                    f"New limit ({new_global_limit}) cannot be less than the current global max worker limit ({self._total_max_workers}). "
                    f"Use 'decrease_max_workers' on individual groups to lower capacity."
                )

            self._total_max_workers = new_global_limit
            self._logger.info(f"Global max workers limit increased to {new_global_limit}.")

    def create_command_group(self, command_group_name: str, max_workers: int, agents_per_container: int = 30, logger: Optional[logging.Logger] = None, command_group_type: str = None) -> None:
        """
        Internal method to create and register the default group.
        """
        self._check_disposed()
        if max_workers < 1 or not isinstance(max_workers, int):
            raise ValueError("max_workers must be a positive integer.")
        if command_group_name is None:
            raise ValueError("group_name cannot be None.")
        if command_group_name in self._command_groups:
            raise ValueError(f"A CommandGroup with the name '{command_group_name}' already exists.")

        if self.get_total_active_workers() + max_workers > self._total_max_workers:
            raise RuntimeError(f"Cannot create CommandGroup '{command_group_name}'. Total active workers would exceed global limit of {self._total_max_workers}, increase new total limit to create a new group.")

        # Create the CommandGroup instance and register it
        group = CommandGroup(command_center=self, group_name=command_group_name, max_workers=max_workers, agents_per_container=agents_per_container, logger=logger, group_type=command_group_type)
        self._command_groups[command_group_name] = group

    def get_command_group(self, group_name: str) -> Optional[CommandGroup]:
        """
        Retrieves a CommandGroup by its unique name.

        Args:
            group_name (str): The unique identifier of the CommandGroup.

        Returns:
            Optional[CommandGroup]: The CommandGroup instance, or None if not found.
        """
        self._check_disposed()
        command = self._command_groups.get(group_name)
        if command is None:
            self._logger.warning(f"CommandGroup '{group_name}' not found.")
            raise KeyError(f"CommandGroup '{group_name}' not found.")
        return command

#endregion Command Group Management
#region Activity Management
    def create_activity(self, name: str, command_group_name: str = "default", **kwargs: Any) -> Optional[BaseActivity]:
        """
        Builds and registers a new activity instance from a template.

        Args:
            name (str): The name of the registered activity template (e.g., "job_activity").
            **kwargs: Keyword arguments to pass to the activity's constructor.
            command_group_name (str): The name of the command group to register the activity in.

        Returns:
            Optional[BaseActivity]: The created activity instance, or None if creation fails.
        """
        self._check_disposed()  # Ensure CommandCenter is active

        # Pass the CommandCenter's signal controller if the activity needs one
        if 'signal_controller' not in kwargs and self._external_signal_controller:
            kwargs['signal_controller'] = self._external_signal_controller

        try:
            activity = self._activity_builder.build_activity(name, **kwargs)
            if activity:
                command = self.get_command_group(command_group_name)
                activity._group_name = command.name
                activity._group_id = command.id
                command._active_activities[activity.id] = activity
                self._logger.info(f"Created and registered Activity '{activity.id}' of type '{name}'. Using command group '{command.name}'.")
                # You could also emit a notification here
                # self._notify('ACTIVITY_CREATED', {'activity_id': activity.id, 'type': name})
                return activity
        except Exception as e:
            self._logger.error(f"Failed to create activity of type '{name}': {e}", exc_info=True)

        return None

    def remove_activity_by_command_group(self, activity: BaseActivity, dispose: bool =True, command_group_name: str = "default") -> bool:
        """
        Removes an activity from the CommandCenter's management.

        Args:
            activity (BaseActivity): The activity instance to remove.
            dispose (bool): If True, the activity will be disposed of after removal.
            command_group_name (str): The name of the command group to remove the activity from.

        Returns:
            bool: True if the activity was successfully removed, False if it was not found.
        """
        self._check_disposed()
        command = self.get_command_group(command_group_name)
        if activity.id in command._active_activities:
            activity._group_name = None
            activity._group_id = None
            del command._active_activities[activity.id]
            self._logger.info(f"Activity '{activity.id}' removed from CommandGroup '{command.name}'.")
            if dispose:
                activity.dispose()
            return True
        self._logger.warning(f"Activity '{activity.id}' not found in CommandGroup '{command.name}'.")
        return False

    def remove_activity(self, activity: BaseActivity, dispose: bool =True) -> bool:
        """
        Removes an activity from the CommandCenter's management.

        Args:
            activity (BaseActivity): The activity instance to remove.
            dispose (bool): If True, the activity will be disposed of after removal.

        Returns:
            bool: True if the activity was successfully removed, False if it was not found.
        """
        self._check_disposed()

        for group in self._command_groups.values():
            if activity.id in group._active_activities:
                activity._group_name = None
                activity._group_id = None
                del group._active_activities[activity.id]
                self._logger.info(f"Activity '{activity.id}' removed from CommandGroup '{group.name}'.")
                if dispose:
                    activity.dispose()
                return True
        self._logger.warning(f"Activity '{activity.id}' not found'.")
        return False


    def find_activity_by_id(self, activity_id: str, command_group_name: str = "default") -> Optional[BaseActivity]:
        """
        Searches for an activity by its unique ID across all command groups.

        Args:
            activity_id (str): The unique identifier of the activity.
            command_group_name (str): The name of the command group to search in.

        Returns:
            Optional[BaseActivity]: The activity instance if found, or None if not found.
        """
        self._check_disposed()
        command = self.get_command_group(command_group_name)
        return command._active_activities.get(activity_id)


    def verify_activity(self, activity: BaseActivity, command_group_name: str = "default") -> bool:
        """
        Verifies if the provided activity is existing to a specified command group.

        Args:
            activity (BaseActivity): The activity instance to verify.
            command_group_name (str): The name of the command group to check in.

        Returns:
            bool: True if the activity is existing, False otherwise.
        """
        self._check_disposed()
        command = self.get_command_group(command_group_name)
        return activity.id in command._active_activities


    def register_activity_template(self, name: str, activity_class: Type[BaseActivity]):
        """
        Registers a new activity class with the factory, making it available for creation.

        This allows developers to extend the library with their own custom activity types.

        Args:
            name (str): The unique name to assign to the activity template.
            activity_class (Type[BaseActivity]): The custom activity class to register.
        """
        self._check_disposed()
        self._activity_builder.register_activity(name, activity_class)
        self._logger.info(f"New activity template registered: '{name}'")

    def unregister_activity_template(self, name: str):
        """
        Removes a previously registered activity template.

        Args:
            name (str): The name of the activity template to remove.
        """
        self._check_disposed()
        try:
            self._activity_builder.unregister_activity(name)
            self._logger.info(f"Activity template unregistered: '{name}'")
        except KeyError as e:
            self._logger.warning(f"Failed to unregister activity template: {e}")

    def list_activity_templates(self) -> list[str]:
        """
        Returns a list of all currently registered activity template names.

        Returns:
            list[str]: A list of available activity template names.
        """
        self._check_disposed()
        return self._activity_builder.list_activities()


    def deploy_activity(self, activity: 'BaseActivity', worker_count: int, command_group_name: str = "default", reset_agents: bool = False,):
        """
        Creates, assigns, and deploys a specified number of workers to a given
        JobActivity, starting the work immediately.

        This is a high-level convenience method that handles the entire setup
        process for running a job in parallel.

        Args:
            activity (JobActivity): The pre-configured job to be executed. It must
                                    have a `perform_activity` and `start` method.
            worker_count (int): The number of agents to create and assign to the job.
            command_group_name (str): The name of the command group to deploy the activity in.
            reset_agents (bool): If True, agents will be reset before deployment.

        Raises:
            TypeError: If the provided object is not a valid JobActivity.
            RuntimeError: If there are not enough available worker slots.
        """
        self._check_disposed()
        command = self.get_command_group(command_group_name)
        if not self.verify_activity(activity, command_group_name):
            raise ValueError(f"Activity '{activity.id}' is not registered in CommandGroup '{command_group_name}'.")

        # --- Safety Checks ---
        if not isinstance(activity, BaseActivity) or not all(
                hasattr(activity, attr) for attr in ['perform_activity', 'start']):
            raise TypeError("The provided activity is not a valid JobActivity with the required methods.")

        available_slots = command._max_workers - command._worker_count
        if worker_count > available_slots:
            raise RuntimeError(f"Cannot deploy {worker_count} workers. Only {available_slots} slots are available.")

        # --- Deployment Logic ---
        self._logger.info(f"Deploying {worker_count} agents to Activity '{activity.id}'... using command group '{command.name}'.")

        # "Open the gate" for all agents before they are deployed
        activity.start()

        # Create and deploy the team of agents
        for _ in range(worker_count):
            # Create an agent whose target is the activity's main work loop
            agent = self.create_agent(command_group_name=command_group_name, target=activity.perform_activity, reset_agent=reset_agents)

            # Formally register the agent with the activity
            activity.register_agent(agent)

        activity.deploy_all_agents()
        self._logger.info(f"Deployment complete for Activity '{activity.id}' in command group {command.name}.")

#endregion Activity Management
#region Controller Contract
    def set_external_controller(self, controller: SignalController, logger: Optional[logging.Logger] = None):
        """
        Sets an external SignalController to manage this CommandCenter.
        This allows the CommandCenter to be controlled remotely.
        """
        self._check_disposed()
        if self._external_signal_controller:
            raise RuntimeError("External SignalController is already set.")
        if not isinstance(controller, SignalController):
            raise TypeError("Expected a SignalController instance.")
        if logger:
            self._logger = logger
        self._external_signal_controller = controller
        try:
            self._external_signal_controller.register(self)
            self._logger.info(f"CommandCenter '{self.id}' registered with external SignalController.")
        except Exception as e:
            self._logger.warning(f"Failed to register CommandCenter with external SignalController: {e}", exc_info=True)


    # In CommandCenter class
    def _get_object_details(self) -> ConcurrentDict[str, Any]:
        """
        Returns a dictionary of metadata about this object, fulfilling the
        contract for registration with a SignalController. This exposes the
        core public functions of the CommandCenter as callable commands.
        """
        self._check_disposed()
        return ConcurrentDict({
            "name": "command_center",
            "commands": ConcurrentDict({
                # --- Group Management ---
                'create_command_group': self.create_command_group,
                'get_command_group': self.get_command_group,
                'list_command_groups': lambda: [g.name for g in self._command_groups.values()],

                # --- Global Resource Management ---
                'get_total_active_workers': self.get_total_active_workers,
                'get_total_max_workers': self.get_total_max_workers,
                'adjust_global_limit': self.adjust_global_limit,

                # --- Global Introspection ---
                'get_all_active_agents': self.get_all_active_agents,
                'get_command_group_of_agent': self.get_command_group_of_agent,

                # --- Template Management (already have) ---
                'register_activity_template': self.register_activity_template,
                'list_activity_templates': self.list_activity_templates,
                'register_template': self.register_template,
                'list_templates': self.list_templates
            }),
        })

    def _notify(self, event_type: str, data: Optional[Dict[str, Any]] = None):
        """
        Helper to send notifications to the external signal controller if it exists.
        This allows the CommandCenter to be observable.
        """
        self._check_disposed()
        if self._external_signal_controller and not self._external_signal_controller._disposed:
            try:
                self._external_signal_controller.notify(self.id, event_type, data)
            except Exception as e:
                self._logger.error(f"Error notifying external SignalController: {e}", exc_info=True)

#endregion Controller Contract

#region Agent Pool Management
    def set_agent_pool_distribution(self, throughput_agents: int = 60, dispatch_agents: int= 40, targeted_dispatch_agents: int = 0, command_group_name: str = "default"):
        """
        Sets the distribution parameters for the AgentPool.

        Args:
            throughput_agents (int): Maximum number of agents dedicated to discrete queues
            dispatch_agents (int): Maximum number of agents available for dispatching.
            targeted_dispatch_agents (int): The number of agents available for targeted dispatching (e.g., for specific tasks, thread affinity, LLM tooling).
            command_group_name (str): The name of the command group to set the distribution for.
        """
        self._check_disposed()
        if not isinstance(throughput_agents, int) or throughput_agents < 0:
            raise ValueError("Throughput must be a non-negative integer.")
        if not isinstance(dispatch_agents, int) or dispatch_agents < 0:
            raise ValueError("Dispatched agents must be a non-negative integer.")
        if not isinstance(targeted_dispatch_agents, int) or targeted_dispatch_agents < 0:
            raise ValueError("Dispatch targeted must be a non-negative integer.")
        if throughput_agents + dispatch_agents + targeted_dispatch_agents > 100:
            raise ValueError("Total distribution cannot exceed 100% of the agent pool capacity.")

        command = self.get_command_group(command_group_name)
        command._group_pool_container.set_distribution(throughput_agents, dispatch_agents, targeted_dispatch_agents)
        self._logger.info(f"AgentPool distribution set: throughput={throughput_agents}, dispatched_agents={dispatch_agents}, dispatch_targeted={targeted_dispatch_agents}")
        self._notify('AGENT_POOL_DISTRIBUTION_SET', {
            'throughput_agents': throughput_agents,
            'dispatched_agents': dispatch_agents,
            'dispatch_targeted': targeted_dispatch_agents
        })

#endregion Agent Pool Management
#region Agent Management
    def find_agent_by_id(self, factory_id: str, command_group_name: str = "default") -> Optional[Agent]:
        """
        This will iterate over command groups to look for the agent if it cannot be found in default.

        Args:
            factory_id (str): The ULID or unique string used to identify the agent.
            command_group_name (str): The name of the command group to search in.
        """
        self._check_disposed()
        command = self.get_command_group(command_group_name)
        agent = command._active_agents.get(factory_id)
        if agent:
            return agent
        # If not found in the specified group, search all groups
        for group in self._command_groups.values():
            agent = group._active_agents.get(factory_id)
            if agent:
                return agent
        return None

    def create_agent(
            self,
            template_name: str = "default",
            define_home: Optional[Union[Callable[..., None], Pack]] = None,
            target: Optional[Union[Callable[..., None], Pack]] = None,
            command_group_name: str = "default",
            reset_agent: bool = False,
            *args, **kwargs
    ) -> Agent:
        """
        Creates a single agent from a registered template with optional task control hooks.

        Args:
            template_name (str): The name of the registered agent template.
            define_home (Callable | Pack, optional): A function representing the agent's long-lived event loop.
            target (Callable | Pack, optional): A one-time task to run before the main loop.
            command_group_name (str): The name of the command group to register the agent in.
            reset_agent (bool): If True, the agent will be reset before execution.
            *args: Positional overrides passed to the template factory.
            **kwargs: Keyword overrides passed to the template factory.

        Returns:
            Agent: The created agent instance.
        """
        self._check_disposed()

        if define_home is None and target is None:
            raise ValueError("At least one of define_home or target must be provided.")
        return self._create_and_register_agent(template_name=template_name, define_home=define_home,target=target, command_group=command_group_name, reset_agent=reset_agent,*args, **kwargs)

    def create_agents(
        self,
        count: int,
        template_name: str = "default",
        target: Optional[Union[Callable[..., None], Pack]] = None,
        define_home: Optional[Union[Callable[..., None], Pack]] = None,
        command_group_name: str = "default",
        reset_agents: bool = False,
        *args, **kwargs
    ) -> ConcurrentList[Agent]:
        """
        Creates a batch of agents using the same template and optional execution logic.

        Args:
            count (int): Number of agents to create.
            command_group_name (str): The name of the command group to register the agents in.
            template_name (str): Template to use for agent construction.
            target (Callable | Pack, optional): One-time task to execute inside each agent.
            define_home (Callable | Pack, optional): Loop function to run as main logic.
            reset_agents (bool): If True, the agent will be reset before execution.
            *args: Positional overrides for the factory.
            **kwargs: Keyword overrides for the factory.

        Returns:
            ConcurrentList[Agent]: The list of successfully created agents.

        Warnings:
            Will warn if the global worker cap is reached mid-creation.
        """
        self._check_disposed()

        new_agents = ConcurrentList()
        for i in range(count):
            try:
                agent = self.create_agent(command_group_name=command_group_name, template_name=template_name, define_home=define_home, target=target, reset_agent=reset_agents, *args, **kwargs)
                new_agents.append(agent)
            except RuntimeError:
                warnings.warn(f"Worker cap reached. Created {i} of {count} requested agents.", UserWarning)
                break
        return new_agents

    def submit(
        self,
        target: Union[Callable[..., Any], Pack],
        define_home: Optional[Union[Callable[..., None], Pack]] = None,
        template_name: str = "default",
        command_group_name: str = "default",
        reset_agent: bool = False,
        *args, **kwargs
    ) -> None:
        """
        Submits a fire-and-forget task using an ephemeral agent.

        The agent is immediately started, runs the task, and is automatically cleaned up.

        Args:
            target (Callable | Pack): The task to run inside the agent.
            command_group_name (str): The name of the command group to register the agent in.
            define_home (Callable | Pack, optional): A function representing the agent's long-lived event loop.
            template_name (str, optional): Template to use (defaults to 'default').
            reset_agent (bool): If True, the agent will be reset before execution.
            *args: Positional overrides passed to the agent template.
            **kwargs: Keyword overrides passed to the agent template.
        """
        agent = self.create_agent(command_group_name=command_group_name, template_name=template_name,
                                  target=target, define_home=define_home, reset_agent=reset_agent, *args, **kwargs)
        agent.deploy()

    def group_submit(
            self,
            agents: int,
            target: Union[Callable[..., Any], Pack],
            define_home: Optional[Union[Callable[..., None], Pack]] = None,
            template_name: str = "default",
            command_group_name: str = "default",
            reset_agents: bool = False,
            *args, **kwargs
    ) -> None:
        """
        Submits a fire-and-forget task using an ephemeral agent.

        The agent is immediately started, runs the task, and is automatically cleaned up.

        Args:
            target (Callable | Pack): The task to run inside the agent.
            command_group_name (str): The name of the command group to register the agent in.
            define_home (Callable | Pack, optional): A function representing the agent's long-lived event loop.
            agents (int): Number of agents to create and run the task in parallel.
            template_name (str, optional): Template to use (defaults to 'default').
            reset_agents (bool): If True, the agents will be reset before execution.
            *args: Positional overrides passed to the agent template.
            **kwargs: Keyword overrides passed to the agent template.
        """
        if not isinstance(agents, int) or agents < 1:
            raise ValueError("number_of_agents must be a positive integer.")
        command = self.get_command_group(command_group_name)
        if agents + command._worker_count > command._max_workers:
            raise RuntimeError(f"Cannot create {agents} agents. Worker cap of {command._max_workers} reached in command group '{command_group_name}'.")

        with self._lock:
            #Create and start the specified number of agents
            for _ in range(agents):
                agent = self.create_agent(template_name, target=target, define_home=define_home, command_group_name= command_group_name, reset_agent=reset_agents,  *args, **kwargs)
                agent.deploy()

    def _register_agent(self, agent: Agent, command: CommandGroup) -> None:
        """
        Internal helper to register an agent in the active list.
        """
        if not self._disposed and agent:
            with self._lock:
                agent._group_name = command.name
                agent._group_id = command.id
                command._worker_count.increment()
                command._active_agents[agent.factory_id] = agent
                self._notify('AGENT_CREATED', {'agent_id': agent.factory_id, 'template_name': agent.name, 'command_group': command.id, 'command_group_name': command.name})

    def _unregister_agent(self, agent: Agent):
        """
        Internal helper to unregister and forget an agent.
        """
        if not self._disposed and agent:
            command = self.get_command_group_of_agent(agent.factory_id)
            if not command:
                raise RuntimeError(f"Agent '{agent.factory_id}' not found in any command group. Significant error!")
            with self._lock:
                agent._group_name = None
                agent._group_id = None
                if command._active_agents.pop(agent.factory_id, None):
                    command._worker_count.decrement()
                    self._notify('AGENT_UNREGISTERED', {'agent_id': agent.factory_id, 'command_group': command.id, 'command_group_name': command.name})

    def increase_max_workers(self, amount: int = 1, command_group_name: str = "default"):
        """
        Increases the maximum allowed concurrent agents.

        Args:
            amount (int): The number of additional workers to allow (must be positive).
            command_group_name (str): The name of the command group to modify.

        Raises:
            ValueError: If amount is not a positive integer.
        """
        self._check_disposed()
        command = self.get_command_group(command_group_name)
        if not isinstance(amount, int) or amount < 1:
            raise ValueError("Amount must be a positive integer.")
        if self.get_total_active_workers() + amount > self._total_max_workers:
            raise RuntimeError(f"Cannot create CommandGroup '{command_group_name}'. Total active workers would exceed global limit of {self._total_max_workers}, increase new total limit to create a new group.")
        with self._lock:
            command._max_workers += amount
            command._group_pool_container.increase_max_worker_count(amount)
            self._notify('CONFIG_CHANGED', {'setting': 'max_workers', 'new_value': command._max_workers, 'command_group': command})

    def decrease_max_workers(self, amount: int = 1, command_group_name: str = "default"):
        """
        Decreases the maximum allowed concurrent agents.

        Args:
            amount (int): The number of workers to remove from the cap (must be positive).
            command_group_name (str): The name of the command group to modify.

        Raises:
            ValueError: If amount is not a positive integer.
            RuntimeError: If the decrease would result in fewer slots than active agents.
        """
        self._check_disposed()
        if not isinstance(amount, int) or amount < 1:
            raise ValueError("Amount must be a positive integer.")
        command = self.get_command_group(command_group_name)
        with self._lock:
            if command._worker_count > command._max_workers - amount:
                raise RuntimeError("Cannot decrease below current active worker count.")
            command._max_workers -= amount
            command._group_pool_container.decrease_max_worker_count(amount)
            self._notify('CONFIG_CHANGED', {'setting': 'max_workers', 'new_value': command._max_workers, 'command_group': command.id})

    def _create_and_register_agent(self, template_name: str, define_home: Optional[Union[Callable[..., None], Pack]] = None,
            target: Optional[Union[Callable[..., None], Pack]] = None, command_group:str = "default", reset_agent: bool = False,*args, **kwargs) -> Agent:
        """
        Internal method to create and register an agent under the global worker cap.

        Args:
            template_name (str): The symbolic name of the registered agent template.
            define_home (Callable | Pack, optional): A function representing the agent's long-lived event loop.
            target (Callable | Pack, optional): A one-time task to run before the main loop.
            command_group (str): The name of the command group to register the agent in.
            reset_agent (bool): If True, the agent will be reset before execution.
            *args: Optional positional overrides for the factory.
            **kwargs: Optional keyword overrides for the factory.

        Returns:
            Agent: The newly constructed and registered agent instance.

        Raises:
            RuntimeError: If the worker cap is exceeded or the CommandCenter is disposed.
            Exception: Any exceptions raised by the template factory.
        """
        if self._disposed:
            raise RuntimeError("CommandCenter is disposed.")

        command = self.get_command_group(command_group)

        if command._worker_count >= command._max_workers:
            self._notify('WORKER_CAP_REACHED', {'max_workers': command._max_workers, 'command_group': command.id})
            self._logger.warning(f"Cannot create agent. Worker cap of {command._max_workers} reached in command group '{command_group}'.")
            raise RuntimeError(f"Cannot create agent. Worker cap of {command._max_workers} reached.")

        # Attempt to get an agent from the pool first
        agent = self._attempt_pool_get_agent(template_name=template_name, command_group_id=command.id)

        #TODO: WE need to handle the case where the pool returns None, which means we need to apply backpressure if the pool is maxed they wont' be able tom ake workers anyways
        #we need to fill the pool immediately upon creation
        # Fallback to factory if needed
        if agent is None:
            agent = self._create_agent_from_template(template_name=template_name, command_group_id=command.id)

        # Ensure the agent is properly configured
        self._post_agent_creation(agent=agent, define_home=define_home, target=target, reset_agent=reset_agent, *args, **kwargs)
        # Final registration
        self._register_agent(agent, command)
        return agent

    def _attempt_pool_get_agent(self, template_name: str, command_group_id: str) -> Optional[Agent]:
        """
        Attempts to retrieve an agent from the AgentPool if available.
        """
        try:
            return self._agent_pool.try_get_agent(template_name=template_name, group_name_id=command_group_id)
        except Exception as e:
            self._logger.error(f"AgentPool failed to provide pooled agent: {e}. Falling back to factory.")
            self._notify('POOL_GET_FAILED', {'template_name': template_name, 'command_group': command_group_id})


    def _create_agent_from_template(self, template_name: str, command_group_id: str, *args, **kwargs) -> Agent:
        """
        Internal helper to create an agent from a registered template.
        This is used by the CommandCenter to create agents from templates.
        """
        try:
            kwargs["command_center"] = self
            agent = self._builder.create_agent(template_name, *args, **kwargs)
            agent.template_name = template_name
            #TODO: Register agent with pool
            return agent
        except Exception as e:
            self._logger.error(f"Failed to create agent from template '{template_name}': {e}", exc_info=True)
            self._notify('AGENT_CREATION_FAILED', {'template_name': template_name, 'error': str(e)})
            raise RuntimeError(f"Agent creation failed: {str(e)}") from e

    def _post_agent_creation(self, agent: Agent, define_home: Optional[Union[Callable[..., None], Pack]] = None,
            target: Optional[Union[Callable[..., None], Pack]] = None, reset_agent: bool = False, *args, **kwargs) -> None:
        """
        Internal helper to finalize agent creation and setup.
        """
        #TODO: Implement kwargs onto agent somehow
        if reset_agent:
            agent.reset() #TODO: This reset still needs to be fleshed out
        if target:
            agent.set_target(target)
        if define_home:
            agent.set_home(define_home)


    def register_template(self, template_name: str, factory_fn: Union[Callable[..., Agent], Pack]):
        """
        Registers a new agent creation template.

        Args:
            template_name (str): Symbolic name of the template.
            factory_fn (Callable | Pack): Factory function or Pack object used to construct the agent.
        """
        if self._disposed:
            raise RuntimeError("Cannot register templates after CommandCenter is disposed.")
        self._builder.register_template(template_name, factory_fn)
        self._notify('TEMPLATE_REGISTERED', {'template_name': template_name})

    def unregister_template(self, template_name: str) -> bool:
        """
        Removes a previously registered agent template.

        Args:
            template_name (str): Symbolic name of the template to remove.

        Returns:
            bool: True if removed successfully, False if not found.
        """
        self._check_disposed()
        was_unregistered = self._builder.unregister_template(template_name)
        if was_unregistered:
            self._notify('TEMPLATE_UNREGISTERED', {'template_name': template_name})
        return was_unregistered

    def list_templates(self) -> List[str]:
        """
        Lists all registered agent templates.

        Returns:
            List[str]: A list of symbolic template names.
        """
        self._check_disposed()
        return self._builder.list_templates()

    def get_active_agents(self, command_group_name: str = "default") -> List[Agent]:
        """
        Returns all currently active agents managed by this CommandCenter.

        Returns:
            List[Agent]: A list of active agent instances.
        """
        if self._disposed:
            return []
        command = self.get_command_group(command_group_name)
        return list(command._active_agents.values())


    def get_all_active_agents(self) -> List[Agent]:
        """
        Returns all currently active agents across all command groups.

        Returns:
            List[Agent]: A list of active agent instances.
        """
        if self._disposed:
            return []
        agents = []
        for group in self._command_groups.values():
            agents.extend(group._active_agents.values())
        return agents

    def get_agent_by_id(self, factory_id: str, command_group_name:str = "default") -> Optional[Agent]:
        """
        Retrieves an agent by its factory-assigned ID.

        Args:
            factory_id (str): The ULID or unique string used to identify the agent.
            command_group_name (str): The name of the command group to search in.

        Returns:
            Optional[Agent]: The matching agent, or None if not found or disposed.
        """
        if self._disposed or not factory_id:
            return None
        command = self.get_command_group(command_group_name)
        return command._active_agents.get(factory_id)


    def check_if_agent_exists(self, factory_id: str, command_group_name:str = "default") -> bool:
        """
        Checks if an agent with the given factory ID exists in the specified command group.

        Args:
            factory_id (str): The ULID or unique string used to identify the agent.
            command_group_name (str): The name of the command group to search in.

        Returns:
            bool: True if the agent exists, False otherwise.
        """
        self._check_disposed()
        command = self.get_command_group(command_group_name)
        return factory_id in command._active_agents


    def get_command_group_of_agent(self, factory_id: str) -> Optional[CommandGroup]:
        """
        Retrieves the CommandGroup that manages the agent with the given factory ID.

        Args:
            factory_id (str): The ULID or unique string used to identify the agent.

        Returns:
            Optional[CommandGroup]: The CommandGroup instance managing the agent, or None if not found.
        """
        self._check_disposed()
        for group in self._command_groups.values():
            if factory_id in group._active_agents:
                return group
        return None

#endregion Agent Management
#region SignalController Management
    def add_signal_controller(self, name: str, controller: Optional[SignalController] = None, command_group_name: str = "default") -> SignalController:
        """
        Adds a new SignalController to the CommandCenter's management. If an existing
        controller instance is not provided, a new one is created. This allows the
        CommandCenter to manage multiple, named communication buses.

        Args:
            name (str): A unique name to identify this SignalController.
            controller (Optional[SignalController]): An existing SignalController instance.
                                                     If None, a new one will be created.
            command_group_name (str): The name of the command group to associate with this controller.

        Returns:
            SignalController: The newly added or created SignalController instance.

        Raises:
            ValueError: If a SignalController with the same name already exists.
        """
        self._check_disposed()
        with self._lock:
            command = self.get_command_group(command_group_name)
            existing = self.find_controller_by_name(name, command_group_name)
            if existing:
                self._logger.warning(f"SignalController with name '{name}' already exists in command group '{command_group_name}'. Returning existing controller.")
                return existing
            else:
                new_controller = controller or SignalController(controller_name=name, logger=self._logger)
                new_controller._group_name = command.name
                new_controller._group_id = command.id
                command._signal_controllers[new_controller.id] = new_controller
                self._logger.info(f"Added SignalController: '{name}'")
                self._notify('SIGNAL_CONTROLLER_ADDED', {'controller_name': name, 'command_group': command.id, 'command_group_name': command.name})
                return new_controller


    def find_controller_by_name(self, name: str, command_group_name: str = "default") -> Optional[SignalController]:
        """
        Finds a SignalController by its name within the specified command group.

        Args:
            name (str): The name of the SignalController to find.
            command_group_name (str): The name of the command group to search in.

        Returns:
            List[SignalController]: The SignalController instance if found, or None if not found.
        """
        self._check_disposed()
        returnlist = []
        command = self.get_command_group(command_group_name)
        for controller in command._signal_controllers.values():
            if controller.name == name:
                returnlist.append(controller)

        if returnlist:
            # If multiple controllers with this name exist, raise an error
            if len(returnlist) > 1:
                raise ValueError(
                    f"Multiple SignalControllers with the name '{name}' exist in command group '{command_group_name}'. Please use a unique name.")
        controller = returnlist[0] if returnlist else None
        return controller

    def remove_signal_controller(self, signal_controller: 'SignalController', dispose: bool = True) -> bool:
        """
        Removes a SignalController from the CommandCenter.

        Args:
            signal_controller (SignalController): The SignalController instance to remove.
            dispose (bool): If True, the SignalController's dispose() method will be
                            called upon removal. Defaults to True.

        Returns:
            bool: True if the controller was found and removed, False otherwise.
        """
        self._check_disposed()

        for group in self._command_groups.values():
            if signal_controller.id in group._signal_controllers:
                controller = group._signal_controllers.pop(signal_controller.id)
                name = controller.name
                self._logger.info(f"Removed SignalController: '{name}'")
                self._notify('SIGNAL_CONTROLLER_REMOVED', {'controller_name': name, 'command_group': group.id, 'command_group_name': group.name})
                controller._group_name = None
                controller._group_id = None
                if dispose:
                    try:
                        controller.dispose()
                    except Exception as e:
                        self._logger.error(f"Error disposing removed SignalController '{name}': {e}", exc_info=True)
                return True
        self._logger.warning(f"SignalController '{signal_controller.name}' not found in any command group.")
        return False

    def get_signal_controller(self, controller_id: str, command_group_name: str = "default") -> Optional[SignalController]:
        """
        Retrieves a managed SignalController by its name.

        Args:
            controller_id (str): The name of the SignalController to retrieve.
            command_group_name (str): The name of the command group to search in.

        Returns:
            Optional[SignalController]: The SignalController instance, or None if not found.
        """
        self._check_disposed()
        command = self.get_command_group(command_group_name)
        return command._signal_controllers.get(controller_id)

    def get_signal_controller_by_id(self, controller_id: str) -> Optional[SignalController]:
        """
        Retrieves a managed SignalController by its unique ID.

        Args:
            controller_id (str): The unique identifier of the SignalController.

        Returns:
            Optional[SignalController]: The SignalController instance, or None if not found.
        """
        self._check_disposed()
        for group in self._command_groups.values():
            if controller_id in group._signal_controllers:
                return group._signal_controllers[controller_id]
        return None


    def list_signal_controllers(self) -> List[str]:
        """
        Lists the names of all managed SignalControllers.

        Returns:
            List[str]: A list of SignalController names.
        """
        self._check_disposed()

        signal_controller_list = []
        for group in self._command_groups.values():
            for controller in group._signal_controllers.values():
                signal_controller_list.append(controller.name)

        return signal_controller_list

    def invoke_on_controller_by_id(self, controller_id: str, object_id: str, command: str, *args, **kwargs) -> Any:
        """
        Invokes a command on an object registered with a specific internal SignalController.

        This acts as a proxy, allowing remote command execution on any managed bus.

        Args:
            controller_id (str): The name of the internal SignalController to use.
            object_id (str): The ID of the target object on that controller.
            command (str): The name of the command to execute (e.g., 'open', 'reset').
            *args: Positional arguments to pass to the command.
            **kwargs: Keyword arguments to pass to the command.

        Returns:
            Any: The result from the invoked command.

        Raises:
            ValueError: If no controller with the given name exists.
        """
        self._check_disposed()
        controller = self.get_signal_controller_by_id(controller_id)
        if not controller:
            raise ValueError(f"No SignalController with the name '{controller.name}' is managed by this CommandCenter.")
        return controller.invoke(object_id, command, *args, **kwargs)

    def invoke_on_controller_by_name(self, controller_name: str, object_id: str, command: str, command_group_name: str = "default", *args, **kwargs) -> Any:
        """
        Invokes a command on an object registered with a specific internal SignalController.

        This acts as a proxy, allowing remote command execution on any managed bus.

        Args:
            controller_name (str): The name of the internal SignalController to use.
            command_group_name (str): The name of the command group to search in.
            object_id (str): The ID of the target object on that controller.
            command (str): The name of the command to execute (e.g., 'open', 'reset').
            *args: Positional arguments to pass to the command.
            **kwargs: Keyword arguments to pass to the command.

        Returns:
            Any: The result from the invoked command.

        Raises:
            ValueError: If no controller with the given name exists.
        """
        self._check_disposed()
        controller = self.find_controller_by_name(controller_name, command_group_name)
        if not controller:
            raise ValueError(
                f"No SignalController with the name '{controller_name}' is managed by this CommandCenter.")
        return controller.invoke(object_id, command, *args, **kwargs)

    def subscribe_to_event(self, controller_name: str, object_id: str, event_type: str, callback: Callable, command_group_name: str = "default"):
        """
        Subscribes a callback to an event on a specific object managed by an internal SignalController.

        Args:
            controller_name (str): The name of the communication bus to listen on.
            object_id (str): The ID of the object emitting the event.
            event_type (str): The name of the event to subscribe to (e.g., 'THRESHOLD_MET').
            callback (Callable): The function to call when the event occurs.
            command_group_name (str): The name of the command group to search in.

        Raises:
            ValueError: If no controller with the given name exists.
        """
        self._check_disposed()
        controller = self.get_signal_controller(controller_name, command_group_name)
        if not controller:
            raise ValueError(f"No SignalController with the name '{controller_name}' is managed by this CommandCenter.")
        controller.subscribe(object_id, event_type, callback)

    def add_hook_to_controller(self, controller_name: str, hook_type: str, callback: Callable, command_group_name: str = "default"):
        """
        Attaches a pre- or post-invocation hook to an internal SignalController for auditing
        or performance monitoring.

        Args:
            controller_name (str): The name of the controller to attach the hook to.
            hook_type (str): The type of hook, must be either 'pre_invoke' or 'post_invoke'.
            command_group_name (str): The name of the command group to search in.
            callback (Callable): The hook function to add.

        Raises:
            ValueError: If the controller name is not found or the hook_type is invalid.
        """
        self._check_disposed()
        controller = self.get_signal_controller(controller_name, command_group_name)
        if not controller:
            raise ValueError(f"No SignalController with the name '{controller_name}' is managed by this CommandCenter in command group {command_group_name}.")

        if hook_type == 'pre_invoke':
            controller.add_pre_invoke_hook(callback)
        elif hook_type == 'post_invoke':
            controller.add_post_invoke_hook(callback)
        else:
            raise ValueError("hook_type must be either 'pre_invoke' or 'post_invoke'.")

    def list_objects_on_controller(self, controller_name: str, name_filter: Optional[str] = None, command_group_name:str = "default") -> List[Dict[str, Any]]:
        """
        Gets a list of all objects currently registered on a specific internal SignalController.

        Args:
            controller_name (str): The name of the controller to query.
            name_filter (Optional[str]): An optional filter to only list objects with a specific name.
            command_group_name (str): The name of the command group to search in.

        Returns:
            List[Dict[str, Any]]: A list of object details.

        Raises:
            ValueError: If no controller with the given name exists.
        """
        self._check_disposed()
        controller = self.get_signal_controller(controller_name, command_group_name)
        if not controller:
            raise ValueError(f"No SignalController with the name '{controller_name}' is managed by this CommandCenter in command group {command_group_name}.")
        return controller.list_objects(name_filter)

    def get_waiting_objects_on_controller(self, controller_name: str, command_group_name: str = "default") -> List[str]:
        """
        Gets a list of object IDs that are currently in a "waiting" state on a specific
        internal SignalController.

        Args:
            controller_name (str): The name of the controller to query.
            command_group_name (str): The name of the command group to search in.

        Returns:
            List[str]: A list of object IDs in a waiting state.

        Raises:
            ValueError: If no controller with the given name exists.
        """
        self._check_disposed()
        controller = self.get_signal_controller(controller_name, command_group_name)
        if not controller:
            raise ValueError(f"No SignalController with the name '{controller_name}' is managed by this CommandCenter in command group {command_group_name}.")
        return controller.get_waiting_objects()

#endregion SignalController Management
#endregion CommandCenter
