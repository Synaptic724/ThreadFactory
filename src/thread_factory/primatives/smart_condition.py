import threading
import time
import ulid
from typing import Optional, Union, Iterable, Any, Callable
from dataclasses import dataclass
# Assuming ConcurrentQueue is correctly imported from your project's modules
from thread_factory.concurrency.concurrent_queue import ConcurrentQueue


@dataclass
class Waiter:
    """
    Represents a single thread currently waiting on the SmartCondition.

    Attributes:
        factory_id (str): A unique string identifier (ULID or "MainThread")
                          associated with the waiting thread.
        lock (threading.Lock): A private, dedicated lock for this specific
                               waiter thread. This lock is used by the thread
                               to block itself until notified.
        thread (threading.Thread): A direct reference to the `threading.Thread`
                                   object that is waiting.
    """
    factory_id: str
    lock: threading.Lock
    thread: threading.Thread


class SmartCondition:
    """
    SmartCondition
    ---------------
    A custom, thread-aware condition variable that extends the capabilities
    of `threading.Condition`. It provides:
    - Thread-aware semantics using unique `factory_id`s (typically ULIDs).
    - The ability to target and wake specific threads or groups of threads
      based on their `factory_id`s.
    - Snapshot access to all currently waiting threads and their identifiers.

    This class is particularly useful in complex concurrent systems, such as
    thread pools, dynamic semaphores, or orchestrators, where more granular
    control over thread signaling and coordination is required than offered
    by standard condition variables.
    """

    def __init__(self, lock: Optional[threading.Lock] = None):
        """
        Initializes the SmartCondition.

        Args:
            lock (Optional[threading.Lock]): An optional external lock object
                                             to be used for synchronization.
                                             If None, a new reentrant lock (`threading.RLock`)
                                             is created and used internally.
                                             The condition variable operates on this lock,
                                             meaning `wait()`, `notify()`, and `notify_all()`
                                             methods require this lock to be acquired by the
                                             calling thread.
        """
        self._lock: threading.RLock = lock or threading.RLock()
        self.acquire: Callable = self._lock.acquire  # Expose acquire method of the internal lock
        self.release: Callable = self._lock.release  # Expose release method of the internal lock
        self._waiters: ConcurrentQueue[Waiter] = ConcurrentQueue[
            Waiter]()  # Queue of Waiter objects, representing all blocked threads.

    def __enter__(self):
        """
        Enters the runtime context for the SmartCondition, acquiring its internal lock.
        Allows use with the `with` statement.
        """
        self._lock.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any):
        """
        Exits the runtime context for the SmartCondition, releasing its internal lock.
        Automatically called when exiting a `with` statement.
        """
        return self._lock.__exit__(exc_type, exc_val, exc_tb)

    def _ensure_factory_id(self) -> str:
        """
        Ensures that the current `threading.Thread` object has a `factory_id` attribute.
        If the attribute already exists and is not None, its value is returned.
        Otherwise, a new `factory_id` is assigned: "MainThread" for the main thread,
        or a new ULID string for other threads.

        This method is crucial for enabling thread-aware functionality
        within `SmartCondition` (e.g., targeted notifications).

        Returns:
            str: The unique `factory_id` associated with the current thread.
        """
        thread = threading.current_thread()
        if hasattr(thread, "factory_id") and thread.factory_id is not None:
            return thread.factory_id

        # If the attribute is missing or None, assign it based on thread type.
        if thread.name == "MainThread":
            thread.factory_id = "MainThread"
        else:
            # Assign a new ULID if it's not the MainThread and has no pre-existing factory_id.
            thread.factory_id = str(ulid.ULID())

        return thread.factory_id  # Returns the now-guaranteed-to-be-set factory_id

    def wait(self, timeout: Optional[float] = None) -> bool:
        """
        Waits until a notification is received or an optional timeout occurs.
        The calling thread must hold the `SmartCondition`'s internal lock (`self._lock`)
        when calling this method. This method will temporarily release the lock,
        block the current thread, and then re-acquire the lock before returning.

        Args:
            timeout (Optional[float]): The maximum time (in seconds) to wait.
                                       If None, wait indefinitely.

        Returns:
            bool: True if a notification was received (i.e., the wait completed
                  before timeout), False if the timeout expired.

        Raises:
            RuntimeError: If the internal lock is not held by the calling thread
                          when `wait()` is invoked.
        """
        factory_id = self._ensure_factory_id()  # Ensure thread has an ID for tracking

        if not self._is_owned():
            raise RuntimeError("cannot wait on un-acquired lock")

        current_thread = threading.current_thread()
        waiter_lock = threading.Lock()  # Create a private lock for this specific waiter
        waiter_lock.acquire()  # Acquire the private lock immediately; it will be released by notify()

        # Register this thread as a waiter. This happens while `self._lock` is held.
        waiter = Waiter(factory_id=factory_id, lock=waiter_lock, thread=current_thread)
        self._waiters.enqueue(waiter)

        # Release the SmartCondition's main lock (`self._lock`) and save its state
        # (important for `threading.RLock` to track recursive acquisitions).
        saved_state = self._release_save()
        got_it = False  # Flag to indicate if the wait was successful (not a timeout/exception)

        try:
            # Block the current thread by trying to acquire its private `waiter_lock`.
            # This will only succeed if `notify()` or `notify_all()` release this specific lock.
            if timeout is None:
                waiter_lock.acquire()  # Blocks indefinitely until released
                got_it = True
            else:
                got_it = waiter_lock.acquire(timeout=timeout)  # Blocks for up to 'timeout' seconds
            return got_it
        finally:
            # Re-acquire the SmartCondition's main lock (`self._lock`) before returning.
            # This restores the lock state to what it was before `wait()` was called.
            self._acquire_restore(saved_state)
            if not got_it:
                # If the wait timed out or an exception occurred, the thread needs
                # to remove itself from the `_waiters` queue, as it was not woken by a notification.
                self._waiters.remove_item(waiter)

    def notify(self, n: int = 1, factory_ids: Optional[Union[str, Iterable[str]]] = None) -> None:
        """
        Wakes up `n` waiting threads. If `factory_ids` are provided, only threads
        whose `factory_id` matches one of the specified IDs will be woken.
        The calling thread must hold the `SmartCondition`'s internal lock (`self._lock`).

        Args:
            n (int): The maximum number of threads to wake up. Must be 1 or greater.
            factory_ids (Union[str, Iterable[str]], optional): A single `factory_id` string
                                                               or an iterable of `factory_id` strings.
                                                               Only threads with matching IDs will be
                                                               considered for notification. If None,
                                                               the first `n` threads in the waiting
                                                               queue are notified.

        Raises:
            RuntimeError: If the internal lock is not held by the calling thread.
            ValueError: If `n` is less than 1.
        """
        if not self._is_owned():
            raise RuntimeError("cannot notify on un-acquired lock")
        if n <= 0:
            return

        to_notify = []  # List to store Waiter objects that will be notified
        # Convert single string factory_id to a set for efficient lookup, or keep as None
        target_ids = {factory_ids} if isinstance(factory_ids, str) else set(factory_ids) if factory_ids else None

        # Iterate over a copy of the waiters queue to avoid modification issues during iteration.
        # `_waiters.remove_item(w)` modifies the queue.
        for w in list(self._waiters):
            if n <= 0:  # Stop if 'n' threads have been selected
                break
            # Check if the waiter matches the target_ids (if any specified)
            if target_ids is None or w.factory_id in target_ids:
                # Attempt to remove the waiter from the queue. If successful, add to `to_notify`.
                if self._waiters.remove_item(w):
                    to_notify.append(w)
                    n -= 1  # Decrement count of threads to notify

        # Now, release the private lock of each selected waiter, waking them up.
        for w in to_notify:
            try:
                w.lock.release()  # This unblocks the `waiter_lock.acquire()` call in `wait()`
            except RuntimeError:
                # This can happen if the lock was already released (e.g., due to a race
                # condition where the waiter timed out right before notification,
                # or was notified by another source, and removed itself).
                pass

    def notify_all(self, factory_ids: Optional[Union[str, Iterable[str]]] = None) -> None:
        """
        Wakes up all threads currently waiting on the SmartCondition.
        Optionally, only threads whose `factory_id` matches one of the specified IDs will be woken.
        The calling thread must hold the `SmartCondition`'s internal lock (`self._lock`).

        Args:
            factory_ids (Union[str, Iterable[str]], optional): A single `factory_id` string
                                                               or an iterable of `factory_id` strings.
                                                               Only threads with matching IDs will be woken.
                                                               If None, all waiting threads are notified.

        Raises:
            RuntimeError: If the internal lock is not held by the calling thread.
        """
        if not self._is_owned():
            raise RuntimeError("cannot notify_all on un-acquired lock")
        # Reuse the `notify` method by setting `n` to the current number of waiting threads.
        self.notify(n=len(self._waiters), factory_ids=factory_ids)

    def wait_for(self, predicate: Callable[[], bool], timeout: Optional[float] = None) -> bool:
        """
        Waits until a given `predicate` function evaluates to True, or until an
        optional `timeout` occurs. The `predicate` is checked repeatedly.
        The calling thread must hold the `SmartCondition`'s internal lock when calling
        this method; the lock will be temporarily released and re-acquired during waits.

        Args:
            predicate (Callable[[], bool]): A callable (function or method) that takes no
                                           arguments and returns a boolean value. `wait_for`
                                           will continue waiting as long as `predicate()` is False.
                                           This predicate is evaluated while `self._lock` is held.
            timeout (Optional[float]): The maximum time (in seconds) to wait for the predicate
                                       to become true. If None, wait indefinitely.

        Returns:
            bool: True if the `predicate` became True before the `timeout` expired,
                  False otherwise (i.e., timeout occurred and `predicate` was still False).
        """
        # Ensure the condition's internal lock is held throughout the `wait_for` method.
        # This is the standard pattern for condition variables: the caller holds the lock,
        # which `self.wait()` then releases and re-acquires.
        with self._lock:
            endtime = time.time() + timeout if timeout is not None else None
            while True:
                # First, evaluate the predicate. If true, we can immediately return.
                if predicate():
                    return True  # Predicate satisfied

                # If the predicate is false, calculate the remaining time for the timeout.
                if endtime is not None:
                    remaining = endtime - time.time()
                    if remaining <= 0:
                        # If timeout has already expired, check predicate one last time
                        # and return its current state.
                        return predicate()

                # If the predicate is false and there's still time, wait for a notification.
                # `self.wait()` will temporarily release `self._lock` and re-acquire it
                # when woken or after timeout.
                self.wait(timeout=remaining if endtime else None)

    def get_all_waiting_factory_ids(self) -> list[str]:
        """
        Returns a snapshot (a new list) of all `factory_id` strings for threads
        that are currently registered as waiting on this SmartCondition.

        Returns:
            list[str]: A list of string `factory_id`s (e.g., ULIDs or "MainThread").
                       Returns an empty list if no threads are waiting.
        """
        # Accessing _waiters directly returns a copy of the list of items
        # in the ConcurrentQueue, ensuring thread safety for this snapshot.
        return [w.factory_id for w in self._waiters]

    def get_all_waiters(self) -> list[Waiter]:
        """
        Returns a full snapshot (a new list) of all `Waiter` objects
        currently blocking on this SmartCondition.

        Returns:
            list[Waiter]: A list of `Waiter` dataclass instances, each containing
                          the `factory_id`, private lock, and thread object.
                          Returns an empty list if no threads are waiting.
        """
        # Returns a copy of the list of Waiter objects from the ConcurrentQueue.
        return list(self._waiters)

    def _release_save(self) -> Any:
        """
        Internal helper method to release the condition's lock and save its state.
        This is primarily used by `wait()` when it temporarily releases the lock.
        For `threading.RLock`, it tracks the number of recursive acquisitions.

        Returns:
            Any: The saved state of the lock (e.g., a recursion count for RLock).
        """
        if hasattr(self._lock, '_release_save'):  # For custom locks that implement this
            return self._lock._release_save()
        else:
            # Fallback for standard threading.Lock or RLock not implementing _release_save directly.
            # Manually release the RLock until it's fully unacquired.
            if isinstance(self._lock, threading.RLock):
                release_count = 0
                while self._lock._is_owned():  # Check if current thread owns the lock
                    self._lock.release()
                    release_count += 1
                return release_count
            else:  # For basic threading.Lock, just release once
                self._lock.release()
                return None

    def _acquire_restore(self, saved_state: Any) -> None:
        """
        Internal helper method to re-acquire the condition's lock, restoring its state.
        This is primarily used by `wait()` after it is woken up or times out.
        For `threading.RLock`, it re-acquires the lock the same number of times it was released.

        Args:
            saved_state (Any): The state returned by `_release_save()`.
        """
        if hasattr(self._lock, '_acquire_restore'):  # For custom locks that implement this
            self._lock._acquire_restore(saved_state)
        else:
            # Fallback for standard threading.Lock or RLock not implementing _acquire_restore directly.
            if isinstance(self._lock, threading.RLock) and isinstance(saved_state, int):
                for _ in range(saved_state):
                    self._lock.acquire()  # Reacquire RLock for each previous acquisition
            else:  # For basic threading.Lock, just acquire once
                self._lock.acquire()

    def _is_owned(self) -> bool:
        """
        Internal helper method to determine if the current thread holds the condition's lock.

        Returns:
            bool: True if the current thread owns the lock, False otherwise.
        """
        if hasattr(self._lock, '_is_owned'):  # For RLock, this is built-in
            return self._lock._is_owned()
        # Fallback for generic locks: attempt a non-blocking acquire.
        # If it succeeds, the lock was not held by this thread.
        if self._lock.acquire(blocking=False):
            self._lock.release()  # Release it immediately if we just acquired it
            return False
        return True  # If non-blocking acquire failed, it means this thread already held it.
