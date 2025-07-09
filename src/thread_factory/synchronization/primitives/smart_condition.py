import threading
import time
import ulid
from typing import Optional, Union, Iterable, Any, Callable, List
from dataclasses import dataclass
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.concurrency.concurrent_queue import ConcurrentQueue
from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.utilities.interfaces.disposable import IDisposable
from thread_factory.utilities.coordination.package import Pack

@dataclass
class Waiter:
    """
    Represents a single thread currently waiting on the SmartCondition.

    Attributes:
        factory_id (str): A unique string identifier (ULID or "MainThread")
                          associated with the waiting thread. This ID is used
                          for targeted notifications.
        lock (threading.Lock): A private, dedicated `threading.Lock` object
                               for this specific waiter thread. The thread blocks
                               on acquiring this lock until it is released by
                               a `notify()` or `notify_all()` call.
        thread (threading.Thread): A direct reference to the `threading.Thread`
                                   object that is waiting.
        callback (Optional[Union[Callable[..., None], Pack]]): An optional callable to be
                                                executed by the awaited thread
                                                itself, if `awaited_caller` is True.
    """
    factory_id: str
    lock: threading.Lock
    thread: threading.Thread
    callback: Optional[Union[Callable[..., None], Pack]] = None


class SmartCondition(IDisposable):
    """
    SmartCondition
    ---------------
    A custom, thread-aware condition variable designed specifically for use in high-performance
    concurrent systems like `DynamicWorker` and `DynamicPool` within ThreadFactory.

    Unlike standard `threading.Condition`, this implementation supports:

    - **Thread-aware semantics**: Each thread is tracked using a unique `factory_id` (usually a ULID),
      enabling granular coordination of threads in distributed or agentic thread systems.

    - **Targeted notifications**: Allows precise wake-up calls to specific threads, critical for
      orchestrating behavior across many worker threads in a pool.

    - **Awaited callback delivery**: Callbacks can be passed into the waiter thread to be executed
      once it wakes up, enabling thread-local response behavior (a key feature for DynamicWorker checkpoints).

    - **Snapshot inspection**: Runtime visibility into which threads are waiting, including
      full `Waiter` object snapshots and their `factory_id`s.

    These systems require **precise control** over which threads are signaled, especially in environments
    with hundreds of long-lived workers behaving like agents. `SmartCondition` makes that possible
    with minimal overhead and clean callback integration.
    """

    __slots__ = IDisposable.__slots__ + [
    "_lock", "acquire", "release", "_waiters", "_callback_registry", "_default_callback", "_id",
    ]
    def __init__(self, lock: Optional[threading.Lock] = None, default_callback: Optional[Union[Callable[..., None], Pack]] = None):
        """
        Initializes the SmartCondition.

        Args:
            lock (Optional[threading.Lock]): An optional external lock object
                                             to be used for synchronization.
                                             If None, a new reentrant lock (`threading.RLock`)
                                             is created and used internally.
                                             The condition variable operates on this lock,
                                             meaning `wait()`, `notify()`, `notify_all()`,
                                             and `notify_and_call()` methods require this lock
                                             to be acquired by the calling thread.
        """
        super().__init__()
        self._id = str(ulid.ULID())
        self._lock: threading.RLock = lock or threading.RLock()
        self.acquire: Callable = self._lock.acquire  # Expose acquire method of the internal lock
        self.release: Callable = self._lock.release  # Expose release method of the internal lock
        self._waiters: ConcurrentQueue[Waiter] = ConcurrentQueue[
            Waiter]()  # A thread-safe queue of `Waiter` objects, representing all blocked threads.

        # Registry for callbacks specific to a factory_id, executed upon notification.
        self._callback_registry: ConcurrentDict[str, Union[Callable[..., None], Pack]] = ConcurrentDict()
        # A default callback to be executed if no specific callback is bound for a notified thread.
        self._default_callback: Optional['Package'] = (
            Pack.bundle(default_callback) if default_callback is not None else None
        )

    def dispose(self) -> None:
        """
        Disposes the SmartCondition, releasing all waiters and clearing internal registries.

        This method:
        - Marks the condition as disposed.
        - Wakes all waiting threads without executing callbacks.
        - Clears the waiters queue.
        - Clears callback registries.
        - Releases the internal lock (if possible).

        This is safe to call multiple times.
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

        # Clear all registries
        self._waiters.dispose()
        self._waiters = None
        self._callback_registry.clear()
        self._callback_registry.dispose()
        self._callback_registry = None
        self._default_callback = None

    def __enter__(self):
        """
        Enters the runtime context for the SmartCondition, acquiring its internal lock.
        This allows the use of the `with` statement for convenient lock management.
        """
        self._lock.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any):
        """
        Exits the runtime context for the SmartCondition, releasing its internal lock.
        Automatically called by Python when exiting a `with` statement.
        """
        return self._lock.__exit__(exc_type, exc_val, exc_tb)

    def find_waiter_count(self):
        """
        Returns the number of threads currently waiting on this SmartCondition.
        This is equivalent to the length of the `_waiters` queue.

        Returns:
            int: The number of threads currently waiting.
        """
        return len(self._waiters)

    def _ensure_factory_id(self) -> str:
        """
        Ensures that the current `threading.Thread` object has a `factory_id` attribute.
        This method is called internally by `wait()` and ensures that every thread
        interacting with `SmartCondition` has a consistent and unique identifier.

        If `thread.factory_id` already exists and is not None, its value is returned.
        Otherwise, a new `factory_id` is assigned: "MainThread" for the main thread,
        or a newly generated ULID string for any other thread.

        Returns:
            str: The unique `factory_id` associated with the current thread.
        """
        thread = threading.current_thread()
        # Check if the thread already has a factory_id and it's not None.
        if hasattr(thread, "factory_id") and thread.factory_id is not None:
            return thread.factory_id

        # If the attribute is missing or None, assign it based on the thread type.
        if thread.name == "MainThread":
            thread.factory_id = "MainThread"
        else:
            # For non-main threads without a pre-existing factory_id, assign a new ULID.
            thread.factory_id = str(ulid.ULID())

        return thread.factory_id  # Returns the now-guaranteed-to-be-set factory_id

    def bind_callback(self, factory_id: str, fn: Union[Callable[..., None], Pack]) -> None:
        """
        Binds a specific callable function (`fn`) to a given `factory_id`.
        When a thread with this `factory_id` is notified via `notify_and_call()`,
        this bound callback will be executed.

        Args:
            factory_id (str): The unique identifier of the waiting thread to bind the callback to.
            fn (Callable[[], None]): The function to execute when the specified thread is notified.
                                    It should take no arguments and return None.
        """
        if fn is None:
            raise TypeError("Callback must have a callable function")
        self._callback_registry[factory_id] = Pack.bundle(fn)


    def set_default_callback(self, fn: Union[Callable[..., None], Pack]) -> None:
        """
        Sets a fallback callback function that will be executed for any notified thread
        that does not have a specific callback bound via `bind_callback()`.

        Args:
            fn (Callable[[], None]): The function to be used as the default callback.
                                    It should take no arguments and return None.
        """
        if fn is None:
            raise TypeError("Default callback must have a callable function")
        self._default_callback = Pack.bundle(fn)

    def notify_and_call(self, n: int = 1, factory_ids: Optional[Union[str, Iterable[str]]] = None,
                        callback: Optional[Union[Callable[..., None], Pack]] = None,
                        awaited_caller: bool = False) -> None:
        """
        Notifies `n` waiting threads (optionally targeted by `factory_ids`) and
        executes a corresponding callback for each notified thread.

        Callback Selection Priority (if `awaited_caller` is False):
        1.  A one-time `callback` function provided as an argument to this method.
        2.  A callback specifically bound to the thread's `factory_id` using `bind_callback()`.
        3.  The `default_callback` set via `set_default_callback()`.

        If `awaited_caller` is True, the chosen callback is stored in the Waiter
        object, and the awaited thread will execute it upon waking.

        The calling thread must hold the `SmartCondition`'s internal lock (`self._lock`).

        Args:
            n (int): The maximum number of threads to notify and call. Must be 1 or greater.
            factory_ids (Optional[Union[str, Iterable[str]]]): A single `factory_id` string
                                                               or an iterable of `factory_id` strings.
                                                               Only threads with matching IDs will be
                                                               considered for notification. If None,
                                                               the first `n` threads in the waiting
                                                               queue are notified.
            callback (Optional[Callable[[], None]]): An optional, one-time callable function.
                                                    If provided, it takes the highest priority
                                                    for this specific notification.
            awaited_caller (bool): If True, the chosen callback will be executed by the
                                   awaited thread (the thread that was waiting) after it wakes up.
                                   If False (default), the notifying thread executes the callback.

        Raises:
            RuntimeError: If the internal lock is not held by the calling thread.
            ValueError: If `n` is less than 1.
        """
        if not self._is_owned():
            raise RuntimeError("cannot notify_and_call on un-acquired lock")

        if n <= 0:
            return

        # Prepare target IDs for efficient lookup, or keep as None if all threads are candidates.
        target_ids = {factory_ids} if isinstance(factory_ids, str) else set(factory_ids) if factory_ids else None
        to_notify = []  # Temporarily store `Waiter` objects that are selected for notification.

        # Iterate over a copy of the _waiters queue to allow safe modification during iteration.
        # This is crucial because `remove_item` modifies the queue while we're iterating.
        for w in list(self._waiters):
            if n <= 0:  # Stop once enough threads have been selected.
                break
            # Check if the waiter matches the specified `target_ids` (if any).
            if target_ids is None or w.factory_id in target_ids:
                # Attempt to remove the waiter from the queue. If successful (meaning it was still waiting),
                # add it to the list of threads to notify.
                if self._waiters.remove_item(w):
                    to_notify.append(w)
                    n -= 1  # Decrement the count of threads remaining to notify.

        # For each selected waiter, prepare and/or execute the appropriate callback.
        for w in to_notify:
            # Determine which callback to use based on the priority:
            # 1. Callback passed as an argument to this method (highest priority).
            # 2. Specific bound callback for this factory_id.
            # 3. Default callback set for the SmartCondition instance.
            chosen_callback = callback or self._callback_registry.get(w.factory_id) or self._default_callback
            if chosen_callback:
                # If the chosen callback is a callable, ensure it is packed correctly.
                chosen_callback = Pack.bundle(chosen_callback)

            if awaited_caller:
                # If awaited_caller is True, store the callback in the Waiter object
                # for the awaited thread to execute.
                w.callback = chosen_callback
            else:
                # If awaited_caller is False (default behavior), execute the callback now
                # by the notifying thread.
                if chosen_callback:
                    try:
                        chosen_callback()  # Execute the chosen callback.
                    except Exception as e:
                        # Log any exceptions that occur within the callback to prevent
                        # them from stopping the notification process.
                        print(f"[SmartCondition] Error in callback for {w.factory_id}: {e}")

            try:
                w.lock.release()  # Unblock the `waiter_lock.acquire()` call in `wait()`.
            except RuntimeError:
                # This can occur if the `waiter_lock` was already released, e.g., if the thread
                # timed out just before being notified, or was woken by another source.
                pass

    def wait(self, timeout: Optional[float] = None) -> bool:
        """
        Waits until a notification is received (via `notify()`, `notify_all()`, or `notify_and_call()`)
        or an optional `timeout` occurs.

        The calling thread **must hold the `SmartCondition`'s internal lock (`self._lock`)**
        when calling this method. Internally, `wait()` will temporarily release `self._lock`,
        block the current thread, and then re-acquire `self._lock` before returning.

        If `notify_and_call` was called with `awaited_caller=True`, this method will
        also execute any callback stored within its `Waiter` object after waking up.

        Args:
            timeout (Optional[float]): The maximum time (in seconds) to wait.
                                       If `None`, the thread waits indefinitely.

        Returns:
            bool: `True` if a notification was received (i.e., the wait completed
                  before the `timeout` expired), `False` if the `timeout` expired.

        Raises:
            RuntimeError: If the internal lock (`self._lock`) is not held by the
                          calling thread when `wait()` is invoked.
        """
        if self._disposed:
            raise RuntimeError("SmartCondition has been disposed and cannot be used")
        # Ensure the current thread has a factory_id for tracking and potential targeted notifications.
        factory_id = self._ensure_factory_id()

        # Precondition check: The calling thread must own the condition's lock.
        if not self._is_owned():
            raise RuntimeError("cannot wait on un-acquired lock")

        current_thread = threading.current_thread()
        waiter_lock = threading.Lock()  # Create a private, dedicated lock for this specific waiter.
        waiter_lock.acquire()  # Acquire the private lock immediately; it will block until released by a notifier.

        # Register this thread as a waiter. This addition to `_waiters` happens
        # while `self._lock` is held, ensuring thread safety of the waiters list.
        # Initialize callback to None; it will be set by notify_and_call if awaited_caller is True.
        waiter = Waiter(factory_id=factory_id, lock=waiter_lock, thread=current_thread, callback=None)
        self._waiters.enqueue(waiter)

        # Release the SmartCondition's main lock (`self._lock`) and save its state.
        # This is critical for `threading.RLock` to correctly track recursive acquisitions.
        saved_state = self._release_save()
        was_notified = False  # Flag to track if the wait was successful (notification) or a timeout/exception.

        try:
            # Block the current thread by attempting to acquire its private `waiter_lock`.
            # This call will only succeed when `notify()`, `notify_all()`, or `notify_and_call()`
            # explicitly release this specific `waiter_lock`.
            if timeout is None:
                waiter_lock.acquire()  # Blocks indefinitely until released.
                was_notified = True
            else:
                was_notified = waiter_lock.acquire(timeout=timeout)  # Blocks for up to 'timeout' seconds.

            return was_notified
        finally:
            # Regardless of whether the wait was successful or timed out,
            # the SmartCondition's main lock (`self._lock`) must be re-acquired.
            # This restores the lock state to what it was before `wait()` was called.
            self._acquire_restore(saved_state)

            # --- AWAITED CALLER LOGIC ---
            # If the thread was notified (not timed out), and a callback was
            # stored in its Waiter object, execute it now.
            if was_notified and waiter.callback:
                try:
                    waiter.callback()
                except Exception as e:
                    print(f"[SmartCondition] Error in awaited callback for {waiter.factory_id}: {e}")
                finally:
                    # Clear the callback to prevent accidental re-execution
                    waiter.callback = None
            # --- END AWAITED CALLER LOGIC ---

            if not was_notified:
                # If the wait timed out or an unexpected exception occurred (and thus no notification),
                # the thread is responsible for removing itself from the `_waiters` queue,
                # as it was not removed by a `notify` operation.
                self._waiters.remove_item(waiter)


    def notify(self, n: int = 1, factory_ids: Optional[Union[str, Iterable[str]]] = None,
               awaited_caller: bool = False) -> None:
        """
        Wakes up `n` waiting threads without executing any callbacks directly,
        unless `awaited_caller` is True, in which case a default or bound callback
        will be passed to the awaited thread to execute.

        The calling thread must hold the `SmartCondition`'s internal lock (`self._lock`).

        Args:
            n (int): The maximum number of threads to wake up. Must be 1 or greater.
            factory_ids (Union[str, Iterable[str]], optional): A single `factory_id` string
                                                               or an iterable of `factory_id` strings.
                                                               Only threads with matching IDs will be
                                                               considered for notification. If `None`,
                                                               the first `n` threads in the waiting
                                                               queue (regardless of `factory_id`) are notified.
            awaited_caller (bool): If True, and if a default or bound callback exists, it will be
                                   stored in the Waiter object for the awaited thread to execute.
                                   If False (default), no callback is executed or passed.

        Raises:
            RuntimeError: If the internal lock is not held by the calling thread.
            ValueError: If `n` is less than 1.
        """
        if not self._is_owned():
            raise RuntimeError("cannot notify on un-acquired lock")
        if n <= 0:
            return

        to_notify = []  # List to store Waiter objects that will be selected for notification.
        # Convert single string factory_id to a set for efficient lookup, or keep as None.
        target_ids = {factory_ids} if isinstance(factory_ids, str) else set(factory_ids) if factory_ids else None

        # Iterate over a copy of the `_waiters` queue to allow safe removal during iteration.
        for w in list(self._waiters):
            if n <= 0:  # Stop if the target number of notifications has been met.
                break
            # Check if the current waiter matches the target IDs (if any are specified).
            if target_ids is None or w.factory_id in target_ids:
                # Attempt to remove the waiter from the queue. If successful (meaning it was still waiting),
                # add it to the list for notification.
                if self._waiters.remove_item(w):
                    to_notify.append(w)
                    n -= 1  # Decrement the count of threads remaining to notify.

        # Release the private lock of each selected waiter, which unblocks them.
        for w in to_notify:
            if awaited_caller:
                # If awaited_caller is True, and there's a bound or default callback,
                # store it in the Waiter object for the awaited thread to execute.
                cb_to_pass = self._callback_registry.get(w.factory_id) or self._default_callback
                if cb_to_pass:
                    w.callback = Pack.bundle(cb_to_pass)
            # In 'notify', if awaited_caller is False, no callback is executed here.

            try:
                w.lock.release()  # This unblocks the `waiter_lock.acquire()` call in `wait()`.
            except RuntimeError:
                # This exception can occur if the `waiter_lock` was already released,
                # e.g., if the waiting thread timed out or was notified by another source
                # just before this call and removed itself from the queue.
                pass

    def notify_all(self, factory_ids: Optional[Union[str, Iterable[str]]] = None,
                   awaited_caller: bool = False) -> None:
        """
        Wakes up all threads currently waiting on the SmartCondition.

        If `awaited_caller=True`, the thread that was waiting will execute its callback.
        If `awaited_caller=False`, the notifying thread will execute the callback.
        """
        if not self._is_owned():
            raise RuntimeError("Cannot notify_all on un-acquired lock")

        to_notify = []  # List to store Waiter objects that will be selected for notification.
        target_ids = {factory_ids} if isinstance(factory_ids, str) else set(factory_ids) if factory_ids else None

        for w in list(self._waiters):
            if target_ids is None or w.factory_id in target_ids:
                if self._waiters.remove_item(w):
                    to_notify.append(w)

        for w in to_notify:
            if awaited_caller:
                # If awaited_caller is True, store the callback in the Waiter object
                # for the awaited thread to execute.
                cb_to_pass = self._callback_registry.get(w.factory_id) or self._default_callback
                if cb_to_pass:
                    w.callback = Pack.bundle(cb_to_pass)
            else:
                # If awaited_caller is False, call the callback directly from the notifying thread
                cb_to_pass = self._callback_registry.get(w.factory_id) or self._default_callback
                if cb_to_pass:
                    # **Execute the callback directly here in the notifying thread**
                    cb_to_pass()  # This will execute the callback in the notifying thread

            try:
                w.lock.release()  # This unblocks the `waiter_lock.acquire()` call in `wait()`.
            except RuntimeError:
                # This exception can occur if the `waiter_lock` was already released.
                pass


    def notify_all_and_call(
        self,
        factory_ids: Optional[Union[str, Iterable[str]]] = None,
        awaited_caller: bool = False,
        callback: Optional[Union[Callable[..., None], Pack]] = None,
    ) -> None:
        """
        Wake *every* eligible waiter and optionally run a callback.

        Callback-selection precedence for each waiter is identical to
        `notify_and_call`:

            1. `callback` given to this method
            2. per-waiter bound callback        (bind_callback)
            3. default callback                 (set_default_callback)

        Args
        ----
        factory_ids : str | Iterable[str] | None
            • None   → notify everyone.
            • str    → notify only that id.
            • Iterable → notify each id in the set.
        awaited_caller : bool
            • False (default) → *this thread* runs the chosen callback(s).
            • True            → awakened thread runs its callback.
        callback : Callable | None
            One-off function that overrides all other callbacks.
        """
        if not self._is_owned():
            raise RuntimeError("cannot notify_all_and_call on un-acquired lock")

        # Normalise target-id filter
        target_ids = (
            {factory_ids}
            if isinstance(factory_ids, str)
            else set(factory_ids)
            if factory_ids is not None
            else None
        )

        to_notify: list[Waiter] = []

        # Work on a *copy* to avoid mutating during iteration
        for w in list(self._waiters):
            if target_ids is None or w.factory_id in target_ids:
                if self._waiters.remove_item(w):
                    to_notify.append(w)

        if not to_notify:                     # nothing to do
            return

        for w in to_notify:
            chosen_cb = (
                callback
                or self._callback_registry.get(w.factory_id)
                or self._default_callback
            )
            if chosen_cb:
                chosen_cb = Pack.bundle(chosen_cb)
            if awaited_caller:
                if chosen_cb:
                    w.callback = chosen_cb    # executed by waiter after wake
            else:
                if chosen_cb:
                    try:
                        chosen_cb()             # executed right here
                    except Exception as exc:
                        print(
                            f"[SmartCondition] Error in callback for {w.factory_id}: {exc}"
                        )

            try:
                w.lock.release()                # finally, wake the waiter
            except RuntimeError:
                # If it already timed-out / was woken elsewhere, ignore
                pass


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
            if predicate:
                predicate = Pack.bundle(predicate)  # Ensure the predicate is a Pack if it isn't already.
            endtime = time.time() + timeout if timeout is not None else None
            while True:
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

    def get_all_waiting_factory_ids(self) -> list[str]:
        """
        Returns a snapshot (a new list) of all `factory_id` strings for threads
        that are currently registered as waiting on this SmartCondition.

        Returns:
            list[str]: A list of string `factory_id`s (e.g., ULIDs or "MainThread").
                       Returns an empty list if no threads are waiting.
        """
        # Accessing `_waiters` iterates over a copy of the list of items
        # in the `ConcurrentQueue`, ensuring thread safety for this snapshot.
        return list([w.factory_id for w in self._waiters])

    def get_all_waiters(self) -> List[Waiter]:
        """
        Returns a full snapshot (a new list) of all `Waiter` objects
        currently blocking on this SmartCondition. Each `Waiter` object
        contains details about the waiting thread, including its `factory_id`,
        private lock, and thread object.

        Returns:
            list[Waiter]: A list of `Waiter` dataclass instances.
                          Returns an empty list if no threads are waiting.
        """
        # Returns a copy of the list of `Waiter` objects from the `ConcurrentQueue`.
        return list(self._waiters)

    def _release_save(self) -> Any:
        """
        Internal helper method used by `wait()` to release the condition's lock
        (`self._lock`) and save its state (especially for `threading.RLock`).
        This allows `wait()` to temporarily release the lock while blocking.

        Returns:
            Any: The saved state of the lock. For `threading.RLock`, this is the
                 recursion count (number of times the lock was acquired). For
                 `threading.Lock`, it's typically `None`.
        """
        if hasattr(self._lock, '_release_save'):  # Check for custom lock implementation
            return self._lock._release_save()
        else:
            # Fallback for standard `threading.Lock` or `threading.RLock`
            # if they don't directly expose `_release_save`.
            if isinstance(self._lock, threading.RLock):
                release_count = 0
                # Keep releasing until the lock is no longer owned by the current thread.
                while self._lock._is_owned():
                    self._lock.release()
                    release_count += 1
                return release_count
            else:  # For a basic `threading.Lock`, just release once.
                self._lock.release()
                return None

    def _acquire_restore(self, saved_state: Any) -> None:
        """
        Internal helper method used by `wait()` to re-acquire the condition's lock
        (`self._lock`), restoring its state to what it was before `_release_save()`
        was called.

        Args:
            saved_state (Any): The state returned previously by `_release_save()`.
                                For `threading.RLock`, this is the recursion count,
                                indicating how many times the lock needs to be re-acquired.
        """
        if hasattr(self._lock, '_acquire_restore'):  # Check for custom lock implementation
            self._lock._acquire_restore(saved_state)
        else:
            # Fallback for standard `threading.Lock` or `threading.RLock`
            # if they don't directly expose `_acquire_restore`.
            if isinstance(self._lock, threading.RLock) and isinstance(saved_state, int):
                # Reacquire RLock the same number of times it was released.
                for _ in range(saved_state):
                    self._lock.acquire()
            else:  # For a basic `threading.Lock`, just acquire once.
                self._lock.acquire()

    def _is_owned(self) -> bool:
        """
        Internal helper method to determine if the current thread holds (owns) the
        condition's internal lock (`self._lock`).

        Returns:
            bool: `True` if the current thread owns the lock, `False` otherwise.
        """
        if hasattr(self._lock, '_is_owned'):  # For `threading.RLock`, this is a built-in method.
            return self._lock._is_owned()
        # Fallback for generic `threading.Lock` (which doesn't have `_is_owned`).
        # Attempt a non-blocking acquire. If it succeeds, the lock was not held by this thread.
        if self._lock.acquire(blocking=False):
            self._lock.release()  # Release it immediately as we just acquired it.
            return False
        return True  # If non-blocking acquire failed, it means this thread already held the lock.
