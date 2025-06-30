import threading
from typing import Optional, Callable
import ulid
from thread_factory.utils import IDisposable
from thread_factory.synchronization.primitives.signal_condition import SignalCondition

class ActionBarrier(IDisposable):
    """
    ActionBarrier
    ------------------
    A reusable barrier-like semaphore that unblocks all waiting threads once
    a predefined threshold is reached.

    This class coordinates a group of threads, ensuring that a specific number (`threshold`)
    have arrived before any are allowed to proceed. Threads may optionally "transit"
    into behavior upon release using the `transit` callable.

    Release Modes:
    - Auto: Release when `threshold` is reached (default).
    - Manual: Wait until `release()` is called (`manual_release=True`).

    Parameters:
        threshold (int): Number of threads required to trigger release.
        transit (Optional[Callable[[], None]]): A function executed *by each woken thread*
                                                after the barrier is released.
        reusable (bool): If True, the barrier resets after use. Default: False.
        manual_release (bool): If True, blocks after threshold until `release()` is called.
    """
    __slots__ = IDisposable.__slots__ + [
        "_threshold", "_transit", "_reusable", "_manual_release",
        "_lock", "_condition", "_count", "_released", "_transit_fired", "_id"
    ]

    def __init__(
        self,
        threshold: int,
        transit: Optional[Callable[[], None]] = None,
        reusable: bool = False,
        manual_release: bool = False
    ):
        super().__init__()
        if threshold <= 0:
            raise ValueError("Threshold must be greater than 0")

        self._id = str(ulid.ULID())
        self._threshold = threshold
        self._transit = transit
        self._reusable = reusable
        self._manual_release = manual_release

        self._lock = threading.RLock()
        self._condition = SignalCondition(self._lock)
        self._count = 0
        self._released = False
        self._transit_fired = False

    def dispose(self):
        """Disposes the barrier and unblocks all threads."""
        if self._disposed:
            return
        self._disposed = True
        with self._condition:
            self._condition.notify_all()

    def is_spent(self) -> bool:
        """
        Returns:
            bool: True if the barrier is not reusable and has already been released.
        """
        return self._released and not self._reusable

    def notify_all_override(self) -> None:
        """
        Immediately releases all waiting threads regardless of threshold.

        This forcibly bypasses the threshold requirement. Useful for shutdown,
        admin overrides, or early exits.
        """
        with self._lock:
            if self._disposed:
                return
            self._released = True
            if not self._transit_fired:
                self._transit_fired = True
                self._condition.notify_all(self._transit)
            else:
                self._condition.notify_all()

    def release(self) -> None:
        """
        Manually releases all waiting threads when `manual_release=True`.

        Only effective after the threshold has already been reached.
        """
        with self._condition:
            if self._disposed:
                return
            if self._manual_release and self._count >= self._threshold and not self._released:
                self._released = True
                if not self._transit_fired:
                    self._transit_fired = True
                    self._condition.notify_all(self._transit)
                else:
                    self._condition.notify_all()

    def wait(self, timeout: Optional[float] = None) -> bool:
        """
        Waits at the barrier until threshold is met and threads are released.

        Args:
            timeout (float): Optional timeout in seconds.

        Returns:
            bool: True if released normally, False if timeout or already spent.
        """
        if not self._reusable and self._released:
            return False

        with self._condition:
            if not self._released:
                if self._disposed:
                    return False

                self._count += 1

                if self._count == self._threshold:
                    if not self._manual_release:
                        self._released = True
                        if not self._transit_fired:
                            self._transit_fired = True
                            self._condition.notify_all(self._transit)
                        else:
                            self._condition.notify_all()
                        return True

                released = self._condition.wait(timeout=timeout)

                if released and self._reusable:
                    self._count -= 1
                    if self._count == 0:
                        self._released = False
                        self._transit_fired = False

                return released and not self._disposed
