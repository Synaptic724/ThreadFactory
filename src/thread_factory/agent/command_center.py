import threading
import ulid
from typing import Callable, Optional, Any, List, Dict
from thread_factory.agent.activity_controller import ActivityController
from thread_factory.agent.activator import AgentActivator


class AgentToolkit:
    """
    A central factory for creating and binding agentic behaviors to standard Python threads.

    This toolkit operates on the principle of decoupling an agent's capabilities (its
    tools, memory, and tasks) from its execution context (the thread). It allows you
    to take any standard `threading.Thread` and dynamically "dress" it with
    sophisticated features, turning it into a stateful, command-driven agent.
    """

    def transform_current_thread(
        self,
        factory_id: Optional[str] = None
    ) -> bool:
        """
        Transforms the currently executing thread into a stateful agent.

        This is the primary method to be called from *within* a thread's target
        function to make it agentic. It is idempotent and will raise an error
        if called from the main application thread.

        Args:
            factory_id (Optional[str]): A specific ID to assign to the agent.
                                        If None, a new unique ULID is generated.

        Returns:
            bool: True if the thread was successfully transformed, False if it
                  was already an agent.

        Raises:
            RuntimeError: If this method is called from the main application thread.
        """
        thread = threading.current_thread()
        if thread is threading.main_thread():
            raise RuntimeError("The main thread cannot be transformed into an agent.")

        # Call the helper as a static method on the class.
        return AgentToolkit._transform_logic(thread, factory_id)

    def transform_thread(
        self,
        thread: threading.Thread,
        factory_id: Optional[str] = None,
        raise_on_main: bool = True
    ) -> bool:
        """
        Transforms a specific, provided thread into a stateful agent.

        This method is intended to be called from an *external* manager or factory
        that holds a reference to the thread(s) it wishes to upgrade.

        Args:
            thread (threading.Thread): The thread instance to transform.
            factory_id (Optional[str]): A specific ID for the agent. If None, one is generated.
            raise_on_main (bool): If True, will raise an error if the target thread
                                  is the main thread. Defaults to True.

        Returns:
            bool: True if the thread was successfully transformed, False if it
                  was already an agent.

        Raises:
            RuntimeError: If `raise_on_main` is True and the target is the main thread.
        """
        if raise_on_main and thread is threading.main_thread():
            raise RuntimeError("The main thread cannot be transformed into an agent.")

        # Call the helper as a static method on the class.
        return AgentToolkit._transform_logic(thread, factory_id)

    def activate_agents(
        self,
        threads: List[threading.Thread]
    ) -> int:
        """
        Activates a list of standard threads in bulk.

        This method iterates through a list of threads and attempts to transform
        each one using `transform_thread`.

        Args:
            threads (List[threading.Thread]): A list of thread instances to activate.

        Returns:
            int: The number of threads that were newly activated.
        """
        activated_count = 0
        for thread in threads:
            # This instance method call is correct and thread-safe.
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
        It checks if a thread is already an agent and activates it if not.
        Being a static method guarantees it doesn't rely on instance state.

        Args:
            thread (threading.Thread): The thread to apply the logic to.
            factory_id (Optional[str]): The factory ID for the new agent.

        Returns:
            bool: True on successful activation, False otherwise.
        """
        if AgentActivator.is_agent(thread):
            return False  # The thread is already an agent.

        AgentActivator(thread, factory_id)
        return True  # The transformation was successful.

    def create_controller(self, **kwargs) -> ActivityController:
        """
        Creates a new, standard OperationalController that can be canceled.
        """
        return ActivityController(**kwargs)

    def get_uncancelable_controller(self) -> ActivityController:
        """
        Returns a shared, singleton controller that cannot be canceled.
        """
        return ActivityController.get_uncancelable()

    def create_linked_controller(
            self, *activities: 'Activity', **kwargs
    ) -> ActivityController:
        """
        Creates a new controller that is linked to other activities.
        """
        new_controller = self.create_controller(**kwargs)
        cancel_action = new_controller.cancel
        for act in activities:
            if act.is_cancellation_requested:
                new_controller.cancel()
                break
            act.register_cancellation_callback(cancel_action)
        return new_controller