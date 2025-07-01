import threading
from copy import deepcopy
import ulid
from typing import Callable, Optional, Any, Dict, Union
from thread_factory import ConcurrentDict
from thread_factory.utils import IDisposable


class Activity(IDisposable):
    """
    A dynamic operation token that carries all signals, flags, and behaviors
    injected by a controller. This allows external systems to guide or terminate
    long-running operations by updating this token in real time.

    Each token:
      - Has a unique ULID.
      - Exposes a shallow or deep metadata copy.
      - Supports arbitrary named actions (flags, callables, data).
      - Can be disposed to clear resources.

    This object is handed to an Agent or worker and checked periodically during runtime.
    """

    def __init__(self, metadata: ConcurrentDict[str, Any]):
        """
        Initializes a new Activity token.

        Args:
            metadata (ConcurrentDict[str, Any]): Metadata to associate with this activity.
        """
        super().__init__()
        self._ulid: str = str(ulid.ULID())
        self._metadata: ConcurrentDict[str, Any] = ConcurrentDict(metadata)
        self._actions: ConcurrentDict[str, Any] = ConcurrentDict()
        self._lock: threading.RLock = threading.RLock()

    def dispose(self) -> None:
        """
        Releases all internal state and invalidates the activity.
        Any future use will raise warnings or be ignored.
        """
        if self._disposed:
            return
        self._disposed = True
        self._actions.dispose()
        self._metadata.dispose()
        self._actions = None
        self._metadata = None

    @property
    def ulid(self) -> str:
        """
        Returns:
            str: The globally unique identifier for this token.
        """
        return self._ulid

    @property
    def metadata(self) -> ConcurrentDict[str, Any]:
        """
        Returns:
            ConcurrentDict: A shallow copy of the associated metadata.
        """
        return self._metadata.copy()

    def deep_metadata(self) -> ConcurrentDict[str, Any]:
        """
        Returns:
            ConcurrentDict: A deep copy of the full metadata structure.
        """
        return deepcopy(self._metadata)

    def add_activity(self, name: str, action: Union[Callable[..., Any], bool, Any]) -> None:
        """
        Adds or updates a named action or flag.

        Args:
            name (str): The identifier for this action (e.g., 'cancel_requested').
            action (Callable | bool | Any): The action or flag to store.
        """
        self._actions[name] = action

    def get_activity(self, name: str) -> Optional[Union[Callable[..., Any], bool, Any]]:
        """
        Retrieves a named action by key.

        Args:
            name (str): The action key to retrieve.

        Returns:
            Callable | bool | Any | None: The stored action, if any.
        """
        return self._actions.get(name)

    def __getitem__(self, key: str) -> Any:
        """
        Access an action using dictionary-style syntax.

        Args:
            key (str): The name of the action.

        Returns:
            Any: The stored action or None if missing.
        """
        return self.get_activity(key)

    def __contains__(self, key: str) -> bool:
        """
        Checks if a specific action has been registered.

        Args:
            key (str): The name of the action.

        Returns:
            bool: True if found, False otherwise.
        """
        return key in self._actions
