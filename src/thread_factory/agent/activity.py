import threading
import ulid
from typing import Callable, Optional, Any, Dict, Union
from thread_factory import ConcurrentDict

class Activity:
    """
    A dynamic operation token that carries all signals, flags, and behavior
    injected by a controller. Cancellation is treated like any other named activity.

    An Activity token is given to a long-running function or an Agent,
    which can then periodically check the token's status to see if it
    should gracefully terminate its work. It is created and managed by
    an ActivityController.
    """

    def __init__(self, metadata: Dict[str, Any]):
        """
        Initializes a new Activity token.

        Args:
            metadata (Dict[str, Any]): Metadata to associate with this activity.
        """
        self._ulid = str(ulid.ULID())
        self._metadata = ConcurrentDict(metadata)
        self._activities: ConcurrentDict[str, Any] = ConcurrentDict()
        self._lock = threading.RLock()

    @property
    def ulid(self) -> str:
        """Gets the unique identifier for this activity token."""
        return self._ulid

    @property
    def metadata(self) -> ConcurrentDict[str, Any]:
        """Gets the metadata associated with this activity."""
        return self._metadata.copy()

    def add_activity(self, name: str, action: Union[Callable[..., Any], bool, Any]) -> None:
        """
        Adds a named activity binding, which can be a callable, boolean, or any object.

        Args:
            name (str): The identifier for this behavior or flag.
            action (Callable | bool | Any): The associated logic or value.
        """
        with self._lock:
            self._activities[name] = action

    def get_activity(self, name: str) -> Optional[Union[Callable[..., Any], bool, Any]]:
        """
        Retrieves the activity associated with the given name.

        Args:
            name (str): The identifier of the desired behavior.

        Returns:
            Callable | bool | Any | None: The bound behavior or data.
        """
        with self._lock:
            return self._activities.get(name)

    def __getitem__(self, key: str) -> Any:
        """Shortcut to access activity bindings like a dictionary."""
        return self.get_activity(key)

    def __contains__(self, key: str) -> bool:
        """Checks whether a named activity exists."""
        return key in self._activities
