import threading, warnings, logging, ulid
from typing import Optional, List, Callable, Any, Union, Dict, Type
from thread_factory.agent import ActivityBuilder
from thread_factory.agent.activity.base import BaseActivity
from thread_factory.agent.identity.agent_builder import AgentBuilder
from thread_factory.agent.identity.types.agent import Agent
from thread_factory.synchronization.controllers.signal_controller import SignalController
from thread_factory.utils.coordination.package import Pack
from thread_factory.utils.interfaces.disposable import IDisposable
from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.concurrency.sync_types.sync_int import SyncInt

#region CommandGroup
class CommandGroup(IDisposable):
    def __init__(self,  command_center: 'CommandCenter', group_name: str, max_workers: int, group_type: str = None):
        super().__init__()
        self._lock = threading.RLock()
        self.id = str(ulid.ULID())
        self.name = group_name
        self.type = group_type

        # --- Internal Components ---
        self._worker_count = SyncInt(0)
        self._max_workers = max_workers
        self._command_center = command_center  # Reference to its creator

        # Internal registries for its members
        self._active_agents: ConcurrentDict[str, Agent] = ConcurrentDict()
        self._signal_controllers: ConcurrentDict[str, SignalController] = ConcurrentDict()
        self._active_activities: ConcurrentDict[str, BaseActivity] = ConcurrentDict()

    def dispose(self):
        # Logic to shut down all agents and dispose all activities
        with self._lock:
            if hasattr(self, '_disposed') and self._disposed:
                return
            self._disposed = True
            self._command_center = None

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
            self._worker_count.dispose()


#endregion CommandGroup

