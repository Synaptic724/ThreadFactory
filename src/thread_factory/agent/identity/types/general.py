import logging
from thread_factory.agent.identity.types.agent import Agent
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.synchronization import SignalController
from thread_factory.utils.coordination.package import Pack
from typing import Optional, Callable, Union, Any

class General(Agent):
    """
    General Profile
    ---------
    A specialized agent profile that extends `Agent` to provide a concrete
    implementation for a general-purpose agent. It introduces specific identity
    attributes and mechanisms for dynamic behavior routing through "locations,"
    "save points," and "data transfers."

    This class is designed to be a versatile, ready-to-use agent profile that
    can be configured with a name, job, and group, and can have its behavior
    dynamically defined at runtime by registering callable functions.

    Key Features:
    - **Specific Identity**: Adds `public_id`, `public_name`, `job_title`, and `activity_group`
      attributes for more detailed agent identification.
    - **Location-Based Behavior Routing**: Implements `locations` and `save_points` to
      define distinct, invokable execution zones and checkpoints.
    - **Callable-Based Data Pipelines**: A `data_transfer` mechanism allows for registering
      and executing functions to handle data processing tasks.
    - **Inherits Core Agentic Functionality**: Builds upon all the features of `Agent`,
      including work management, state tracking, and private/public inventories.

    Attributes:
        public_id (Optional[str]): A user-defined identifier for the agent.
        public_name (Optional[str]): A user-defined name for the agent.
        job_title (Optional[str]): A description of the agent's primary function or role.
        activity_group (Optional[str]): The group or team this agent belongs to.
        save_points (ConcurrentDict): A dictionary storing named callable "save points"
                                     for checkpointing execution flow.
        locations (ConcurrentDict): A dictionary storing named callable "locations"
                                   representing distinct execution zones.
        data_transfer (ConcurrentDict): A dictionary storing named callable functions
                                        for data processing and transfer tasks.
    """

    def __init__(self, command_center: 'CommandCenter',
                 target: Union[Callable[..., Any], Pack] = None, # Matches Agent's 'target' type hint
                 public_id: Optional[str] = None,
                 public_name: Optional[str] = None,
                 job_title: Optional[str] = None,
                 # Explicitly add Agent-specific optional parameters if General needs to accept them
                 factory: Any = None,
                 work_queue = None,
                 signal_controller: Optional[SignalController] = None,
                 logger: Optional[logging.Logger] = None,
                 *args, **kwargs):
        """
        Initializes a General profile with specific identity attributes and collections
        for dynamic behavior registration.

        Args:
            command_center (CommandCenter): The central coordination unit.
            target (Union[Callable, Pack], optional): The task this agent runs.
                Defaults to None.
            public_id (str, optional): The public identifier for this agent.
                Defaults to None.
            public_name (str, optional): The public-facing name for this agent.
                Defaults to None.
            job_title (str, optional): A descriptor for the agent's job function.
                Defaults to None.
            activity_group (str, optional): A group this agent is logically assigned to.
                Defaults to None.
            factory (Any, optional): A reference to the parent factory or manager.
                Defaults to None.
            work_queue (Optional[ConcurrentQueue[Work]], optional): A queue from which
                the agent continuously dequeues and executes Work units. Defaults to None.
            signal_controller (Optional[SignalController], optional): An optional
                SignalController instance for external management and event notification.
                Defaults to None.
            logger (Optional[logging.Logger], optional): A custom logger instance for the agent.
                If None, a default logger will be used. Defaults to None.
            *args: Positional arguments passed to the base constructor (`Agent`).
            **kwargs: Keyword arguments passed to the base constructor (`Agent`).
                These can include `name`, `group`, etc., which are then
                forwarded to `threading.Thread`.
        """
        # Capture General-specific identity attributes.
        # Use provided argument first, then pop from kwargs if not provided directly.
        self.public_id = public_id or kwargs.pop("public_id", None)
        self.public_name = public_name or kwargs.pop("public_name", "UnnamedAgent")
        self.job_title = job_title or kwargs.pop("job_title", "General Agent")

        # Initialize General-specific routing registries as ConcurrentDicts.
        # Assuming ConcurrentDict is IDisposable and needs to be initialized.
        self.save_points = None
        self.locations = None
        self.data_transfer = None

        # Call the parent Agent's __init__ method.
        # Pass all necessary arguments that Agent's __init__ expects.
        # Any remaining *args and **kwargs are forwarded directly.
        super().__init__(
            command_center=command_center,
            target=target,
            factory=factory,
            work_queue=work_queue,
            signal_controller=signal_controller,
            logger=logger,
            *args,
            **kwargs
        )

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

    def _get_object_details(self) -> ConcurrentDict[str, Any]:
        """
        Extends the base Agent's object details with commands and metadata specific to a General profile.

        This method exposes unique General agent capabilities to external orchestrators
        or monitoring systems via the SignalController. It provides interfaces for:

        - **Identity Retrieval**: Accessing the agent's public_id, public_name,
          job_title, and activity_group.
        - **Dynamic Behavior Management**: Registering new 'locations', 'save points',
          and 'data transfer' functions, and executing data transfers.
        - **Behavior Inspection**: Retrieving dictionaries of all registered locations,
          save points, and data transfer functions.

        Returns:
            ConcurrentDict[str, Any]: A dictionary containing the agent's base details
                augmented with General profile-specific commands and metadata.
        """
        details = super()._get_object_details()

        details["commands"].update({
            # General identity getters
            "get_public_id": self.get_public_id,
            "get_public_name": self.get_public_name,
            "get_job_title": self.get_job_title,
            "get_activity_group": self.get_activity_group,

            # Behavior routing management
            "register_location": self.register_location,
            "get_locations_dict": self.get_locations_dict,
            "register_save_point": self.register_save_point,
            "get_save_points_dict": self.get_save_points_dict,
            "register_data_transfer": self.register_data_transfer,
            "execute_transfer": self.execute_transfer,
            "get_data_transfer_dict": self.get_data_transfer_dict,

            # The get_name and get_description are overridden in General,
            # so these calls will now reflect the General profile's implementation.
            "get_name": self.get_name,
            "get_description": self.get_description
        })
        # Override or set agent_type specifically for General if desired
        details["name"] = self.__class__.__name__
        return details

#region General-specific Identity Getters
    def get_public_id(self) -> Optional[str]:
        """
        Retrieves the public identifier of this General agent.

        Returns:
            Optional[str]: The public ID, or None if not set.
        """
        with self._lock:
            return self.public_id

    def get_public_name(self) -> Optional[str]:
        """
        Retrieves the public-facing name of this General agent.

        Returns:
            Optional[str]: The public name, or None if not set.
        """
        with self._lock:
            return self.public_name

    def get_job_title(self) -> Optional[str]:
        """
        Retrieves the job title describing this General agent's primary function.

        Returns:
            Optional[str]: The job title, or None if not set.
        """
        with self._lock:
            return self.job_title

    def get_activity_group(self) -> Optional[str]:
        """
        Retrieves the activity group this General agent belongs to.

        Returns:
            Optional[str]: The activity group, or None if not set.
        """
        with self._lock:
            return self.activity_group

#endregion

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
        return f"Agent {self.get_name()} with job '{self.job_title}' in group."

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