import threading
from typing import Optional, Callable
from thread_factory.utils import IDisposable
from thread_factory.primitives import SignalCondition


class ActionBarrier(IDisposable):
    """
    ActionBarrier
    ------------------
    A reusable barrier-like semaphore that unblocks all waiting threads once
    a predefined threshold is reached.

    This class coordinates the execution of a group of threads, ensuring that a
    predefined number of them (the `threshold`) have arrived at a specific point
    before any of them are allowed to proceed.

    It supports two modes for releasing threads:
    - **Auto-release**: When `manual_release=False` (default), all waiting threads are
      automatically unblocked as soon as the `threshold` is met.
    - **Manual-release**: When `manual_release=True`, threads block even after the
      threshold is reached until `release()` is explicitly called.

    This is useful for:
    - Synchronizing the start of a task across multiple threads.
    - Implementing execution phases where all threads must complete one stage
      before starting the next.
    - Coordinating group-based task launches.

    Parameters:
        threshold (int): The number of threads required to trigger the barrier's release.
                         Must be greater than 0.
        callback (Optional[Callable[[], None]]): An optional function to be executed by
                                                 each thread as it is unblocked and woken.
                                                 This hook is triggered after the threshold is met.
        reusable (bool): If True, the barrier automatically resets its state after being
                         triggered, allowing it to be used multiple times. If False
                         (default), the barrier is a single-use object.
        manual_release (bool): If True, threads arriving at the threshold will wait
                               until the `release()` method is called manually.
    """
    __slots__ = IDisposable.__slots__ + [
        "_threshold", "_callback", "_reusable", "_manual_release",
        "_lock", "_condition", "_count", "_released", "_callback_fired"
    ]

    def __init__(
        self,
        threshold: int,
        callback: Optional[Callable[[], None]] = None,
        reusable: bool = False,
        manual_release: bool = False
    ):
        super().__init__()
        if threshold <= 0:
            raise ValueError("Threshold must be greater than 0")

        self._threshold = threshold
        self._callback = callback
        self._reusable = reusable
        self._manual_release = manual_release

        self._lock = threading.RLock()
        self._condition = SignalCondition(self._lock)
        self._count = 0
        self._released = False
        self._callback_fired = False

    def dispose(self):
        """
        Disposes of the barrier and immediately unblocks all waiting threads.

        This is a hard shutdown mechanism, useful for preventing deadlocks during
        application termination or error handling.
        """
        if self._disposed:
            return
        self._disposed = True
        with self._condition:
            self._condition.notify_all()

    def is_spent(self) -> bool:
        """
        Checks if the threshold has already been reached and this semaphore
        is no longer reusable (i.e., it's 'spent').

        Returns:
            bool: True if the threshold has been reached and the barrier is a single-use
                  instance (i.e., it's 'spent'). Returns False otherwise.
        """
        return self._released and not self._reusable

    def notify_all_override(self) -> None:
        """
        Overrides the threshold and immediately wakes all waiting threads.

        This method forcibly releases all threads blocked on `wait()`, regardless of
        whether the threshold has been met. It is useful for implementing forced
        continuation, shutdown, or error handling logic.

        Note: If the barrier is reusable, the counter is reset. If not, this action
              disables any further blocking attempts.
        """
        with self._lock:
            if self._disposed:
                return

            self._released = True
            if not self._callback_fired:
                self._callback_fired = True
                self._condition.notify_all(self._callback)
            else:
                self._condition.notify_all()

    def release(self) -> None:
        """
        Manually releases all waiting threads.

        This method is only applicable when `manual_release=True` and the threshold
        has already been reached.
        """
        with self._condition:
            if self._disposed:
                return
            if self._manual_release and self._count >= self._threshold and not self._released:
                self._released = True
                if not self._callback_fired:
                    self._callback_fired = True
                    self._condition.notify_all(self._callback)
                else:
                    self._condition.notify_all()


    def wait(self, timeout: Optional[float] = None) -> bool:
        """
        Blocks the calling thread until the threshold is reached and all threads are released.

        A thread that calls `wait()` increments the internal counter. When the count
        reaches the `threshold`, the barrier is triggered.

        Args:
            timeout (Optional[float]): The maximum time (in seconds) to wait.
                                       If `None` (default), the thread waits indefinitely.

        Returns:
            bool: True if the thread was unblocked by the barrier being triggered.
                  Returns False if the wait timed out or if the barrier was already
                  'spent' (i.e., triggered and not reusable).

        Notes:
            - A thread that reaches the `threshold` and triggers the barrier's release
              does not block and returns `True` immediately.
            - The `callback` (if provided) is executed by each of the threads that
              were waiting and are subsequently woken up, not by the thread that
              triggers the release.
        """
        if not self._reusable and self._released:
            return False  # Already triggered, no more passes allowed

        with self._condition:
            if not self._released:
                if self._disposed:
                    return False

                self._count += 1

                if self._count == self._threshold:
                    if not self._manual_release:
                        self._released = True
                        if not self._callback_fired:
                            self._callback_fired = True
                            self._condition.notify_all(self._callback)
                        else:
                            self._condition.notify_all()
                        return True  # Current thread triggered it

                # Wait for release or timeout
                released = self._condition.wait(timeout=timeout)

                # Always decrement after release if reusable
                if released and self._reusable:
                    self._count -= 1
                    if self._count == 0:
                        self._released = False
                        self._callback_fired = False

                return released and not self._disposed
