from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.utils.coordination.package import Pack
from thread_factory.utils.interfaces.disposable import IDisposable
from typing import Optional, Callable, Union, Any


class General(IDisposable):
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

    def __init__(self):
        """
        Initializes a blank profile with default field values.
        """
        super().__init__()
        self.id: Optional[str] = None
        self.name: Optional[str] = None
        self.job: Optional[str] = None
        self.group: Optional[str] = None

        self.save_points: ConcurrentDict[str, Union[Callable[..., None], "Pack"]] = ConcurrentDict()
        self.locations: ConcurrentDict[str, Union[Callable[..., None], "Pack"]] = ConcurrentDict()
        self.data_transfer: ConcurrentDict[str, Union[Callable[..., any], "Pack"]] = ConcurrentDict()

        self._bound_target: Optional[Union["ActivatedAgent", "Agent"]] = None

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

    def dispose(self):
        """
        Dispose of internal state and clear all references.
        """
        if self._disposed:
            return
        self.save_points.dispose()
        self.locations.dispose()
        self.data_transfer.dispose()

        self.id = None
        self.name = None
        self.job = None
        self.group = None
        self._bound_target = None
        self._disposed = True


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


    def __repr__(self) -> str:
        return f"<Profile name={self.name} job={self.job} group={self.group} id={self.id} bound={self.is_bound}>"