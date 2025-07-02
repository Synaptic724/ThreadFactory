from abc import ABC, abstractmethod
from thread_factory.concurrency.sync_types.sync_bool import SyncBool

class IDisposable(ABC):
    """
    IDisposable
    -----------
    Abstract base class for all disposable objects in the system.

    Objects that manage runtime, memory, open resources, or registration
    within ThreadFactory must implement this interface.

    Supports context-manager usage:
        with MyObject(...) as obj:
            ...
        # dispose() is called automatically on exit.

    Contract:
    ---------
    - `dispose()` must be safe to call multiple times.
    - `cleanup()` is a semantic alias (not required but encouraged).
    - All disposables must set `_disposed = True` when disposal completes.
    """

    __slots__ = ['_disposed',]

    def __init__(self):
        self._disposed = SyncBool(False)

    @property
    def disposed(self) -> SyncBool:
        """Returns True if the object has already been disposed."""
        return self._disposed

    @property
    def is_disposed(self) -> SyncBool:
        """Alias for `disposed`."""
        return self._disposed

    def __enter__(self):
        """Enable usage with `with` statements."""
        if self._disposed:
            raise RuntimeError(f"{self.__class__.__name__} has already been disposed.")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Ensure disposal on context exit."""
        self.dispose()

    def __del__(self):
        """Best-effort safety: try to dispose on garbage collection."""
        try:
            self.dispose()
        except Exception:
            # Never throw in __del__
            pass

    @abstractmethod
    def dispose(self):
        """
        Dispose must be implemented by subclasses.

        Must:
        -----
        - Release all resources.
        - Deregister or finalize any allocations.
        - Be idempotent (safe to call multiple times).
        """
        raise NotImplementedError("Subclasses must implement dispose().")

    def cleanup(self):
        """Optional semantic alias for `dispose()`."""
        self.dispose()
