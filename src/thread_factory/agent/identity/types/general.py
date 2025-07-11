import logging
from thread_factory.agent.identity.types.agent import Agent, AgentState
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.synchronization import SignalController
from thread_factory.agent.thread_pool.utilities.agent_pool_type import AgentPoolType
from thread_factory.utilities.coordination.package import Pack
from typing import Optional, Callable, Union, Any
from thread_factory.utilities.general_helpers.enum_helpers import EnumHelpers

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
        self.save_points: ConcurrentDict[str, Pack] = ConcurrentDict() #Callables that can be executed for small work or activity
        self.data_transfer: ConcurrentDict[str, Pack] = ConcurrentDict() # Important data transfer areas

        # Agentic State Management
        self._private_inventory = ConcurrentDict() # Local Inventory for this agent, only accessible by the agent itself.
        self.public_inventory: ConcurrentDict[str, Any] = ConcurrentDict() # Public Inventory for this agent, accessible by all threads.

        # Call the parent Agent's __init__ method.
        # Pass all necessary arguments that Agent's __init__ expects.
        # Any remaining *args and **kwargs are forwarded directly.
        super().__init__(
            command_center=command_center,
            target=target,
            signal_controller=signal_controller,
            logger=logger,
            *args,
            **kwargs
        )

        self.location_map.register_locations({
            "dispatcher": self._dispatcher_loop,
        })

    def dispose(self):
        """
        Performs a comprehensive cleanup of the General profile's state,
        disposing of all registered behaviors and identity attributes before
        calling the base class's dispose method.
        """

        with self._lock:
            if self._disposed:
                return

            self._dismiss_agent = True

            # Dispose of collections specific to the General profile
            if self.save_points:
                self.save_points.dispose()
                self.save_points = None
            if self.data_transfer:
                self.data_transfer.dispose()
                self.data_transfer = None
            if self._private_inventory:
                self._private_inventory.dispose()
                self._private_inventory = None
            if self.public_inventory:
                self.public_inventory.dispose()
                self.public_inventory = None

            # Call the dispose method of the parent class
            super().dispose()

    def reset(self) -> None:
        """
        Soft-reset the General agent to a clean state for reuse.

        This method:
        - Clears all registered locations, save points, and data transfer logic.
        - Preserves the instance (no disposal).
        - Invokes the base Agent's `reset()` method to clear work state and inventories.

        Raises:
            RuntimeError: If the agent has already been disposed.
        """
        if self._disposed:
            raise RuntimeError("Cannot reset a disposed agent.")

        if self.save_points:
            self.save_points.clear()
        if self.data_transfer:
            self.data_transfer.clear()
        # Clear inventories without disposing
        if self._private_inventory:
            self._private_inventory.clear()
        if self.public_inventory:
            self.public_inventory.clear()

        self.public_id = None
        self.public_name = None
        self.job_title = None

        # Now defer to base Agent's reset logic
        super().reset()

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

            # Behavior routing management
            "register_save_point": self.register_save_point,
            "get_save_points_dict": self.get_save_points_dict,
            "register_data_transfer": self.register_data_transfer,
            "execute_transfer": self.execute_transfer,
            "get_data_transfer_dict": self.get_data_transfer_dict,
            # The get_name and get_description are overridden in General,
            # so these calls will now reflect the General profile's implementation.
            "get_name": self.get_name,
            "get_description": self.get_description,
            # General-specific inventory management
            "get_from_private_inventory": self.get_from_private_inventory,
            "put_in_private_inventory": self.put_in_private_inventory,

        })
        # Override or set agent_type specifically for General if desired
        details["name"] = self.__class__.__name__
        return details

#region Agentic Activity
    def run(self):
        """
        Main execution entry point for the agentic thread.

        - If `self._pool_agent` is `True`, this thread executes the agentic event
          loop set via `set_home()`. This is the standard behavior for agents
          within a dynamic thread pool.
        - Otherwise, it falls back to the standard `threading.Thread.run()`
          behavior, executing the `_target` function if provided. This supports
          standalone thread logic outside the pool framework.

        Raises:
            RuntimeError: If the agent is a pool agent but `_event_loop` has not
                been set, or if it is a standalone agent but no `_target` is defined.
        """
        with self._lock:
            if self._disposed:
                raise RuntimeError("Cannot activate a disposed agent.")
            self.state = AgentState.ACTIVE

        self._life_loop()

    def _life_loop(self):
        """
        Main execution loop for the agentic thread.

        Based on the agent's pool type, it dynamically transitions into appropriate
        registered locations like dispatcher, throughput, or sleep. If no such behavior
        is required, it returns to idle or home state.
        """
        self._notify(f"Agentic thread started {self.factory_id}.")

        while not self._dismiss_agent:
            if self._dismiss_agent:
                break
#TODO: Investigate a dictionary design instead to create O(1) lookups for locations instead of loops for if statements
            if self._pool_agent and not self._return_home:
                if self._pool_type == AgentPoolType.DISPATCHER:
                    if self.location_map.get("dispatcher"):
                        self.location_map.transit_to("dispatcher")
                elif self._pool_type == AgentPoolType.RESERVED_DISPATCHER:
                    if self.location_map.get("reserved_dispatcher"):
                        self.location_map.transit_to("reserved_dispatcher")
                elif self._pool_type == AgentPoolType.THROUGHPUT:
                    if self.location_map.get("throughput"):
                        self.location_map.transit_to("throughput")
                elif self._pool_type == AgentPoolType.SLEEP:
                    if self.location_map.get("sleep"):
                        self.location_map.transit_to("sleep")
            else:
                self._return_home = False

        self._logger.info(f"Agent '{self.factory_id}' lifeloop terminated.")
        self.dispose()

    def _dispatcher_loop(self) -> None:
        """
        The dispatcher logic registered as a named location.

        Attempts to run the target, then the dispatcher behavior.
        """
        if self.location_map.get("target"):
            self.location_map.transit_to("target")

        if self.location_map.get("dispatcher"):
            self.location_map.transit_to("dispatcher")

    def assign_new_state(self, state: str) -> None:
        """
        Assigns a new state to the agent, updating its internal state and notifying
        the command center of the change.

        Args:
            state (str): The new state name (case-insensitive) or an AgentState instance.
        """
        with self._lock:
            if self._disposed:
                raise RuntimeError("Cannot assign state to a disposed agent.")

            self.state = EnumHelpers.convert_enum_and_check(state, AgentState)
            self._notify(f"Agent {self.factory_id} changed state to {self.state.name}.")

    #endregion Agentic Activity
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

    def get_from_private_inventory(self, key: str, default=None) -> Any:
        """
        Retrieves a value from the private inventory of this agent, only if the calling thread has the
        correct `factory_id`.

        Args:
            key (str): The key of the item to retrieve.
            default (Any, optional): The value to return if the key is not found. Defaults to None.

        Returns:
            Any: The value from the inventory, or the default value if not found.
        """
        self._validate_caller()  # Validate caller using the existing method
        return self._private_inventory.get(key, default)

    def put_in_private_inventory(self, key: str, value: Any) -> None:
        """
        Puts a value in the private inventory of this agent, only if the calling thread has the
        correct `factory_id`.

        Args:
            key (str): The key under which to store the value.
            value (Any): The value to store in the inventory.
        """
        self._validate_caller()  # Validate caller using the existing method
        self._private_inventory[key] = value
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