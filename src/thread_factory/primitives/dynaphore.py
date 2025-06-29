import threading
from thread_factory.utils import IDisposable


class Dynaphore(IDisposable):
    """
    Dynaphore
    ---------
    A dynamic semaphore for thread coordination in high-performance environments.

    This class replaces Python’s standard `threading.Semaphore` with a fully controlled
    implementation that allows dynamic adjustment of available permits at runtime.

    Key Features:
    - Runtime-safe permit scaling using `increase_permits()` and `decrease_permits()`.
    - Explicit blocking acquisition via `wait_for_permit()` with timeout support.
    - Internal counter (_permits) is fully managed in Python, allowing zero or negative values safely.
    - Supports external condition access via `.condition` for integration with custom coordination logic.
    - Optional reentrant lock support for use in nested thread structures.

    Example:
        >>> dyn = Dynaphore(value=2)
        >>> dyn.decrease_permits(2)  # Prevents any permits from being acquired
        >>> dyn.increase_permits(3)  # Now 3 available

        def worker():
            if dyn.wait_for_permit(timeout=5):
                try:
                    do_work()
                finally:
                    dyn.release_permit()
    """

    __slots__ = IDisposable.__slots__ + [
        "_cond", "_permits"
    ]

    def __init__(self, value: int = 1, re_entrant: bool = True):
        """
        Initializes a new Dynaphore instance.

        Args:
            value (int): The initial number of available permits. Must be >= 0.
            re_entrant (bool): If True, uses RLock for the internal Condition (default).
        """
        super().__init__()
        if value < 0:
            raise ValueError("Initial permit value must be non-negative.")

        self._permits = value
        self._cond = threading.Condition() if re_entrant else threading.Condition(threading.Lock())

    def dispose(self):
        """
        Cleans up the Dynaphore and notifies all waiting threads.

        This should be called during shutdown to prevent deadlocks.
        """
        if self._disposed:
            return
        with self._cond:
            self._cond.notify_all()
        self._disposed = True
        self._cond = None

    @property
    def condition(self) -> threading.Condition:
        """
        Returns:
            threading.Condition: The internal condition for external coordination.
        """
        return self._cond

    def increase_permits(self, n: int = 1) -> None:
        """
        Adds additional permits to the semaphore and wakes waiting threads.

        Args:
            n (int): Number of permits to add (must be >= 0).

        Raises:
            ValueError: If n < 0.
        """
        if n < 0:
            raise ValueError("Cannot increase permits by a negative value.")

        with self._cond:
            self._permits += n
            for _ in range(n):
                self._cond.notify()

    def decrease_permits(self, n: int = 1) -> None:
        """
        Reduces the number of available permits (e.g., to pause usage).

        Args:
            n (int): Number of permits to subtract. Must be <= current permits.

        Raises:
            ValueError: If n < 0 or greater than current permit count.
        """
        if n < 0:
            raise ValueError("Cannot decrease permits by a negative value.")

        with self._cond:
            if n > self._permits:
                raise ValueError("Cannot decrease more permits than currently available.")
            self._permits -= n

    def set_permits(self, value: int):
        """
        Directly sets the internal permit count to a new value.

        Args:
            value (int): New permit value. Must be >= 0.

        Raises:
            ValueError: If value < 0.
        """
        if value < 0:
            raise ValueError("Permit count cannot be negative.")

        with self._cond:
            delta = value - self._permits
            self._permits = value
            if delta > 0:
                for _ in range(delta):
                    self._cond.notify()

    def wait_for_permit(self, timeout: float = None) -> bool:
        """
        Attempts to acquire a permit, blocking if necessary.

        Args:
            timeout (float): Max time to wait (in seconds). None means wait forever.

        Returns:
            bool: True if a permit was acquired, False if timed out.
        """
        if self._disposed:
            return False

        with self._cond:
            success = self._cond.wait_for(lambda: self._permits > 0, timeout=timeout)
            if success:
                self._permits -= 1
            return success

    def release_permit(self, n: int = 1) -> None:
        """
        Returns one or more permits back to the pool.

        Args:
            n (int): Number of permits to release.

        Raises:
            ValueError: If n < 1.
        """
        if n < 1:
            raise ValueError("Must release at least one permit.")

        with self._cond:
            self._permits += n
            for _ in range(n):
                self._cond.notify()

    def release_all(self):
        """
        Wakes all threads waiting on the internal condition.

        Note: This does *not* reset the permit count.
        """
        with self._cond:
            self._cond.notify_all()
