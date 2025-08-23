import threading
import time
from typing import Optional, Callable, Any, List, Union
from dataclasses import dataclass
import ulid
from thread_factory.concurrency.concurrent_queue import ConcurrentQueue
from thread_factory.utilities.interfaces.disposable import IDisposable
from thread_factory.utilities.coordination.package import Pack


@dataclass
class Waiter:
    """
    A value object representing a blocked thread within a SignalCondition.

    Attributes:
        lock (threading.Lock): A lock used to suspend and resume the thread.
        thread (threading.Thread): The thread instance being tracked (for diagnostics only).
        callback (Optional[Callable[[], None]]): Optional function to execute after wake-up.
    """
    lock: threading.Lock
    thread: threading.Thread
    callback: Optional[Union[Callable[..., None], Pack]] = None


class TransitCondition(IDisposable):
    """
    TransitCondition
    ----------------
    A lightweight, simplified condition-like primitive designed for event-based synchronization
    and minimal contention environments.

    Unlike `threading.Condition`, this primitive offers:
      1. **Callback Execution Inside the Woken Thread** – ensures the notifier never runs arbitrary code.
      2. **No ID-based Targeting** – maintains strict FIFO fairness.
      3. **Predictable Lifecycle** – integrates callback logic into the `wait()` lifecycle cleanly.

    Use this when you need a **declarative thread wakeup pattern**, where the signaler declares the
    logic and the waiting thread executes it — cleanly and safely.

    Suitable for:
    - Embedding post-wakeup behavior inside producers/consumers.
    - Controlled signal-response loops.
    - Minimalist pipeline signaling.
    - Self-healing wait patterns (using callbacks to re-queue or finalize state).

    Performance Tradeoff:
    - Approximately 6.4x slower than bare `RLock` due to user logic hooks, but massively safer and clearer.
    """
    __slots__ = IDisposable.__slots__ + [
        "_lock", "acquire", "release", "_waiters", "_default_callback", "_id",
    ]
    def __init__(self, lock = None, default_callback: Optional[Union[Callable[..., None], Pack]] = None):
        """
        Initialize the SignalCondition.

        Args:
            lock: Custom lock object to use (must be RLock-compatible).
                                             If None, a new RLock is created internally.
        """
        super().__init__()
        self._id = str(ulid.ULID())
        self._lock: threading.RLock = lock or threading.RLock()
        self.acquire: Callable = self._lock.acquire
        self.release: Callable = self._lock.release
        self._waiters: ConcurrentQueue[Waiter] = ConcurrentQueue()
        self._default_callback: Optional['Pack'] = (
            Pack.bundle(default_callback) if default_callback is not None else None
        )

    def dispose(self) -> None:
        """
        Dispose of this SignalCondition safely.

        This method will:
          - Mark the instance as disposed.
          - Wake all remaining waiters to prevent deadlocks.
          - Clear internal references to allow GC.
        """
        if self._disposed:
            return
        self._disposed = True

        while not self._waiters.is_empty():
            waiter = self._waiters.dequeue()
            try:
                waiter.lock.release()
            except RuntimeError:
                pass  # Already released or timed out

        self.acquire = None
        self.release = None
        self._waiters.dispose()
        self._default_callback = None

    @property
    def id(self) -> str:  # noqa: D401
        """
        ULID that uniquely identifies this latch.
        """
        return self._id

    def __enter__(self):
        """Enter the context manager and acquire the lock."""
        self._lock.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any):
        """Exit the context manager and release the lock."""
        return self._lock.__exit__(exc_type, exc_val, exc_tb)

    def set_default_callback(self, fn: Union[Callable[..., None], Pack]) -> None:
        """
        Sets a fallback callback to be run by any woken thread that
        does not receive a specific callback via `notify()` or `notify_all()`.

        Args:
            fn (Callable[[], None]): The default callable to attach to future wake-ups.
        """
        if not callable(fn):
            raise TypeError("Default callback must be a callable function")
        self._default_callback = Pack.bundle(fn)

    def find_waiter_count(self) -> int:
        """
        Returns:
            int: Number of threads currently blocked and waiting for notification.
        """
        return len(self._waiters)

    def get_all_waiters(self) -> List[Waiter]:
        """
        Returns a snapshot of all waiters currently waiting.

        Returns:
            List[Waiter]: A shallow list copy of all current waiters for diagnostics.
        """
        return list(self._waiters)

    def wait_for(self, predicate: Union[Callable[..., bool], Pack], timeout: Optional[float] = None) -> bool:
        """
        Waits until a given `predicate` function evaluates to `True`, or until an
        optional `timeout` occurs. The `predicate` is checked repeatedly: initially,
        and then after each time the thread is woken from `wait()`.

        The calling thread **must hold the `SmartCondition`'s internal lock (`self._lock`)**
        when calling this method. Internally, `self.wait()` will temporarily release `self._lock`
        while blocking, and then re-acquire it before returning.

        Args:
            predicate (Callable[[], bool]): A callable (function or method) that takes no
                                           arguments and returns a boolean value. `wait_for`
                                           will continue waiting as long as `predicate()` is `False`.
                                           It is evaluated while `self._lock` is held, ensuring thread safety.
            timeout (Optional[float]): The maximum time (in seconds) to wait for the predicate
                                       to become true. If `None`, the thread waits indefinitely.

        Returns:
            bool: `True` if the `predicate` became `True` before the `timeout` expired,
                  `False` otherwise (i.e., `timeout` occurred and `predicate` was still `False`).
        """
        # Ensure the condition's internal lock is held throughout the `wait_for` method.
        # This is the standard pattern for condition variables: the caller holds the lock,
        # which `self.wait()` then releases and re-acquires.
        with self._lock:
            endtime = time.time() + timeout if timeout is not None else None
            while True:

                if predicate:
                    predicate = Pack.bundle(predicate)
                # First, evaluate the predicate. If it's already true, we can return immediately.
                if predicate():
                    return True  # Predicate satisfied

                # If the predicate is false, calculate the remaining time for the timeout.
                if endtime is not None:
                    remaining = endtime - time.time()
                    if remaining <= 0:
                        # If the timeout has expired, check the predicate one last time
                        # and return its current state.
                        return predicate()

                # If the predicate is false and there's still time, wait for a notification.
                # `self.wait()` will temporarily release `self._lock` (because it's within this `with` block)
                # and re-acquire it when woken or after timeout.
                self.wait(timeout=remaining if endtime else None)

    def wait(self, timeout: Optional[float] = None) -> bool:
        """
        Blocks the calling thread until it is notified, then executes
        an attached callback (if any), and resumes.

        Args:
            timeout (Optional[float]): Maximum time to wait (in seconds). `None` = wait forever.

        Returns:
            bool: True if woken by a notifier. False if timed out.

        Raises:
            RuntimeError: If the internal lock is not acquired prior to calling.
        """
        if self._disposed:
            raise RuntimeError("SignalCondition has been disposed")
        if not self._is_owned():
            raise RuntimeError("cannot wait on un-acquired lock")

        # Prepare the local lock the thread will block on.
        waiter_lock = threading.Lock()
        waiter_lock.acquire()

        waiter = Waiter(lock=waiter_lock, thread=threading.current_thread())
        self._waiters.enqueue(waiter)

        # Release main lock temporarily while waiting.
        saved_state = self._release_save()
        woke_normally = False
        try:
            if timeout is None:
                waiter_lock.acquire()
                woke_normally = True
            else:
                woke_normally = waiter_lock.acquire(timeout=timeout)
            return woke_normally
        finally:
            self._acquire_restore(saved_state)
            if woke_normally:
                cb = waiter.callback or self._default_callback
                if cb:
                    try:
                        cb()
                    except Exception as exc:
                        pass
            else:
                # If the wait timed out, clean up the queue entry.
                self._waiters.remove_item(waiter)

    def notify(self, n: int = 1, callback: Optional[Union[Callable[..., None], Pack]] = None) -> None:
        """
        Wake up to `n` waiters, optionally assigning a callback to each.

        Args:
            n (int): Maximum number of threads to notify.
            callback (Optional[Callable[[], None]]): Callable to assign to each woken waiter.

        Raises:
            RuntimeError: If the calling thread doesn't hold the internal lock.
        """
        if n <= 0:
            return
        if not self._is_owned():
            raise RuntimeError("cannot notify on un-acquired lock")
        if callback:
            callback = Pack.bundle(callback)
        to_notify: List[Waiter] = []
        for w in list(self._waiters):
            if n == 0:
                break
            if self._waiters.remove_item(w):
                to_notify.append(w)
                n -= 1

        for w in to_notify:
            w.callback = callback or self._default_callback
            try:
                w.lock.release()
            except RuntimeError:
                pass  # Thread likely timed out and already moved on.

    def notify_all(self, callback: Optional[Union[Callable[..., None], Pack]] = None) -> None:
        """
        Wake all current waiters and optionally assign a callback to each.

        Args:
            callback (Optional[Callable[[], None]]): Callable to assign to each woken waiter.

        Raises:
            RuntimeError: If the internal lock is not held.
        """
        if not self._is_owned():
            raise RuntimeError("cannot notify_all on un-acquired lock")
        if callback:
            callback = Pack.bundle(callback)

        for w in list(self._waiters):
            if self._waiters.remove_item(w):
                w.callback = callback or self._default_callback
                try:
                    w.lock.release()
                except RuntimeError:
                    pass

    def _release_save(self) -> Any:
        """
        Internal: Releases the current lock completely and returns a restore token.

        This ensures compatibility with both CPython and subclassed locks.

        Returns:
            Any: A token (either int or None) used to later restore the lock state.
        """
        if hasattr(self._lock, "_release_save"):
            return self._lock._release_save()
        if isinstance(self._lock, threading.RLock):
            count = 0
            while self._lock._is_owned():
                self._lock.release()
                count += 1
            return count
        self._lock.release()
        return None

    def _acquire_restore(self, saved_state: Any) -> None:
        """
        Internal: Restores the lock state using a token from `_release_save()`.

        Args:
            saved_state (Any): The token returned during lock release.
        """
        if hasattr(self._lock, "_acquire_restore"):
            self._lock._acquire_restore(saved_state)
            return
        if isinstance(self._lock, threading.RLock) and isinstance(saved_state, int):
            for _ in range(saved_state):
                self._lock.acquire()
            return
        self._lock.acquire()

    def _is_owned(self) -> bool:
        """
        Internal: Determines if the current thread owns the lock.

        Returns:
            bool: True if the thread holds the lock.
        """
        if hasattr(self._lock, "_is_owned"):
            return self._lock._is_owned()
        # Manual fallback: Try to acquire. If successful, we didn’t own it.
        if self._lock.acquire(blocking=False):
            self._lock.release()
            return False
        return True
