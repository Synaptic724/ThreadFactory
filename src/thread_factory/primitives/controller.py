import threading
from typing import Any, Callable, Dict, List, Optional
from thread_factory import ConcurrentDict
from thread_factory.utils import IDisposable


class Controller(IDisposable):
    """
    A thread-safe, generic controller for managing and orchestrating any
    compliant concurrent object.
    """
    def __init__(self):
        """
        Initializes the controller's internal state.
        """
        super().__init__()
        self._registry: ConcurrentDict[str, Dict[str, Any]] = ConcurrentDict()
        self._active_waits: ConcurrentDict[str, str] = ConcurrentDict()
        self._outer_lock = threading.Lock()

    def dispose(self) -> None:
        """
        Disposes the controller and its underlying ConcurrentDicts.
        """
        if not self._disposed:
            self._registry.dispose()
            self._active_waits.dispose()
            self._disposed = True

    # --- Event Handling ---

    def on_wait_starting(self, object_id: str):
        """
        An adapter method designed to be used as a signal_callback.
        It translates the simple callback into a richer notification event
        within the controller.
        """
        self.notify(object_id, "WAIT_STARTING")

    def notify(self, object_id: str, event_type: str, data: Optional[Dict] = None):
        """
        Receives and processes a generic notification from a managed object.
        This is how the controller "registers a change".
        """
        if self._disposed or object_id not in self._registry:
            return

        print(f"Controller Event: ID='{object_id}', Event='{event_type}', Data={data or {}}")
        # Example of stateful logic: track active waits
        if event_type == "WAIT_STARTING":
            self._active_waits[object_id] = "WAITING"
        elif event_type in ["OPENED", "DISPOSED"]:
            self._active_waits.pop(object_id, None)


    # --- Core Public API (register, invoke) ---
    # ... (These methods are unchanged from the previous version)

    def register(self, registrant: Any):
        """
        Registers a component with the controller.
        """
        # ... (code is identical to previous version)
        if not all(hasattr(registrant, attr) for attr in ['id', '_get_object_details']):
            raise TypeError(
                "Object does not conform to the controller's contract. "
                "It must have 'id' and '_get_object_details' attributes/methods."
            )
        details = registrant._get_object_details()
        if not (isinstance(details, dict) and 'name' in details and 'commands' in details and isinstance(details['commands'], dict)):
            raise TypeError("'_get_object_details' must return a dict with a 'name' string and a nested 'commands' dictionary.")
        obj_id = registrant.id
        obj_name = details['name']
        commands = details['commands']
        with self._outer_lock:
            if obj_id in self._registry:
                raise ValueError(f"An object with ID '{obj_id}' is already registered.")
            self._registry[obj_id] = {'instance': registrant, 'name': obj_name, 'commands': commands}

    def invoke(self, object_id: str, command: str, *args, **kwargs) -> Any:
        """
        Invokes a registered command on a specific managed object.
        """
        # ... (code is identical to previous version)
        registry_entry = self._registry.get(object_id)
        if not registry_entry:
            raise KeyError(f"No object registered with ID '{object_id}'.")
        if command not in registry_entry['commands']:
            available = list(registry_entry['commands'].keys())
            raise KeyError(f"Object '{object_id}' of name '{registry_entry['name']}' does not have a command '{command}'. Available commands: {available}")
        method_to_call = registry_entry['commands'][command]
        # When we open a latch via the controller, let's notify it.
        if command in ["open", "dispose"]:
             self.notify(object_id, f"{command.upper()}ED")
        return method_to_call(*args, **kwargs)


    # --- Discovery and Introspection ---
    # ... (These methods are unchanged from the previous version)

    def list_objects(self, name_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        # ... (code is identical)
        all_items = self._registry.items()
        all_objects = [{'id': obj_id, 'name': data['name'], 'commands': list(data['commands'].keys())} for obj_id, data in all_items]
        if name_filter:
            return [obj for obj in all_objects if obj['name'] == name_filter]
        return all_objects

    def get_details(self, object_id: str) -> Optional[Dict[str, Any]]:
        # ... (code is identical)
        registry_entry = self._registry.get(object_id)
        if registry_entry:
            return {'id': object_id, 'name': registry_entry['name'], 'commands': list(registry_entry['commands'].keys())}
        return None