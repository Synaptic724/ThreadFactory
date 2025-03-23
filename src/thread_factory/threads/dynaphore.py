import threading


class Dynaphore(threading.Semaphore):
    """
    A dynamic semaphore that can increase or decrease the number of permits at runtime.

    Inherits from threading.Semaphore but adds dynamic scaling of available permits.
    Suitable for systems requiring adaptive concurrency limits.
    """

    def __init__(self, value: int = 1):
        """
        Initialize the Dynaphore.

        Args:
            value (int): The initial number of permits. Must be >= 0.
        """
        super().__init__(value)

    def increase_permits(self, n: int) -> None:
        """
        Dynamically increase the number of available permits by `n`.

        Args:
            n (int): The number of permits to add. Must be >= 0.

        Raises:
            ValueError: If `n` is negative.
        """
        if n < 0:
            raise ValueError("Cannot increase permits by a negative value")

        with self._cond:
            self._value += n
            # Wake up threads waiting on acquire()
            for _ in range(n):
                self._cond.notify()

    def decrease_permits(self, n: int) -> None:
        """
        Dynamically decrease the number of available permits by `n`.

        Args:
            n (int): The number of permits to subtract. Must be >= 0.

        Raises:
            ValueError: If `n` is greater than the current number of permits or negative.
        """
        if n < 0:
            raise ValueError("Cannot decrease permits by a negative value")

        with self._cond:
            if n > self._value:
                raise ValueError("Cannot decrease permits: n exceeds the current number of permits")
            self._value -= n
