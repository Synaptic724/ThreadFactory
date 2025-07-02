import threading
from typing import Optional, List, Callable, Any
from thread_factory.agent.activator import AgentActivator
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.agent_thread_pool import HelpRequest  # Assuming HelpRequest for placeholder


class CommandCenter:
    """
    A central factory for creating, managing, and binding agentic behaviors to threads.

    This toolkit operates on the principle of decoupling an agent's capabilities (its
    tools, memory, and tasks) from its execution context (the thread). It allows you
    to take any standard `threading.Thread` and dynamically "dress" it with
    sophisticated features, or to create pre-configured agentic threads from scratch.
    """

    def __init__(self):
        """
        Initializes the CommandCenter, setting up tracking for active agents
        and a placeholder for a future dynamic agent pool.
        """
        # Tracks activated threads, keyed by their assigned factory_id.
        self._active_agents: ConcurrentDict[str, threading.Thread] = ConcurrentDict()

        # Placeholder for a future dynamic thread pool implementation.
        self.agent_pool: Optional[Any] = None

    def _create_agent_wrapper(self, user_target: Callable[[], Any]) -> Callable[[], None]:
        """
        Creates a wrapper that executes the user's target function and ensures
        the agent's resources are disposed of properly afterward.

        Args:
            user_target (Callable[[], Any]): The original function the user wants to run.

        Returns:
            Callable[[], None]: The wrapped function to be used as the thread's target.
        """

        def _execute_and_dispose():
            try:
                # Execute the user's original code.
                user_target()
            finally:
                # After the target completes or fails, clean up the agent.
                thread_instance = threading.current_thread()
                # The thread was patched, so it has a `dispose` method.
                if AgentActivator.is_agent(thread_instance) and hasattr(thread_instance, 'dispose'):
                    thread_instance.dispose()

        return _execute_and_dispose

    def create_agents(
            self,
            count: int,
            target: Callable[[], Any],
            name_prefix: str = "Agent"
    ) -> List[threading.Thread]:
        """
        Creates standard threads, dynamically dresses them as agents, and returns them.

        Each thread is configured to automatically clean up its agentic resources
        (via dispose) after its target function finishes execution.

        Args:
            count (int): The number of agent threads to create.
            target (Callable): The target function for the threads to execute.
            name_prefix (str): A prefix for naming the created agent threads.

        Returns:
            List[threading.Thread]: A list of the newly created (but not started)
                                    threads, now dressed as agents.
        """
        new_threads: List[threading.Thread] = []
        for i in range(count):
            # 1. Create a wrapper to run the user's code and then auto-dispose.
            wrapped_target = self._create_agent_wrapper(target)

            # 2. Create a standard thread instance with the wrapped target.
            thread = threading.Thread(
                target=wrapped_target,
                name=f"{name_prefix}-{i}"
            )

            # 3. Dynamically "dress" the thread with agentic features *before* it starts.
            #    This patches the thread object with methods and a `factory_id`.
            AgentActivator(thread)

            # 4. Store the newly activated agent thread in our tracking dictionary.
            #    The thread object now has the .factory_id attribute patched onto it.
            self._active_agents[thread.factory_id] = thread
            new_threads.append(thread)

        return new_threads

    def request_help(self, request: HelpRequest):
        """
        (Placeholder) Issues a help request to the dynamic agent pool.

        Args:
            request (HelpRequest): The help request object detailing the work to be done.

        Raises:
            NotImplementedError: This feature is not yet implemented.
            RuntimeError: If the agent_pool is not configured.
        """
        if self.agent_pool:
            raise NotImplementedError("Agent pool functionality is not yet implemented.")
        else:
            raise RuntimeError("Cannot request help, the agent_pool is not configured.")

    def transform_current_thread(
            self,
            factory_id: Optional[str] = None
    ) -> bool:
        """
        Transforms the currently executing thread into a stateful agent.

        Args:
            factory_id (Optional[str]): A specific ID to assign to the agent.

        Returns:
            bool: True if the thread was successfully transformed, False if it
                  was already an agent.

        Raises:
            RuntimeError: If this method is called from the main application thread.
        """
        thread = threading.current_thread()
        if thread is threading.main_thread():
            raise RuntimeError("The main thread cannot be transformed into an agent.")

        return CommandCenter._transform_logic(thread, factory_id)

    def transform_thread(
            self,
            thread: threading.Thread,
            factory_id: Optional[str] = None,
            raise_on_main: bool = True
    ) -> bool:
        """
        Transforms a specific, provided thread into a stateful agent.

        Args:
            thread (threading.Thread): The thread instance to transform.
            factory_id (Optional[str]): A specific ID for the agent.
            raise_on_main (bool): If True, raises an error if the target is the main thread.

        Returns:
            bool: True if transformed, False if it was already an agent.

        Raises:
            RuntimeError: If `raise_on_main` is True and the target is the main thread.
        """
        if raise_on_main and thread is threading.main_thread():
            raise RuntimeError("The main thread cannot be transformed into an agent.")

        return CommandCenter._transform_logic(thread, factory_id)

    def activate_agents(
            self,
            threads: List[threading.Thread]
    ) -> int:
        """
        Activates a list of standard threads in bulk.

        Args:
            threads (List[threading.Thread]): A list of thread instances to activate.

        Returns:
            int: The number of threads that were newly activated.
        """
        activated_count = 0
        for thread in threads:
            if self.transform_thread(thread, raise_on_main=False):
                activated_count += 1
        return activated_count

    @staticmethod
    def _transform_logic(
            thread: threading.Thread,
            factory_id: Optional[str]
    ) -> bool:
        """
        Private static helper containing the core activation logic.

        Args:
            thread (threading.Thread): The thread to apply the logic to.
            factory_id (Optional[str]): The factory ID for the new agent.

        Returns:
            bool: True on successful activation, False otherwise.
        """
        if AgentActivator.is_agent(thread):
            return False

        AgentActivator(thread, factory_id)
        return True