import threading
from typing import Optional, List, Callable, Any
from concurrent.futures import ThreadPoolExecutor, Future
from thread_factory.agent.activator import AgentActivator
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.agent.thread_pool import HelpRequest
from thread_factory.utils.coordination.package import Pack


class CommandCenter:
    """
    CommandCenter
    --------------
    A central management unit for agentic thread creation, transformation, and execution.

    This object is responsible for spawning agent threads, wrapping them with lifecycle
    logic, and offloading tasks to a local thread pool. It serves both as an entry point
    for quick fire-and-forget execution (`submit`) and as a full system for building
    deeply integrated agent-based threading structures.
    """

    def __init__(self, max_workers: int = 8):
        """
        Initializes the CommandCenter, including the internal offload pool and
        agent tracking dictionary.

        Args:
            max_workers (int): The number of threads allowed in the offload pool.
        """
        self._active_agents: ConcurrentDict[str, threading.Thread] = ConcurrentDict()
        self.agent_pool: Optional[Any] = None  # Placeholder for future dynamic pool
        self._offload_pool = ThreadPoolExecutor(max_workers=max_workers)

    def _create_agent_wrapper(self, user_target: Callable[[], Any]) -> Callable[[], None]:
        """
        Wraps a user's function to ensure the agent disposes itself after execution.

        Args:
            user_target (Callable): The original user function to run inside the agent.

        Returns:
            Callable: A wrapped function that executes the user's task and performs
                      thread disposal after completion.
        """
        def _execute_and_dispose():
            try:
                user_target()
            finally:
                thread_instance = threading.current_thread()
                if AgentActivator.is_agent(thread_instance) and hasattr(thread_instance, 'dispose'):
                    thread_instance.dispose()
        return _execute_and_dispose

    def create_agents(self, count: int, target: Callable[[], Any], name_prefix: str = "Agent") -> List[threading.Thread]:
        """
        Creates a number of agent threads from a given target function.

        Each thread is patched with agentic features and scheduled for disposal after execution.

        Args:
            count (int): Number of threads to create.
            target (Callable): The user function each thread should run.
            name_prefix (str): Prefix used to name the threads.

        Returns:
            List[threading.Thread]: A list of newly created (but not yet started) threads.
        """
        new_threads: List[threading.Thread] = []
        for i in range(count):
            wrapped_target = self._create_agent_wrapper(target)
            thread = threading.Thread(target=wrapped_target, name=f"{name_prefix}-{i}")
            AgentActivator(thread)
            self._active_agents[thread.factory_id] = thread
            new_threads.append(thread)
        return new_threads

    def submit(self, callable: Callable[[], Any], factory_id: Optional[str] = None) -> Future:
        """
        Submits a task to the internal offload pool for execution on a background thread.

        The executing thread is automatically transformed into an agent prior to running.

        Args:
            callable (Callable): The task to run.
            factory_id (Optional[str]): Optional agent ID to assign to the executing thread.

        Returns:
            Future: A concurrent.futures.Future representing the asynchronous execution.
        """
        def agent_wrapper():
            current = threading.current_thread()
            if not AgentActivator.is_agent(current):
                AgentActivator(current, factory_id)
            return callable()

        return self._offload_pool.submit(agent_wrapper)

    def request_help(self, request: HelpRequest):
        """
        Issues a HelpRequest to the dynamic agent pool.

        Args:
            request (HelpRequest): A HelpRequest object detailing the required agent behavior.

        Raises:
            NotImplementedError: If agent pool logic hasn't been implemented yet.
            RuntimeError: If the agent pool hasn't been configured.
        """
        if self.agent_pool:
            raise NotImplementedError("Agent pool functionality is not yet implemented.")
        else:
            raise RuntimeError("Cannot request help, the agent_pool is not configured.")

    def transform_current_thread(self, factory_id: Optional[str] = None) -> bool:
        """
        Transforms the calling thread into an agentic thread.

        Args:
            factory_id (Optional[str]): An optional ID to assign to the agent.

        Returns:
            bool: True if the thread was transformed, False if it was already an agent.

        Raises:
            RuntimeError: If called from the main application thread.
        """
        thread = threading.current_thread()
        if thread is threading.main_thread():
            raise RuntimeError("The main thread cannot be transformed into an agent.")
        return CommandCenter._transform_logic(thread, factory_id)

    def transform_thread(self, thread: threading.Thread, factory_id: Optional[str] = None, raise_on_main: bool = True) -> bool:
        """
        Transforms a given thread into an agentic thread.

        Args:
            thread (threading.Thread): The thread to transform.
            factory_id (Optional[str]): An optional ID for the agent.
            raise_on_main (bool): If True, raises an error when targeting the main thread.

        Returns:
            bool: True if transformation occurred, False if already an agent.

        Raises:
            RuntimeError: If `raise_on_main` is True and the thread is the main thread.
        """
        if raise_on_main and thread is threading.main_thread():
            raise RuntimeError("The main thread cannot be transformed into an agent.")
        return CommandCenter._transform_logic(thread, factory_id)

    def activate_agents(self, threads: List[threading.Thread]) -> int:
        """
        Bulk transforms threads into agents.

        Args:
            threads (List[threading.Thread]): The threads to activate.

        Returns:
            int: The number of threads successfully transformed.
        """
        activated_count = 0
        for thread in threads:
            if self.transform_thread(thread, raise_on_main=False):
                activated_count += 1
        return activated_count

    def shutdown(self, wait: bool = True):
        """
        Gracefully shuts down the internal offload pool.

        Args:
            wait (bool): If True, waits for all running tasks to complete before returning.
        """
        self._offload_pool.shutdown(wait=wait)

    @staticmethod
    def _transform_logic(thread: threading.Thread, factory_id: Optional[str]) -> bool:
        """
        Internal helper that applies agent transformation logic.

        Args:
            thread (threading.Thread): The thread to transform.
            factory_id (Optional[str]): Optional agent ID to assign.

        Returns:
            bool: True if transformation occurred, False otherwise.
        """
        if AgentActivator.is_agent(thread):
            return False
        AgentActivator(thread, factory_id)
        return True

CC = CommandCenter