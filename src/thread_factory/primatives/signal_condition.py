import threading
from typing import Optional, Callable, Any, List
from dataclasses import dataclass
from thread_factory.concurrency.concurrent_queue import ConcurrentQueue
from thread_factory.utils.interfaces.disposable import IDisposable


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
    callback: Optional[Callable[[], None]] = None


class SignalCondition(IDisposable):
    """
    A *minimal* Condition-flavoured primitive with **embedded callbacks**.

    Differences to :class:`threading.Condition`:
    ------------------------------------------------
    1. **Always awaited-caller execution** – Any callback set via
       :py:meth:`notify` / :py:meth:`notify_all` (or the optional *default*)
       is executed *inside the woken thread* **after** it re-acquires the
       internal lock.  The notifying thread *never* runs user code.

    2. **No targeting / no IDs** – Every waiter is treated equally.  First
       come, first served.

    3. **No advanced semantics** – No bias, worker-type checks, or
       per-thread registries.  The goal is surfacing a single, declarative
       pattern:

            • Thread blocks via ``wait()``
            • Notifier wakes it and optionally attaches a callable
            • Waiter runs the callable → continues

    Typical use-cases:
    ------------------
    • Embedding *post-wake initialization* in a producer/consumer queue.
    • Barrier coordination where each participant performs a local
      side-effect on release.
    • Replacing scattered ``wait()/notify()`` pairs with a *single* call that
      declares *both* the wake and the follow-up action.

    Performance note:
    -----------------
    • Raw `RLock.acquire()/release()` took ~0.00196s
    • `SignalCondition.wait()/notify()` took ~0.01256s
    → SignalCondition is ~6.4× slower in minimal contention scenarios.
    """

    def __init__(self, lock: Optional[threading.Lock] = None):
        """
        Initialize the SignalCondition.

        Args:
            lock (Optional[threading.Lock]): Custom lock object to use (must be RLock-compatible).
                                              If None, a new RLock is created.
        """
        super().__init__()
        self._lock: threading.RLock = lock or threading.RLock()
        self.acquire: Callable = self._lock.acquire
        self.release: Callable = self._lock.release
        self._waiters: ConcurrentQueue[Waiter] = ConcurrentQueue()
        self._default_callback: Optional[Callable[[], None]] = None

    def __enter__(self):
        """Enter the context manager and acquire the lock."""
        self._lock.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any):
        """Exit the context manager and release the lock."""
        return self._lock.__exit__(exc_type, exc_val, exc_tb)

    def set_default_callback(self, fn: Callable[[], None]) -> None:
        """
        Set a fallback callback that is executed by any woken thread
        which did not receive an explicit callback.

        Args:
            fn (Callable[[], None]): The default callable. Set to None to clear it.
        """
        self._default_callback = fn

    def find_waiter_count(self) -> int:
        """
        Returns:
            int: The number of threads currently blocked.
        """
        return len(self._waiters)

    def get_all_waiters(self) -> List[Waiter]:
        """
        Snapshot of all waiters currently waiting.

        Returns:
            List[Waiter]: A shallow copy of all current waiters.
        """
        return list(self._waiters)

    def wait(self, timeout: Optional[float] = None) -> bool:
        """
        Block the calling thread until notified or timeout occurs.

        Args:
            timeout (Optional[float]): Maximum time to wait in seconds.

        Returns:
            bool: True if woken by notifier, False if timed out.

        Raises:
            RuntimeError: If the internal lock is not acquired.
        """
        if self._disposed:
            raise RuntimeError("SignalCondition has been disposed")
        if not self._is_owned():
            raise RuntimeError("cannot wait on un-acquired lock")

        waiter_lock = threading.Lock()
        waiter_lock.acquire()

        waiter = Waiter(lock=waiter_lock, thread=threading.current_thread())
        self._waiters.enqueue(waiter)

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
                        print(f"[SignalCondition] Callback error: {exc}")
            else:
                self._waiters.remove_item(waiter)

    def notify(self, n: int = 1, callback: Optional[Callable[[], None]] = None) -> None:
        """
        Wake up to `n` waiters, optionally attaching a callback to each.

        Args:
            n (int): Number of waiters to wake.
            callback (Optional[Callable[[], None]]): Optional function passed to each waiter.

        Raises:
            RuntimeError: If the lock is not acquired.
        """
        if n <= 0:
            return
        if not self._is_owned():
            raise RuntimeError("cannot notify on un-acquired lock")

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
                pass  # Likely timed out

    def notify_all(self, callback: Optional[Callable[[], None]] = None) -> None:
        """
        Wake all current waiters, optionally attaching a callback to each.

        Args:
            callback (Optional[Callable[[], None]]): Optional function passed to all waiters.

        Raises:
            RuntimeError: If the lock is not acquired.
        """
        if not self._is_owned():
            raise RuntimeError("cannot notify_all on un-acquired lock")

        for w in list(self._waiters):
            if self._waiters.remove_item(w):
                w.callback = callback or self._default_callback
                try:
                    w.lock.release()
                except RuntimeError:
                    pass

    def _release_save(self) -> Any:
        """
        Internal: Fully releases the internal RLock and returns a restore token.

        Returns:
            Any: Token used for restoring the original lock state.
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
        Internal: Re-acquires the internal RLock based on the saved token.

        Args:
            saved_state (Any): Token returned by _release_save().
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
        Internal: Checks if the current thread holds the internal lock.

        Returns:
            bool: True if the lock is held by this thread.
        """
        if hasattr(self._lock, "_is_owned"):
            return self._lock._is_owned()
        if self._lock.acquire(blocking=False):
            self._lock.release()
            return False
        return True

    def dispose(self) -> None:
        """
        Dispose of the SignalCondition, releasing all resources and clearing waiters.

        This method is idempotent and can be called multiple times without side effects.
        """
        if self._disposed:
            return
        self._disposed = True
        # Clear all waiters
        while not self._waiters.is_empty():
            waiter = self._waiters.dequeue()
            try:
                waiter.lock.release()
            except RuntimeError:
                pass
        self.acquire = None
        self.release = None
        self._waiters.dispose()
        self._default_callback = None

