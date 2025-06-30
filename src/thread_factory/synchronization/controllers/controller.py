import logging
import threading
from typing import Any, Callable, Dict, List, Optional
from thread_factory.concurrency import ConcurrentDict
from thread_factory.utils import IDisposable


class Controller(IDisposable):
    """
    Controller: A management system for registering, invoking, and controlling objects
    that expose commands through a standardized interface.

    Objects must expose:
      - `id` attribute (unique identifier)
      - `_get_object_details()` method returning {'name': ..., 'commands': {command_name: callable, ...}}

    Supports:
      - Centralized invocation and broadcast
      - Subscription-based event notification
      - Lifecycle management via `dispose` and `reset`
      - Pre/post hook injection for diagnostics and behaviors

    Thread-safe via RLocks and ConcurrentDicts.
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize the Controller.

        Args:
            logger: Optional custom logger. Defaults to a new stream logger.
        """
        super().__init__()

        # Setup internal logger if none provided
        if logger is None:
            self._logger = logging.getLogger(__name__)
            if not self._logger.handlers:
                handler = logging.StreamHandler()
                formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
                handler.setFormatter(formatter)
                self._logger.addHandler(handler)
                self._logger.setLevel(logging.DEBUG)
        else:
            self._logger = logger

        # Object registry: maps object_id -> {'instance', 'name', 'commands'}
        self._registry: ConcurrentDict[str, Dict[str, Any]] = ConcurrentDict()

        # Tracks which objects are currently in a "waiting" state
        self._active_waits: ConcurrentDict[str, str] = ConcurrentDict()

        # Global lock for safe concurrent access
        self._outer_lock = threading.RLock()

        # Event subscribers: object_id -> event_type -> [callbacks]
        self._subscribers: ConcurrentDict[str, ConcurrentDict[str, List[Callable]]] = ConcurrentDict()

        # Hook system for pre/post-invocation
        self._hooks: Dict[str, List[Callable]] = {
            'pre_invoke': [],
            'post_invoke': [],
        }

    # -------------------------------------------
    # Hook Registration
    # -------------------------------------------

    def add_pre_invoke_hook(self, callback: Callable[[str, str], None]):
        """Registers a function to run before invoking any command."""
        self._hooks['pre_invoke'].append(callback)
        self._logger.debug(f"Added pre-invoke hook: {getattr(callback, '__name__', 'unnamed')}")

    def add_post_invoke_hook(
            self,
            callback: Callable[[str, str, Any, Optional[Exception]], None]
    ):
        """Registers a function to run after invoking any command (with result/exception)."""
        self._hooks['post_invoke'].append(callback)
        self._logger.debug(f"Added post-invoke hook: {getattr(callback, '__name__', 'unnamed')}")

    def _run_hooks(self, hook_name: str, *args):
        """Execute all registered hooks for the given event."""
        for hook in self._hooks[hook_name]:
            try:
                hook(*args)
            except Exception as e:
                self._logger.error(f"Error in '{hook_name}' hook '{getattr(hook, '__name__', 'unnamed')}': {e}",
                                   exc_info=True)

    # -------------------------------------------
    # Object Invocation
    # -------------------------------------------

    def invoke(self, object_id: str, command: str, *args, **kwargs) -> Any:
        """
        Invoke a named command on a registered object.

        Args:
            object_id: Unique ID of the target object.
            command: Command name to invoke.
            *args: Positional arguments to the command.
            **kwargs: Keyword arguments to the command.

        Returns:
            The result of the command invocation.
        """
        registry_entry = self._registry.get(object_id)
        if not registry_entry:
            raise KeyError(f"No object registered with ID '{object_id}'.")
        if command not in registry_entry['commands']:
            available = list(registry_entry['commands'].keys())
            raise KeyError(f"Object '{object_id}' has no command '{command}'. Available: {available}")

        self._run_hooks('pre_invoke', object_id, command)

        result = None
        exception = None
        try:
            method_to_call = registry_entry['commands'][command]
            self._logger.debug(f"Invoking '{command}' on object '{object_id}' with args: {args}, kwargs: {kwargs}")

            # Execute command before notifying subscribers
            result = method_to_call(*args, **kwargs)

            # Notify on known terminal operations
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
            self._run_hooks('post_invoke', object_id, command, result, exception)

        if exception:
            raise exception

        return result

    # -------------------------------------------
    # Lifecycle Management
    # -------------------------------------------

    def dispose(self) -> None:
        """
        Dispose of all registered objects and the controller itself.
        """
        if self._disposed:
            self._logger.debug("Controller already disposed. Skipping dispose operation.")
            return
        with self._outer_lock:
            if self._disposed:
                return
            self._logger.info("Controller disposing...")
            self._logger.debug(f"Attempting to dispose {len(self._registry)} registered objects manually.")

            for obj_id, data in list(self._registry.items()):
                try:
                    data["instance"].dispose()
                    self.notify(obj_id, "DISPOSED_BY_CONTROLLER")
                except Exception as e:
                    self._logger.error(f"Error while disposing object '{obj_id}' during controller dispose: {e}",
                                       exc_info=True)

            self._registry.dispose()
            self._active_waits.dispose()
            self._subscribers.dispose()
            self._registry = None
            self._active_waits = None
            self._subscribers = None
            self._disposed = True
            self._logger.info("Controller disposed.")

    def register(self, registrant: Any):
        """
        Register a new controllable object.

        The object must expose `.id` and `_get_object_details()`.

        Raises:
            TypeError or ValueError on contract violation or duplicate ID.
        """
        if not all(hasattr(registrant, attr) for attr in ['id', '_get_object_details']):
            raise TypeError("Object must have 'id' and '_get_object_details' attributes/methods.")
        details = registrant._get_object_details()
        if not (isinstance(details, dict) and 'name' in details and 'commands' in details and isinstance(
                details['commands'], dict)):
            raise TypeError("'_get_object_details' must return a dict with 'name' and 'commands' keys.")

        obj_id = registrant.id
        with self._outer_lock:
            if obj_id in self._registry:
                raise ValueError(f"Object with ID '{obj_id}' is already registered.")
            self._registry[obj_id] = {
                'instance': registrant,
                'name': details['name'],
                'commands': details['commands']
            }
            self._logger.debug(f"Registered object: ID='{obj_id}', Name='{details['name']}'")

    def unregister(self, object_id: str, dispose_object: bool = True):
        """
        Unregister a previously registered object.

        Args:
            object_id: The ID of the object to unregister.
            dispose_object: Whether to dispose of the object before removal.
        """
        with self._outer_lock:
            if object_id not in self._registry:
                self._logger.warning(f"Attempted to unregister non-existent object: {object_id}")
                return

            if dispose_object:
                try:
                    self._registry[object_id]["instance"].dispose()
                    self.notify(object_id, "DISPOSED_BY_CONTROLLER")
                except Exception as e:
                    self._logger.error(f"Error while disposing object '{object_id}' during unregister: {e}",
                                       exc_info=True)

            # Clean up all traces safely
            if object_id in self._active_waits:
                self._active_waits.pop(object_id)
            if object_id in self._subscribers:
                self._subscribers.pop(object_id)
            if object_id in self._registry:
                self._registry.pop(object_id)

            self._logger.debug(f"Unregistered object: {object_id}")

    # -------------------------------------------
    # Broadcast and Notification
    # -------------------------------------------

    def invoke_on_all(self, command: str, name_filter: Optional[str] = None):
        """
        Broadcast a command to all registered objects (optionally filtered by name).
        """
        objects_to_invoke = self.list_objects(name_filter=name_filter)
        self._logger.info(f"Broadcasting command '{command}' to {len(objects_to_invoke)} objects.")
        for obj_summary in objects_to_invoke:
            obj_id = obj_summary['id']
            try:
                self.invoke(obj_id, command)
            except Exception:
                # Skip failures but do not interrupt the loop
                pass

    def on_wait_starting(self, object_id: str):
        """
        Manually mark an object as entering a wait state.
        """
        self.notify(object_id, "WAIT_STARTING")

    def notify(self, object_id: str, event_type: str, data: Optional[Dict] = None):
        """
        Notify subscribers of an event related to a specific object.

        Also manages internal wait tracking.
        """
        if self._disposed or not self._registry or object_id not in self._registry:
            if self._disposed:
                self._logger.debug(f"Controller disposed. Ignoring notification for {object_id}, event {event_type}")
            else:
                self._logger.warning(f"Notification received for unregistered object {object_id}, event {event_type}")
            return

        self._logger.info(f"Controller Event: ID='{object_id}', Event='{event_type}'")
        if event_type == "WAIT_STARTING":
            self._active_waits[object_id] = "WAITING"
        elif event_type in ["OPENED_BY_CONTROLLER", "DISPOSED_BY_CONTROLLER", "RESET_BY_CONTROLLER"]:
            if object_id in self._active_waits:
                self._active_waits.pop(object_id)

        if self._subscribers and object_id in self._subscribers and event_type in self._subscribers.get(object_id, {}):
            for callback in self._subscribers[object_id][event_type]:
                try:
                    callback(object_id, event_type, data)
                except Exception as e:
                    self._logger.error(f"Subscriber callback failed for event '{event_type}' on '{object_id}': {e}",
                                       exc_info=True)

    def subscribe(self, object_id: str, event_type: str, callback: Callable):
        """
        Subscribe a callback to a specific event for a specific object.
        """
        with self._outer_lock:
            if object_id not in self._registry:
                self._logger.warning(
                    f"Attempted to subscribe to non-existent object ID '{object_id}'. Subscription ignored.")
                return

            self._subscribers.setdefault(object_id, ConcurrentDict())
            self._subscribers[object_id].setdefault(event_type, [])
            if callback not in self._subscribers[object_id][event_type]:
                self._subscribers[object_id][event_type].append(callback)
                self._logger.debug(f"New subscription to '{event_type}' on '{object_id}'")

    # -------------------------------------------
    # Query Methods
    # -------------------------------------------

    def list_objects(self, name_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List all registered objects, optionally filtered by name.
        """
        if not self._registry:
            return []
        all_items = self._registry.items()
        all_objects = [{'id': obj_id, 'name': data['name'], 'commands': list(data['commands'].keys())}
                       for obj_id, data in all_items]
        if name_filter:
            return [obj for obj in all_objects if obj['name'] == name_filter]
        return all_objects

    def get_waiting_objects(self) -> List[str]:
        """
        Returns the IDs of all objects currently in a waiting state.
        """
        if not self._active_waits:
            return []
        return self._active_waits.keys()
