import threading
import warnings
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
    --------------
    A central factory and management unit for creating and executing agent threads
    under a unified worker cap.
    ...
    """

    def __init__(self, max_workers: int = 8):
        """
        Initializes the CommandCenter.

        Args:
            max_workers (int): Maximum number of concurrent agents allowed to exist,
                               regardless of creation method.
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
        Fully disposes the CommandCenter and all tracked active agents.
        This is an idempotent operation.
        """
        with self._lock:
            if self._disposed:
                return
            self._disposed = True

            for agent in list(self._active_agents.values()):
                if hasattr(agent, "dispose") and callable(agent.dispose):
                    agent.dispose()

            self._active_agents.clear()
            self._active_agents = None

            if self._builder:
                self._builder.dispose()
                self._builder = None

    def shutdown(self):
        """A convenience alias for the .dispose() method."""
        self.dispose()

    def _create_and_register_agent(self, template_name: str, *args, **kwargs) -> Agent:
        """
        Internal factory to create, register, and cap an agent.
        It handles incrementing and checking the worker cap.
        """
        if self._disposed:
            raise RuntimeError("CommandCenter is disposed.")

        if self._worker_count.increment() > self._max_workers:
            self._worker_count.decrement()
            raise RuntimeError(f"Cannot create agent. Worker cap of {self._max_workers} reached.")

        try:
            kwargs['command_center'] = self
            agent = self._builder.create_agent(template_name, *args, **kwargs)
            self._register_agent(agent)
            return agent
        except Exception:
            self._worker_count.decrement()
            raise

    def create_agent(self, template_name: str, define_home: Union[Callable[[...], None], Pack] = None,
                     target: Union[Callable[[...], None], Pack] = None, *args, **kwargs) -> Agent:
        """
        Creates a single, dedicated agent, respecting the global worker cap.

        This method returns the agent instance to you for manual control. The agent's
        native `run()` method will be the execution entry point.

        Args:
            template_name (str): The name of the template to use.
            target (Callable | Pack, optional): The task to execute in the background.
            define_home (Callable | Pack, optional): The target function that will become
                the agent's main event loop.
            *args, **kwargs: Runtime arguments for the template's factory.

        Returns:
            Agent: A newly created, configured agent instance.
        """
        agent = self._create_and_register_agent(template_name, *args, **kwargs)
        if target and (isinstance(target, Callable) or isinstance(target, Pack)):
            target = Pack.bundle(target)
            agent.set_home(target)
        # This wrapper contains our cleanup logic.
        def home_with_cleanup():
            try:
                # Execute the original home function if it was provided.
                if define_home:
                    # Unpack if necessary
                    (Pack.bundle(define_home))()
            finally:
                self._unregister_agent(agent)
                self._worker_count.decrement()

        # We set our wrapper as the agent's event loop.
        # The agent's own .run() method will call this.
        agent.set_home(home_with_cleanup)

        return agent

    def create_agents(self, count: int, template_name: str, target: Union[Callable[[...], None], Pack] = None,
                      define_home: Union[Callable[[...], None], Pack] = None, *args, **kwargs) -> ConcurrentList[Agent]:
        """
        Creates a batch of agent threads, respecting the global worker cap.
        ...
        """
        new_agents = ConcurrentList()
        for i in range(count):
            try:
                agent = self.create_agent(template_name, define_home=define_home, target=target, *args, **kwargs)
                new_agents.append(agent)
            except RuntimeError:
                warnings.warn(
                    f"Worker cap reached. Created {i} of {count} requested agents.",
                    UserWarning
                )
                break
        return new_agents

    def submit(self, target: Union[Callable[[...], Any], Pack], template_name: str = "default", *args, **kwargs) -> None:
        """
        Submits a fire-and-forget task on a new agent, respecting the global worker cap.

        This method creates an agent, sets its task, starts it immediately, and returns nothing.
        The agent's native `run()` method is the execution entry point.

        Args:
            target (Callable | Pack): The task to execute in the background.
            template_name (str, optional): The template for the agent.
            *args, **kwargs: Runtime arguments for the template factory.
        """
        # We now use create_agent to handle creation and capping.
        # We pass the user's target in the 'define_home' parameter.
        agent = self.create_agent(template_name, target=target, *args, **kwargs)
        agent.start()

    # --- Other methods remain the same ---

    def get_active_agents(self) -> List[Agent]:
        if self._disposed: return []
        return list(self._active_agents.values())

    def get_agent_by_id(self, factory_id: str) -> Optional[Agent]:
        if self._disposed or not factory_id: return None
        return self._active_agents.get(factory_id)

    def _register_agent(self, agent: Agent):
        if self._disposed or not agent: return
        self._active_agents[agent.factory_id] = agent

    def _unregister_agent(self, agent: Agent):
        if self._disposed or not agent: return
        self._active_agents.pop(agent.factory_id, None)

    def register_template(self, name: str, factory_fn: Callable[..., Agent], *args, **kwargs):
        self._builder.register_template(name, factory_fn, *args, **kwargs)

    def unregister_template(self, name: str) -> bool:
        return self._builder.unregister_template(name)

    def list_templates(self) -> List[str]:
        return self._builder.list_templates()