import threading, ulid
from typing import Callable, Optional, Any, Union
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.utils.coordination.package import Pack
from thread_factory.utils.interfaces.disposable import IDisposable


class ActivatedAgent(IDisposable):
    """
    Dresses a standard threading.Thread with agentic features.

    This class holds the agentic state (like inventories and locations) and
    monkey-patches the target thread with methods to access and manipulate
    this state, effectively upgrading a simple thread into a stateful agent.
    """

    def __init__(
            self,
            profile: Any,
            thread: threading.Thread,
    ):
        """
        Initializes the Activator, sets up all agentic state, and
        patches the target thread to make it agentic.

        Args:
            thread (threading.Thread): The thread instance to upgrade.
            factory_id (Optional[str]): The unique identifier for the thread.
        """
        super().__init__()
        # --- Default Factory --- #
        self._lock = threading.RLock()
        self._thread_target = thread
        self._profile = profile() if profile else None

        # --- Agentic State --- #
        self._patch_thread()

    def dispose(self):
        """
        Performs a comprehensive cleanup of the agent's state and unpatches
        the thread to prevent memory leaks. This is idempotent.
        """
        if self._disposed:
            return
        with self._lock:
            self._profile.unpatch_thread(self._thread_target)
            self._unpatch_thread()
            # Clear all collections to release references
            if self._profile:
                self._profile.dispose()
                self._profile = None

            # Nullify references
            self._thread_target = None
            self._command_center = None  # Clear command center reference
            self._disposed = True

    def _patch_thread(self):
        """
        Internal method to patch the target thread with agentic methods and properties.
        """
        methods_to_patch = ['get_factory_id',
            'bind_to_inventory_by_id', 'get_from_inventory_by_id',
            'dispose'
        ]
        for method_name in methods_to_patch:
            setattr(self._thread_target, method_name, getattr(self, method_name))
        setattr(self._thread_target, 'factory_id', self.factory_id)
        setattr(self._thread_target, '_worker_type', self._worker_type)
        setattr(self._thread_target, '_pool_agent', self._pool_agent)
        setattr(self._thread_target, '_command_center', self._command_center)
        setattr(self._thread_target, '_profile', self._profile)


    def _unpatch_thread(self):
        """
        Internal method to remove all patched methods and properties from
        the target thread during disposal.
        """
        methods_to_unpatch = [
            'get_factory_id',
            'bind_to_inventory_by_id', 'get_from_inventory_by_id',
            'dispose', 'factory_id', '_worker_type',
            '_pool_agent', '_command_center', '_profile',
            'profile' # <--- ADD THIS LINE to unpatch the profile
        ]
        for method_name in methods_to_unpatch:
            if hasattr(self._thread_target, method_name):
                try:
                    delattr(self._thread_target, method_name)
                except AttributeError:
                    pass

    def __call__(self) -> "ActivatedAgent":
        """
        Returns the current ActivatedAgent instance.

        This allows the object to be used in callable contexts,
        making it compatible with factory patterns, decorators,
        or injection systems expecting a callable agent object.

        Returns:
            ActivatedAgent: This instance.
        """
        return self

    def run(self) -> Any:
        """
        Directly invokes the wrapped thread's target logic.

        This does not start a new thread; it simply runs the function synchronously
        in the current thread context. Useful for testing or when overriding agent logic.

        Returns:
            Any: The result of the target function if it has a return value.

        Raises:
            RuntimeError: If the thread target is missing or disposed.
        """
        if self._disposed or self._thread_target is None:
            raise RuntimeError("Agent has been disposed or lacks a valid thread target.")
        return self._thread_target.run()
