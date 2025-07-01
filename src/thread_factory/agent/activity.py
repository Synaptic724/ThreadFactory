import threading
import ulid
from typing import Callable, Optional, Any, List, Dict
from thread_factory import ConcurrentDict, ConcurrentList
from thread_factory.utils.exceptions.operation_canceled_error import OperationCanceledError

class Activity:
    """
    Represents a request for an operation that can be canceled.

    An Activity token is given to a long-running function or an Agent,
    which can then periodically check the token's status to see if it
    should gracefully terminate its work. It is created and managed by
    an OperationalController.
    """

    def __init__(self, source: 'OperationalController', metadata: Dict[str, Any]):
        """
        Initializes a new Activity. (Typically created via an OperationalController).
        """
        self._source = source
        self._ulid = str(ulid.ULID())
        self._metadata = ConcurrentDict(metadata)
        self._activities: ConcurrentDict[str, Callable[..., Any]] = ConcurrentDict()
        self._activities_lock = threading.RLock()

    @property
    def ulid(self) -> str:
        """Gets the unique identifier for this activity token."""
        return self._ulid

    @property
    def metadata(self) -> ConcurrentDict[str, Any]:
        """Gets the metadata associated with this activity."""
        return self._metadata.copy()

    @property
    def is_cancellation_requested(self) -> bool:
        """Checks if cancellation has been requested via the source controller."""
        return self._source.is_cancellation_requested

    @property
    def can_be_canceled(self) -> bool:
        """Checks if this activity supports cancellation."""
        return self._source.can_be_canceled

    def throw_if_cancellation_requested(self):
        """
        Throws an OperationCanceledError if cancellation has been requested.
        This is the core of the cooperative cancellation pattern.
        """
        if self.is_cancellation_requested:
            raise OperationCanceledError("Cancellation has been requested for this operation.")

    def register_cancellation_callback(self, callback: Callable[[], None]) -> None:
        """
        Registers a callback that will be invoked when this Activity is canceled.
        If already canceled, the callback is executed immediately.
        """
        self._source.register_callback(callback)

    def add_activity(self, name: str, action: Callable[..., Any]) -> None:
        """Adds a named callable action for dynamic execution."""
        with self._activities_lock:
            self._activities[name] = action

    def get_activity(self, name: str) -> Optional[Callable[..., Any]]:
        """Retrieves a named callable action."""
        with self._activities_lock:
            return self._activities.get(name)

