from typing import Callable, Optional, Any
from thread_factory.runtime import Worker, WorkerState
from thread_factory.dynamic_thread_pool.help_request import HelpRequest
from thread_factory.runtime.orchestrator.monitoring.records.records import WorkStatus, Record
import threading


class DynamicWorker(Worker):
    """
    DynamicWorker
    -------------
    An advanced, agentic thread object designed for sophisticated, long-lived operations
    within a dynamic execution pool. Building upon the foundational `Worker` class,
    `DynamicWorker` introduces a rich set of features that enable adaptive behavior,
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
        if worker._value_work:
            worker.acquire_and_run_work()
            if worker.get_work_state() == WorkStatus.COMPLETED:
                print(f"Worker {threading.current_thread().factory_id} successfully completed work!")
                worker.dispose_work()
            else:
                print(f"Worker {threading.current_thread().factory_id} work status: {worker.get_work_state().name}")
        else:
            print(f"Worker {threading.current_thread().factory_id} has no work bound.")
        # Optionally, move to a registered location or save point
        if "upload" in worker.locations:
            worker.locations["upload"]()


    # Create a DynamicWorker instance
    config = WorkerConfig(worker_name="MyDynamicAgent", target_function=None) # target_function will be set by set_home
    worker = DynamicWorker(config)

    # Bind some private data to the worker's inventory
    worker.bind_to_inventory("api_key", "sk-12345abcdef")
    print(f"Worker's API Key: {worker.get_from_inventory('api_key')}")

    # Register a specific behavior location
    worker.register_location("upload_process", my_upload_logic)

    # Set the worker's default 'home' behavior
    worker.set_home(my_home_behavior)

    # Create a dummy HelpRequest and bind it
    dummy_request = HelpRequest(job_id="job_001", job_data={"file": "report.pdf"})
    worker._value_work = dummy_request # Directly binding for example purposes

    # Start the worker thread
    worker.start()
    worker.join() # Wait for the worker to complete its home behavior and finish

    print(f"Final state of worker: {worker.state.name}")
    ```
    """

    def __init__(self, *args, **kwargs):
        """
        Initializes a new DynamicWorker instance.

        This constructor extends the base `Worker` initialization by setting up
        specific attributes crucial for the dynamic and agentic behaviors,
        including behavior coordination points, and both thread-local and shared
        memory inventories.

        Args:
            *args: Arbitrary positional arguments passed to the base `Worker` constructor.
            **kwargs: Arbitrary keyword arguments passed to the base `Worker` constructor.
        """
        super().__init__(*args, **kwargs)

        # --- Behavior Coordination ---
        # `save_points`: A dictionary storing named callable functions. These functions
        # represent points in the worker's execution flow that can be returned to,
        # serving as "checkpoints" or "resume points" for complex behaviors.
        # Each key is a string name, and each value is a parameterless callable.
        self.save_points: dict[str, Callable[[], None]] = {}
        # `locations`: A dictionary storing named callable functions. These functions
        # represent distinct "execution zones" or specialized behaviors that the
        # worker can dynamically "move into" or invoke. Similar to save_points,
        # each key is a string name, and each value is a parameterless callable.
        self.locations: dict[str, Callable[[], None]] = {}
        # `_event_loop`: An optional callable that defines the worker's primary
        # or "home" execution loop. This function is invoked when the worker's
        # `run` method is called, dictating its default behavior. It must be
        # set before the worker starts.
        self._event_loop: Optional[Callable[[], None]] = None
        # `_value_work`: An optional `HelpRequest` instance. When set, this
        # represents the specific unit of work (job) that this `DynamicWorker`
        # is currently responsible for processing. Its lifecycle is managed
        # by methods within this class.
        self._value_work: HelpRequest | None = None
        # `_worker_type`: A string identifier specifying the type of this worker.
        # Hardcoded to "dynamic" to distinguish it from other worker types.
        self._worker_type = "dynamic"

        # --- Agentic Memory (Inventory) ---
        # `_inventory`: A `threading.local()` object. This ensures that the
        # `data` dictionary stored within it is strictly private and accessible
        # only to the thread associated with this specific `DynamicWorker` instance.
        # It prevents data conflicts in multi-threaded environments.
        self._inventory = threading.local()
        # `_inventory.data`: The actual dictionary used to store thread-local,
        # private key-value data for this worker. This acts as the worker's
        # personal memory or scratchpad.
        self._inventory.data = {}
        # `shared_inventory`: A standard Python dictionary that serves as a
        # global repository for data accessible by all `DynamicWorker` instances
        # (and potentially other components of the system). Access to this
        # inventory should consider thread-safety mechanisms if concurrent writes
        # are expected from multiple workers.
        self.shared_inventory: dict[str, Any] = {}
        # `data_transfer`: A dictionary mapping string names to callable functions.
        # These callables are designed to facilitate data movement or processing
        # within the worker. They act as named pipelines or transformations
        # that can be invoked to handle specific data-related operations.
        # Each callable should typically be parameterless for direct execution
        # via `execute_transfer`.
        self.data_transfer: dict[str, Callable[..., Any]] = {}

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
        # Checks if a HelpRequest (`_value_work`) is currently bound to this worker.
        if self._value_work:
            # Delegates the state update to the bound HelpRequest object.
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
        # Checks if a HelpRequest (`_value_work`) is currently bound to this worker.
        if self._value_work:
            # Returns the current status directly from the bound HelpRequest.
            return self._value_work.get_state()
        # If no work is bound, indicates by returning None.
        return None

    def mark_work_in_progress(self) -> None:
        """
        Marks the currently bound `HelpRequest` as 'in progress'.

        This is a convenience method for quickly updating the work status
        to indicate active processing.
        """
        # Checks if a HelpRequest is bound.
        if self._value_work:
            # Updates the state of the bound HelpRequest to WorkStatus.IN_PROGRESS.
            self._value_work.mark_in_progress()

    def mark_work_completed(self) -> None:
        """
        Marks the currently bound `HelpRequest` as 'completed'.

        This signals successful conclusion of the assigned work.
        """
        # Checks if a HelpRequest is bound.
        if self._value_work:
            # Updates the state of the bound HelpRequest to WorkStatus.COMPLETED.
            self._value_work.mark_completed()

    def mark_work_failed(self) -> None:
        """
        Marks the currently bound `HelpRequest` as 'failed'.

        This indicates that the assigned work could not be successfully completed.
        """
        # Checks if a HelpRequest is bound.
        if self._value_work:
            # Updates the state of the bound HelpRequest to WorkStatus.FAILED.
            self._value_work.mark_failed()

    def mark_work_cancelled(self) -> None:
        """
        Marks the currently bound `HelpRequest` as 'cancelled'.

        This is used when the assigned work has been externally aborted or withdrawn.
        """
        # Checks if a HelpRequest is bound.
        if self._value_work:
            # Updates the state of the bound HelpRequest to WorkStatus.CANCELLED.
            self._value_work.mark_cancelled()

    def reset_work(self) -> None:
        """
        Resets the currently bound `HelpRequest` to its initial 'pending' state.

        This can be useful for retrying failed work or re-queuing a task.
        """
        # Checks if a HelpRequest is bound.
        if self._value_work:
            # Resets the state of the bound HelpRequest to WorkStatus.PENDING.
            self._value_work.reset()

    def get_work_record(self) -> Optional[Record]:
        """
        Retrieves the `Record` object associated with the currently bound `HelpRequest`.

        The `Record` typically contains metadata, status history, and results
        related to the execution of the `HelpRequest`.

        Returns:
            Optional[Record]: The `Record` instance if work is bound, otherwise `None`.
        """
        # Checks if a HelpRequest is bound.
        if self._value_work:
            # Returns the Record object from the bound HelpRequest.
            return self._value_work.get_record()
        # Returns None if no work is currently bound.
        return None

    def acquire_and_run_work(self):
        """
        Initiates the execution of the `HelpRequest` currently bound to this worker.

        This method instructs the bound `HelpRequest` to acquire and then execute
        its designated task. The actual work logic resides within the `HelpRequest`
        implementation.
        """
        # Checks if a HelpRequest is currently bound to the worker.
        if self._value_work:
            # Calls the `acquire_work` method on the bound HelpRequest, which typically
            # handles the execution of the work item.
            self._value_work.acquire_work()

    def cancel_bound_job(self):
        """
        Cancels the job associated with the `HelpRequest` currently bound to this worker.

        This method triggers the cancellation mechanism defined within the
        `HelpRequest`, potentially stopping ongoing work gracefully.
        """
        # Checks if a HelpRequest is currently bound.
        if self._value_work:
            # Invokes the `cancel_job` method on the bound HelpRequest.
            self._value_work.cancel_job()

    def dispose_work(self) -> None:
        """
        Disposes of the `HelpRequest` currently bound to this worker and
        detaches it, clearing the reference.

        This is typically called when a work item is no longer needed or after
        its completion/failure, allowing for resource cleanup.
        """
        # Checks if a HelpRequest is currently bound.
        if self._value_work:
            # Calls the `dispose` method on the bound HelpRequest for cleanup.
            self._value_work.dispose()
            # Clears the reference to the HelpRequest, effectively detaching it.
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
        """
        self.save_points[name] = fn

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
        """
        self.locations[name] = fn

    def set_home(self, fn: Callable[[], None]) -> None:
        """
        Sets the primary, default execution loop or "home behavior" for the worker.

        This function defines what the `DynamicWorker` will do when its `run()`
        method is invoked. It is the core behavior that the worker continuously
        executes unless explicitly directed otherwise.

        Args:
            fn (Callable[[], None]): A parameterless callable function that
                                     represents the worker's main operational loop.
                                     This function will be executed repeatedly
                                     (or once, if designed that way) by the worker thread.
        """
        self._event_loop = fn

    def run(self):
        """
        The main execution entry point for the DynamicWorker thread.

        This method is automatically called when `worker.start()` is invoked.
        It first performs initial setup (binding the factory ID), sets the
        worker's state to STARTING, then executes the `_event_loop` (the
        "home" function). If no home function has been set, a `RuntimeError`
        is raised. Upon completion of the home function, it signals its
        imminent death.
        """
        # Binds the unique factory ID of this worker to the current thread.
        # This is crucial for ID-based access controls and tracing.
        self._bind_factory_id()
        # Updates the worker's internal state to indicate that it is beginning execution.
        self.state = WorkerState.STARTING
        # Critically checks if a "home" function (`_event_loop`) has been assigned.
        # A worker cannot operate without a defined main behavior.
        if self._event_loop is None:
            # If no home function is set, raises an error, indicating a misconfiguration.
            raise RuntimeError(f"[Worker {self.factory_id}] No home() set before thread start.")
        # Executes the primary, "home" behavior defined for this worker.
        # All core operational logic typically flows from this single call.
        self._event_loop()
        # Sets the `death_event`, signaling to any waiting components (e.g., the pool)
        # that this worker has completed its execution and is ready for termination/cleanup.
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
        # If `enforce_id` is True, validate that the calling thread has the correct factory ID.
        if enforce_id:
            self._validate_caller(factory_id)
        # Store the `value` in the thread-local `_inventory.data` dictionary
        # under the specified `key`. This data is private to this worker's thread.
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
        # If `enforce_id` is True, validate that the calling thread has the correct factory ID.
        if enforce_id:
            self._validate_caller(factory_id)
        # Retrieve the value associated with the `key` from the thread-local inventory.
        # If the key is not found, return the specified `default` value.
        return self._inventory.data.get(key, default)

    def execute_transfer(self, name: str, factory_id: Optional[str] = None, enforce_id: bool = False) -> Any:
        """
        Executes a callable function registered within the `data_transfer` dictionary.

        This method allows for the invocation of predefined data handling routines
        or pipelines by their registered name. It can also enforce access control
        based on the caller's `factory_id`.

        Args:
            name (str): The unique string name of the transfer callable to execute.
                        This name must correspond to a key in the `self.data_transfer`
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
        # If ID enforcement is active, perform a security check on the calling thread.
        if enforce_id:
            self._validate_caller(factory_id)
        # Check if a callable function is registered under the given `name` in `data_transfer`.
        if name not in self.data_transfer:
            # If not found, raise a KeyError to indicate an invalid transfer name.
            raise KeyError(f"No data_transfer entry named '{name}'")
        # Execute the registered callable
        return self.data_transfer[name]()

    def _validate_caller(self, factory_id: Optional[str] = None) -> None:
        """
        Internal method to validate if the current calling thread's `factory_id`
        matches an expected ID.

        This method is a security measure used by other methods (like inventory access)
        to ensure that only authorized `DynamicWorker` instances (or threads with
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
            # If they do not match, raise a PermissionError to deny access.
            raise PermissionError(
                f"[Access Denied] Caller factory_id={current_id} does not match expected={expected}"
            )

    # --- External Access (ID-Based) ---
    def get_factory_id(self) -> str:
        """
        Retrieves the unique factory ID assigned to this `DynamicWorker` instance.

        The factory ID serves as a unique identifier for the worker within its
        hosting factory or pool, enabling specific targeting and management.

        Returns:
            str: The unique string identifier of this worker.
        """
        return self.factory_id

    def bind_to_inventory_by_id(self, factory_id: str, key: str, value: Any) -> None:
        """
        Binds a value to the private inventory of *another* `DynamicWorker` instance,
        identified by its `factory_id`.

        This method allows for inter-worker communication and state manipulation,
        where one worker can directly inject data into another worker's private memory.

        Args:
            factory_id (str): The unique `factory_id` of the target `DynamicWorker`
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
        Retrieves a value from the private inventory of *another* `DynamicWorker` instance,
        identified by its `factory_id`.

        This method enables one worker to inspect or retrieve data from another
        worker's private memory, facilitating observation or data sharing patterns.

        Args:
            factory_id (str): The unique `factory_id` of the target `DynamicWorker`
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

    def _resolve_worker_by_id(self, factory_id: str) -> Optional['DynamicWorker']:
        """
        Internal helper method to resolve a `DynamicWorker` instance by its `factory_id`.

        This method attempts to locate another `DynamicWorker` within the system
        (typically through the `factory` object that created this worker).
        It is a crucial component for enabling inter-worker communication by ID.

        NOTE: This method relies on the `factory` attribute of the worker. For this
        functionality to work, the `factory` (e.g., a `DynamicThreadPool`) must
        have a `get_worker_by_id` method implemented and correctly associated
        with this worker. If your `factory` does not provide this, you may need
        to override this method in a custom subclass or inject the lookup mechanism.

        Args:
            factory_id (str): The unique ID of the `DynamicWorker` instance to resolve.

        Returns:
            Optional['DynamicWorker']: The `DynamicWorker` instance if found, otherwise `None`.
        """
        if self.factory and hasattr(self.factory, "get_worker_by_id"):
            # If available, use the factory's method to retrieve the target worker.
            return self.factory.get_worker_by_id(factory_id)

        return None

    # --- Disposal ---
    def dispose(self):
        """
        Performs a comprehensive cleanup of the `DynamicWorker`'s agentic state
        and then triggers the disposal process of its base `Worker` class.

        This method ensures that all dynamic behaviors, memory structures, and
        bound work are properly cleared to prevent resource leaks or unintended
        side effects upon worker termination or recycling. It's safe to call
        multiple times.
        """
        # Check if the worker has already been disposed to prevent redundant cleanup.
        if self.disposed:
            return
        self.dispose_work()
        if self.save_points is not None:
            self.save_points.clear()
        self.save_points = None
        # garbage collected.
        if self.locations is not None:
            self.locations.clear()
        self.locations = None
        self._event_loop = None
        super().dispose()

    def __repr__(self):
        """
        Provides a developer-friendly string representation of the `DynamicWorker` instance.

        This representation is useful for debugging and logging, showing the
        worker's unique identifier and its current operational state.

        Returns:
            str: A formatted string showing the worker's `factory_id` and its
                 current `WorkerState` name.
        """
        return f"<AgenticWorker id={self.factory_id} state={self.state.name}>"