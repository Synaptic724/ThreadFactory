import threading
import ulid
from thread_factory.utils.interfaces.disposable import IDisposable
from typing import Optional, Callable, Union, Any
from thread_factory.utils.interfaces.iprofile import IProfile


class BaseProfile(IDisposable, IProfile):
    """
    General Profile
    ---------
    A lightweight container for agent identity and execution structure.

    This object may only be bound to an AgentActivator or Agent instance.
    """

    __slots__ = IDisposable.__slots__ + [
        "id", "name", "job", "group",
        "save_points", "locations", "data_transfer",
        "_bound_target", "_thread_target", "_command_center",
        "_worker_type", "_pool_agent", "_activator", "_lock", "_factory_id",
    ]

    def __init__(self):
        """
        Initializes the Activator, sets up all agentic state, and
        patches the target thread to make it agentic.

        Args:
            thread (threading.Thread): The thread instance to upgrade.
            factory_id (Optional[str]): The unique identifier for the thread.
        """
        super().__init__()
        self._factory_id = str(ulid.ULID())
        self._worker_type = "agentic"
        self._thread_target = None
        self._pool_agent = False # Indicates this worker is part of a dynamic thread pool
        self._command_center = None  # Placeholder for a Command Center reference if needed
        self._activator = None
        self._lock = threading.RLock()

    def dispose(self):
        """
        Dispose of internal state and clear all references.
        """
        if self._disposed:
            return
        self._command_center = None
        self._thread_target = None
        self._disposed = True

    def get_name(self) -> str:
        """
        Retrieves the name of the agent.

        Returns:
            str: The name of the agent.
        """
        return "This is a BaseProfile, and thus is nameless."

    def get_description(self) -> str:
        """
        Retrieves a description of the agent.

        Returns:
            str: A description of the agent.
        """
        return "This is a BaseProfile, it's purpose is to provide a base for agent profiles."

    def bind_essentials(self, target: threading.Thread, command_center: 'CommandCenter', agent: 'AgentActivator') -> None:
        """
        Bind default values to the profile.

        Args:
            target (threading.Thread): The thread to bind defaults to.
            command_center (CommandCenter): The command center for managing agents.
        """
        self._thread_target = target
        self._command_center = command_center
        self._activator = agent

    def __repr__(self) -> str:
        return f"<AgentActivator id={self.factory_id} thread={repr(self._thread_target)}>"

    def __str__(self) -> str:
        return f"AgentActivator<{self.factory_id}>"

    @property
    def factory_id(self):
        return self._factory_id


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

    def bind_to(self, obj: Union["AgentActivator", "Agent"]):
        """
        Bind this profile to a supported agent.

        Args:
            obj: An AgentActivator or Agent instance.

        Raises:
            TypeError: If object is not a valid agent type.
            RuntimeError: If the profile is already bound.
        """
        if self._bound_target is not None:
            raise RuntimeError("Profile is already bound to an agent.")

        from thread_factory.agent.identity.activator import AgentActivator
        from thread_factory.agent.thread_pool.agent import Agent

        if not isinstance(obj, (AgentActivator, Agent)):
            raise TypeError("Profile can only be bound to AgentActivator or Agent.")

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
