import threading, ulid
from thread_factory.agent.identity.profiles.base import BaseProfile
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.utils.coordination.package import Pack
from thread_factory.utils.interfaces.disposable import IDisposable
from typing import Optional, Callable, Union, Any
from thread_factory.utils.interfaces.iprofile import IProfile

class General(BaseProfile, IProfile):
    """
    General Profile
    ---------
    A lightweight container for agent identity and execution structure.

    This object may only be bound to an ActivatedAgent or Agent instance.
    """
    def __init__(self):
        """
        Initializes a blank profile with default field values.
        """
        super().__init__()
        self.id: Optional[str] = None
        self.name: Optional[str] = None
        self.job: Optional[str] = None
        self.group: Optional[str] = None

        self._private_inventory = threading.local()
        self._private_inventory.data = ConcurrentDict()
        self._public_inventory: ConcurrentDict[str, Any] = ConcurrentDict()

        # Initialize collections for save points, locations, and data transfer functions
        self.save_points: ConcurrentDict[str, Union[Callable[..., None], "Pack"]] = ConcurrentDict()
        self.locations: ConcurrentDict[str, Union[Callable[..., None], "Pack"]] = ConcurrentDict()
        self.data_transfer: ConcurrentDict[str, Union[Callable[..., any], "Pack"]] = ConcurrentDict()

    def dispose(self):
        """
        Dispose of internal state and clear all references.
        """
        if self._disposed:
            return
        self.save_points.dispose()
        self.save_points = None
        self.locations.dispose()
        self.locations = None
        self.data_transfer.dispose()
        self.data_transfer = None
        self._private_inventory.dispose()
        self._private_inventory = None
        self._public_inventory.dispose()
        self._public_inventory = None

        self.id = None
        self.name = None
        self.job = None
        self.group = None
        super().dispose()

    def bind_defaults(self, id = None, name: str = None, job: str = None, group: str = None):
        """
        Binds the default profile to the provided thread and command center.

        Args:
            thread (threading.Thread): The thread to bind the profile to.
            command_center (CommandCenter, optional): The command center for coordination.
            factory_id (Optional[str]): Unique identifier for the thread.
        """
        self.id = id if id else str(ulid.ULID())
        self.name = name if name else "UnnamedAgent"
        self.job = job if job else "generic"
        self.group = group if group else "default"

    def define_defaults(self, *args, **kwargs):
        """
        Defines the profile with provided arguments.

        Supports both positional and keyword arguments for flexibility.
        Positional order: (id, name, job, group)

        Args:
            *args: Optional positional arguments in the order:
                   id, name, job, group
            **kwargs: Named arguments for any of: id, name, job, group
        """
        id_ = kwargs.get("id", args[0] if len(args) > 0 else None)
        name = kwargs.get("name", args[1] if len(args) > 1 else None)
        job = kwargs.get("job", args[2] if len(args) > 2 else None)
        group = kwargs.get("group", args[3] if len(args) > 3 else None)

        self.id = id_ if id_ else str(ulid.ULID())
        self.name = name if name else "UnnamedAgent"
        self.job = job if job else "generic"
        self.group = group if group else "default"

    def get_name(self) -> str:
        """
        Retrieves the name of the agent.

        Returns:
            str: The name of the agent.
        """
        return self.name if self.name else "UnnamedAgent"

    def get_description(self) -> str:
        """
        Retrieves a description of the agent.

        Returns:
            str: A description of the agent.
        """
        return f"Agent {self.get_name()} with job '{self.job}' in group '{self.group}'"

    def register_data_transfer(self, name: str, fn: Union[Callable[..., Any], Pack]):
        """
        Registers a named callable function for data processing tasks.

        Args:
            name (str): The unique name for the data transfer function.
            fn (Union[Callable[..., Any], Pack]): The function to register.

        Raises:
            TypeError: If the provided function is an async coroutine.
        """
        if fn:
            fn = Pack.bundle(fn)
        self.data_transfer[name] = fn

    def get_data_transfer_dict(self) -> ConcurrentDict[str, Union[Callable[..., Any], Pack]]:
        """
        Retrieves a copy of all registered data transfer functions.

        Returns:
            ConcurrentDict[str, Union[Callable[..., Any], Pack]]: A dictionary of transfer functions.
        """
        return self.data_transfer.copy()

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
        if name not in self.data_transfer:
            raise KeyError(f"No data_transfer entry named '{name}'")
        return self.data_transfer[name]()

    def register_save_point(self, name: str, fn: Union[Callable[..., None], Pack]):
        """
        Registers a named callable as a "save point" for checkpointing execution flow.

        Args:
            name (str): The unique name for the save point.
            fn (Union[Callable[..., None], Pack]): The function representing the save point.

        Raises:
            TypeError: If the provided function is an async coroutine.
        """
        if fn:
            fn = Pack.bundle(fn)
        self.save_points[name] = fn

    def get_save_points_dict(self) -> ConcurrentDict[str, Union[Callable[..., None], Pack]]:
        """
        Retrieves a copy of all registered save point functions.

        Returns:
            ConcurrentDict[str, Union[Callable[..., None], Pack]]: A dictionary of save points.
        """
        return self.save_points.copy()

    def register_location(self, name: str, fn: Union[Callable[..., None], Pack]):
        """
        Registers a named callable as a distinct "location" or execution zone.

        Args:
            name (str): The unique name for the location.
            fn (Union[Callable[..., None], Pack]): The function defining the location's behavior.

        Raises:
            TypeError: If the provided function is an async coroutine.
        """
        if fn:
            fn = Pack.bundle(fn)
        self.locations[name] = fn

    def get_locations_dict(self) -> ConcurrentDict[str, Union[Callable[..., None], Pack]]:
        """
        Retrieves a copy of all registered location functions.

        Returns:
            ConcurrentDict[str, Union[Callable[..., None], Pack]]: A dictionary of locations.
        """
        return self.locations.copy()


    def bind_to_inventory(self, key: str, value: Any):
        """
        Binds a key-value pair to the agent's private, thread-local inventory.

        This data is only accessible to this specific agent's thread.

        Args:
            key (str): The key to store the data under.
            value (Any): The value to store.
        """
        self._private_inventory.data[key] = value

    def get_from_inventory(self, key: str, default=None) -> Any:
        """
        Retrieves a value from the agent's private, thread-local inventory.

        Args:
            key (str): The key of the item to retrieve.
            default (Any, optional): The value to return if the key is not found.

        Returns:
            Any: The retrieved value, or the default if not found.
        """
        return self._private_inventory.data.get(key, default)

    def set_shared_inventory_item(self, key: str, value: Any):
        """
        Sets a key-value pair in the shared inventory, accessible by all agents.

        Args:
            key (str): The key to store the data under.
            value (Any): The value to store.
        """
        self._public_inventory[key] = value

    def get_shared_inventory_item(self, key: str, default: Any = None) -> Any:
        """
        Retrieves a value from the shared inventory.

        Args:
            key (str): The key of the item to retrieve.
            default (Any, optional): The value to return if the key is not found.

        Returns:
            Any: The retrieved value, or the default if not found.
        """
        return self._public_inventory.get(key, default)

    def get_shared_inventory(self) -> ConcurrentDict[str, Any]:
        """
        Retrieves a copy of the entire shared inventory dictionary.

        Returns:
            ConcurrentDict[str, Any]: A copy of the shared inventory.
        """
        return self._public_inventory.copy()


    def __repr__(self) -> str:
        return f"<Profile name={self.name} job={self.job} group={self.group} id={self.id}>"