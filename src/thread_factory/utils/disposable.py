from abc import ABC, abstractmethod

class IDisposable(ABC):
    """
    Abstract base class for all disposable objects in the system.

    Usage:
        Any object that holds runtime, memory, open resources, or registration
        within ThreadFactory must implement this.

        Automatically supports context-manager usage:
            with MyObject(...) as obj:
                ...
            # dispose() is called automatically on exit.

    Implementations MUST:
        - Provide a `dispose()` method.
        - Register all their cleanups inside `dispose()`.
        - Optionally provide a `cleanup()` alias.
        - Handle multiple calls to `dispose()` gracefully.
    """
    def __init__(self):
        """
        Constructor for IDisposable.
        This is a no-op, but can be overridden by subclasses if needed.
        """
        self.disposed = False

    @abstractmethod
    def dispose(self):
        """
        Dispose must be implemented by subclasses.
        It MUST:
            - Release all allocated resources.
            - Kill or join all running runtime.
            - Deregister itself from any supervisors or orchestrators.
            - Clear any persistent state to avoid memory leakage.
            - Be idempotent (safe to call multiple times).
        """
        raise NotImplementedError
