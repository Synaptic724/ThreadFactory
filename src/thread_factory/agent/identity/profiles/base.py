import threading
import ulid
from thread_factory.utils.interfaces.disposable import IDisposable
from typing import Optional, Callable, Union, Any


class BaseProfile(IDisposable):
    """
    General Profile
    ---------
    A lightweight container for agent identity and execution structure.

    This object may only be bound to an ActivatedAgent or Agent instance.
    """

    __slots__ = IDisposable.__slots__ + [
        "id", "name", "job", "group",
        "save_points", "locations", "data_transfer",
        "_bound_target"
    ]

    def __init__(
            self,
            thread: threading.Thread,
            command_center: 'CommandCenter',
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
        self.factory_id = factory_id if factory_id else str(ulid.ULID())
        self._worker_type = "agentic"
        self._thread_target = thread
        self._pool_agent = False # Indicates this worker is part of a dynamic thread pool
        self._command_center = command_center  # Placeholder for a Command Center reference if needed
        self._lock = threading.RLock()

        self._bound_target: Optional[Union["ActivatedAgent", "Agent"]] = None

    def dispose(self):
        """
        Dispose of internal state and clear all references.
        """
        if self._disposed:
            return
        self._command_center = None
        self._bound_target = None
        self._thread_target = None
        self._disposed = True


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

    def bind_to(self, obj: Union["ActivatedAgent", "Agent"]):
        """
        Bind this profile to a supported agent.

        Args:
            obj: An ActivatedAgent or Agent instance.

        Raises:
            TypeError: If object is not a valid agent type.
            RuntimeError: If the profile is already bound.
        """
        if self._bound_target is not None:
            raise RuntimeError("Profile is already bound to an agent.")

        from thread_factory.agent.identity.activator import ActivatedAgent
        from thread_factory.agent.thread_pool.agent import Agent

        if not isinstance(obj, (ActivatedAgent, Agent)):
            raise TypeError("Profile can only be bound to ActivatedAgent or Agent.")

        self._bound_target = obj

    def unbind(self):
        """
        Unbind the profile from its current agent.
        """
        self._bound_target = None

    @property
    def is_bound(self) -> bool:
        """
        Indicates whether this profile is bound to a valid agent.
        """
        return self._bound_target is not None
