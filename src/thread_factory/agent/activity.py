import threading
from copy import deepcopy

import ulid
from typing import Callable, Optional, Any, Dict, Union
from thread_factory import ConcurrentDict
from thread_factory.utils import IDisposable


class Activity(IDisposable):
    """
    A dynamic operation token that carries all signals, flags, and behavior
    injected by a controller. Cancellation is treated like any other named activity.

    An Activity token is given to a long-running function or an Agent,
    which can then periodically check the token's status to see if it
    should gracefully terminate its work. It is created and managed by
    an ActivityController.
    """

    def __init__(self, metadata: ConcurrentDict[str, Any]):
        """
        Initializes a new Activity token.

        Args:
            metadata (Dict[str, Any]): Metadata to associate with this activity.
        """
        super().__init__()
        self._ulid = str(ulid.ULID())
        self._metadata = ConcurrentDict(metadata)
        self._actions: ConcurrentDict[str, Any] = ConcurrentDict()
        self._lock = threading.RLock()

    def dispose(self) -> None:
        """Disposes of the activity token, releasing all resources."""
        if self._disposed:
            return
        self._disposed = True
        self._actions.dispose()
        self._actions = None
        self._metadata.dispose()
        self._metadata = None

    @property
    def ulid(self) -> str:
        """Gets the unique identifier for this activity token."""
        return self._ulid

    @property
    def metadata(self) -> ConcurrentDict[str, Any]:
        """Returns a shallow copy of the metadata."""
        return self._metadata.copy()

    def deep_metadata(self) -> ConcurrentDict[str, Any]:
        """Returns a deep copy of the metadata."""
        return deepcopy(self._metadata)

    def add_activity(self, name: str, action: Union[Callable[..., Any], bool, Any]) -> None:
        """
        Adds a named activity binding, which can be a callable, boolean, or any object.

        Args:
            name (str): The identifier for this behavior or flag.
            action (Callable | bool | Any): The associated logic or value.
        """
        self._actions[name] = action

    def get_activity(self, name: str) -> Optional[Union[Callable[..., Any], bool, Any]]:
        """
        Retrieves the activity associated with the given name.

        Args:
            name (str): The identifier of the desired behavior.

        Returns:
            Callable | bool | Any | None: The bound behavior or data.
        """
        return self._actions.get(name)

    def __getitem__(self, key: str) -> Any:
        """Shortcut to access activity bindings like a dictionary."""
        return self.get_activity(key)

    def __contains__(self, key: str) -> bool:
        """Checks whether a named activity exists."""
        return key in self._actions
