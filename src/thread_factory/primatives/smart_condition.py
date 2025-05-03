import threading
from typing import Optional, Union, Iterable, Any, Callable
from collections import deque
from dataclasses import dataclass
import time
from thread_factory.runtime.worker.worker import Worker

@dataclass
class Waiter:
    """
    Encapsulates a single waiting thread's lock plus its single factory_id.
    Internally uses an RLock to support nested acquisitions if needed.
    """
    factory_id: int
    lock: threading.Lock

class SmartCondition:
    """
    A drop-in Condition-like class that uses an RLock by default and
    enables targeted wakeups using one or multiple factory IDs, *without*
    inheriting from threading.Condition.

    Features:
    - `with cond:` usage (context manager).
    - `wait()`, `notify()`, `notify_all()`, `wait_for()` mechanics.
    - A "smart" wait queue that stores waiters each with a single factory_id.

    Example:
        cond = SmartCondition()

        # Thread #1 (knows its own factory_id)
        with cond:
            cond.wait()  # uses current_thread().factory_id internally

        # Thread #2
        with cond:
            # notify factory_id 1 or 2
            cond.notify(factory_ids=[1, 2])

    NOTE: Each thread is expected to have a .factory_id attribute if using wait().
    """

    def __init__(self, lock: Optional[threading.Lock] = None):
        """
        Initialize the SmartCondition. By default, uses an RLock.
        """
        if lock is None:
            lock = threading.RLock()
        self._lock = lock  # Underlying (recursive) lock

        # For convenience, mimic Condition's pattern of exposing acquire/release
        self.acquire = self._lock.acquire
        self.release = self._lock.release

        # The waiters: each is a Waiter(factory_id=int, lock=RLock())
        self._waiters = deque()

    # ------------------------------------------------------------------------
    # Context Manager Support
    # ------------------------------------------------------------------------
    def __enter__(self):
        """
        Usage:
            with cond:
                ...
        acquires the underlying lock.
        """
        self._lock.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        On exiting the `with` block, release the lock.
        """
        return self._lock.__exit__(exc_type, exc_val, exc_tb)

    # ------------------------------------------------------------------------
    # Key Condition-Like Methods
    # ------------------------------------------------------------------------
    def wait(self, timeout: Optional[float] = None) -> bool:
        """
        Wait until notified. While waiting, the lock is released and
        reacquired once awakened (or timed out).

        The current thread must provide a .factory_id attribute (an int).

        :param timeout:
            Optional timeout in seconds (float). If None, wait indefinitely.
        :return:
            True if awakened normally, False if timed out.
        :raises RuntimeError:
            If the lock is not acquired before calling wait().
        :raises AttributeError:
            If the current thread doesn't have .factory_id
        """
        if not self._is_owned():
            raise RuntimeError("cannot wait on un-acquired lock")

        factory_id = self._get_factory_id_from_thread()

        # Use a plain Lock (NOT RLock)
        waiter_lock = threading.Lock()
        waiter_lock.acquire()  # locked by this thread

        self._waiters.append(Waiter(factory_id=factory_id, lock=waiter_lock))

        saved_state = self._release_save()
        got_it = False
        try:
            if timeout is None:
                # This will now truly block
                waiter_lock.acquire()
                got_it = True
            else:
                if timeout > 0:
                    got_it = waiter_lock.acquire(timeout=timeout)
                else:
                    got_it = waiter_lock.acquire(blocking=False)
            return got_it
        finally:
            self._acquire_restore(saved_state)
            if not got_it:
                try:
                    self._waiters.remove(Waiter(factory_id, waiter_lock))
                except ValueError:
                    pass

    def notify(self, n: int = 1, factory_ids: Optional[Union[int, Iterable[int]]] = None) -> None:
        """
        Wake up to `n` threads waiting on this condition.

        :param n:
            Maximum number of waiters to wake.
        :param factory_ids:
            If specified, only wake threads whose factory_id is in the set.
            This can be a single int or an iterable of ints.
        :raises RuntimeError:
            If the lock is not acquired before calling notify().
        """
        if not self._is_owned():
            raise RuntimeError("cannot notify on un-acquired lock")

        if n <= 0:
            return  # no-op

        to_notify = []
        still_waiting = deque()

        # Normalize factory_ids into a set, or None for "notify any"
        if factory_ids is None:
            # Standard "notify any" approach: from the left of the queue
            while self._waiters and n > 0:
                to_notify.append(self._waiters.popleft())
                n -= 1
            # Put the rest back
            still_waiting.extend(self._waiters)
        else:
            # If user passes a single int, wrap it into a set
            if isinstance(factory_ids, int):
                factory_ids_set = {factory_ids}
            else:
                factory_ids_set = set(factory_ids)

            # Only notify waiters whose factory_id is in factory_ids_set
            while self._waiters:
                w = self._waiters.popleft()
                if n > 0 and w.factory_id in factory_ids_set:
                    to_notify.append(w)
                    n -= 1
                else:
                    still_waiting.append(w)

        # Update our queue to those who remain waiting
        self._waiters = still_waiting

        # Release each chosen waiter's lock, unblocking them
        for w in to_notify:
            try:
                w.lock.release()
            except RuntimeError:
                # Already released or invalid
                pass

    def notify_all(self, factory_ids: Optional[Union[int, Iterable[int]]] = None) -> None:
        """
        Wake up all threads waiting on this condition. If `factory_ids` is given,
        wake up only those threads whose factory_id is in that set.
        """
        if not self._is_owned():
            raise RuntimeError("cannot notify_all on un-acquired lock")

        self.notify(n=len(self._waiters), factory_ids=factory_ids)

    def wait_for(self, predicate: Callable[[], bool], timeout: Optional[float] = None) -> bool:
        """
        Repeatedly wait until the predicate is True or until the timeout occurs.
        Returns the final value of the predicate.

        This uses the current thread's factory_id automatically.

        :param predicate:
            A callable returning a boolean: when True, stop waiting.
        :param timeout:
            Optional overall timeout (in seconds). If None, wait indefinitely.
        :return:
            The final value of the predicate.
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
            self.wait(timeout=remaining if endtime else None)

    def get_all_waiting_factory_ids(self) -> list[int]:
        """
        Returns a flat list of all factory IDs currently associated with waiting threads.

        Example return: [42, 42, 99, 100]

        Returns:
            List[int]: All active factory_ids from waiting threads.
        """
        return [w.factory_id for w in self._waiters]

    # ----------------------------------------------------------------
    # Internals for releasing/restoring an RLock's recursion level
    # ----------------------------------------------------------------
    def _release_save(self) -> Any:
        """
        Fully release the RLock, returning any internal state (like the
        recursion level) needed to restore it later.
        """
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
        if hasattr(self._lock, '_is_owned'):
            return self._lock._is_owned()
        # Fallback approach used in Python's Condition:
        if self._lock.acquire(blocking=False):
            self._lock.release()
            return False
        return True

    def _get_factory_id_from_thread(self) -> int:
        """
        Extract a single integer factory_id from the current thread.
        Ensures the thread is an instance of `Worker` and has .factory_id.
        """
        thread = threading.current_thread()

        # Explicitly check if it's a Worker
        if not isinstance(thread, Worker):
            raise TypeError(f"Current thread {thread.name} is not a Worker instance; "
                            "cannot retrieve factory_id.")

        # At this point, thread is a Worker, so we can safely access factory_id
        return thread.factory_id
