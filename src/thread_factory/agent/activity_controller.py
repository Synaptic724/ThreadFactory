import ulid
from typing import Callable, Dict, Any
from thread_factory import ConcurrentDict
from thread_factory.agent.activity import Activity
from thread_factory.utils import IDisposable


class ActivityController(IDisposable):
    """
    Signal and behavior controller for a single agent or operation.

    This controller owns a single `Activity` token, which reflects dynamic
    behaviors, flags, and metadata updates in real time. External systems
    may bind actions or register callbacks for coordination.
    """

    def __init__(self, **kwargs: Any):
        """
        Initializes a new controller with its own activity and metadata.

        Args:
            **kwargs: Arbitrary metadata to associate with the operation,
                      such as job_name, priority, labels, etc.
        """
        super().__init__()
        self._ulid = str(ulid.ULID())
        self._metadata = ConcurrentDict(kwargs)
        self._actions = ConcurrentDict[str, Any]()         # renamed from _activities
        self._callbacks = ConcurrentDict[str, Callable[[], None]]()
        self._activity = Activity(self._metadata)          # single persistent token

    def dispose(self) -> None:
        """
        Clears all internal state and severs activity bindings.
        This controller should not be reused after disposal.
        """
        if self._disposed:
            return
        self._callbacks.dispose()
        self._callbacks = None
        self._actions.dispose()
        self._actions = None
        self._metadata.dispose()
        self._metadata = None
        self._activity = None
        self._disposed = True


    @property
    def activity(self) -> Activity:
        """
        Returns the persistent `Activity` token owned by this controller.

        Returns:
            Activity: A shared token reflecting current actions and metadata.
        """
        return self._activity

    @property
    def metadata(self) -> ConcurrentDict[str, Any]:
        """Returns a copy of the metadata dictionary."""
        return self._metadata.copy()

    def bind(self, name: str, value: Any) -> None:
        """
        Binds or updates an action into the activity's live action map.

        Args:
            name (str): The action identifier.
            value (Any): Callable, static value, or flag.
        """
        self._actions[name] = value
        self._activity.add_activity(name, value)

    def register_callback(self, name: str, callback: Callable[[], None]) -> None:
        """
        Registers a named callback for external triggering.

        Args:
            name (str): Callback identifier (e.g., "on_shutdown").
            callback (Callable): The function to call.
        """
        self._callbacks[name] = callback

    def run_callback(self, name: str) -> bool:
        """
        Runs a registered callback by name, if present.

        Args:
            name (str): Name of the callback.

        Returns:
            bool: True if callback executed, False otherwise.
        """
        callback = self._callbacks.get(name)
        if callback:
            try:
                callback()
                return True
            except Exception:
                pass  # Real-world use would log this
        return False