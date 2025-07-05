import threading, warnings, logging, ulid
from typing import Optional, List, Callable, Any, Union, Dict
from thread_factory.agent.identity.agent_builder import AgentBuilder
from thread_factory.agent.identity.types.agent import Agent
from thread_factory.synchronization import SignalController
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
        Initializes the CommandCenter.

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
#endregion Destructor

#region Controller Contract
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
        if not isinstance(amount, int) or amount < 1:
            raise ValueError("Amount must be a positive integer.")
        with self._lock:
            if self._worker_count > self._max_workers - amount:
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

        if self._worker_count >= self._max_workers:
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
        return self._signal_controllers.get(name)

    def list_signal_controllers(self) -> List[str]:
        """
        Lists the names of all managed SignalControllers.

        Returns:
            List[str]: A list of SignalController names.
        """
        if not self._signal_controllers:
            return []
        return list(self._signal_controllers.keys())
#endregion SignalController Management
#endregion CommandCenter
