import threading, warnings
from typing import Optional, List, Callable, Any, Union
from thread_factory.agent.identity.agent_builder import AgentBuilder
from thread_factory.agent.identity.types.agent import Agent
from thread_factory.utils.coordination.package import Pack
from thread_factory.utils.interfaces.disposable import IDisposable
from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.concurrency.sync_types.sync_int import SyncInt


class CommandCenter(IDisposable):
    """
    CommandCenter
    ----------------
    A central orchestration unit responsible for managing agent thread lifecycles,
    enforcing global worker limits, and creating agents from predefined templates.

    The CommandCenter allows for:
    - Creation of agent threads from registered templates
    - Lifecycle management (disposal and deregistration)
    - Batch creation, fire-and-forget task launching, and custom behavior hooks
    """

    def __init__(self, max_workers: int = 8):
        """
        Initializes the CommandCenter with a worker cap and internal registries.

        Args:
            max_workers (int): Maximum number of concurrent agents allowed to exist.
        """
        super().__init__()
        if max_workers < 1 or not isinstance(max_workers, int):
            raise ValueError("max_workers must be a positive integer.")

        self._lock = threading.RLock()
        self._active_agents: ConcurrentDict[str, Agent] = ConcurrentDict()
        self._builder = AgentBuilder()
        self._worker_count = SyncInt(0)
        self._max_workers = max_workers

    def dispose(self):
        """
        Disposes the CommandCenter and all agents it created and registered.

        This is a terminal and idempotent operation. All agents are disposed if they support `.dispose()`,
        and the internal registries are cleared.
        """
        with self._lock:
            if self._disposed:
                return
            self._disposed = True

            if self._active_agents:
                for agent in list(self._active_agents.values()):
                    try:
                        if hasattr(agent, "dispose") and callable(agent.dispose):
                            agent.dispose()
                        self._worker_count.decrement()
                    except Exception:
                        pass
                self._active_agents.clear()
                self._active_agents = None

            try:
                self._builder.dispose()
            except Exception:
                pass

    def shutdown(self):
        """
        Alias for `.dispose()`.

        Provides semantic clarity when intentionally terminating the CommandCenter.
        """
        self.dispose()


    def _register_agent(self, agent: Agent):
        """
        Internal helper to register an agent in the active list.

        Args:
            agent (Agent): The agent to register.
        """
        if not self._disposed and agent:
            with self._lock:
                self._worker_count.increment()
                self._active_agents[agent.factory_id] = agent

    def _unregister_agent(self, agent: Agent):
        """
        Internal helper to unregister and forget an agent.

        Args:
            agent (Agent): The agent to remove from tracking.
        """
        if not self._disposed and agent:
            with self._lock:
                self._active_agents.pop(agent.factory_id, None)
                self._worker_count.decrement()

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
            if self._worker_count.value > self._max_workers - amount:
                raise RuntimeError("Cannot decrease below current active worker count.")
            self._max_workers -= amount

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
            raise RuntimeError(f"Cannot create agent. Worker cap of {self._max_workers} reached.")

        try:
            # First, try to create the agent without incrementing worker count
            kwargs["command_center"] = self
            agent = self._builder.create_agent(template_name, *args, **kwargs)
            self._register_agent(agent)
            return agent
        except Exception as e:
            raise RuntimeError(f"Agent creation failed: {str(e)}") from e

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

    def unregister_template(self, name: str) -> bool:
        """
        Removes a previously registered agent template.

        Args:
            name (str): Symbolic name of the template to remove.

        Returns:
            bool: True if removed successfully, False if not found.
        """
        return self._builder.unregister_template(name)

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

CC = CommandCenter