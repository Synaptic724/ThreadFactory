import threading
import ulid
from thread_factory.utilities.interfaces.disposable import IDisposable

class Dynaphore(threading.Semaphore, IDisposable):
    """
    Dynaphore
    ---------
    A dynamic semaphore for thread coordination in high-performance environments.

    This class extends Python’s standard `threading.Semaphore` with the ability to
    dynamically scale the number of permits up or down at runtime.

    Unlike standard semaphores, Dynaphore provides:
    - A public `Condition` object for external wait/notify signaling.
    - Runtime-safe scaling of permits using `increase_permits()` and `decrease_permits()`.
    - Explicit permit acquisition via `wait_for_permit()` and release via `release_permit()`.
    - Optional use of `RLock` or plain `Lock` for re-entrant or non-reentrant access.

    This class is useful for:
    - Resource pool regulation
    - Adaptive throttling
    - Runtime coordination across multiple threads and systems

    Example:
        ```python
        dyn = Dynaphore(value=2)

        def worker():
            if dyn.wait_for_permit():
                try:
                    do_work()
                finally:
                    dyn.release_permit()

        # Add more capacity dynamically
        dyn.increase_permits(3)
        ```

    Parameters:
        value (int): Initial number of permits (must be >= 0).
        re_entrant (bool): If True (default), uses an RLock in the internal Condition.

    """
    __slots__ = IDisposable.__slots__ + [
        "_cond", "_id",
    ]
    def __init__(self, value: int = 1, re_entrant: bool = True):
        super().__init__(value)
        IDisposable.__init__(self)

        self._id = str(ulid.ULID())
        if re_entrant:
            self._cond = threading.Condition()  # Uses RLock by default
        else:
            self._cond = threading.Condition(threading.Lock())

    def dispose(self):
        """
        Cleans up the Dynaphore and notifies all waiting threads.

        This method should be called when the Dynaphore is no longer needed
        to ensure no threads remain blocked on the internal condition.
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
            threading.Condition: The internal condition used for thread coordination.

        This allows external callers to manually wait, notify, or build complex multi-condition logic.
        """
        return self._cond

    def increase_permits(self, n: int = 1) -> None:
        """
        Increases the number of available permits and notifies waiting threads.

        Parameters:
            n (int): Number of permits to add (must be >= 0).

        Raises:
            ValueError: If `n` is negative.
        """
        if n < 0:
            raise ValueError("Cannot increase permits by a negative value")

        with self._cond:
            self._value += n
            for _ in range(n):
                self._cond.notify()

    def decrease_permits(self, n: int = 1) -> None:
        """
        Decreases the number of available permits.

        Parameters:
            n (int): Number of permits to remove (must be >= 0 and <= current value).

        Raises:
            ValueError: If `n` is negative or exceeds available permits.
        """
        if n < 0:
            raise ValueError("Cannot decrease permits by a negative value")

        with self._cond:
            if n > self._value:
                raise ValueError("Cannot decrease more permits than available")
            self._value -= n

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
            delta = value - self._value
            self._value = value
            if delta > 0:
                for _ in range(delta):
                    self._cond.notify()

    def wait_for_permit(self, timeout: float = None) -> bool:
        """
        Waits until at least one permit becomes available, then reserves it.

        Parameters:
            timeout (float, optional): Max time in seconds to wait. If None, waits indefinitely.

        Returns:
            bool: True if a permit was acquired, False if timed out.

        Behavior:
            This method blocks the thread until a permit becomes available or timeout occurs.
        """
        if self._disposed:
            return False

        with self._cond:
            result = self._cond.wait_for(lambda: self._value > 0, timeout=timeout)
            if result:
                self._value -= 1
            return result

    def release_permit(self, n: int = 1):
        """
        Releases one or more permits back to the pool.

        Parameters:
            n (int): Number of permits to release.

        Raises:
            ValueError: If n < 1.
        """
        if n < 1:
            raise ValueError("Must release at least one permit.")

        with self._cond:
            self._value += n
            for _ in range(n):
                self._cond.notify()

    def release_all(self):
        """
        Wakes all threads waiting on the internal condition.

        Note: This does *not* reset the permit count.
        """
        with self._cond:
            self._cond.notify_all()