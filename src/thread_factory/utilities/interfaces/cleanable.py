import threading
from abc import ABC, abstractmethod

class Cleanable(ABC):
    """
    Cleanable
    -----------
    Abstract base class for all Cleanable objects in the system.

    Objects that manage runtime, memory, open resources, or registration
    within commandops must implement this interface.

    Supports context-manager usage:
        with MyObject(...) as obj:
            ...
        # cleanup() is called automatically on exit.

    Contract:
    ---------
    - `cleanup()` must be safe to call multiple times.
    - All cleanup must set `_cleaned = True` when cleanup completes.
    """

    __slots__ = ['_cleaned']

    def __init__(self):
        self._cleaned = False

    @property
    def cleaned(self) -> bool:
        """Returns True if the object has already been cleaned."""
        return self._cleaned

    @property
    def is_cleaned(self) -> bool:
        """Alias for `cleaned`."""
        return self._cleaned

    def check_cleaned(self):
        """
        Check if the object has been cleaned.

        Raises:
            RuntimeError: If the object has already been cleaned.
        """
        if self._cleaned:
            raise RuntimeError(f"{self.__class__.__name__} has already been cleaned. ")

    def __enter__(self):
        """Enable usage with `with` statements."""
        if self._cleaned:
            raise RuntimeError(f"{self.__class__.__name__} has already been cleaned.")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Ensure cleanup on context exit."""
        self.cleanup()

    def __del__(self):
        """Best-effort safety: try to dispose on garbage collection."""
        try:
            self.cleanup()
        except Exception:
            # Never throw in __del__
            pass

    @abstractmethod
    def cleanup(self):
        """
        Dispose must be implemented by subclasses.

        Must:
        -----
        - Release all resources.
        - Deregister or finalize any allocations.
        - Be idempotent (safe to call multiple times).
        """
        raise NotImplementedError("Subclasses must implement cleanup().")