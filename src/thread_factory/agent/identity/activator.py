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
            command_center: 'CommandCenter',
            profile: Any,
            thread: threading.Thread,
            factory_id: Optional[str] = None
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
        self._thread_target = thread
        self.factory_id = factory_id if factory_id else str(ulid.ULID())
        self._worker_type = "agentic"
        self._pool_agent = False # Indicates this worker is part of a dynamic thread pool
        self._command_center = command_center  # Placeholder for a Command Center reference if needed
        self._lock = threading.RLock()
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
            self._unpatch_thread()
            # Clear all collections to release references
            try:
                if self._inventory:
                    if hasattr(self._inventory, "data"):
                        self._inventory.data.clear()
            except AttributeError as e:
                pass
            if hasattr(self, "profile"):
                self.profile.dispose()

            # Clear shared inventory as well
            if self._public_inventory:  # Add this line
                self._private_inventory.dispose()  # And this line

            # Nullify references
            self._thread_target = None
            self._command_center = None  # Clear command center reference
            self._disposed = True

    def _patch_thread(self):
        """
        Internal method to patch the target thread with agentic methods and properties.
        """
        methods_to_patch = [
            'bind_to_inventory', 'get_from_inventory',
            'set_shared_inventory_item', 'get_shared_inventory_item',
            'get_shared_inventory', 'get_factory_id',
            'bind_to_inventory_by_id', 'get_from_inventory_by_id',
            'dispose'
        ]
        for method_name in methods_to_patch:
            setattr(self._thread_target, method_name, getattr(self, method_name))
        setattr(self._thread_target, 'factory_id', self.factory_id)
        setattr(self._thread_target, '_worker_type', self._worker_type)



    def _unpatch_thread(self):
        """
        Internal method to remove all patched methods and properties from
        the target thread during disposal.
        """
        methods_to_unpatch = [
            'bind_to_inventory', 'get_from_inventory',
            'set_shared_inventory_item', 'get_shared_inventory_item',
            'get_shared_inventory', 'get_factory_id',
            'bind_to_inventory_by_id', 'get_from_inventory_by_id',
            'dispose', 'factory_id', '_worker_type',
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

    @property
    def native_id(self) -> Optional[int]:
        """
        Retrieves the native (OS-level) thread ID, if supported.

        Returns:
            Optional[int]: The native ID if available, otherwise None.
        """
        if self._thread_target:
            return getattr(self._thread_target, "native_id", None)
        return None

    def start(self):
        """
        Starts the agent's internal thread execution.

        Equivalent to `threading.Thread.start()`. Will raise if already started
        or if the agent has been disposed.

        Raises:
            RuntimeError: If thread has already been started or disposed.
        """
        if self._disposed or self._thread_target is None:
            raise RuntimeError("Cannot start a disposed or missing agent thread.")
        self._thread_target.start()

    def join(self, timeout: Optional[float] = None):
        """
        Blocks until the thread finishes execution.

        Args:
            timeout (Optional[float]): Optional max wait time in seconds.

        Raises:
            RuntimeError: If the agent has been disposed or lacks a thread target.
        """
        if self._disposed or self._thread_target is None:
            raise RuntimeError("Cannot join a disposed or missing agent thread.")
        self._thread_target.join(timeout)

    def is_alive(self) -> bool:
        """
        Checks whether the underlying thread is still running.

        Returns:
            bool: True if alive, False otherwise.
        """
        return self._thread_target.is_alive() if self._thread_target else False

    @property
    def name(self) -> str:
        """
        Gets the thread's display name.

        Returns:
            str: The name of the internal thread.

        Raises:
            RuntimeError: If the thread has been disposed or unset.
        """
        if not self._thread_target:
            raise RuntimeError("Agent thread is not initialized.")
        return self._thread_target.name

    @name.setter
    def name(self, value: str):
        """
        Sets the thread's display name.

        Args:
            value (str): The new name to assign.

        Raises:
            RuntimeError: If the agent is disposed or the thread is not initialized.
        """
        if not self._thread_target:
            raise RuntimeError("Agent thread is not initialized.")
        self._thread_target.name = value

    @property
    def ident(self) -> Optional[int]:
        """
        Gets the internal thread's Python-level identifier.

        Returns:
            Optional[int]: Thread ID if started, else None.
        """
        return self._thread_target.ident if self._thread_target else None

    @property
    def daemon(self) -> bool:
        """
        Indicates whether this thread is marked as a daemon.

        Returns:
            bool: True if daemon, False otherwise.

        Raises:
            RuntimeError: If thread is not initialized.
        """
        if not self._thread_target:
            raise RuntimeError("Agent thread is not initialized.")
        return self._thread_target.daemon

    @daemon.setter
    def daemon(self, value: bool):
        """
        Sets the daemon status for the thread.

        Args:
            value (bool): True to mark as daemon, False otherwise.

        Raises:
            RuntimeError: If the thread is already started or uninitialized.
        """
        if not self._thread_target:
            raise RuntimeError("Agent thread is not initialized.")
        self._thread_target.daemon = value

    def __repr__(self) -> str:
        return f"<ActivatedAgent id={self.factory_id} thread={repr(self._thread_target)}>"

    def __str__(self) -> str:
        return f"ActivatedAgent<{self.factory_id}>"

    @staticmethod
    def is_agent(thread: threading.Thread) -> bool:
        """
        Checks if a thread has already been activated as an agent.

        This is done by checking for the `_worker_type` attribute on the thread.

        Args:
            thread (threading.Thread): The thread to check.

        Returns:
            bool: True if the thread is an agent, False otherwise.
        """
        return getattr(thread, '_worker_type', None) == 'agentic'

    def get_factory_id(self) -> str:
        """
        Retrieves the unique factory ID assigned to this agent.

        Returns:
            str: The agent's unique string identifier.
        """
        return self.factory_id

    def bind_to_inventory_by_id(self, factory_id: str, key: str, value: Any):
        """
        Binds a value to the private inventory of another agent, identified by its ID.

        This requires the `factory` to be set during initialization.

        Args:
            factory_id (str): The ID of the target agent.
            key (str): The key to store the data under in the target's inventory.
            value (Any): The value to store.
        """
        worker = self._resolve_worker_by_id(factory_id)
        if worker and hasattr(worker, 'bind_to_inventory'):
            worker.bind_to_inventory(key, value)

    def get_from_inventory_by_id(self, factory_id: str, key: str, default=None) -> Any:
        """
        Retrieves a value from the private inventory of another agent by its ID.

        This requires the `factory` to be set during initialization.

        Args:
            factory_id (str): The ID of the target agent.
            key (str): The key of the item to retrieve.
            default (Any, optional): The value to return if not found.

        Returns:
            Any: The retrieved value or the default.
        """
        worker = self._resolve_worker_by_id(factory_id)
        if worker and hasattr(worker, 'get_from_inventory'):
            return worker.get_from_inventory(key, default)
        return default

    def _resolve_worker_by_id(self, factory_id: str) -> Optional[threading.Thread]:
        """
        Internal helper to find another agent thread via the managing factory.

        Args:
            factory_id (str): The ID of the agent to find.

        Returns:
            Optional[threading.Thread]: The thread object if found, otherwise None.
        """
        if self._command_center:
            return self._command_center.get_agent_by_id(factory_id)
        return None

