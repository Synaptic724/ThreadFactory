import threading, ulid
from thread_factory.agent.identity.types.agentic_base import AgenticBase
from thread_factory.agent.identity.types.base import BaseProfile
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.utils.coordination.package import Pack
from thread_factory.utils.interfaces.disposable import IDisposable
from typing import Optional, Callable, Union, Any

class General(AgenticBase):
    """
    General Profile
    ---------
    A lightweight container for agent identity and execution structure.

    This object may only be bound to an ActivatedAgent or Agent instance.
    """

    def __init__(self, command_center: 'CommandCenter', target: Union[Callable[..., Any], Pack] = None,
                 id: str = None, name: str = None, job: str = None, group: str = None, *args, **kwargs):
        """
        Initializes a blank profile with default field values.
        """
        super().__init__(command_center, target, *args, *kwargs)
        self.id: Optional[str] = id
        self.name: Optional[str] = name
        self.job: Optional[str] = job
        self.group: Optional[str] = group

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

        self.id: Optional[str] = None
        self.name: Optional[str] = None
        self.job: Optional[str] = None
        self.group: Optional[str] = None
        super().dispose()

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



    def __repr__(self) -> str:
        return f"<Profile name={self.name} job={self.job} group={self.group} id={self.id}>"


    def set_home(self, fn: Union[Callable[..., None], Pack]) -> None:
        self._event_loop = Pack.bundle(fn) if fn else fn


    def _validate_caller(self, factory_id: Optional[str] = None) -> None:
        expected = factory_id or self.factory_id
        current_id = getattr(threading.current_thread(), "factory_id", None)
        if current_id != expected:
            raise PermissionError(
                f"[Access Denied] Caller factory_id={current_id} does not match expected={expected}"
            )

    def __str__(self) -> str:
        return f"AgenticProfile<{self.factory_id}>"