#region CommandCenter
class CommandCenter(IDisposable):
    """
    CommandCenter
    ----------------
    A central orchestration unit responsible for managing agent thread lifecycles,
    enforcing global worker limits, creating agents from predefined templates,
    and managing its own SignalControllers. It can also be registered with an
    external SignalController to be managed remotely.
    """

    def __init__(self,
                 max_workers: int = 8,
                 command_group_name: str = "default",
                 logger: Optional[logging.Logger] = None,
                 external_signal_controller: Optional[SignalController] = None):
        """
        Initializes the CommandCenter. This object is responsible for managing
        the lifecycle of agents, enforcing a global worker cap, and providing
        a centralized interface for creating and managing agents.
        It can also register with an external SignalController for remote management.

        It currently has a default maximum of 8 concurrent agents, but this can be
        adjusted using the `increase_max_workers` and `decrease_max_workers` methods.
        This class is thread-safe and can be used in multithreaded environments.
        It is also disposable, meaning it can be cleaned up and all resources released
        when no longer needed.

        The threadpool integration is built into this object however this will be moved
        to a normal threadpool in the future.  There will be a main pool
        that will utilize standard workers and  an agent pool in the future,
        allowing for more granular control over thread management and resource allocation.

        Args:
            max_workers (int): Maximum number of concurrent agents allowed to exist.
            logger (Optional[logging.Logger]): A logger instance.
            external_signal_controller (Optional[SignalController]): An external controller
                to register with, allowing this CommandCenter to be controlled remotely.
        """
        super().__init__()
        # --- Core Components ---
        self._logger = logger or logging.getLogger(__name__)
        self._lock = threading.RLock()
        self._builder = AgentBuilder()
        self._activity_builder = ActivityBuilder()

        # --- Group Management ---
        self._command_groups: ConcurrentDict[str, CommandGroup] = ConcurrentDict()
        self.create_command_group(command_group_name, max_workers) # creates initial command group

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
        Disposes the CommandCenter and all resources it manages, including all
        agents and SignalControllers. This is a terminal and idempotent operation.
        """
        with self._lock:
            if self._disposed:
                return
            self._disposed = True

            self._logger.info(f"Disposing CommandCenter '{self.id}'...")

            # --- Unregister from external controller first ---
            if self._external_signal_controller:
                try:
                    # Set dispose_object=False as we are already disposing.
                    self._external_signal_controller.unregister(self.id, dispose_object=False)
                    self._logger.info(f"Unregistered CommandCenter '{self.id}' from external SignalController.")
                except Exception as e:
                    self._logger.warning(f"Failed to unregister CommandCenter from external SignalController: {e}", exc_info=True)

            # --- Dispose internal SignalControllers ---
            if self._signal_controllers:
                for controller_name, controller in list(self._signal_controllers.items()):
                    self._logger.debug(f"Disposing internal SignalController: {controller_name}")
                    try:
                        controller.dispose()
                    except Exception as e:
                        self._logger.error(f"Error disposing internal SignalController '{controller_name}': {e}", exc_info=True)
                self._signal_controllers.dispose()
                self._signal_controllers = None

            # --- Dispose Agents ---
            if self._active_agents:
                for agent in list(self._active_agents.values()):
                    try:
                        if hasattr(agent, "dispose") and callable(agent.dispose):
                            agent.dispose()
                    except Exception:
                        pass
                self._active_agents.clear()
                self._active_agents = None

            # --- Dispose Activities ---
            if self._activity_builder:
                self._activity_builder.dispose()
                self._activity_builder = None

            if self._active_activities:
                for activity in list(self._active_activities.values()):
                    activity.dispose()
                self._active_activities.dispose()
                self._active_activities = None
            try:
                self._builder.dispose()
            except Exception:
                pass

            self._logger.info(f"CommandCenter '{self.id}' disposed.")

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
    def create_command_group(self, command_group_name: str, max_workers, command_group_type:str = None) -> None:
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

        group = CommandGroup(group_name=command_group_name, max_workers=max_workers, command_center=self, group_type=command_group_type)
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
                command._active_activities[activity.id] = activity
                self._logger.info(f"Created and registered Activity '{activity.id}' of type '{name}'. Using command group '{command.name}'.")
                # You could also emit a notification here
                # self._notify('ACTIVITY_CREATED', {'activity_id': activity.id, 'type': name})
                return activity
        except Exception as e:
            self._logger.error(f"Failed to create activity of type '{name}': {e}", exc_info=True)

        return None


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
        Verifies if the provided activity is registered in the specified command group.

        Args:
            activity (BaseActivity): The activity instance to verify.
            command_group_name (str): The name of the command group to check in.

        Returns:
            bool: True if the activity is registered, False otherwise.
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


    def deploy_activity(self, activity: 'BaseActivity', worker_count: int, command_group_name: str = "default"):
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

        available_slots = command._max_workers - command._worker_count.value
        if worker_count > available_slots:
            raise RuntimeError(f"Cannot deploy {worker_count} workers. Only {available_slots} slots are available.")

        # --- Deployment Logic ---
        self._logger.info(f"Deploying {worker_count} agents to Activity '{activity.id}'... using command group '{command.name}'.")

        # "Open the gate" for all agents before they are deployed
        activity.start()

        # Create and deploy the team of agents
        for _ in range(worker_count):
            # Create an agent whose target is the activity's main work loop
            agent = self.create_agent(command_group_name=command_group_name, target=activity.perform_activity)

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

    @property
    def id(self) -> str:
        """
        The unique identifier for this CommandCenter instance.
        """
        return self._id

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
                'create_agent': self.create_agent,
                'create_agents': self.create_agents,
                'submit': self.submit,
                'list_templates': self.list_templates,
                'get_active_agents': self.get_active_agents,
                'increase_max_workers': self.increase_max_workers,
                'decrease_max_workers': self.decrease_max_workers,
                'add_signal_controller': self.add_signal_controller,
                'remove_signal_controller': self.remove_signal_controller,
                'list_signal_controllers': self.list_signal_controllers,
                'list_activity_templates': self.list_activity_templates,
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
            command_group_name:str = "default",
            template_name: str = "default",
            define_home: Optional[Union[Callable[..., None], Pack]] = None,
            target: Optional[Union[Callable[..., None], Pack]] = None,
            *args, **kwargs
    ) -> Agent:
        """
        Creates a single agent from a registered template with optional task control hooks.

        Args:
            template_name (str): The name of the registered agent template.
            define_home (Callable | Pack, optional): A function representing the agent's long-lived event loop.
            target (Callable | Pack, optional): A one-time task to run before the main loop.
            command_group_name (str): The name of the command group to register the agent in.
            *args: Positional overrides passed to the template factory.
            **kwargs: Keyword overrides passed to the template factory.

        Returns:
            Agent: The created agent instance.
        """
        self._check_disposed()
        if define_home is None and target is None:
            raise ValueError("At least one of define_home or target must be provided.")
        agent = self._create_and_register_agent(template_name, command_group_name, *args, **kwargs)
        if target:
            agent.set_target(target)
        if define_home:
            agent.set_home(define_home)
        return agent

    def create_agents(
        self,
        count: int,
        command_group_name: str = "default",
        template_name: str = "default",
        target: Optional[Union[Callable[..., None], Pack]] = None,
        define_home: Optional[Union[Callable[..., None], Pack]] = None,
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
                agent = self.create_agent(command_group_name=command_group_name, template_name=template_name, define_home=define_home, target=target, *args, **kwargs)
                new_agents.append(agent)
            except RuntimeError:
                warnings.warn(f"Worker cap reached. Created {i} of {count} requested agents.", UserWarning)
                break
        return new_agents

    def submit(
        self,
        target: Union[Callable[..., Any], Pack],
        define_home: Optional[Union[Callable[..., None], Pack]] = None,
        command_group_name: str = "default",
        template_name: str = "default",
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
            *args: Positional overrides passed to the agent template.
            **kwargs: Keyword overrides passed to the agent template.
        """
        agent = self.create_agent(command_group_name=command_group_name, template_name=template_name,
                                  target=target, define_home=define_home,*args, **kwargs)
        agent.deploy()

    def group_submit(
            self,
            agents: int,
            target: Union[Callable[..., Any], Pack],
            define_home: Optional[Union[Callable[..., None], Pack]] = None,
            command_group_name: str = "default",
            template_name: str = "default",
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
                agent = self.create_agent(template_name, target=target, define_home=define_home, command_group_name= command_group_name, *args, **kwargs)
                agent.deploy()

    def _register_agent(self, agent: Agent, command: CommandGroup) -> None:
        """
        Internal helper to register an agent in the active list.
        """
        if not self._disposed and agent:
            with self._lock:
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
        with self._lock:
            command._max_workers += amount
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
            self._notify('CONFIG_CHANGED', {'setting': 'max_workers', 'new_value': command._max_workers, 'command_group': command.id})

    def _create_and_register_agent(self, template_name: str, command_group:str = "default",  *args, **kwargs) -> Agent:
        """
        Internal method to create and register an agent under the global worker cap.

        Args:
            template_name (str): The symbolic name of the registered agent template.
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
            self._notify('WORKER_CAP_REACHED', {'max_workers': command._max_workers, 'command_group': command_group.id} )
            raise RuntimeError(f"Cannot create agent. Worker cap of {command._max_workers} reached.")

        try:
            kwargs["command_center"] = self
            agent = self._builder.create_agent(template_name, *args, **kwargs)
            self._register_agent(agent, command)
            return agent
        except Exception as e:
            raise RuntimeError(f"Agent creation failed: {str(e)}") from e

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
            if name in self.find_controller_by_name(name, command_group_name):
                raise ValueError(f"A SignalController with the name '{name}' already exists in command group '{command_group_name}'.")
            new_controller = controller or SignalController(logger=self._logger)
            command._signal_controllers[new_controller.id] = new_controller
            self._logger.info(f"Added SignalController: '{name}'")
            self._notify('SIGNAL_CONTROLLER_ADDED', {'controller_name': name, 'command_group': command.id, 'command_group_name': command.name})
            return new_controller


    def find_controller_by_name(self, name: str, command_group_name: str = "default") -> List[SignalController]:
        """
        Finds a SignalController by its name within the specified command group.

        Args:
            name (str): The name of the SignalController to find.
            command_group_name (str): The name of the command group to search in.

        Returns:
            Optional[SignalController]: The SignalController instance if found, or None if not found.
        """
        self._check_disposed()
        returnlist = []
        command = self.get_command_group(command_group_name)
        for controller in command._signal_controllers.values():
            if controller.name == name:
                returnlist.append(controller)

        return returnlist if returnlist else None

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
        for controller in self._signal_controllers.values():
            if controller.id == controller_id:
                return controller
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

    def invoke_on_controller(self, controller_id: str, object_id: str, command: str, command_group_name: str = "default", *args, **kwargs) -> Any:
        """
        Invokes a command on an object registered with a specific internal SignalController.

        This acts as a proxy, allowing remote command execution on any managed bus.

        Args:
            controller_name (str): The name of the internal SignalController to use.
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

    def subscribe_to_event(self, controller_name: str, object_id: str, event_type: str, callback: Callable):
        """
        Subscribes a callback to an event on a specific object managed by an internal SignalController.

        Args:
            controller_name (str): The name of the communication bus to listen on.
            object_id (str): The ID of the object emitting the event.
            event_type (str): The name of the event to subscribe to (e.g., 'THRESHOLD_MET').
            callback (Callable): The function to call when the event occurs.

        Raises:
            ValueError: If no controller with the given name exists.
        """
        self._check_disposed()
        controller = self.get_signal_controller(controller_name)
        if not controller:
            raise ValueError(f"No SignalController with the name '{controller_name}' is managed by this CommandCenter.")
        controller.subscribe(object_id, event_type, callback)

    def add_hook_to_controller(self, controller_name: str, hook_type: str, callback: Callable):
        """
        Attaches a pre- or post-invocation hook to an internal SignalController for auditing
        or performance monitoring.

        Args:
            controller_name (str): The name of the controller to attach the hook to.
            hook_type (str): The type of hook, must be either 'pre_invoke' or 'post_invoke'.
            callback (Callable): The hook function to add.

        Raises:
            ValueError: If the controller name is not found or the hook_type is invalid.
        """
        self._check_disposed()
        controller = self.get_signal_controller(controller_name)
        if not controller:
            raise ValueError(f"No SignalController with the name '{controller_name}' is managed by this CommandCenter.")

        if hook_type == 'pre_invoke':
            controller.add_pre_invoke_hook(callback)
        elif hook_type == 'post_invoke':
            controller.add_post_invoke_hook(callback)
        else:
            raise ValueError("hook_type must be either 'pre_invoke' or 'post_invoke'.")

    def list_objects_on_controller(self, controller_name: str, name_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Gets a list of all objects currently registered on a specific internal SignalController.

        Args:
            controller_name (str): The name of the controller to query.
            name_filter (Optional[str]): An optional filter to only list objects with a specific name.

        Returns:
            List[Dict[str, Any]]: A list of object details.

        Raises:
            ValueError: If no controller with the given name exists.
        """
        self._check_disposed()
        controller = self.get_signal_controller(controller_name)
        if not controller:
            raise ValueError(f"No SignalController with the name '{controller_name}' is managed by this CommandCenter.")
        return controller.list_objects(name_filter)

    def get_waiting_objects_on_controller(self, controller_name: str) -> List[str]:
        """
        Gets a list of object IDs that are currently in a "waiting" state on a specific
        internal SignalController.

        Args:
            controller_name (str): The name of the controller to query.

        Returns:
            List[str]: A list of object IDs in a waiting state.

        Raises:
            ValueError: If no controller with the given name exists.
        """
        self._check_disposed()
        controller = self.get_signal_controller(controller_name)
        if not controller:
            raise ValueError(f"No SignalController with the name '{controller_name}' is managed by this CommandCenter.")
        return controller.get_waiting_objects()

#endregion SignalController Management
#endregion CommandCenter
