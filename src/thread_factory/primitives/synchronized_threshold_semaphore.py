import threading
import time
from typing import Optional, Callable
from thread_factory.utils import IDisposable


class SynchronizedThresholdSemaphore(IDisposable):
    """
    SynchronizedThresholdSemaphore
    ------------------------------
    A reusable barrier-like semaphore that unblocks all waiting threads once
    a predefined threshold is reached.

    Supports automatic release, manual release, timeout handling, and reusability.

    Useful for:
    - Coordinating N threads before beginning a task
    - Group-based task launches
    - Controlling execution phases

    Parameters:
        threshold (int): Number of threads required to trigger release.
        callback (Optional[Callable[[], None]]): Optional hook when threshold is reached.
        reusable (bool): If True, resets after triggering (default: False).
        manual_release (bool): If True, waits after threshold until release() is called.
        timeout (Optional[float]): The maximum time in seconds to wait for the threshold to be met.
        raise_on_timeout (bool): If True, raises a TimeoutError on timeout instead of returning False.
    """
    __slots__ = IDisposable.__slots__ + [
        "_threshold", "_callback", "_reusable", "_manual_release",
        "_timeout", "_raise_on_timeout", "_broken", "_start_time",
        "_lock", "_condition", "_count", "_released",
    ]

    def __init__(
            self,
            threshold: int,
            callback: Optional[Callable[[], None]] = None,
            reusable: bool = False,
            manual_release: bool = False,
            timeout: Optional[float] = None,
            raise_on_timeout: bool = False
    ):
        super().__init__()
        if threshold <= 0:
            raise ValueError("Threshold must be greater than 0")

        self._threshold = threshold
        self._callback = callback
        self._reusable = reusable
        self._manual_release = manual_release
        self._timeout = timeout
        self._raise_on_timeout = raise_on_timeout

        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._count = 0
        self._released = False
        self._broken = False
        self._start_time = None

    def dispose(self):
        """
        Disposes of the semaphore, releasing all waiting threads and preventing further use.
        """
        if self._disposed:
            return
        self._disposed = True
        with self._condition:
            self._broken = True
            self._released = True
            self._condition.notify_all()

    def is_spent(self) -> bool:
        """
        Returns:
            bool: True if the threshold has already been reached and this semaphore
            is not reusable (i.e., it's 'spent').
        """
        return self._released and not self._reusable

    def notify_all_override(self) -> None:
        """
        Overrides the threshold and wakes all waiting threads immediately.
        """
        with self._condition:
            if self._disposed:
                return

            self._released = True
            self._broken = True
            self._condition.notify_all()
            if self._reusable:
                self.reset()

    def release(self) -> None:
        """
        Manually releases all waiting threads.
        """
        with self._condition:
            if self._disposed:
                return
            if self._manual_release and self._count >= self._threshold and not self._released:
                self._released = True
                self._condition.notify_all()

    def reset(self):
        """
        Resets the semaphore state.
        This method should be called with the condition lock held if called internally.
        """
        self._released = False
        self._broken = False
        self._start_time = None
        self._count = 0

    def wait(self, timeout: Optional[float] = None) -> bool:
        """
        Waits until the threshold is reached and all threads are released.
        """
        with self._condition:
            # Check for broken or disposed state first
            if self._disposed:
                return False
            if self._broken:
                if self._raise_on_timeout:
                    raise TimeoutError("Semaphore is already in a broken state due to a timeout or override.")
                return False

            # Set start time for the first thread entering the barrier
            if self._start_time is None:
                self._start_time = time.monotonic()

            self._count += 1

            if self._count == self._threshold and not self._released:
                if self._callback:
                    try:
                        self._callback()
                    except Exception:
                        pass
                if not self._manual_release:
                    self._released = True
                    self._condition.notify_all()

            # Calculate the effective timeout for this wait call
            effective_timeout = timeout if timeout is not None else self._timeout
            remaining = effective_timeout
            if self._start_time is not None and effective_timeout is not None:
                elapsed = time.monotonic() - self._start_time
                if elapsed >= effective_timeout:
                    remaining = 0
                else:
                    remaining = effective_timeout - elapsed

            # Wait for release or timeout
            released = self._condition.wait_for(
                lambda: self._released or self._disposed,
                timeout=remaining
            )

            self._count -= 1

            # Check if wait_for timed out
            if not released and not self._disposed:
                self._broken = True
                self._released = True  # Release others who might also be waiting
                self._condition.notify_all()
                if self._raise_on_timeout:
                    raise TimeoutError("Semaphore wait timed out.")

            # If this is the last thread and the semaphore is reusable, reset it
            if self._reusable and self._count == 0 and self._released:
                self.reset()

            # Return status based on whether it was released or disposed
            return released and not self._disposed