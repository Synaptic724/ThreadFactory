from thread_factory.agent.identity.types.agent import Agent
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.utils.coordination.package import Pack
from typing import Optional, Callable, Union, Any

class General(Agent):
    """
    General Profile
    ---------
    A specialized agent profile that extends `AgenticBase` to provide a concrete
    implementation for a general-purpose agent. It introduces specific identity
    attributes and mechanisms for dynamic behavior routing through "locations,"
    "save points," and "data transfers."

    This class is designed to be a versatile, ready-to-use agent profile that
    can be configured with a name, job, and group, and can have its behavior
    dynamically defined at runtime by registering callable functions.

    Key Features:
    - **Specific Identity**: Adds `id`, `name`, `job`, and `group` attributes for more detailed agent identification.
    - **Location-Based Behavior Routing**: Implements `locations` and `save_points` to define distinct, invokable execution zones and checkpoints.
    - **Callable-Based Data Pipelines**: A `data_transfer` mechanism allows for registering and executing functions to handle data processing tasks.
    - **Inherits Core Agentic Functionality**: Builds upon all the features of `AgenticBase`, including work management, state tracking, and private/public inventories.

    Attributes:
        public_id (Optional[str]): A user-defined identifier for the agent.
        name (Optional[str]): A user-defined name for the agent.
        job (Optional[str]): A description of the agent's primary function or role.
        group (Optional[str]): The group or team this agent belongs to.
        save_points (ConcurrentDict): A dictionary storing named callable "save points" for checkpointing execution flow.
        locations (ConcurrentDict): A dictionary storing named callable "locations" representing distinct execution zones.
        data_transfer (ConcurrentDict): A dictionary storing named callable functions for data processing and transfer tasks.
    """

    def __init__(self, command_center: 'CommandCenter', target: Pack = None,
                 public_id: str = None, public_name: str = None,
                 job_title: str = None, activity_group: str = None,
                 *args, **kwargs):
        """
        Initializes a General profile with specific identity attributes and collections
        for dynamic behavior registration.

        Args:
            command_center ('CommandCenter'): The central coordination unit.
            target (Union[Callable[..., Any], Pack], optional): The task this agent runs.
            public_id (str, optional): The public identifier for this agent.
            public_name (str, optional): The public-facing name for this agent.
            job_title (str, optional): A descriptor for the agent's job function.
            activity_group (str, optional): A group this agent is logically assigned to.
            *args: Positional arguments passed to base constructor.
            **kwargs: Keyword arguments passed to base constructor.
        """
        # Extract identity values directly from kwargs (in case user passed them there)
        self.public_id: Optional[str] = public_id or kwargs.pop("public_id", None)
        self.public_name: Optional[str] = public_name or kwargs.pop("public_name", None)
        self.job_title: Optional[str] = job_title or kwargs.pop("job_title", None)
        self.activity_group: Optional[str] = activity_group or kwargs.pop("activity_group", None)

        # Setup routing registries
        self.save_points = None
        self.locations = None
        self.data_transfer = None

        # Only now call super with clean args
        super().__init__(command_center, target, *args, **kwargs)

    def dispose(self):
        """
        Performs a comprehensive cleanup of the General profile's state,
        disposing of all registered behaviors and identity attributes before
        calling the base class's dispose method.
        """
        if self._disposed:
            return

        # Dispose of collections specific to the General profile
        if self.save_points:
            self.save_points.dispose()
            self.save_points = None
        if self.locations:
            self.locations.dispose()
            self.locations = None
        if self.data_transfer:
            self.data_transfer.dispose()
            self.data_transfer = None

        # Call the dispose method of the parent class
        super().dispose()

    def get_name(self) -> str:
        """
        Retrieves the name of the agent, providing a default if not set.

        Returns:
            str: The agent's name, or "UnnamedAgent" if the name is not specified.
        """
        return self.public_name if self.public_name else "UnnamedAgent"

    def get_description(self) -> str:
        """
        Retrieves a formatted description of the agent, including its name, job, and group.

        Returns:
            str: A descriptive string summarizing the agent's identity.
        """
        return f"Agent {self.get_name()} with job '{self.job_title}' in group '{self.activity_group}'"

    def __repr__(self) -> str:
        """
        Provides a developer-friendly string representation of the General profile,
        showing its specific identity attributes.

        Returns:
            str: A string detailing the agent's name, job, group, and ID.
        """
        return self.get_description()

    def register_data_transfer(self, name: str, fn: Union[Callable[..., Any], Pack]):
        """
        Registers a named callable function for data processing or movement tasks.
        These functions can be invoked by name using `execute_transfer`.

        Args:
            name (str): The unique name to assign to the data transfer function.
            fn (Union[Callable[..., Any], Pack]): The callable function or `Pack` to register.
        """
        if self._disposed:
            raise RuntimeError("Cannot register data transfer on a disposed agent.")
        if self.data_transfer:
            self.data_transfer[name] = Pack.bundle(fn) if fn else None
        else:
            self.data_transfer = ConcurrentDict({name: Pack.bundle(fn) if fn else None})

    def get_data_transfer_dict(self) -> ConcurrentDict[str, Union[Callable[..., Any], Pack]]:
        """
        Retrieves a copy of the dictionary containing all registered data transfer functions.

        Returns:
            ConcurrentDict[str, Union[Callable[..., Any], Pack]]: A shallow copy of the
                data transfer dictionary.
        """
        if self.data_transfer is None:
            return ConcurrentDict()
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
        if self._disposed:
            raise RuntimeError("Cannot execute data transfer on a disposed agent.")

        if self.data_transfer is None:
            raise KeyError("No data transfer functions registered.")

        if name not in self.data_transfer:
            raise KeyError(f"No data_transfer entry named '{name}'")
        return self.data_transfer[name]()

    def register_save_point(self, name: str, fn: Union[Callable[..., None], Pack]):
        """
        Registers a named callable as a "save point" for checkpointing execution flow.
        This allows the agent to return to a specific point in its logic.

        Args:
            name (str): The unique name for the save point.
            fn (Union[Callable[..., None], Pack]): The callable function or `Pack`
                representing the save point's logic.
        """
        if self._disposed:
            raise RuntimeError("Cannot register save point on a disposed agent.")
        if self.save_points is None:
            self.save_points = ConcurrentDict({name : Pack.bundle(fn) if fn else None})
        else:
            self.save_points[name] = Pack.bundle(fn) if fn else None

    def get_save_points_dict(self) -> ConcurrentDict[str, Union[Callable[..., None], Pack]]:
        """
        Retrieves a copy of the dictionary of all registered save point functions.

        Returns:
            ConcurrentDict[str, Union[Callable[..., None], Pack]]: A shallow copy of
                the save points dictionary.
        """
        if self.save_points is None:
            return ConcurrentDict()
        return self.save_points.copy()

    def register_location(self, name: str, fn: Union[Callable[..., None], Pack]):
        """
        Registers a named callable as a distinct "location" or execution zone.
        This allows the agent to dynamically switch between different behaviors.

        Args:
            name (str): The unique name for the location.
            fn (Union[Callable[..., None], Pack]): The callable function or `Pack`
                defining the location's behavior.
        """
        if self._disposed:
            raise RuntimeError("Cannot register location on a disposed agent.")
        if self.locations is None:
            self.locations = ConcurrentDict({name: Pack.bundle(fn) if fn else None})
        else:
            self.locations[name] = Pack.bundle(fn) if fn else None

    def get_locations_dict(self) -> ConcurrentDict[str, Union[Callable[..., None], Pack]]:
        """
        Retrieves a copy of the dictionary of all registered location functions.

        Returns:
            ConcurrentDict[str, Union[Callable[..., None], Pack]]: A shallow copy of
                the locations dictionary.
        """
        if self.locations is None:
            return ConcurrentDict()
        return self.locations.copy()