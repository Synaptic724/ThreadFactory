import threading, warnings, logging, ulid
from typing import Optional, List, Callable, Any, Union, Dict
from thread_factory.agent.identity.agent_builder import AgentBuilder
from thread_factory.agent.identity.types.agent import Agent
from thread_factory.synchronization.controllers.signal_controller import SignalController
from thread_factory.utils.coordination.package import Pack
from thread_factory.utils.interfaces.disposable import IDisposable
from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.concurrency.sync_types.sync_int import SyncInt

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
        if max_workers < 1 or not isinstance(max_workers, int):
            raise ValueError("max_workers must be a positive integer.")

        self._logger = logger or logging.getLogger(__name__)
        self._lock = threading.RLock()

        # --- Core Components ---
        self._active_agents: ConcurrentDict[str, Agent] = ConcurrentDict()
        self._builder = AgentBuilder()
        self._worker_count = SyncInt(0)
        self._max_workers = max_workers
        self._signal_controllers: ConcurrentDict[str, SignalController] = ConcurrentDict()

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
        """The unique identifier for this CommandCenter instance."""
        return self._id

    def _get_object_details(self) -> Dict[str, Any]:
        """
        Returns a dictionary of metadata about this object, fulfilling the
        contract for registration with a SignalController. This exposes the
        core public functions of the CommandCenter as callable commands.
        """
        self._check_disposed()
        return {
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
                'list_signal_controllers': self.list_signal_controllers
            }),
        }

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
    def create_agent(
            self,
            template_name: str,
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
            *args: Positional overrides passed to the template factory.
            **kwargs: Keyword overrides passed to the template factory.

        Returns:
            Agent: The created agent instance.
        """
        self._check_disposed()
        agent = self._create_and_register_agent(template_name, *args, **kwargs)
        if target:
            agent.set_target(target)
        if define_home:
            agent.set_home(define_home)
        return agent

    def create_agents(
        self,
        count: int,
        template_name: str,
        target: Optional[Union[Callable[..., None], Pack]] = None,
        define_home: Optional[Union[Callable[..., None], Pack]] = None,
        *args, **kwargs
    ) -> ConcurrentList[Agent]:
        """
        Creates a batch of agents using the same template and optional execution logic.

        Args:
            count (int): Number of agents to create.
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
                agent = self.create_agent(template_name, define_home=define_home, target=target, *args, **kwargs)
                new_agents.append(agent)
            except RuntimeError:
                warnings.warn(f"Worker cap reached. Created {i} of {count} requested agents.", UserWarning)
                break
        return new_agents

    def submit(
        self,
        target: Union[Callable[..., Any], Pack],
        template_name: str = "default",
        *args, **kwargs
    ) -> None:
        """
        Submits a fire-and-forget task using an ephemeral agent.

        The agent is immediately started, runs the task, and is automatically cleaned up.

        Args:
            target (Callable | Pack): The task to run inside the agent.
            template_name (str, optional): Template to use (defaults to 'default').
            *args: Positional overrides passed to the agent template.
            **kwargs: Keyword overrides passed to the agent template.
        """
        agent = self.create_agent(template_name, define_home=target, *args, **kwargs)
        agent.start()

    def _register_agent(self, agent: Agent):
        """Internal helper to register an agent in the active list."""
        if not self._disposed and agent:
            with self._lock:
                self._worker_count.increment()
                self._active_agents[agent.factory_id] = agent
                self._notify('AGENT_CREATED', {'agent_id': agent.factory_id, 'template_name': agent.name})

    def _unregister_agent(self, agent: Agent):
        """Internal helper to unregister and forget an agent."""
        if not self._disposed and agent:
            with self._lock:
                if self._active_agents.pop(agent.factory_id, None):
                    self._worker_count.decrement()
                    self._notify('AGENT_UNREGISTERED', {'agent_id': agent.factory_id})

    def increase_max_workers(self, amount: int = 1):
        """
        Increases the maximum allowed concurrent agents.

        Args:
            amount (int): The number of additional workers to allow (must be positive).

        Raises:
            ValueError: If amount is not a positive integer.
        """
        self._check_disposed()
        if not isinstance(amount, int) or amount < 1:
            raise ValueError("Amount must be a positive integer.")
        with self._lock:
            self._max_workers += amount
            self._notify('CONFIG_CHANGED', {'setting': 'max_workers', 'new_value': self._max_workers})

    def decrease_max_workers(self, amount: int = 1):
        """
        Decreases the maximum allowed concurrent agents.

        Args:
            amount (int): The number of workers to remove from the cap (must be positive).

        Raises:
            ValueError: If amount is not a positive integer.
            RuntimeError: If the decrease would result in fewer slots than active agents.
        """
        self._check_disposed()
        if not isinstance(amount, int) or amount < 1:
            raise ValueError("Amount must be a positive integer.")
        with self._lock:
            if self._worker_count.get() > self._max_workers - amount:
                raise RuntimeError("Cannot decrease below current active worker count.")
            self._max_workers -= amount
            self._notify('CONFIG_CHANGED', {'setting': 'max_workers', 'new_value': self._max_workers})

    def _create_and_register_agent(self, template_name: str, *args, **kwargs) -> Agent:
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

        if self._worker_count.get() >= self._max_workers:
            self._notify('WORKER_CAP_REACHED', {'max_workers': self._max_workers})
            raise RuntimeError(f"Cannot create agent. Worker cap of {self._max_workers} reached.")

        try:
            kwargs["command_center"] = self
            agent = self._builder.create_agent(template_name, *args, **kwargs)
            self._register_agent(agent)
            return agent
        except Exception as e:
            raise RuntimeError(f"Agent creation failed: {str(e)}") from e

    def register_template(self, name: str, factory_fn: Union[Callable[..., Agent], Pack]):
        """
        Registers a new agent creation template.

        Args:
            name (str): Symbolic name of the template.
            factory_fn (Callable | Pack): Factory function or Pack object used to construct the agent.
        """
        if self._disposed:
            raise RuntimeError("Cannot register templates after CommandCenter is disposed.")
        self._builder.register_template(name, factory_fn)
        self._notify('TEMPLATE_REGISTERED', {'template_name': name})

    def unregister_template(self, name: str) -> bool:
        """
        Removes a previously registered agent template.

        Args:
            name (str): Symbolic name of the template to remove.

        Returns:
            bool: True if removed successfully, False if not found.
        """
        self._check_disposed()
        was_unregistered = self._builder.unregister_template(name)
        if was_unregistered:
            self._notify('TEMPLATE_UNREGISTERED', {'template_name': name})
        return was_unregistered

    def list_templates(self) -> List[str]:
        """
        Lists all registered agent templates.

        Returns:
            List[str]: A list of symbolic template names.
        """
        self._check_disposed()
        return self._builder.list_templates()

    def get_active_agents(self) -> List[Agent]:
        """
        Returns all currently active agents managed by this CommandCenter.

        Returns:
            List[Agent]: A list of active agent instances.
        """
        if self._disposed:
            return []
        return list(self._active_agents.values())

    def get_agent_by_id(self, factory_id: str) -> Optional[Agent]:
        """
        Retrieves an agent by its factory-assigned ID.

        Args:
            factory_id (str): The ULID or unique string used to identify the agent.

        Returns:
            Optional[Agent]: The matching agent, or None if not found or disposed.
        """
        if self._disposed or not factory_id:
            return None
        return self._active_agents.get(factory_id)
#endregion Agent Management
#region SignalController Management
    def add_signal_controller(self, name: str, controller: Optional[SignalController] = None) -> SignalController:
        """
        Adds a new SignalController to the CommandCenter's management. If an existing
        controller instance is not provided, a new one is created. This allows the
        CommandCenter to manage multiple, named communication buses.

        Args:
            name (str): A unique name to identify this SignalController.
            controller (Optional[SignalController]): An existing SignalController instance.
                                                     If None, a new one will be created.

        Returns:
            SignalController: The newly added or created SignalController instance.

        Raises:
            ValueError: If a SignalController with the same name already exists.
        """
        self._check_disposed()
        with self._lock:
            if name in self._signal_controllers:
                raise ValueError(f"A SignalController with the name '{name}' already exists.")
            new_controller = controller or SignalController(logger=self._logger)
            self._signal_controllers[name] = new_controller
            self._logger.info(f"Added SignalController: '{name}'")
            self._notify('SIGNAL_CONTROLLER_ADDED', {'controller_name': name})
            return new_controller

    def remove_signal_controller(self, name: str, dispose: bool = True) -> bool:
        """
        Removes a SignalController from the CommandCenter.

        Args:
            name (str): The name of the SignalController to remove.
            dispose (bool): If True, the SignalController's dispose() method will be
                            called upon removal. Defaults to True.

        Returns:
            bool: True if the controller was found and removed, False otherwise.
        """
        self._check_disposed()
        with self._lock:
            if name not in self._signal_controllers:
                self._logger.warning(f"Attempted to remove non-existent SignalController: '{name}'")
                return False
            controller = self._signal_controllers.pop(name)
            self._logger.info(f"Removed SignalController: '{name}'")
            self._notify('SIGNAL_CONTROLLER_REMOVED', {'controller_name': name})
            if dispose and controller:
                try:
                    controller.dispose()
                except Exception as e:
                    self._logger.error(f"Error disposing removed SignalController '{name}': {e}", exc_info=True)
            return True

    def get_signal_controller(self, name: str) -> Optional[SignalController]:
        """
        Retrieves a managed SignalController by its name.

        Args:
            name (str): The name of the SignalController to retrieve.

        Returns:
            Optional[SignalController]: The SignalController instance, or None if not found.
        """
        self._check_disposed()
        return self._signal_controllers.get(name)

    def list_signal_controllers(self) -> List[str]:
        """
        Lists the names of all managed SignalControllers.

        Returns:
            List[str]: A list of SignalController names.
        """
        self._check_disposed()
        if not self._signal_controllers:
            return []
        return list(self._signal_controllers.keys())

    def invoke_on_controller(self, controller_name: str, object_id: str, command: str, *args, **kwargs) -> Any:
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
        controller = self.get_signal_controller(controller_name)
        if not controller:
            raise ValueError(f"No SignalController with the name '{controller_name}' is managed by this CommandCenter.")
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
