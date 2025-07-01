import threading
import ulid
from typing import Callable, Optional, Any
from thread_factory import ConcurrentDict
from thread_factory.utils.general_helpers.coroutine_helpers import CoroutineHelpers

class AgentActivator:
    """
    Dresses a standard threading.Thread with agentic features.

    This class holds the agentic state (like inventories and locations) and
    monkey-patches the target thread with methods to access and manipulate
    this state, effectively upgrading a simple thread into a stateful agent.
    """

    def __init__(
            self,
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
        self._thread_target = thread
        self.factory_id = factory_id if factory_id else str(ulid.ULID())
        self._disposed = False

        # --- Agentic State Initialization ---
        self._lock = threading.RLock()
        # This worker_type is the flag used by is_agent() to identify an activated thread.
        self._worker_type = "agentic"
        self._inventory = threading.local()
        self._inventory.data = ConcurrentDict()
        self._shared_inventory: ConcurrentDict[str, Any] = ConcurrentDict()
        self._data_transfer: ConcurrentDict[str, Callable[..., Any]] = ConcurrentDict()
        self._save_points: ConcurrentDict[str, Callable[[], None]] = ConcurrentDict()
        self._locations: ConcurrentDict[str, Callable[[], None]] = ConcurrentDict()

        # --- Monkey-Patch the Thread ---
        self._patch_thread()

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

    def _patch_thread(self):
        """
        Internal method to apply agentic methods and properties to the
        target thread using `setattr`. This is the core of the
        monkey-patching process.
        """
        methods_to_patch = [
            'bind_to_inventory', 'get_from_inventory', 'set_shared_inventory_item',
            'get_shared_inventory_item', 'get_shared_inventory', 'register_data_transfer',
            'get_data_transfer_dict', 'execute_transfer', 'register_save_point',
            'get_save_points_dict', 'register_location', 'get_locations_dict',
            'get_factory_id', 'bind_to_inventory_by_id', 'get_from_inventory_by_id', 'dispose'
        ]

        for method_name in methods_to_patch:
            setattr(self._thread_target, method_name, getattr(self, method_name))

        # Patch the identifying attributes directly onto the thread.
        setattr(self._thread_target, 'factory_id', self.factory_id)
        setattr(self._thread_target, '_worker_type', self._worker_type)

    def _unpatch_thread(self):
        """
        Internal method to remove all patched methods and properties from
        the target thread during disposal.
        """
        methods_to_unpatch = [
            'bind_to_inventory', 'get_from_inventory', 'set_shared_inventory_item',
            'get_shared_inventory_item', 'get_shared_inventory', 'register_data_transfer',
            'get_data_transfer_dict', 'execute_transfer', 'register_save_point',
            'get_save_points_dict', 'register_location', 'get_locations_dict',
            'get_factory_id', 'bind_to_inventory_by_id', 'get_from_inventory_by_id',
            'dispose', 'factory_id', '_worker_type'
        ]
        for method_name in methods_to_unpatch:
            if hasattr(self._thread_target, method_name):
                try:
                    delattr(self._thread_target, method_name)
                except AttributeError:
                    pass

    def bind_to_inventory(self, key: str, value: Any):
        """
        Binds a key-value pair to the agent's private, thread-local inventory.

        This data is only accessible to this specific agent's thread.

        Args:
            key (str): The key to store the data under.
            value (Any): The value to store.
        """
        self._inventory.data[key] = value

    def get_from_inventory(self, key: str, default=None) -> Any:
        """
        Retrieves a value from the agent's private, thread-local inventory.

        Args:
            key (str): The key of the item to retrieve.
            default (Any, optional): The value to return if the key is not found.

        Returns:
            Any: The retrieved value, or the default if not found.
        """
        return self._inventory.data.get(key, default)

    def set_shared_inventory_item(self, key: str, value: Any):
        """
        Sets a key-value pair in the shared inventory, accessible by all agents.

        Args:
            key (str): The key to store the data under.
            value (Any): The value to store.
        """
        self._shared_inventory[key] = value

    def get_shared_inventory_item(self, key: str, default: Any = None) -> Any:
        """
        Retrieves a value from the shared inventory.

        Args:
            key (str): The key of the item to retrieve.
            default (Any, optional): The value to return if the key is not found.

        Returns:
            Any: The retrieved value, or the default if not found.
        """
        return self._shared_inventory.get(key, default)

    def get_shared_inventory(self) -> ConcurrentDict[str, Any]:
        """
        Retrieves a copy of the entire shared inventory dictionary.

        Returns:
            ConcurrentDict[str, Any]: A copy of the shared inventory.
        """
        return self._shared_inventory.copy()

    def register_data_transfer(self, name: str, fn: Callable[..., Any]):
        """
        Registers a named callable function for data processing tasks.

        Args:
            name (str): The unique name for the data transfer function.
            fn (Callable[..., Any]): The function to register.

        Raises:
            TypeError: If the provided function is an async coroutine.
        """
        if CoroutineHelpers.is_coroutine(fn):
            raise TypeError(f"Cannot register coroutine '{name}'. Agent runs synchronously.")
        self._data_transfer[name] = fn

    def get_data_transfer_dict(self) -> ConcurrentDict[str, Callable[..., Any]]:
        """
        Retrieves a copy of all registered data transfer functions.

        Returns:
            ConcurrentDict[str, Callable[..., Any]]: A dictionary of transfer functions.
        """
        return self._data_transfer.copy()

    def execute_transfer(self, name: str) -> Any:
        """
        Executes a previously registered data transfer function by its name.

        Args:
            name (str): The name of the data transfer function to execute.

        Returns:
            Any: The result returned by the executed function.

        Raises:
            KeyError: If no function is registered with the given name.
        """
        if name not in self._data_transfer:
            raise KeyError(f"No data_transfer entry named '{name}'")
        return self._data_transfer[name]()

    def register_save_point(self, name: str, fn: Callable[[], None]):
        """
        Registers a named callable as a "save point" for checkpointing execution flow.

        Args:
            name (str): The unique name for the save point.
            fn (Callable[[], None]): The function representing the save point.

        Raises:
            TypeError: If the provided function is an async coroutine.
        """
        if CoroutineHelpers.is_coroutine(fn):
            raise TypeError(f"Cannot register coroutine '{name}'. Agent runs synchronously.")
        self._save_points[name] = fn

    def get_save_points_dict(self) -> ConcurrentDict[str, Callable[[], None]]:
        """
        Retrieves a copy of all registered save point functions.

        Returns:
            ConcurrentDict[str, Callable[[], None]]: A dictionary of save points.
        """
        return self._save_points.copy()

    def register_location(self, name: str, fn: Callable[[], None]):
        """
        Registers a named callable as a distinct "location" or execution zone.

        Args:
            name (str): The unique name for the location.
            fn (Callable[[], None]): The function defining the location's behavior.

        Raises:
            TypeError: If the provided function is an async coroutine.
        """
        if CoroutineHelpers.is_coroutine(fn):
            raise TypeError(f"Cannot register coroutine '{name}'. Agent runs synchronously.")
        self._locations[name] = fn

    def get_locations_dict(self) -> ConcurrentDict[str, Callable[[], None]]:
        """
        Retrieves a copy of all registered location functions.

        Returns:
            ConcurrentDict[str, Callable[[], None]]: A dictionary of locations.
        """
        return self._locations.copy()

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
        if self.factory and hasattr(self.factory, "get_worker_by_id"):
            return self.factory.get_worker_by_id(factory_id)
        return None

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
            if self._inventory:
                self._inventory.data.clear()
            self._shared_inventory.clear()
            self._data_transfer.clear()
            self._save_points.clear()
            self._locations.clear()

            # Nullify references
            self._thread_target = None
            self._disposed = True