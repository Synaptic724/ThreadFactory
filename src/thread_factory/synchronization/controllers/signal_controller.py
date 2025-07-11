import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Union

import ulid

from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.utilities.interfaces.disposable import IDisposable
from thread_factory.utilities.coordination.package import Pack

class SignalController(IDisposable):
    """
    SignalController: A management system for registering, invoking, and controlling objects
    that expose commands through a standardized interface.

    Objects managed by this controller must adhere to a specific contract:
    - They must have a unique `id` attribute (string) for identification within the registry.
    - They must implement a `_get_object_details()` method which returns a dictionary
      containing:
        - 'name' (str): A human-readable name for the object.
        - 'commands' (Dict[str, Callable]): A dictionary where keys are command names (str)
          and values are the corresponding callable methods or functions exposed by the object.

    This SignalController provides the following functionalities:
    - **Centralized Invocation and Broadcast**: Allows invoking specific commands on individual
      registered objects or broadcasting a command to multiple objects.
    - **Subscription-based Event Notification**: Enables external components to subscribe to
      events emitted by registered objects, facilitating reactive programming patterns.
    - **Lifecycle Management**: Provides methods for registering, unregistering, and disposing
      of objects, including a comprehensive dispose mechanism for the controller itself.
    - **Pre/Post Hook Injection**: Supports the injection of custom functions (hooks) that
      execute before and after command invocations, useful for diagnostics, logging, or
      implementing cross-cutting concerns.

    The SignalController is designed to be thread-safe, utilizing `threading.RLock` for global
    synchronization and `ConcurrentDict` for thread-safe access to its internal data structures.


    ***This object is currently integrated with:
    - `SignalLatch`: For managing waiting states and signaling between threads.
    - `SignalBarrier`: For synchronizing groups of threads at specific points in execution.
    - `ClockBarrier`: For time-based synchronization of threads.
    - `TransitBarrier`: Executes all threads in a group once into a callable after a threshold is reached.
    - `SyncSignalFork`: Distributes threads into multiple groups based on a conditions.

    These components allow the SignalController to manage complex thread interactions.
    There will be more integration with other synchronization primitives in the future.***
    """

    def __init__(self, controller_name: str = None, controller_type: str = None, logger: Optional[logging.Logger] = None):
        """
        Initialize the SignalController.

        Args:
            logger (Optional[logging.Logger]): An optional custom logger instance.
                                               If `None`, a default stream logger will be
                                               configured for the controller.
        """
        super().__init__()
        self._id = str(ulid.ULID())

        # optional users management tools
        self.name = controller_name if controller_name else "SignalController"
        self.type = controller_type
        self.job = None  # Placeholder for a job or task associated with this controller, if any.
        self.task = None  # Placeholder for a job or task associated with this controller, if any.
        self.activity_id = None  # Placeholder for an activity ID, if applicable.


        # internal group management
        self._group_name = None
        self._group_id = None

        # Setup internal logger if none provided
        if logger is None:
            self._logger = logging.getLogger(__name__)
            if not self._logger.handlers:
                # Configure a default stream handler if no handlers are already set
                handler = logging.StreamHandler()
                formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
                handler.setFormatter(formatter)
                self._logger.addHandler(handler)
                self._logger.setLevel(logging.DEBUG)
        else:
            self._logger = logger

        # Object registry: maps object_id (str) to a dictionary containing:
        # 'instance' (Any): The actual object instance.
        # 'name' (str): The object's human-readable name.
        # 'commands' (Dict[str, Callable]): A dictionary of callable commands exposed by the object.
        self._registry: ConcurrentDict[str, ConcurrentDict[str, Any]] = ConcurrentDict()

        # Tracks which objects are currently in a "waiting" state.
        # Maps object_id (str) to a status string (e.g., "WAITING").
        self._active_waits: ConcurrentDict[str, str] = ConcurrentDict()

        # Global re-entrant lock for safe concurrent access to shared resources within the controller,
        # particularly for methods that modify the registry or subscribers.
        self._outer_lock = threading.RLock()

        # Event subscribers: maps object_id (str) to a ConcurrentDict, which then maps
        # event_type (str) to a list of registered callback functions (List[Callable]).
        self._subscribers: ConcurrentDict[str, ConcurrentDict[str, ConcurrentList[Callable]]] = ConcurrentDict()

        # Hook system for pre/post-invocation.
        # Maps hook_name (str, e.g., 'pre_invoke', 'post_invoke') to a list of callable hooks.
        self._hooks: ConcurrentDict[str, ConcurrentList[Callable]] = ConcurrentDict()
        self._hooks['pre_invoke'] = ConcurrentList()  # List to store pre-invocation callbacks.
        self._hooks['post_invoke'] = ConcurrentList() # List to store post-invocation callbacks.

    def dispose(self) -> None:
        """
        Dispose of all registered objects and the controller itself.

        This method iterates through all registered objects and attempts to call their
        `dispose()` method (if available and implemented). It then cleans up all
        internal data structures to release resources and marks the controller as disposed.
        Subsequent operations on a disposed controller may behave unexpectedly or raise errors.
        This method is idempotent and thread-safe.
        """
        # Check if already disposed to prevent redundant operations
        if self._disposed:
            self._logger.debug("SignalController already disposed. Skipping dispose operation.")
            return

        with self._outer_lock:
            # Double-check inside the lock to prevent race conditions during the initial check
            if self._disposed:
                return

            self._logger.info("SignalController disposing...")
            self._logger.debug(f"Attempting to dispose {len(self._registry)} registered objects manually.")

            # Iterate over a copy of items to avoid issues if registry is modified during iteration
            for obj_id, data in list(self._registry.items()):
                try:
                    # Attempt to dispose of the individual object instance
                    if hasattr(data["instance"], "dispose") and callable(data["instance"].dispose):
                        data["instance"].dispose()
                        self.notify(obj_id, "DISPOSED_BY_CONTROLLER")
                except Exception as e:
                    self._logger.error(f"Error while disposing object '{obj_id}' during controller dispose: {e}",
                                       exc_info=True)

            # Dispose of internal ConcurrentDicts to release their underlying resources
            if self._registry: # Check if it's not None from a previous dispose (for idempotency)
                self._registry.dispose()
            if self._active_waits:
                self._active_waits.dispose()
            if self._subscribers:
                self._subscribers.dispose()
            if self._hooks:
                self._hooks.dispose()

            # Clear references to allow garbage collection
            self._registry = None
            self._active_waits = None
            self._subscribers = None
            self._hooks = None # Also clear hooks to prevent use after dispose

            # Mark the controller as disposed
            self._disposed = True
            self._logger.info("SignalController disposed.")
            # Clear the logger to prevent further logging after disposal
            self._logger = None

    # -------------------------------------------
    # Hook Registration
    # -------------------------------------------

    def add_pre_invoke_hook(self, callback: Union[Callable[..., None], Pack]):
        """
        Registers a function to be executed *before* any command invocation.

        Pre-invoke hooks receive the `object_id` and `command` name as arguments.

        Args:
            callback (Callable[[str, str], None]): The function to register.
                                                   It should accept two string arguments:
                                                   `object_id` (the ID of the object on which the command is invoked)
                                                   and `command` (the name of the command being invoked).
        """
        if callback:
            Pack.bundle(callback)
        self._hooks['pre_invoke'].append(callback)
        self._logger.debug(f"Added pre-invoke hook: {getattr(callback, '__name__', 'unnamed')}")

    def add_post_invoke_hook(
            self,
            callback: Union[Callable[..., Any], Pack]
    ):
        """
        Registers a function to be executed *after* any command invocation.

        Post-invoke hooks receive the `object_id`, `command` name, the `result` of the
        invocation, and any `exception` that occurred (if any).

        Args:
            callback (Callable[[str, str, Any, Optional[Exception]], None]): The function to register.
                It should accept four arguments:
                - `object_id` (str): The ID of the object on which the command was invoked.
                - `command` (str): The name of the command that was invoked.
                - `result` (Any): The return value of the invoked command. This will be `None` if an exception occurred during the invocation.
                - `exception` (Optional[Exception]): The exception object if the command invocation failed, otherwise `None`.
        """
        if callback:
            Pack.bundle(callback)
        self._hooks['post_invoke'].append(callback)
        self._logger.debug(f"Added post-invoke hook: {getattr(callback, '__name__', 'unnamed')}")

    def _run_hooks(self, hook_name: str, *args):
        """
        Execute all registered hooks for the given hook event.

        Args:
            hook_name (str): The name of the hook category (e.g., 'pre_invoke', 'post_invoke').
            *args: Variable positional arguments to pass to each hook function.
        """
        for hook in self._hooks[hook_name]:
            try:
                hook(*args)
            except Exception as e:
                # Log any errors occurring within a hook to prevent it from crashing the main flow.
                self._logger.error(f"Error in '{hook_name}' hook '{getattr(hook, '__name__', 'unnamed')}': {e}",
                                   exc_info=True)

    # -------------------------------------------
    # Object Invocation
    # -------------------------------------------

    def invoke(self, object_id: str, command: str, *args, **kwargs) -> Any:
        """
        Invoke a named command on a registered object.

        This method first retrieves the object from the registry, executes any pre-invoke hooks,
        calls the specified command on the object, and then executes any post-invoke hooks.
        It also handles notifying subscribers for specific lifecycle commands.

        Args:
            object_id (str): Unique ID of the target object on which the command will be invoked.
            command (str): The name of the command (method) to invoke on the object.
            *args: Positional arguments to be passed to the command.
            **kwargs: Keyword arguments to be passed to the command.

        Returns:
            Any: The result returned by the invoked command.

        Raises:
            KeyError: If no object is registered with the given `object_id`.
            KeyError: If the registered object does not expose the specified `command`.
            Exception: Any exception raised by the invoked command itself will be re-raised
                       after post-invoke hooks are executed.
        """
        registry_entry = self._registry.get(object_id)
        if not registry_entry:
            raise KeyError(f"No object registered with ID '{object_id}'.")
        if command not in registry_entry['commands']:
            available = list(registry_entry['commands'].keys())
            raise KeyError(f"Object '{object_id}' has no command '{command}'. Available commands: {available}")

        # Run pre-invocation hooks
        self._run_hooks('pre_invoke', object_id, command)

        result = None
        exception = None
        try:
            method_to_call = registry_entry['commands'][command]
            self._logger.debug(f"Invoking '{command}' on object '{object_id}' with args: {args}, kwargs: {kwargs}")

            # Execute command before notifying subscribers for clarity in logic flow
            result = method_to_call(*args, **kwargs)

            # Notify on known terminal operations or state changes initiated by the controller
            if command == "open":
                self.notify(object_id, "OPENED_BY_CONTROLLER")
            elif command == "dispose":
                self.notify(object_id, "DISPOSED_BY_CONTROLLER")
            elif command == "reset":
                self.notify(object_id, "RESET_BY_CONTROLLER")

        except Exception as e:
            exception = e
            self._logger.error(f"Exception while invoking '{command}' on '{object_id}': {e}", exc_info=True)
        finally:
            # Always run post-invocation hooks, regardless of success or failure
            self._run_hooks('post_invoke', object_id, command, result, exception)

        if exception:
            # Re-raise the exception if one occurred during command execution
            raise exception

        return result

    # -------------------------------------------
    # Lifecycle Management
    # -------------------------------------------

    def register(self, registrant: Any):
        """
        Register a new controllable object with the SignalController.

        The object must adhere to the contract:
        - It must have an `id` attribute (string) which serves as its unique identifier.
        - It must have a `_get_object_details()` method that returns a dictionary
          with 'name' (str) and 'commands' (Dict[str, Callable]).

        Args:
            registrant (Any): The object instance to be registered.

        Raises:
            TypeError: If the `registrant` does not expose the required `id` attribute
                       or `_get_object_details()` method, or if `_get_object_details()`
                       returns an incorrectly formatted dictionary.
            ValueError: If an object with the same `id` is already registered.
        """
        # Validate the object contract
        if not all(hasattr(registrant, attr) for attr in ['id', '_get_object_details']):
            raise TypeError("Object must have 'id' attribute and '_get_object_details' method.")

        details = registrant._get_object_details()
        if not (isinstance(details, ConcurrentDict) and 'name' in details and 'commands' in details and isinstance(
                details['commands'], ConcurrentDict)):
            raise TypeError("'_get_object_details' must return a dictionary with 'name' (str) and 'commands' "
                            "(ConcurrentDict([str, Callable]) keys.")

        obj_id = registrant.id
        with self._outer_lock:
            # Ensure no duplicate IDs are registered
            if obj_id in self._registry:
                raise ValueError(f"Object with ID '{obj_id}' is already registered.")

            # Store the object instance, its name, and its commands in the registry
            self._registry[obj_id] = ConcurrentDict({
                'instance': registrant,
                'name': details['name'],
                'commands': details['commands']
            })
            self._logger.debug(f"Registered object: ID='{obj_id}', Name='{details['name']}'")

    def unregister(self, object_id: str, dispose_object: bool = True):
        """
        Unregister a previously registered object from the SignalController.

        This method removes the object's entry from the registry, clears any associated
        active waits or subscriptions, and optionally calls the object's `dispose()` method.

        Args:
            object_id (str): The unique ID of the object to unregister.
            dispose_object (bool): If `True`, the object's `dispose()` method will be called
                                   (if it exists and is callable) before removal from the
                                   controller's registry. Defaults to `True`.
        """
        with self._outer_lock:
            if object_id not in self._registry:
                self._logger.warning(f"Attempted to unregister non-existent object: {object_id}. No action taken.")
                return

            if dispose_object:
                try:
                    # Attempt to dispose of the object's instance if the flag is set
                    if hasattr(self._registry[object_id]["instance"], "dispose") and \
                       callable(self._registry[object_id]["instance"].dispose):
                        self._registry[object_id]["instance"].dispose()
                        self.notify(object_id, "DISPOSED_BY_CONTROLLER")
                except Exception as e:
                    self._logger.error(f"Error while disposing object '{object_id}' during unregister: {e}",
                                       exc_info=True)

            # Clean up all traces of the object safely from all internal data structures.
            # Using .pop() with checks ensures thread-safety and prevents KeyErrors if
            # another thread concurrently removed an item (though the outer lock should prevent this).
            if object_id in self._active_waits:
                self._active_waits.pop(object_id)
            if object_id in self._subscribers:
                self._subscribers.pop(object_id)
            if object_id in self._registry: # Final check before popping from main registry
                self._registry.pop(object_id)

            self._logger.debug(f"Unregistered object: {object_id}")

    @property
    def id(self) -> str:  # noqa: D401
        """
        ULID that uniquely identifies this latch.
        """
        return self._id

    # -------------------------------------------
    # Broadcast and Notification
    # -------------------------------------------

    def invoke_on_all(self, command: str, name_filter: Optional[str] = None):
        """
        Broadcast a command to all registered objects, optionally filtered by their name.

        This method iterates through all objects in the registry (or a filtered subset)
        and attempts to invoke the specified command on each. Failures on individual
        objects are logged but do not stop the broadcast to other objects.

        Args:
            command (str): The name of the command to invoke on each object.
            name_filter (Optional[str]): If provided, only objects whose 'name' matches
                                         this filter will have the command invoked.
                                         Defaults to `None`, meaning the command is
                                         invoked on all registered objects.
        """
        objects_to_invoke = self.list_objects(name_filter=name_filter)
        self._logger.info(f"Broadcasting command '{command}' to {len(objects_to_invoke)} objects.")
        for obj_summary in objects_to_invoke:
            obj_id = obj_summary['id']
            try:
                # Invoke the command on each object. Exceptions are caught internally by `invoke`.
                self.invoke(obj_id, command)
            except Exception:
                # An exception from invoke() (e.g., command not found on a specific object)
                # is already logged by invoke, so we just pass here to continue the loop
                # without interrupting the broadcast for other objects.
                pass

    def on_wait_starting(self, object_id: str):
        """
        Manually mark an object as entering a wait state.

        This convenience method uses the `notify` mechanism to signal a "WAIT_STARTING" event,
        which updates the controller's internal tracking of waiting objects.

        Args:
            object_id (str): The ID of the object that is beginning a wait operation.
        """
        self.notify(object_id, "WAIT_STARTING")

    def notify(self, object_id: str, event_type: str, data: Optional[Dict] = None):
        """
        Notify subscribers of an event related to a specific object and manage internal wait tracking.

        This method is the central point for emitting events. It updates the internal
        `_active_waits` state based on certain `event_type` values and then dispatches
        the event to all registered subscribers for that specific `object_id` and `event_type`.

        Args:
            object_id (str): The unique ID of the object from which the event originates.
            event_type (str): A string representing the type of event (e.g., "WAIT_STARTING",
                              "OPENED", "CLOSED", "ERROR").
            data (Optional[Dict]): An optional dictionary containing additional event-specific data.
                                   Defaults to `None`.
        """
        # Early exit if the controller is disposed or the object is not registered
        if self._disposed:
            self._logger.debug(f"SignalController disposed. Ignoring notification for {object_id}, event {event_type}")
            return
        if not self._registry or object_id not in self._registry:
            self._logger.warning(f"Notification received for unregistered object {object_id}, event {event_type}. "
                                 f"This event will not be dispatched to subscribers.")
            return

        self._logger.info(f"SignalController Event: ID='{object_id}', Event='{event_type}'")

        # Update internal active waits tracking based on specific event types
        if event_type == "WAIT_STARTING":
            self._active_waits[object_id] = "WAITING"
        elif event_type in [
            "OPENED_BY_CONTROLLER",
            "DISPOSED_BY_CONTROLLER",
            "RESET_BY_CONTROLLER",
            "SEMAPHORE_RELEASED"  # Added to handle ThresholdSemaphore release events
        ]:
            # These events indicate a terminal state or completion, so remove from active waits
            if object_id in self._active_waits:
                self._active_waits.pop(object_id)

        # Dispatch the event to subscribers if any exist for this object and event type
        # Check if _subscribers is not None (in case controller is disposing concurrently)
        if self._subscribers and object_id in self._subscribers:
            object_subscribers = self._subscribers.get(object_id, ConcurrentDict())
            if event_type in object_subscribers:
                for callback in object_subscribers[event_type]:
                    try:
                        # Execute each subscribed callback
                        callback(object_id, event_type, data)
                    except Exception as e:
                        # Log errors in subscriber callbacks but do not stop other callbacks or the notification process
                        self._logger.error(f"Subscriber callback failed for event '{event_type}' on '{object_id}': {e}",
                                           exc_info=True)

    def subscribe(self, object_id: str, event_type: str, callback: Union[Callable[..., None], Pack]):
        """
        Subscribe a callback function to a specific event type for a specific object.

        When the `notify` method is called for the given `object_id` and `event_type`,
        all subscribed `callback` functions will be invoked.

        Args:
            object_id (str): The unique ID of the object to which to subscribe.
            event_type (str): The type of event (e.g., "DATA_UPDATED", "STATUS_CHANGE") to subscribe to.
            callback (Callable): The function to be called when the event occurs.
                                 It should accept arguments matching the `notify` method's
                                 signature for data dispatch: `object_id` (str), `event_type` (str),
                                 and `data` (Optional[Dict]).

        # INTERNAL NOTE:
            We will not Pack the callback as its internal.
        """
        with self._outer_lock:
            if object_id not in self._registry:
                self._logger.warning(
                    f"Attempted to subscribe to non-existent object ID '{object_id}'. Subscription ignored.")
                return

            # Use setdefault for ConcurrentDicts to safely initialize nested dictionaries and lists
            self._subscribers.setdefault(object_id, ConcurrentDict())
            # Get the inner ConcurrentDict for the object, then setdefault for the event type list
            self._subscribers[object_id].setdefault(event_type, ConcurrentList())
            # Only add the callback if it's not already in the list to prevent duplicate subscriptions
            if callback not in self._subscribers[object_id][event_type]:
                self._subscribers[object_id][event_type].append(callback)
                self._logger.debug(f"New subscription to '{event_type}' on '{object_id}'")

    def unsubscribe(self, object_id: str, event_type: str, callback: Callable[..., None]):
        """
        Unsubscribe a callback function from a specific event type for a specific object.

        Args:
            object_id (str): The unique ID of the object from which to unsubscribe.
            event_type (str): The type of event to unsubscribe from.
            callback (Callable): The function to be unsubscribed.
        """
        with self._outer_lock:
            if object_id in self._subscribers:
                object_subscribers = self._subscribers[object_id]
                if event_type in object_subscribers:
                    if callback in object_subscribers[event_type]:
                        object_subscribers[event_type].remove(callback)
                        self._logger.debug(f"Unsubscribed callback from '{event_type}' on '{object_id}'")
                        # Optionally, clean up empty ConcurrentLists or ConcurrentDicts
                        if not object_subscribers[event_type]:
                            object_subscribers.pop(event_type)
                            if not object_subscribers:
                                self._subscribers.pop(object_id)
                    else:
                        self._logger.warning(
                            f"Attempted to unsubscribe a non-existent callback for event '{event_type}' on '{object_id}'.")
                else:
                    self._logger.warning(
                        f"Attempted to unsubscribe from non-existent event type '{event_type}' on '{object_id}'.")
            else:
                self._logger.warning(
                    f"Attempted to unsubscribe from non-existent object ID '{object_id}'.")

    # -------------------------------------------
    # Query Methods
    # -------------------------------------------

    def list_objects(self, name_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List all registered objects, optionally filtered by their name.

        Returns a summary of each object, including its ID, name, and available commands.

        Args:
            name_filter (Optional[str]): If provided, only objects whose 'name' strictly
                                         matches this filter will be included in the list.
                                         Defaults to `None`, which means all registered
                                         objects are listed.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, where each dictionary represents
                                  an object with keys:
                                  - 'id' (str): The unique ID of the object.
                                  - 'name' (str): The human-readable name of the object.
                                  - 'commands' (List[str]): A list of command names
                                    exposed by the object.
        """
        if not self._registry:
            return [] # Return empty list if no objects are registered

        all_items = self._registry.items() # Get items from the ConcurrentDict
        all_objects = [{'id': obj_id, 'name': data['name'], 'commands': list(data['commands'].keys())}
                       for obj_id, data in all_items]

        if name_filter:
            # Apply the name filter if specified
            return [obj for obj in all_objects if obj['name'] == name_filter]
        return all_objects

    def get_waiting_objects(self) -> List[str]:
        """
        Returns the IDs of all objects currently in a waiting state.

        An object is marked as "waiting" via the `on_wait_starting` method or by
        a "WAIT_STARTING" event notification.

        Returns:
            List[str]: A list of unique identifiers (strings) for objects
                       that are currently marked as waiting. Returns an empty list
                       if no objects are in a waiting state.
        """
        if not self._active_waits:
            return [] # Return empty list if no objects are actively waiting
        return self._active_waits.keys() # Return a list of keys (object IDs)