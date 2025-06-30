from typing import Callable, Optional, Any
from thread_factory.runtime import Worker, WorkerState
from thread_factory.agent_thread_pool.help_request import HelpRequest
from thread_factory.runtime.orchestrator.monitoring.records.records import WorkStatus, Record
from thread_factory.utils.general_helpers.coroutine_helpers import CoroutineHelpers
import threading

class Agent(Worker):
    """
    Agent
    -------------
    An advanced, agentic thread object designed for sophisticated, long-lived operations
    within a dynamic execution pool. Building upon the foundational `Worker` class,
    `Agent` introduces a rich set of features that enable adaptive behavior,
    stateful operations, and flexible data management.

    This class empowers developers to create intelligent, self-managing worker threads
    capable of routing their own behavior, managing their own memory, and coordinating
    complex tasks through bound work requests.

    Key Features:
    - **Location-Based Behavior Routing**: Define named `save_points` for checkpointing
      and resuming execution, and `locations` for defining specific callable execution
      zones, enabling dynamic navigation of a worker's operational flow.
    - **Bound Work Integration**: Seamlessly integrates with `HelpRequest` objects,
      allowing the worker to "bind" to a specific unit of work, track its status,
      and execute it upon acquisition.
    - **Rich State Tracking & Mutability**: Extends the base `WorkerState` with
      detailed work status tracking (in progress, completed, failed, cancelled, pending).
    - **Thread-Local and Shared Inventories**: Provides both private, thread-local
      memory (`_inventory`) for isolated state and a `shared_inventory` for
      globally accessible data, facilitating flexible data management.
    - **Callable-Based Data Pipelines**: The `data_transfer` mechanism allows for
      registration and execution of callable functions to facilitate dynamic
      data movement and processing within the worker's context.
    - **Optional ID-Enforced Access Controls**: Implement secure access to worker
      properties and methods by validating the `factory_id` of the calling thread,
      ensuring controlled interactions in multi-worker environments.

    This class is ideal for scenarios requiring autonomous agents, long-running
    processes with state, and dynamic task execution in thread-pooled systems.

    Attributes:
        _save_points (dict[str, Callable[[], None]]):
            A private dictionary storing named callable functions. These functions
            represent points in the worker's execution flow that can be returned to,
            serving as "checkpoints" or "resume points" for complex behaviors.
            Each key is a string name, and each value is a parameterless callable.
            Exposed via `get_save_points_dict()`.

        _locations (dict[str, Callable[[], None]]):
            A private dictionary storing named callable functions. These functions
            represent distinct "execution zones" or specialized behaviors that the
            worker can dynamically "move into" or invoke.
            Each key is a string name, and each value is a parameterless callable.
            Exposed via `get_locations_dict()`.

        _event_loop (Optional[Callable[[], None]]):
            A private, optional callable that defines the worker's primary
            or "home" execution loop. This function is invoked when the worker's
            `run` method is called, dictating its default behavior. It must be
            set before the worker starts via `set_home()`.

        _value_work (HelpRequest | None):
            A private, optional `HelpRequest` instance. When set, this
            represents the specific unit of work (job) that this `Agent`
            is currently responsible for processing. Its lifecycle is managed
            by methods within this class (e.g., `set_value_work()`, `get_value_work()`).

        _worker_type (str):
            A string identifier specifying the type of this worker.
            Hardcoded to "dynamic" to distinguish it from other worker types.

        _inventory (threading.local):
            A `threading.local()` object. This ensures that the `data` dictionary
            stored within it (`_inventory.data`) is strictly private and accessible
            only to the thread associated with this specific `Agent` instance.
            It prevents data conflicts in multi-threaded environments. This acts as
            the worker's personal memory or scratchpad. Data is accessed via
            `bind_to_inventory()` and `get_from_inventory()`.

        _shared_inventory (dict[str, Any]):
            A private, standard Python dictionary that serves as a global repository
            for data accessible by all `Agent` instances (and potentially
            other components of the system). Access to this inventory should consider
            thread-safety mechanisms if concurrent writes are expected from multiple workers.
            Accessed via `set_shared_inventory_item()`, `get_shared_inventory_item()`,
            and `get_shared_inventory()`.

        _data_transfer (dict[str, Callable[..., Any]]):
            A private dictionary mapping string names to callable functions.
            These callables are designed to facilitate data movement or processing
            within the worker. They act as named pipelines or transformations
            that can be invoked to handle specific data-related operations via
            `execute_transfer()`. Each callable should typically be parameterless
            for direct execution via `execute_transfer()`.
            Exposed via `get_data_transfer_dict()` and `register_data_transfer()`.

    Example Usage:
    ```python
    from thread_factory.runtime import WorkerConfig
    from thread_factory.dynamic_thread_pool.help_request import HelpRequest

    def my_upload_logic():
        print(f"Worker {threading.current_thread().factory_id} is uploading data...")
        # Simulate some work
        import time
        time.sleep(1)
        print(f"Worker {threading.current_thread().factory_id} finished uploading.")

    def my_home_behavior():
        print(f"Worker {threading.current_thread().factory_id} is at home, checking for work...")
        if worker.get_value_work(): # Use getter
            worker.acquire_and_run_work()
            if worker.get_work_state() == WorkStatus.COMPLETED:
                print(f"Worker {threading.current_thread().factory_id} successfully completed work!")
                worker.dispose_work()
            else:
                print(f"Worker {threading.current_thread().factory_id} work status: {worker.get_work_state().name}")
        else:
            print(f"Worker {threading.current_thread().factory_id} has no work bound.")
        # Optionally, move to a registered location or save point
        if "upload_process" in worker.get_locations_dict(): # Use getter
            worker.get_locations_dict()["upload_process"]() # Use getter


    # Create a Agent instance
    config = WorkerConfig(worker_name="MyDynamicAgent", target_function=None) # target_function will be set by set_home
    worker = Agent(config)

    # Bind some private data to the worker's inventory
    worker.bind_to_inventory("api_key", "sk-12345abcdef")
    print(f"Worker's API Key: {worker.get_from_inventory('api_key')}")

    # Register a specific behavior location
    worker.register_location("upload_process", my_upload_logic)

    # Set the worker's default 'home' behavior
    worker.set_home(my_home_behavior)

    # Create a dummy HelpRequest and bind it (using new setter)
    dummy_request = HelpRequest(job_id="job_001", job_data={"file": "report.pdf"})
    worker.set_value_work(dummy_request) # Using the new setter method

    # Start the worker thread
    worker.start()
    worker.join() # Wait for the worker to complete its home behavior and finish

    print(f"Final state of worker: {worker.state.name}")
    ```
    """

    def __init__(self, *args, **kwargs):
        """
        Initializes a new Agent instance.

        This constructor extends the base `Worker` initialization by setting up
        specific attributes crucial for the dynamic and agentic behaviors,
        including behavior coordination points, and both thread-local and shared
        memory inventories.

        Args:
            *args: Arbitrary positional arguments passed to the base `Worker` constructor.
            **kwargs: Arbitrary keyword arguments passed to the base `Worker` constructor.
        """
        super().__init__(*args, **kwargs)

        # --- Behavior Coordination (Private Attributes) ---
        self._save_points: dict[str, Callable[[], None]] = {}
        self._locations: dict[str, Callable[[], None]] = {}
        self._event_loop: Optional[Callable[[], None]] = None
        self._value_work: HelpRequest | None = None
        self._worker_type = "agentic"

        # --- Agentic Memory (Inventory) (Private Attributes) ---
        self._inventory = threading.local()
        self._inventory.data = {}
        self._shared_inventory: dict[str, Any] = {}
        self._data_transfer: dict[str, Callable[..., Any]] = {}


    # --- Core Work Lifecycle Handling ---
    def set_work_state(self, new_state: WorkStatus) -> None:
        """
        Sets the status of the `HelpRequest` currently bound to this worker.

        This method provides a controlled way to update the progress or outcome
        of the active work item.

        Args:
            new_state (WorkStatus): The new status to apply to the bound work
                                    (e.g., WorkStatus.IN_PROGRESS, WorkStatus.COMPLETED).
        """
        if self._value_work:
            self._value_work.set_state(new_state)

    def get_work_state(self) -> Optional[WorkStatus]:
        """
        Retrieves the current status of the `HelpRequest` bound to this worker.

        This allows external components or the worker itself to query the
        progress or outcome of its active task.

        Returns:
            Optional[WorkStatus]: The current status of the bound work (e.g.,
                                  WorkStatus.PENDING, WorkStatus.COMPLETED),
                                  or `None` if no `HelpRequest` is currently bound.
        """
        if self._value_work:
            return self._value_work.get_state()
        return None

    def get_value_work(self) -> Optional[HelpRequest]:
        """
        Retrieves the `HelpRequest` instance currently bound to this worker.

        This provides controlled read access to the active work item.

        Returns:
            Optional[HelpRequest]: The bound `HelpRequest` object, or `None` if
                                   no work is currently assigned.
        """
        return self._value_work

    def set_value_work(self, help_request: HelpRequest) -> None:
        """
        Binds a `HelpRequest` instance to this worker.

        This method assigns a specific unit of work for the `Agent`
        to process.

        Args:
            help_request (HelpRequest): The `HelpRequest` object to bind to the worker.
        """
        self._value_work = help_request

    def mark_work_in_progress(self) -> None:
        """
        Marks the currently bound `HelpRequest` as 'in progress'.

        This is a convenience method for quickly updating the work status
        to indicate active processing.
        """
        if self._value_work:
            self._value_work.mark_in_progress()

    def mark_work_completed(self) -> None:
        """
        Marks the currently bound `HelpRequest` as 'completed'.

        This signals successful conclusion of the assigned work.
        """
        if self._value_work:
            self._value_work.mark_completed()

    def mark_work_failed(self) -> None:
        """
        Marks the currently bound `HelpRequest` as 'failed'.

        This indicates that the assigned work could not be successfully completed.
        """
        if self._value_work:
            self._value_work.mark_failed()

    def mark_work_cancelled(self) -> None:
        """
        Marks the currently bound `HelpRequest` as 'cancelled'.

        This is used when the assigned work has been externally aborted or withdrawn.
        """
        if self._value_work:
            self._value_work.mark_cancelled()

    def reset_work(self) -> None:
        """
        Resets the currently bound `HelpRequest` to its initial 'pending' state.

        This can be useful for retrying failed work or re-queuing a task.
        """
        if self._value_work:
            self._value_work.reset()

    def get_work_record(self) -> Optional[Record]:
        """
        Retrieves the `Record` object associated with the currently bound `HelpRequest`.

        The `Record` typically contains metadata, status history, and results
        related to the execution of the `HelpRequest`.

        Returns:
            Optional[Record]: The `Record` instance if work is bound, otherwise `None`.
        """
        if self._value_work:
            return self._value_work.get_record()
        return None

    def acquire_and_run_work(self):
        """
        Initiates the execution of the `HelpRequest` currently bound to this worker.

        This method instructs the bound `HelpRequest` to acquire and then execute
        its designated task. The actual work logic resides within the `HelpRequest`
        implementation.
        """
        if self._value_work:
            self._value_work.acquire_work()

    def cancel_bound_job(self):
        """
        Cancels the job associated with the `HelpRequest` currently bound to this worker.

        This method triggers the cancellation mechanism defined within the
        `HelpRequest`, potentially stopping ongoing work gracefully.
        """
        if self._value_work:
            self._value_work.cancel_job()

    def dispose_work(self) -> None:
        """
        Disposes of the `HelpRequest` currently bound to this worker and
        detaches it, clearing the reference.

        This is typically called when a work item is no longer needed or after
        its completion/failure, allowing for resource cleanup.
        """
        if self._value_work:
            self._value_work.dispose()
            self._value_work = None

    # --- Behavior Routing ---
    def register_save_point(self, name: str, fn: Callable[[], None]) -> None:
        """
        Registers a callable function as a named "save point".

        Save points allow the worker to record specific states or behaviors
        that can be returned to or triggered later. This is particularly useful
        for implementing retry mechanisms, step-wise processing, or stateful
        resumption of tasks.

        Args:
            name (str): A unique string identifier for the save point.
            fn (Callable[[], None]): A parameterless callable function that
                                     encapsulates the behavior associated with this
                                     save point.

        Raises:
            TypeError: If the provided `fn` is a coroutine function, as `Agent`
                       is not designed to `await` coroutines directly in its synchronous
                       execution loop.
        """
        if CoroutineHelpers.is_coroutine(fn):
            raise TypeError(f"Cannot register coroutine function '{name}' as a save point. Agent runs synchronously.")
        self._save_points[name] = fn

    def get_save_points_dict(self) -> dict[str, Callable[[], None]]:
        """
        Retrieves a copy of the dictionary of registered save points.

        This method provides read-only access to the collection of named callable
        functions that represent checkpoints for the worker's execution.

        Returns:
            dict[str, Callable[[], None]]: A dictionary where keys are save point names
                                           and values are the associated callable functions.
                                           Returns a shallow copy to prevent external modification.
        """
        return self._save_points.copy()

    def register_location(self, name: str, fn: Callable[[], None]) -> None:
        """
        Registers a callable function as a named "location" or execution zone.

        Locations represent distinct operational phases or functional areas
        within the worker's lifecycle. The worker can "move into" these locations
        by invoking the associated callable, enabling dynamic behavior routing.

        Args:
            name (str): A unique string identifier for the location.
            fn (Callable[[], None]): A parameterless callable function that
                                     defines the behavior or set of operations
                                     performed when the worker is at this location.

        Raises:
            TypeError: If the provided `fn` is a coroutine function, as `Agent`
                       is not designed to `await` coroutines directly in its synchronous
                       execution loop.
        """
        if CoroutineHelpers.is_coroutine(fn):
            raise TypeError(f"Cannot register coroutine function '{name}' as a location. Agent runs synchronously.")
        self._locations[name] = fn

    def get_locations_dict(self) -> dict[str, Callable[[], None]]:
        """
        Retrieves a copy of the dictionary of registered locations.

        This method provides read-only access to the collection of named callable
        functions that represent distinct execution zones or behaviors for the worker.

        Returns:
            dict[str, Callable[[], None]]: A dictionary where keys are location names
                                           and values are the associated callable functions.
                                           Returns a shallow copy to prevent external modification.
        """
        return self._locations.copy()

    def set_home(self, fn: Callable[[], None]) -> None:
        """
        Sets the primary, default execution loop or "home behavior" for the worker.

        This function defines what the `Agent` will do when its `run()`
        method is invoked. It is the core behavior that the worker continuously
        executes unless explicitly directed otherwise.

        Args:
            fn (Callable[[], None]): A parameterless callable function that
                                     represents the worker's main operational loop.
                                     This function will be executed repeatedly
                                     (or once, if designed that way) by the worker thread.

        Raises:
            TypeError: If the provided `fn` is a coroutine function, as `Agent`
                       is not designed to `await` coroutines directly in its synchronous
                       execution loop.
        """
        if CoroutineHelpers.is_coroutine(fn):
            raise TypeError("Cannot set a coroutine function as home. Agent runs synchronously.")
        self._event_loop = fn

    def run(self):
        """
        The main execution entry point for the Agent thread.

        This method is automatically called when `worker.start()` is invoked.
        It first performs initial setup (binding the factory ID), sets the
        worker's state to STARTING, then executes the `_event_loop` (the
        "home" function). If no home function has been set, a `RuntimeError`
        is raised. Upon completion of the home function, it signals its
        imminent death.
        """
        self._bind_factory_id()
        self.state = WorkerState.STARTING
        if self._event_loop is None:
            raise RuntimeError(f"[Worker {self.factory_id}] No home() set before thread start.")
        self._event_loop()
        self.death_event.set()

    # --- Inventory Management ---
    def bind_to_inventory(self, key: str, value: Any, factory_id: Optional[str] = None, enforce_id: bool = False):
        """
        Binds a key-value pair to this worker's *private, thread-local* inventory.

        This method allows the worker to store data that is exclusively accessible
        by itself, preventing interference from other threads. Optionally, it can
        enforce that only a caller with a specific `factory_id` can perform this binding.

        Args:
            key (str): The unique string key under which to store the value.
            value (Any): The data to be stored. Can be of any Python type.
            factory_id (Optional[str]): An optional `factory_id` to enforce caller
                                       identity. If `enforce_id` is True and this
                                       is provided, the caller's thread ID must match.
            enforce_id (bool): If `True`, the `_validate_caller` method will be
                               invoked to ensure the current thread's `factory_id`
                               matches `factory_id` (or this worker's own ID if
                               `factory_id` is None). Raises `PermissionError` on mismatch.
        """
        if enforce_id:
            self._validate_caller(factory_id)
        self._inventory.data[key] = value

    def get_from_inventory(self, key: str, default=None, factory_id: Optional[str] = None, enforce_id: bool = False) -> Any:
        """
        Retrieves a value from this worker's *private, thread-local* inventory.

        This method provides controlled access to the worker's isolated memory.
        Similar to `bind_to_inventory`, it can enforce ID-based access control.

        Args:
            key (str): The key of the item to retrieve from the inventory.
            default (Any, optional): The value to return if the `key` is not found
                                     in the inventory. Defaults to `None`.
            factory_id (Optional[str]): An optional `factory_id` to enforce caller
                                       identity. If `enforce_id` is True and this
                                       is provided, the caller's thread ID must match.
            enforce_id (bool): If `True`, the `_validate_caller` method will be
                               invoked to ensure the current thread's `factory_id`
                               matches `factory_id` (or this worker's own ID if
                               `factory_id` is None). Raises `PermissionError` on mismatch.

        Returns:
            Any: The value associated with the `key` if found, otherwise the `default` value.
        """
        if enforce_id:
            self._validate_caller(factory_id)
        return self._inventory.data.get(key, default)

    def set_shared_inventory_item(self, key: str, value: Any) -> None:
        """
        Sets a key-value pair in the shared inventory.

        The shared inventory is accessible across all `Agent` instances
        and other components that can reach this worker object.

        Args:
            key (str): The key under which to store the value.
            value (Any): The value to store.
        """
        self._shared_inventory[key] = value

    def get_shared_inventory_item(self, key: str, default: Any = None) -> Any:
        """
        Retrieves a value from the shared inventory.

        Args:
            key (str): The key of the item to retrieve.
            default (Any, optional): The value to return if the key is not found. Defaults to `None`.

        Returns:
            Any: The value associated with the key, or the default value if not found.
        """
        return self._shared_inventory.get(key, default)

    def get_shared_inventory(self) -> dict[str, Any]:
        """
        Retrieves the entire shared inventory dictionary.

        Note: This returns a direct reference to the internal dictionary.
        Modifications to the returned dictionary will affect the worker's
        shared state. Use `set_shared_inventory_item` for controlled updates.

        Returns:
            dict[str, Any]: The shared inventory dictionary.
        """
        return self._shared_inventory

    def register_data_transfer(self, name: str, fn: Callable[..., Any]) -> None:
        """
        Registers a callable function for data transfer operations.

        These functions can be invoked via `execute_transfer` to perform specific
        data processing or movement tasks.

        Args:
            name (str): The unique name for the data transfer function.
            fn (Callable[..., Any]): The callable function to register. It should
                                     typically be parameterless for use with `execute_transfer`.

        Raises:
            TypeError: If the provided `fn` is a coroutine function.
        """
        if CoroutineHelpers.is_coroutine(fn):
            raise TypeError(f"Cannot register coroutine function '{name}' for data transfer. Agent runs synchronously.")
        self._data_transfer[name] = fn

    def get_data_transfer_dict(self) -> dict[str, Callable[..., Any]]:
        """
        Retrieves a copy of the dictionary of registered data transfer functions.

        Returns:
            dict[str, Callable[..., Any]]: A dictionary where keys are transfer names
                                           and values are the associated callable functions.
                                           Returns a shallow copy to prevent external modification.
        """
        return self._data_transfer.copy()

    def execute_transfer(self, name: str, factory_id: Optional[str] = None, enforce_id: bool = False) -> Any:
        """
        Executes a callable function registered within the `_data_transfer` dictionary.

        This method allows for the invocation of predefined data handling routines
        or pipelines by their registered name. It can also enforce access control
        based on the caller's `factory_id`.

        Args:
            name (str): The unique string name of the transfer callable to execute.
                        This name must correspond to a key in the `self._data_transfer`
                        dictionary.
            factory_id (Optional[str]): If provided and `enforce_id` is True, this
                                       `factory_id` is used to validate the caller's
                                       identity.
            enforce_id (bool): If `True`, the `_validate_caller` method will be
                               invoked to ensure the current thread's `factory_id`
                               matches `factory_id` (or this worker's own ID if
                               `factory_id` is None).

        Returns:
            Any: The result returned by the executed data transfer function.
                 The return type depends entirely on the registered callable.

        Raises:
            KeyError: If no data transfer function is registered under the given `name`.
            PermissionError: If `enforce_id` is True and the caller's thread ID does
                             not match the expected `factory_id`.
        """
        if enforce_id:
            self._validate_caller(factory_id)
        if name not in self._data_transfer:
            raise KeyError(f"No data_transfer entry named '{name}'")
        return self._data_transfer[name]()

    def _validate_caller(self, factory_id: Optional[str] = None) -> None:
        """
        Internal method to validate if the current calling thread's `factory_id`
        matches an expected ID.

        This method is a security measure used by other methods (like inventory access)
        to ensure that only authorized `Agent` instances (or threads with
        specific IDs) can perform certain operations.

        Args:
            factory_id (Optional[str]): The `factory_id` to compare against the
                                       current thread's ID. If `None`, this worker's
                                       own `factory_id` (`self.factory_id`) is used
                                       as the expected ID.

        Raises:
            PermissionError: If the current thread's `factory_id` does not match
                             the `expected` `factory_id`.
        """
        expected = factory_id or self.factory_id
        current_id = getattr(threading.current_thread(), "factory_id", None)
        if current_id != expected:
            raise PermissionError(
                f"[Access Denied] Caller factory_id={current_id} does not match expected={expected}"
            )

    # --- External Access (ID-Based) ---
    def get_factory_id(self) -> str:
        """
        Retrieves the unique factory ID assigned to this `Agent` instance.

        The factory ID serves as a unique identifier for the worker within its
        hosting factory or pool, enabling specific targeting and management.

        Returns:
            str: The unique string identifier of this worker.
        """
        return self.factory_id

    def bind_to_inventory_by_id(self, factory_id: str, key: str, value: Any) -> None:
        """
        Binds a value to the private inventory of *another* `Agent` instance,
        identified by its `factory_id`.

        This method allows for inter-worker communication and state manipulation,
        where one worker can directly inject data into another worker's private memory.

        Args:
            factory_id (str): The unique `factory_id` of the target `Agent`
                              whose inventory will be modified.
            key (str): The key under which the `value` will be stored in the target worker's
                       private inventory.
            value (Any): The data to be stored in the target worker's inventory.
        """
        worker = self._resolve_worker_by_id(factory_id)
        if worker:
            worker.bind_to_inventory(key, value)

    def get_from_inventory_by_id(self, factory_id: str, key: str, default=None) -> Any:
        """
        Retrieves a value from the private inventory of *another* `Agent` instance,
        identified by its `factory_id`.

        This method enables one worker to inspect or retrieve data from another
        worker's private memory, facilitating observation or data sharing patterns.

        Args:
            factory_id (str): The unique `factory_id` of the target `Agent`
                              from whose inventory the value will be retrieved.
            key (str): The key of the item to retrieve from the target worker's
                       private inventory.
            default (Any, optional): The value to return if the `key` is not found
                                     in the target worker's inventory. Defaults to `None`.

        Returns:
            Any: The value associated with the `key` in the target worker's inventory,
                 or the `default` value if the key is not found or the target worker
                 cannot be resolved.
        """
        worker = self._resolve_worker_by_id(factory_id)
        if worker:
            return worker.get_from_inventory(key, default)
        return default

    def _resolve_worker_by_id(self, factory_id: str) -> Optional['Agent']:
        """
        Internal helper method to resolve a `Agent` instance by its `factory_id`.

        This method attempts to locate another `Agent` within the system
        (typically through the `factory` object that created this worker).
        It is a crucial component for enabling inter-worker communication by ID.

        NOTE: This method relies on the `factory` attribute of the worker. For this
        functionality to work, the `factory` (e.g., a `DynamicThreadPool`) must
        have a `get_worker_by_id` method implemented and correctly associated
        with this worker. If your `factory` does not provide this, you may need
        to override this method in a custom subclass or inject the lookup mechanism.

        Args:
            factory_id (str): The unique ID of the `Agent` instance to resolve.

        Returns:
            Optional['Agent']: The `Agent` instance if found, otherwise `None`.
        """
        if self.factory and hasattr(self.factory, "get_worker_by_id"):
            return self.factory.get_worker_by_id(factory_id)
        return None

    # --- Disposal ---
    def dispose(self):
        """
        Performs a comprehensive cleanup of the `Agent`'s agentic state
        and then triggers the disposal process of its base `Worker` class.

        This method ensures that all dynamic behaviors, memory structures, and
        bound work are properly cleared to prevent resource leaks or unintended
        side effects upon worker termination or recycling. It's safe to call
        multiple times.
        """
        if self.disposed:
            return
        self.dispose_work()
        if self._save_points is not None:
            self._save_points.clear()
        self._save_points = None
        if self._locations is not None:
            self._locations.clear()
        self._locations = None
        self._event_loop = None
        self._disposed = True
        self.state = WorkerState.DISPOSED

    def __repr__(self):
        """
        Provides a developer-friendly string representation of the `Agent` instance.

        This representation is useful for debugging and logging, showing the
        worker's unique identifier and its current operational state.

        Returns:
            str: A formatted string showing the worker's `factory_id` and its
                 current `WorkerState` name.
        """
        return f"<AgenticWorker id={self.factory_id} state={self.state.name}>"