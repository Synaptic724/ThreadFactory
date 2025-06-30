import threading


class Latch:
    """
    SimpleLatch
    -----------
    A lightweight synchronization primitive that blocks threads until it is manually opened.

    - Once opened, all waiting threads proceed and future calls pass through without blocking.
    - Optionally, it can be reset manually to block again.
    - Safe for concurrent use.

    Example Usage:
    --------------
    >>> latch = Latch()
    >>> def task():
    ...     latch.wait()
    ...     print("Latch opened!")

    >>> threading.Thread(target=task).start()
    >>> latch.open()
    """

    def __init__(self):
        self._open = False
        self._condition = threading.Condition()

    def wait(self, timeout: float = None) -> bool:
        """
        Blocks the calling thread until the latch is opened.
        Returns True if the latch is open, False if it timed out.

        Args:
            timeout (float): Optional timeout in seconds.
        """
        with self._condition:
            if self._open:
                return True
            self._condition.wait(timeout)
            return self._open

    def open(self):
        """
        Opens the latch and releases all waiting threads.
        Once opened, it remains open until explicitly reset.
        """
        with self._condition:
            self._open = True
            self._condition.notify_all()

    def reset(self):
        """
        Resets the latch to the closed state.
        Threads calling `wait()` after this will block again.
        """
        with self._condition:
            self._open = False

    def is_open(self) -> bool:
        """
        Returns whether the latch is currently open.
        """
        with self._condition:
            return self._open

