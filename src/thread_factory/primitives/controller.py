import logging
import threading
from typing import Any, Callable, Dict, List, Optional
from thread_factory import ConcurrentDict
from thread_factory.utils import IDisposable

class Controller(IDisposable):
    """
    A thread-safe, generic controller for managing and orchestrating any
    compliant concurrent object from the library.

    This controller operates on a "capability-based" model. It has no
    hardcoded knowledge of specific object types. Instead, any object that
    wishes to be managed must register itself and provide a standard set of
    details about its name and available commands.

    It also features a powerful hook system, allowing users to inject custom
    logic (like logging, metrics, or validation) before and after commands
    are executed.
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initializes the controller's internal state.

        Args:
            logger (Optional[logging.Logger]): An optional, pre-configured
                logger instance. If None, a namespaced logger
                (e.g., 'thread_factory.controller') will be used automatically.
                This allows advanced users to inject a custom logger.
        """
        super().__init__()
        # Use the provided logger, or fall back to the module's default logger.
        self._logger = logger

        # The central registry for all managed objects.
        # Structure: { 'object_id': {'instance': obj, 'name': str, 'commands': {}} }
        self._registry: ConcurrentDict[str, Dict[str, Any]] = ConcurrentDict()

        # Tracks objects that have signaled they are in a "waiting" state.
        self._active_waits: ConcurrentDict[str, str] = ConcurrentDict()

        # A lock to make multi-step operations on the registry atomic.
        # e.g., to prevent race conditions during check-then-set operations.
        self._outer_lock = threading.Lock()

        # For the event subscription system (Pub/Sub).
        # Structure: {'object_id': {'event_type': [callback1, callback2]}}
        self._subscribers: ConcurrentDict[str, Dict[str, List[Callable]]] = ConcurrentDict()

        # For the invocation hook system.
        # Allows adding behavior before and after command execution.
        self._hooks: Dict[str, List[Callable]] = {
            'pre_invoke': [],
            'post_invoke': [],
        }

    # --- Invocation Hook Management ---

    def add_pre_invoke_hook(self, callback: Callable[[str, str], None]):
        """
        Adds a callback to run *before* any command is invoked via `invoke`.

        This is useful for custom logging, metrics, or validation. The hook
        will be called synchronously within the `invoke` method.

        Args:
            callback (Callable): A function to be executed.
                It must accept two arguments: `object_id` (str) and
                `command_name` (str).
        """
        self._hooks['pre_invoke'].append(callback)
        self._logger.debug(f"Added pre-invoke hook: {getattr(callback, '__name__', 'unnamed')}")

    def add_post_invoke_hook(
            self,
            callback: Callable[[str, str, Any, Optional[Exception]], None]
    ):
        """
        Adds a callback to run *after* any command invoked via `invoke` completes.

        This hook runs in a `finally` block, so it will execute even if the
        command fails. It allows for custom actions like stopping timers,
        logging results, or handling errors.

        Args:
            callback (Callable): A function to be executed. It must accept
                four arguments:
                - `object_id` (str)
                - `command_name` (str)
                - `result` (Any): The return value of the command, or None if it failed.
                - `exception` (Optional[Exception]): The exception object if the
                  command failed, otherwise None.
        """
        self._hooks['post_invoke'].append(callback)
        self._logger.debug(f"Added post-invoke hook: {getattr(callback, '__name__', 'unnamed')}")

    def _run_hooks(self, hook_name: str, *args):
        """Internal helper to safely run all registered hooks for a given type."""
        for hook in self._hooks[hook_name]:
            try:
                hook(*args)
            except Exception as e:
                # Log the error but continue, so one bad hook doesn't
                # prevent others from running.
                self._logger.error(f"Error in '{hook_name}' hook '{getattr(hook, '__name__', 'unnamed')}': {e}",
                                   exc_info=True)

    # --- Core Public API ---

    def invoke(self, object_id: str, command: str, *args, **kwargs) -> Any:
        """
        Invokes a registered command on a specific object, executing any
        registered pre- and post-invocation hooks.

        This is the primary method for externally controlling managed objects.

        Args:
            object_id (str): The unique ID of the target object.
            command (str): The string name of the command to execute.
            *args: Positional arguments to pass to the command.
            **kwargs: Keyword arguments to pass to the command.

        Returns:
            Any: The return value from the executed command.

        Raises:
            KeyError: If the object_id or command is not found in the registry.
            Exception: Any exception raised by the command itself will be
                       re-raised after the post-invocation hooks have run.
        """
        # Retrieve the object's registration data.
        registry_entry = self._registry.get(object_id)
        if not registry_entry:
            raise KeyError(f"No object registered with ID '{object_id}'.")
        if command not in registry_entry['commands']:
            available = list(registry_entry['commands'].keys())
            raise KeyError(f"Object '{object_id}' has no command '{command}'. Available: {available}")

        # --- Hook Execution and Command Invocation ---
        self._run_hooks('pre_invoke', object_id, command)

        result = None
        exception = None
        try:
            # Retrieve the callable method from the registry.
            method_to_call = registry_entry['commands'][command]
            self._logger.debug(f"Invoking '{command}' on object '{object_id}' with args: {args}, kwargs: {kwargs}")

            # Notify on built-in state-changing commands for internal tracking.
            if command in ["open", "dispose", "reset"]:
                self.notify(object_id, f"{command.upper()}ED_BY_CONTROLLER")

            # Execute the actual command.
            result = method_to_call(*args, **kwargs)

        except Exception as e:
            # If the command fails, capture the exception.
            exception = e
            self._logger.error(f"Exception while invoking '{command}' on '{object_id}': {e}", exc_info=True)
        finally:
            # Run post-invocation hooks regardless of success or failure.
            self._run_hooks('post_invoke', object_id, command, result, exception)

        # If an exception occurred, re-raise it so the original caller is aware.
        if exception:
            raise exception

        return result

    # ... Other methods from the previous version are included below ...
    # (For brevity, their comments are not repeated here, but they are fully documented)
    def dispose(self) -> None:
        """
        Disposes the controller, all its registered objects, and its
        underlying ConcurrentDicts. This is idempotent.
        """
        if not self._disposed:
            self._logger.info("Controller disposing...")
            self.invoke_on_all('dispose')
            self._registry.dispose()
            self._active_waits.dispose()
            self._subscribers.dispose()
            self._disposed = True
            self._logger.info("Controller disposed.")

    def register(self, registrant: Any):
        """
        Registers a component with the controller, enforcing the library's
        integration contract.

        The contract requires the object to have:
        1. An `.id` property (str).
        2. A `._get_object_details()` method that returns a dict with 'name'
           and 'commands' keys.
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
        Unregisters an object from the controller and optionally disposes it.
        """
        with self._outer_lock:
            if object_id not in self._registry:
                self._logger.warning(f"Attempted to unregister non-existent object: {object_id}")
                return
            if dispose_object:
                try:
                    self.invoke(object_id, 'dispose')
                except Exception as e:
                    self._logger.error(f"Error while disposing object '{object_id}' during unregister: {e}",
                                       exc_info=True)
            self._registry.pop(object_id, None)
            self._active_waits.pop(object_id, None)
            self._subscribers.pop(object_id, None)
            self._logger.debug(f"Unregistered object: {object_id}")

    def invoke_on_all(self, command: str, name_filter: Optional[str] = None):
        """
        Invokes a command on all registered objects, or all objects of a
        specific name. Errors are logged but do not stop the process.
        """
        objects_to_invoke = self.list_objects(name_filter=name_filter)
        self._logger.info(f"Broadcasting command '{command}' to {len(objects_to_invoke)} objects.")
        for obj_summary in objects_to_invoke:
            obj_id = obj_summary['id']
            try:
                self.invoke(obj_id, command)
            except Exception as e:
                self._logger.error(f"Error invoking '{command}' on '{obj_id}': {e}", exc_info=True)

    def on_wait_starting(self, object_id: str):
        """
        Adapter method designed to be used as a signal_callback for primitives
        like SignalLatch. It translates a simple signal into a richer event.
        """
        self.notify(object_id, "WAIT_STARTING")

    def notify(self, object_id: str, event_type: str, data: Optional[Dict] = None):
        """
        Receives and processes a notification from a managed object or the
        controller itself, updating internal state and notifying any subscribers.
        """
        if self._disposed or object_id not in self._registry:
            return
        self._logger.info(f"Controller Event: ID='{object_id}', Event='{event_type}'")
        if event_type == "WAIT_STARTING":
            self._active_waits[object_id] = "WAITING"
        elif "ED_BY_CONTROLLER" in event_type:
            self._active_waits.pop(object_id, None)
        if object_id in self._subscribers and event_type in self._subscribers[object_id]:
            for callback in self._subscribers[object_id][event_type]:
                try:
                    callback(object_id, event_type, data)
                except Exception as e:
                    self._logger.error(f"Subscriber callback failed for event '{event_type}' on '{object_id}': {e}",
                                       exc_info=True)

    def subscribe(self, object_id: str, event_type: str, callback: Callable):
        """
        Subscribes a callback to a specific event from a specific object.
        """
        with self._outer_lock:
            self._subscribers.setdefault(object_id, {})
            self._subscribers[object_id].setdefault(event_type, [])
            if callback not in self._subscribers[object_id][event_type]:
                self._subscribers[object_id][event_type].append(callback)
                self._logger.debug(f"New subscription to '{event_type}' on '{object_id}'")

    def list_objects(self, name_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Returns a list of summaries for all registered objects.
        """
        all_items = self._registry.items()
        all_objects = [{'id': obj_id, 'name': data['name'], 'commands': list(data['commands'].keys())} for obj_id, data
                       in all_items]
        if name_filter:
            return [obj for obj in all_objects if obj['name'] == name_filter]
        return all_objects

    def get_waiting_objects(self) -> List[str]:
        """
        Returns a list of IDs for objects currently in a waiting state.
        """
        return self._active_waits.keys()