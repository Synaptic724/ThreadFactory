import threading
from typing import Optional, List, Callable, Any, Union
from concurrent.futures import ThreadPoolExecutor, Future
from synchronization.primitives.test_signal_latch import IDisposable
from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.agent.identity.activator import ActivatedAgent
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.agent.thread_pool import HelpRequest
from thread_factory.utils.coordination.package import Pack


class CommandCenter(IDisposable):
    """
    CommandCenter
    --------------
    A central management unit for agentic thread creation, transformation, and execution.

    This class serves as the gateway to the agentic threading model in ThreadFactory.
    It provides utilities to spawn agent threads, convert threads into agents,
    and dispatch work using a fire-and-forget thread pool mechanism.

    While a dynamic agent pool is planned for the future, the current implementation wraps
    a `ThreadPoolExecutor` to support basic concurrent execution via `.submit()`.

    Core Responsibilities:
    -----------------------
    - Create new agent threads (`create_agents`)
    - Convert threads to agents (`transform_thread`, `transform_current_thread`)
    - Execute functions as agents in the background (`submit`)
    - Track live agents (`_active_agents`)
    - Manage agent lifecycle and cleanup (`shutdown`, `dispose`)
    """

    def __init__(self, max_workers: int = 8):
        """
        Initializes the CommandCenter with an internal thread pool executor and an
        agent tracking dictionary.

        Args:
            max_workers (int): Maximum number of threads allowed in the background pool.
                               This does not affect manually spawned agents.
        """
        super().__init__()
        self._active_agents: ConcurrentDict[str, ActivatedAgent] = ConcurrentDict()
        self.agent_pool: Optional[Any] = None  # Placeholder for future pooled agent support
        self._offload_pool = ThreadPoolExecutor(max_workers=max_workers)
        self._lock = threading.RLock()

    def dispose(self):
        """
        Fully disposes the CommandCenter and all associated agents.

        This method:
        - Disposes every tracked ActivatedAgent (if it supports `dispose`)
        - Clears and nullifies the agent registry
        - Shuts down and nullifies the background thread pool
        - Resets agent pool and internal fields to prevent memory retention

        Safe to call multiple times (idempotent).
        """
        with self._lock:
            if self._disposed:
                return
            self._disposed = True
            self._active_agents.freeze()

            for agent in list(self._active_agents.values()):
                if hasattr(agent, "dispose"):
                    try:
                        agent.dispose()
                    except Exception:
                        pass

            try:
                self._active_agents.unfreeze()
                self._active_agents.clear()
            except Exception:
                pass

            self._active_agents = None
            self.agent_pool = None

            try:
                self._offload_pool.shutdown(wait=True)
            except Exception:
                pass
            self._offload_pool = None

    def shutdown(self):
        """
        Alias for `.dispose()`. Gracefully disposes all agents and tears down resources.
        """
        self.dispose()

    def get_active_agents(self) -> List[ActivatedAgent]:
        """
        Returns a list of all currently tracked agents.
        It's a snapshot of the active agents at the time of the call.
        """
        with self._lock:
            return list(self._active_agents.values())

    def _register_agent(self, thread: threading.Thread, factory_id: Optional[str] = None):
        """
        Registers a thread as an ActivatedAgent and stores it in the active agent registry.

        Args:
            thread (threading.Thread): The thread to convert and register.
            factory_id (Optional[str]): Optional agent ID to assign for identification.

        Raises:
            TypeError: If the resulting thread is not an ActivatedAgent.
        """
        with self._lock:
            agent = ActivatedAgent(thread, factory_id)
            if not isinstance(agent, ActivatedAgent):
                raise TypeError("Only ActivatedAgent instances are permitted in CommandCenter.")
            self._active_agents[agent.factory_id] = agent

    def _unregister_agent(self, thread: threading.Thread):
        """
        Removes a thread from the active agent registry.

        Args:
            thread (threading.Thread): The agent thread to unregister.
        """
        fid = getattr(thread, "factory_id", None)
        if fid:
            with self._lock:
                self._active_agents.pop(fid, None)

    def _create_agent_wrapper(self, user_target: Callable[[], Any]) -> Callable[[], None]:
        """
        Internal wrapper to execute a function as an agent.

        Ensures agent conversion, execution, unregistration, and disposal.

        Args:
            user_target (Callable): User function to run inside the agent.

        Returns:
            Callable[[], None]: Safe function for thread execution.
        """
        def _execute_and_dispose():
            thread = threading.current_thread()
            if not ActivatedAgent.is_agent(thread):
                agent = ActivatedAgent(thread)
                with self._lock:
                    self._active_agents[agent.factory_id] = agent
            try:
                user_target()
            finally:
                self._unregister_agent(thread)
                if hasattr(thread, "dispose"):
                    thread.dispose()

        return _execute_and_dispose

    def create_agents(
        self,
        count: int,
        target: Union[Callable[..., None], Pack],
        name_prefix: str = "Agent"
    ) -> ConcurrentList[ActivatedAgent]:
        """
        Creates a number of ActivatedAgent threads using a wrapped user target.

        These threads are not started automatically and are registered for lifecycle tracking.

        Args:
            count (int): Number of agents to create.
            target (Callable): The task function to run in each agent.
            name_prefix (str): Prefix for thread names.

        Returns:
            ConcurrentList[ActivatedAgent]: List of initialized agent threads.
        """
        if target:
            Pack.bundle(target)

        new_agents = ConcurrentList()
        for i in range(count):
            wrapped_target = self._create_agent_wrapper(target)
            thread = threading.Thread(target=wrapped_target, name=f"{name_prefix}-{i}")
            agent = ActivatedAgent(thread)
            with self._lock:
                self._active_agents[agent.factory_id] = agent
            new_agents.append(agent)
        return new_agents

    def submit(self, target: Optional[Union[Callable[[], Any], Pack]]) -> Future:
        """
        Submit a callable to the internal agent-compatible thread pool.

        This promotes the executing thread to an ActivatedAgent automatically.

        Args:
            target (Callable | Pack): Task to execute.

        Returns:
            Future: A Future tracking the background task.
        """
        if target:
            Pack.bundle(target)

        def agent_wrapper():
            thread = threading.current_thread()
            if not ActivatedAgent.is_agent(thread):
                agent = ActivatedAgent(thread)
                with self._lock:
                    self._active_agents[agent.factory_id] = agent
            try:
                return target()
            finally:
                self._unregister_agent(thread)
                if hasattr(thread, "dispose"):
                    thread.dispose()

        with self._lock:
            return self._offload_pool.submit(agent_wrapper)

    def request_help(self, request: HelpRequest):
        """
        Issues a HelpRequest to the dynamic agent pool.

        Currently not implemented. Will eventually route thread-group requests
        to the main agent dispatcher for complex group execution.

        Args:
            request (HelpRequest): A cooperative execution request.

        Raises:
            NotImplementedError: Always, until agent_pool logic is implemented.
            RuntimeError: If agent_pool is unset.
        """
        if self.agent_pool:
            raise NotImplementedError("Agent pool functionality is not yet implemented.")
        else:
            raise RuntimeError("Cannot request help, the agent_pool is not configured.")

    def transform_current_thread(self, factory_id: Optional[str] = None) -> bool:
        """
        Transforms the current thread into an ActivatedAgent.

        Args:
            factory_id (Optional[str]): ID to assign to the current thread.

        Returns:
            bool: True if transformation succeeded, False if already an agent.

        Raises:
            RuntimeError: If called from the main thread.
        """
        current = threading.current_thread()
        if current is threading.main_thread():
            raise RuntimeError("Main thread cannot be transformed into an agent.")
        return self.transform_thread(current, factory_id)

    def transform_thread(
        self,
        thread: threading.Thread,
        factory_id: Optional[str] = None,
        raise_on_main: bool = True
    ) -> bool:
        """
        Transforms a thread into an ActivatedAgent if not already one.

        Args:
            thread (threading.Thread): Target thread to transform.
            factory_id (Optional[str]): Optional ID to assign to the agent.
            raise_on_main (bool): If True, disallows transforming the main thread.

        Returns:
            bool: True if transformation occurred, False if already an agent.

        Raises:
            RuntimeError: If attempting to transform the main thread and raise_on_main is True.
            TypeError: If transformation failed or resulted in a non-agent.
        """
        if raise_on_main and thread is threading.main_thread():
            raise RuntimeError("Main thread cannot be transformed into an agent.")
        if ActivatedAgent.is_agent(thread):
            return False
        agent = ActivatedAgent(thread, factory_id)
        if not isinstance(agent, ActivatedAgent):
            raise TypeError("Transformation did not yield a valid ActivatedAgent.")
        with self._lock:
            self._active_agents[agent.factory_id] = agent
        return True

    def activate_agents(self, threads: List[threading.Thread]) -> int:
        """
        Batch transforms a list of threads into ActivatedAgents.

        Args:
            threads (List[threading.Thread]): Threads to convert.

        Returns:
            int: Number of successfully transformed threads.
        """
        count = 0
        for thread in threads:
            if self.transform_thread(thread, raise_on_main=False):
                count += 1
        return count

    def _transform_logic(self, thread: threading.Thread, factory_id: Optional[str]) -> bool:
        """
        Internal helper that applies transformation logic.

        Args:
            thread (threading.Thread): Target thread.
            factory_id (Optional[str]): Optional agent ID.

        Returns:
            bool: True if transformation occurred, False otherwise.
        """
        if ActivatedAgent.is_agent(thread):
            return False
        self._register_agent(thread, factory_id)
        return True


CC = CommandCenter