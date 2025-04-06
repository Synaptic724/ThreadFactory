import threading
from typing import Optional, Union, Iterable, Any, Callable
from collections import deque
from dataclasses import dataclass
import time

@dataclass
class Waiter:
    """Encapsulates a single waiting thread's lock plus its relevant IDs."""
    factory_ids: set
    lock: threading.Lock

class SmartCondition:
    """
    A drop-in Condition-like class that uses an RLock by default and enables
    targeted wakeups using one or multiple factory IDs, *without* inheriting
    from threading.Condition.

    Features:
    - `with cond:` usage (context manager).
    - `wait()`, `notify()`, `notify_all()`, `wait_for()` mechanics.
    - A "smart" wait queue that stores waiters with factory IDs.

    Example:
        cond = SmartCondition()

        # Thread #1
        with cond:
            cond.wait(factory_ids=1)

        # Thread #2
        with cond:
            cond.notify(factory_ids=[1,2])  # wakes threads waiting on 1 or 2
    """

    def __init__(self, lock: Optional[threading.Lock] = None):
        """
        Initialize the SmartCondition. By default, uses an RLock.
        """
        if lock is None:
            lock = threading.RLock()
        self._lock = lock  # This is our underlying (recursive) lock

        # For convenience, mimic Condition's pattern of exposing acquire/release
        self.acquire = self._lock.acquire
        self.release = self._lock.release

        # The waiters: each is a Waiter(factory_ids=set(...), lock=Lock())
        self._waiters = deque()

    # ------------------------------------------------------------------------
    #  Context Manager Support
    # ------------------------------------------------------------------------
    def __enter__(self):
        """
        Support usage like:
            with cond:
                ...
        which acquires the underlying lock.
        """
        self._lock.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        On exiting the `with` block, release the lock.
        """
        return self._lock.__exit__(exc_type, exc_val, exc_tb)

    # ------------------------------------------------------------------------
    #  The Key Condition-Like Methods
    # ------------------------------------------------------------------------
    def wait(
        self,
        factory_ids: Optional[Union[int, Iterable[int]]] = None,
        timeout: Optional[float] = None
    ) -> bool:
        """
        Wait until notified. While waiting, the lock is released and
        reacquired once awakened (or timed out).

        :param factory_ids:
            An int or iterable of ints representing one or more IDs
            this thread is waiting on. If None, we treat it as an empty set.
        :param timeout:
            Optional timeout in seconds (float). If None, wait indefinitely.
        :return: True if awakened normally, False if timed out.
        :raises RuntimeError:
            If the lock is not acquired before calling wait().
        """
        if not self._is_owned():
            raise RuntimeError("cannot wait on un-acquired lock")

        # Normalize factory_ids to a set
        if factory_ids is None:
            factory_ids_set = set()
        elif isinstance(factory_ids, int):
            factory_ids_set = {factory_ids}
        else:
            factory_ids_set = set(factory_ids)

        # Create a Lock that this thread will block on
        waiter_lock = threading.Lock()
        # Acquire it so the thread is forced to block on `waiter_lock.acquire()`
        waiter_lock.acquire()

        # Add to our wait-queue
        self._waiters.append(Waiter(factory_ids=factory_ids_set, lock=waiter_lock))

        # Release the underlying RLock fully, but remember how many times we had it
        saved_state = self._release_save()

        got_it = False
        try:
            if timeout is None:
                # Block indefinitely on the waiter's lock
                waiter_lock.acquire()
                got_it = True
            else:
                # Acquire with a timeout or possibly non-blocking if timeout <= 0
                if timeout > 0:
                    got_it = waiter_lock.acquire(timeout=timeout)
                else:
                    got_it = waiter_lock.acquire(blocking=False)
            return got_it
        finally:
            # Always re-acquire the underlying lock (and restore recursion count)
            self._acquire_restore(saved_state)

            # If we didn't get the lock (timed out or something else), remove from waiters
            if not got_it:
                try:
                    self._waiters.remove(Waiter(factory_ids_set, waiter_lock))
                except ValueError:
                    pass

    def notify(
        self,
        n: int = 1,
        factory_ids: Optional[Union[int, Iterable[int]]] = None
    ) -> None:
        """
        Wake up to `n` threads waiting on this condition.

        :param n:
            Maximum number of waiters to wake.
        :param factory_ids:
            If specified, only wake threads whose factory IDs intersect
            this set. (Can be a single int or an iterable.)
        :raises RuntimeError:
            If the lock is not acquired before calling notify().
        """
        if not self._is_owned():
            raise RuntimeError("cannot notify on un-acquired lock")

        if n <= 0:
            return  # no-op

        to_notify = []
        still_waiting = deque()

        # Normalize factory_ids
        if factory_ids is None:
            # Standard "notify any" approach: from the left of the queue
            while self._waiters and n > 0:
                to_notify.append(self._waiters.popleft())
                n -= 1
            still_waiting.extend(self._waiters)
        else:
            if isinstance(factory_ids, int):
                factory_ids_set = {factory_ids}
            else:
                factory_ids_set = set(factory_ids)

            # Only notify waiters whose ID sets overlap with factory_ids_set
            while self._waiters:
                w = self._waiters.popleft()
                if n > 0 and (w.factory_ids & factory_ids_set):
                    to_notify.append(w)
                    n -= 1
                else:
                    still_waiting.append(w)

        # Update our queue to those who remain waiting
        self._waiters = still_waiting

        # Release the lock for each chosen waiter, unblocking them
        for w in to_notify:
            try:
                w.lock.release()
            except RuntimeError:
                # Already released or invalid
                pass

    def get_all_waiting_factory_ids(self) -> list[int]:
        """
        Returns a flat list of all factory IDs currently associated with waiting threads.

        Each thread may be associated with one or more factory_ids,
        and the list may include duplicates to reflect multiple waiters on the same ID.

        Example return: [42, 42, 99, 100]

        Returns:
            List[int]: All active factory_ids from waiting threads.
        """
        all_ids = []
        for waiter in self._waiters:
            all_ids.extend(waiter.factory_ids)
        return all_ids

    def notify_all(
        self,
        factory_ids: Optional[Union[int, Iterable[int]]] = None
    ) -> None:
        """
        Wake up all threads waiting on this condition. If `factory_ids` is given,
        wake up only those threads with an overlapping ID set.
        """
        if not self._is_owned():
            raise RuntimeError("cannot notify_all on un-acquired lock")

        self.notify(n=len(self._waiters), factory_ids=factory_ids)

    def wait_for(
        self,
        predicate: Callable[[], bool],
        timeout: Optional[float] = None,
        factory_ids: Optional[Union[int, Iterable[int]]] = None
    ) -> bool:
        """
        Repeatedly wait (with optional factory IDs) until the predicate is True
        or until the timeout occurs. Returns the final value of the predicate.
        """
        endtime = None
        if timeout is not None:
            endtime = time.time() + timeout

        while True:
            if predicate():
                return True
            if endtime is not None:
                remaining = endtime - time.time()
                if remaining <= 0:
                    return predicate()
            self.wait(factory_ids=factory_ids, timeout=remaining if endtime else None)

    # ----------------------------------------------------------------
    #  Internals for releasing and restoring an RLock's recursion level
    # ----------------------------------------------------------------
    def _release_save(self) -> Any:
        """
        Fully release the RLock, but return any internal
        state (like the recursion level) needed to restore it later.
        """
        # If the underlying lock is an RLock, it might have _release_save.
        # If not, we fall back to a single release. But let's handle the general
        # case for an RLock so recursion count is properly restored.
        if hasattr(self._lock, '_release_save'):
            return self._lock._release_save()
        else:
            # For a basic Lock, there's no recursion level, so just release once.
            self._lock.release()
            return None

    def _acquire_restore(self, saved_state: Any) -> None:
        """
        Reacquire the RLock to the recursion level it had before _release_save().
        """
        if hasattr(self._lock, '_acquire_restore'):
            self._lock._acquire_restore(saved_state)
        else:
            # For a basic Lock, we just reacquire once.
            self._lock.acquire()

    def _is_owned(self) -> bool:
        """
        Return True if the current thread owns the underlying lock.
        This is important for verifying correct usage.
        """
        # If the lock has its own method:
        if hasattr(self._lock, '_is_owned'):
            return self._lock._is_owned()

        # Fallback approach used in Python's Condition:
        # Try a non-blocking acquire. If we succeed, that means
        # the lock wasn't owned, so we release again and return False.
        if self._lock.acquire(blocking=False):
            self._lock.release()
            return False
        return True
