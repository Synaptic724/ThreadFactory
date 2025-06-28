import threading
from typing import Optional, Callable
from thread_factory.utils import IDisposable


class ThresholdSemaphore(IDisposable):
    """
    ThresholdSemaphore
    ------------------
    A reusable barrier-like semaphore that unblocks all waiting threads once
    a predefined threshold is reached.

    Useful for:
    - Coordinating N threads before beginning a task
    - Group-based task launches
    - Controlling group entry points in orchestration systems

    Parameters:
        threshold (int): Number of threads required to trigger release.
        callback (Optional[Callable[[], None]]): Optional hook when threshold is reached.
        reusable (bool): If True, resets after triggering (default: False).
    """

    def __init__(self, threshold: int, callback: Optional[Callable[[], None]] = None, reusable: bool = False):
        super().__init__()
        if threshold <= 0:
            raise ValueError("Threshold must be greater than 0")

        self._threshold = threshold
        self._callback = callback
        self._reusable = reusable

        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._count = 0
        self._released = False

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        with self._condition:
            self._condition.notify_all()

    def notify_all_override(self) -> None:
        """
        Overrides the threshold and wakes all waiting threads immediately.

        This forcibly releases all threads blocked on `wait()` regardless of whether
        the threshold has been met. Useful for shutdown, error handling, or admin-triggered
        continuation.

        Note: If reusable, the counter is reset. If not reusable, this disables further blocking.
        """
        with self._lock:
            if self._disposed:
                return

            self._released = True
            self._count = 0  # Reset for reuse
            self._condition.notify_all()


    def wait(self, timeout: Optional[float] = None) -> bool:
        """
        Waits until the threshold is reached and all threads are released.

        Returns:
            bool: True if released normally, False if timed out or disposed.
        """
        if not self._reusable and self._released:
            return False  # Already triggered, no more passes allowed

        with self._condition:
            if self._disposed:
                return False

            self._count += 1

            # Threshold reached: fire callback, release all
            if self._count == self._threshold:
                self._released = True
                if self._callback:
                    try:
                        self._callback()
                    except Exception as e:
                        pass
                self._condition.notify_all()
                return True

            # Wait for release or timeout
            released = self._condition.wait_for(lambda: self._released or self._disposed, timeout=timeout)

            if released and self._reusable and self._count >= self._threshold:
                self._count -= 1
                if self._count == 0:
                    self._released = False  # Reset for next round
            return released and not self._disposed
