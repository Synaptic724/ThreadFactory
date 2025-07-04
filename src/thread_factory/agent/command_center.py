import threading
from typing import Optional, List, Callable, Any, Union
from concurrent.futures import ThreadPoolExecutor, Future
from synchronization.primitives.test_signal_latch import IDisposable
from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.agent.activator import ActivatedAgent
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
        self._active_agents: ConcurrentDict[str, threading.Thread] = ConcurrentDict()
        self.agent_pool: Optional[Any] = None  # Placeholder for future pooled agent support
        self._offload_pool = ThreadPoolExecutor(max_workers=max_workers)

    def _register_agent(self, thread: threading.Thread, factory_id: Optional[str] = None):
        """
        Registers a thread as an agent using the AgentActivator.

        Args:
            thread (threading.Thread): The thread to convert and register.
            factory_id (Optional[str]): Optional ID to assign for agent tracking.
        """
        AgentActivator(thread, factory_id)
        self._active_agents[thread.factory_id] = thread

    def _unregister_agent(self, thread: threading.Thread):
        """
        Removes a thread from the active agent registry.

        Args:
            thread (threading.Thread): The agent thread to unregister.
        """
        fid = getattr(thread, "factory_id", None)
        if fid:
            self._active_agents.pop(fid, None)

    def _create_agent_wrapper(self, user_target: Callable[[], Any]) -> Callable[[], None]:
        """
        Internal helper that wraps a user function with agent lifecycle logic.

        Ensures that:
        - The thread is promoted to an agent (if not already)
        - The user task executes
        - The agent is removed and disposed after execution

        Args:
            user_target (Callable): The function to be executed by the agent.

        Returns:
            Callable: A safe wrapper with agent transformation and teardown logic.
        """
        def _execute_and_dispose():
            try:
                thread = threading.current_thread()
                if not AgentActivator.is_agent(thread):
                    self._register_agent(thread)
                user_target()
            finally:
                self._unregister_agent(threading.current_thread())
                if hasattr(threading.current_thread(), 'dispose'):
                    threading.current_thread().dispose()
        return _execute_and_dispose

    def create_agents(self, count: int, target: Callable[[], Any], name_prefix: str = "Agent") -> ConcurrentList[threading.Thread]:
        """
        Creates multiple agent threads from a shared target function.

        Each agent is wrapped with disposal logic and tracked internally.
        Threads are returned in a non-started state.

        Args:
            count (int): Number of agent threads to create.
            target (Callable): Function to run inside each agent.
            name_prefix (str): Base name used to name the threads.

        Returns:
            List[threading.Thread]: List of initialized (but not started) agent threads.
        """
        if target:
            Pack.bundle(target)

        new_threads: ConcurrentList[threading.Thread] = ConcurrentList()
        for i in range(count):
            wrapped_target = self._create_agent_wrapper(target)
            thread = threading.Thread(target=wrapped_target, name=f"{name_prefix}-{i}")
            self._register_agent(thread)
            new_threads.append(thread)
        return new_threads

    def submit(self, callable: Optional[Union[Callable[[], Any], Pack]]) -> Future:
        """
        Offloads a callable to the internal thread pool for background execution.

        This allows simple fire-and-forget task scheduling. The executing thread
        is automatically promoted to agent status and cleaned up afterward.

        Args:
            callable (Callable or Pack): The task to run in the background.

        Returns:
            Future: A concurrent Future tracking the task’s result or exception.
        """
        if callable:
            Pack.bundle(callable)

        def agent_wrapper():
            thread = threading.current_thread()
            if not AgentActivator.is_agent(thread):
                self._register_agent(thread)
            try:
                return callable()
            finally:
                self._unregister_agent(thread)
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
        Converts the calling thread into an agent thread, if not already.

        Useful for embedding agent behavior into existing threads.

        Args:
            factory_id (Optional[str]): Optional agent ID to assign.

        Returns:
            bool: True if transformation occurred, False if already an agent.

        Raises:
            RuntimeError: If called from the main thread.
        """
        thread = threading.current_thread()
        if thread is threading.main_thread():
            raise RuntimeError("The main thread cannot be transformed into an agent.")
        return self._transform_logic(thread, factory_id)

    def transform_thread(self, thread: threading.Thread, factory_id: Optional[str] = None, raise_on_main: bool = True) -> bool:
        """
        Converts any thread into an agent thread, if not already.

        Args:
            thread (threading.Thread): Target thread.
            factory_id (Optional[str]): Optional ID to assign.
            raise_on_main (bool): Whether to disallow main-thread transformation.

        Returns:
            bool: True if transformation succeeded, False if already an agent.

        Raises:
            RuntimeError: If main thread is passed and raise_on_main is True.
        """
        if raise_on_main and thread is threading.main_thread():
            raise RuntimeError("The main thread cannot be transformed into an agent.")
        return self._transform_logic(thread, factory_id)

    def activate_agents(self, threads: List[threading.Thread]) -> int:
        """
        Bulk-transforms a group of threads into agents.

        Args:
            threads (List[threading.Thread]): Target threads.

        Returns:
            int: Count of successfully activated agents.
        """
        activated_count = 0
        for thread in threads:
            if self.transform_thread(thread, raise_on_main=False):
                activated_count += 1
        return activated_count

    def shutdown(self, wait: bool = True):
        """
        Gracefully shuts down the CommandCenter, stopping the thread pool and cleaning up agents.

        All active agents will be disposed if they support `dispose()` and removed from the registry.

        Args:
            wait (bool): If True, waits for thread pool tasks to complete.
        """
        if self._disposed:
            return
        self._disposed = True

        # Dispose all known agents
        for agent in list(self._active_agents.values()):
            if hasattr(agent, "dispose"):
                try:
                    agent.dispose()
                except Exception:
                    pass

        self._active_agents.clear()
        self._offload_pool.shutdown(wait=wait)

    def dispose(self):
        """
        Public alias for `shutdown()` with `wait=True`.

        This makes the class compatible with systems that use IDisposable or cleanup hooks.
        """
        self.shutdown(wait=True)

    def _transform_logic(self, thread: threading.Thread, factory_id: Optional[str]) -> bool:
        """
        Internal helper that applies transformation logic.

        Args:
            thread (threading.Thread): Target thread.
            factory_id (Optional[str]): Optional agent ID.

        Returns:
            bool: True if transformation occurred, False otherwise.
        """
        if AgentActivator.is_agent(thread):
            return False
        self._register_agent(thread, factory_id)
        return True

CC = CommandCenter