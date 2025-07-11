import threading, time, ulid
from typing import Optional, Union, Iterable, Any, Callable
from thread_factory.concurrency.concurrent_set import ConcurrentSet
from thread_factory.utilities.interfaces.disposable import IDisposable
from thread_factory.synchronization.primitives.smart_condition import SmartCondition
from thread_factory.utilities.coordination.package import Pack

#FlowRegulator class

class FlowRegulator(IDisposable):
    """
    FlowRegulator
    ----------
    A dynamic, "smart" semaphore implementation that provides granular control
    over permits and thread notifications. It extends standard semaphore
    functionality by allowing runtime adjustment of available permits,
    targeted thread awakening using unique identifiers (ULIDs), and
    robust disposal mechanisms.

    This lock is designed for scenarios requiring flexible synchronization,
    such as managing access to limited resources where the resource count
    can change, or coordinating groups of threads with specific needs.

    It leverages a `SmartCondition` internally for advanced thread signaling,
    enabling targeted wakeups, dynamic bias buffering, and event-driven callbacks.

    Thread Behavior
    ---------------
    Threads do **not** need to declare themselves explicitly to use FlowRegulator.

    • All threads are automatically assigned a `factory_id` (ULID) by the internal SmartCondition.
    • This allows for targeted notifications, callback binding, and fine-grained control.
    • Compatible with raw `threading.Thread`, `DynamicWorker`, `GeneralWorker`, or any subclass.

    If a thread manually sets `thread.factory_id`, that ID will be respected.
    Otherwise, the ID is auto-generated the first time it interacts with the lock.

    Use Cases
    ---------
    - Adaptive thread pools with dynamic worker management.
    - Burstable queues with gated concurrency.
    - Work stealing patterns with targeted wakeups.
    - Systems requiring dynamic throttling or bias control.

    Performance Benchmark (μs per operation)
    ----------------------------------------
    Based on 1000 iterations of `acquire()` with one permit available:

        threading.Lock        │  0.07 μs
        FlowRegulator (this)     │  4.40 μs
        Thread Spawn (bare)   │ 195.8 μs

    ⚠ Note:
        While ~63× slower than a raw lock, `FlowRegulator` provides intelligent
        scheduling, permit biasing, and cross-thread callback coordination—
        ideal for controlled concurrency and thread orchestration.

    """
    __slots__ = IDisposable.__slots__ + [
    "_cond", "_value", "_log_ids", "_bias_threshold", "_pending_permits",
        "_id"
    ]
    def __init__(self, value: int = 1, bias_threshold: Optional[int] = None):
        """
        Initializes a new FlowRegulator instance.

        Args:
            value (int): The initial number of available permits. Must be a non-negative integer.

        Raises:
            ValueError: If the initial `value` is less than 0.
        """
        super().__init__()  # Initialize the IDisposable base class
        if value < 0:
            raise ValueError("FlowRegulator initial value must be >= 0")

        self._id = str(ulid.ULID())
        self._cond: SmartCondition = SmartCondition()
        self._value: int = value  # Current count of available permits
        self._log_ids: ConcurrentSet[str] = ConcurrentSet() # Stores unique identifiers of threads that attempted to acquire the lock
        self._bias_threshold: Optional[int] = bias_threshold
        self._pending_permits: int = 0  # buffered until bias flush

    def dispose(self):
        """
        Disposes of the FlowRegulator, releasing all its resources and
        waking up any threads currently waiting to acquire a permit.
        After disposal, the lock should no longer be used. This method is idempotent.
        """
        if self.disposed:  # Check if the lock has already been disposed
            return
        # Acquire the internal condition lock before performing disposal operations
        with self._cond:
            self._disposed = True  # Mark the lock as disposed
            self._cond.notify_all() # Now this is called with the lock acquired
            self._cond.dispose()
            self._cond = None # Set to None after disposal
            self._log_ids.clear()
            self._log_ids.dispose()
            self._log_ids = None

    @property
    def condition(self) -> SmartCondition:
        """
        Provides direct access to the internal SmartCondition object.
        This property is primarily for advanced use cases or introspection,
        allowing direct interaction with the underlying condition variable.

        Returns:
            SmartCondition: The internal SmartCondition instance.
        """
        return self._cond

    def get_waiter_count(self):
        """
        Returns the number of threads currently waiting on this lock.
        This is useful for monitoring and debugging purposes.

        Returns:
            int: The count of waiting threads.
        """
        return self._cond.find_waiter_count()

    def _try_bias_flush(self) -> None:
        if self._bias_threshold is None:
            return

        waiters = len(self._cond.get_all_waiters())
        if waiters > self._bias_threshold and self._pending_permits > 0:
            self._value += self._pending_permits
            self._cond.notify(n=self._pending_permits)
            self._pending_permits = 0

    def _buffer_or_grant(self, n: int) -> None:
        if self._bias_threshold is None:  # bias OFF
            self._value += n
            return

        # bias ON  → just buffer, don’t flush yet
        self._pending_permits += n
        #  ⬅ NO call to _try_bias_flush() here

    def _flush_pending_permits(self, wake_all: bool = False, wake_n: int | None = None) -> None:
        """
        Move all buffered permits into `_value` and wake waiting threads.

        Args:
            wake_all:  If True, call `notify_all()`.
            wake_n:    If given, wake exactly this many via `notify(n=wake_n)`.
                       (Ignored if wake_all is True.)
        """
        if self._pending_permits == 0:
            return                                   # nothing to do

        self._value += self._pending_permits
        self._pending_permits = 0

        if wake_all:
            self._cond.notify_all()
        elif wake_n is not None:
            self._cond.notify(n=wake_n)

    def set_bias_threshold(self, threshold: Optional[int]) -> None:
        """
        Change the bias threshold at runtime.

        • threshold ∈ {None, 0}  → bias OFF → flush & wake *everyone*
        • Any other integer      → bias ON; if buffered permits exist and
          current waiters ≥ new threshold, flush exactly that many now.
        """
        self._bias_threshold = threshold

        with self._cond:
            # --- turn bias OFF → flush everything ---
            if threshold in (None, 0):
                self._flush_pending_permits(wake_all=True)
                return

            # --- bias lowered but still active ---
            waiter_cnt = len(self._cond.get_all_waiters())
            if self._pending_permits and waiter_cnt >= threshold:
                n_flush = self._pending_permits          # cache before reset
                self._flush_pending_permits(wake_n=n_flush)

    def has_factory_id(self) -> bool:
        """
        Checks if the current thread has a factory_id assigned.
        """
        thread = threading.current_thread()
        return hasattr(thread, "factory_id")

    def set_callback(self, factory_id: str, callback: Union[Callable[..., None], Pack]) -> None:
        """
        Registers a specific callback for a particular factory_id.

        Args:
            factory_id (str): The unique identifier of the waiting thread.
            callback (Callable[[], None]): The callback to be executed when this thread is notified.
        """
        if callback:
            callback = Pack(callback)  # Ensure callback is wrapped in Pack if provided
        self._cond.bind_callback(factory_id, callback)

    def set_default_callback(self, callback: Union[Callable[..., None], Pack]) -> None:
        """
        Registers a default callback to be executed if no specific callback
        is bound to a waiting thread.

        Args:
            callback (Callable[[], None]): The callback to be executed for any notified thread without a specific callback.
        """
        if callback:
            callback = Pack(callback)  # Ensure callback is wrapped in Pack if provided
        self._cond.set_default_callback(callback)

    def _attempt_bias_flush(self, n: int, factory_ids: Optional[Union[str, Iterable[str]]] = None, callback: Optional[Union[Callable[..., None], Pack]] = None,
                               awaited_caller: bool = False):
        """
        Flush buffered permits and wake *at most* `max_to_wake` threads
        without violating the bias reserve.
        Called from release/notify/increase_permits when bias is active.
        """
        if self._bias_threshold is None or self._pending_permits == 0:
            return  # classic mode / nothing buffered
        if callback:
            callback = Pack(callback)  # Ensure callback is wrapped in Pack if provided

        waiters = len(self._cond.get_all_waiters())
        excess = max(0, waiters - self._bias_threshold)  # threads allowed to wake
        to_flush = min(self._pending_permits, n, excess)

        if to_flush:
            self._value += to_flush
            self._pending_permits -= to_flush
            self._cond.notify_and_call(n=to_flush, factory_ids=factory_ids, callback=callback, awaited_caller=awaited_caller)

    def _attempt_bias_flush_all(self, factory_ids: Optional[Union[str, Iterable[str]]] = None,
                   awaited_caller: bool = False, callback: Optional[Union[Callable[..., None], Pack]] = None):
        """
        Flush buffered permits and wake *at most* `max_to_wake` threads
        without violating the bias reserve.
        Called from release/notify/increase_permits when bias is active.
        """
        if self._bias_threshold is None or self._pending_permits == 0:
            return  # classic mode / nothing buffered
        if callback:
            callback = Pack(callback)  # Ensure callback is wrapped in Pack if provided

        waiters = len(self._cond.get_all_waiters())
        excess = max(0, waiters - self._bias_threshold)  # threads allowed to wake
        to_flush = min(self._pending_permits, self.get_waiter_count(), excess)

        if to_flush:
            self._value += to_flush
            self._pending_permits -= to_flush
            self._cond.notify_and_call(n=to_flush, factory_ids=factory_ids, callback=callback, awaited_caller=awaited_caller)

    def bypass_bias_and_notify(self, n: int, factory_ids: Optional[Union[str, Iterable[str]]] = None, callback: Optional[Union[Callable[..., None], Pack]] = None,
                               awaited_caller: bool = False) -> None:
        """
        Bypass the bias and notify up to `n` threads.

        - Flushes up to `n` buffered permits into the value pool.
        - Notifies up to `n` threads, either in FIFO order or targeted by factory_id.
        - Completely ignores bias threshold.

        Args:
            n (int): Number of permits to flush and threads to notify.
            factory_ids (Optional[str or Iterable[str]]): Specific threads to notify, or None for FIFO.
        """
        if n < 1:
            raise ValueError("n must be >= 1")
        if self._disposed:
            return
        if callback:
            callback = Pack(callback)  # Ensure callback is wrapped in Pack if provided

        with self._cond:
            to_flush = min(self._pending_permits, n)
            if to_flush <= 0:
                return  # Nothing to do

            self._value += to_flush
            self._pending_permits -= to_flush

            self._cond.notify_and_call(
                n=n,
                factory_ids=factory_ids,
                callback=callback,
                awaited_caller=awaited_caller
            )

    def bypass_bias(self) -> None:
        """
        Force-flush any buffered permits and wake everyone.
        Use only when you intentionally want to break the bias gate.
        """
        with self._cond:
            if self._pending_permits:
                self._value += self._pending_permits
                self._pending_permits = 0
                self._cond.notify_all()

    def acquire(self, blocking: bool = True, timeout: Optional[float] = None) -> bool:
        """
        Acquire one permit (returns True) or time-out / dispose (returns False).

        Bias rules:
          – If bias_threshold is None → ordinary semaphore.
          – While bias is active, newly released permits are buffered; they are
            flushed *only* when (current_waiters + 1) > bias_threshold.

        The call honours return_home_on_block and per-thread worker-type checks.
        """
        if self._disposed:
            raise RuntimeError("FlowRegulator has been disposed and cannot be acquired.")

        if not blocking and timeout is not None:
            raise ValueError("Cannot give a timeout with blocking=False")

        this_id = self._cond._ensure_factory_id()
        if this_id not in self._log_ids:
            self._log_ids.add(this_id)

        endtime = None if timeout is None else time.time() + timeout

        with self._cond:
            if self._disposed:  # disposed *before* we started
                return False

            while True:
                ### 1 — did someone call dispose() while we were asleep?
                if self._disposed:  # ← RE-CHECK EACH ITERATION
                    return False

                ### 2 — fast-path: permit available
                if self._value > 0:
                    self._value -= 1
                    return True

                ### 3 — timeout expired?
                if endtime is not None and time.time() >= endtime:
                    return False

                ### 4 — bias flush check
                if (
                        self._bias_threshold is not None
                        and self._pending_permits
                        and len(self._cond.get_all_waiters()) + 1 > self._bias_threshold
                ):
                    # Move buffered permits into circulation and wake exactly that many waiters
                    self._value += self._pending_permits
                    self._pending_permits = 0
                    self._cond.notify(n=self._value)
                    continue  # loop back and try to grab one immediately

                ### 5 — really wait
                remaining = None if endtime is None else max(0, endtime - time.time())
                if not self._cond.wait(timeout=remaining):
                    return False  # woke by timeout, not by notify

    __enter__ = acquire  # Allows using the FlowRegulator as a context manager (e.g., `with lock:`)

    def release(self,
                n: int = 1,
                factory_ids: Optional[Union[str, Iterable[str]]] = None
    ) -> None:
        """
        Releases `n` permits, making them available for other threads to acquire.
        Optionally, specific waiting threads can be targeted by their `factory_id`s
        to be woken up.

        Args:
            n (int): The number of permits to release. Must be 1 or greater.
            factory_ids (Union[str, Iterable[str]], optional): A single factory ID (string)
                                                               or an iterable of factory IDs
                                                               to specifically notify. If None,
                                                               the `SmartCondition` will notify
                                                               general waiting threads (FIFO).

        Raises:
            ValueError: If `n` is less than 1.
            RuntimeError: If called when the internal condition's lock is not acquired (should not happen
                          if used correctly with `with self._cond:` context or within `acquire`).
        """
        if n < 1:
            raise ValueError("Number of permits to release (n) must be >= 1.")

        with self._cond:  # Acquire the internal condition's lock for synchronized state modification
            self._buffer_or_grant(n)
            if self._bias_threshold is None:  # bias OFF
                self._cond.notify(n=n, factory_ids=factory_ids)
            else:  # bias ON
                self._attempt_bias_flush(n, factory_ids)

    def notify(self, n: int = 1, factory_ids: Optional[Union[str, Iterable[str]]] = None,
               awaited_caller: bool = False, callback: Optional[Union[Callable[..., None], Pack]] = None) -> None:
        """
        Notifies `n` waiting threads, increments permits by `n`, and executes their callbacks.
        This method combines permit release with flexible notification and callback execution.

        Args:
            n (int): The number of permits to increment and threads to notify. Must be 1 or greater.
            factory_ids (Union[str, Iterable[str]], optional): A specific factory ID or a set of IDs to notify.
            awaited_caller (bool): If True, the waking thread will execute the callback; otherwise, the notifying thread will.
            callback (Optional[Callable[[], None]]): A callback function to be executed by the waking thread.
        """
        if n < 1:
            raise ValueError("Number of permits/notifications (n) must be >= 1.")
        if self._disposed:
            return
        if callback:
            callback = Pack(callback)  # Ensure callback is wrapped in Pack if provided

        with self._cond:  # Acquire the internal condition's lock for synchronized state modification
            self._buffer_or_grant(n)
            if self._bias_threshold is None:
                self._cond.notify_and_call(
                    n=n,
                    factory_ids=factory_ids,
                    callback=callback,
                    awaited_caller=awaited_caller
                )
            else:  # bias ON
                self._attempt_bias_flush(n, factory_ids)

    def notify_all(self, factory_ids: Optional[Union[str, Iterable[str]]] = None,
                   awaited_caller: bool = False, callback: Optional[Union[Callable[..., None], Pack]] = None) -> None:
        """
        Notifies all waiting threads, potentially increments permits, and executes their callbacks.
        This method combines permit release with flexible notification and callback execution.

        Args:
            factory_ids (Union[str, Iterable[str]], optional): A factory ID or a set of IDs to notify.
                                                                If None, all waiting threads are considered.
            awaited_caller (bool): If True, the waking thread will execute the callback; otherwise, the notifying thread will.
        """
        if self._disposed:
            return
        if callback:
            callback = Pack(callback)  # Ensure callback is wrapped in Pack if provided

        with self._cond:  # Acquire the internal condition's lock for synchronized state modification
            # Get a snapshot of currently waiting threads within the lock to ensure consistency
            waiting_threads_snapshot = self._cond.get_all_waiters()

            # Filter by factory_ids if specified
            if factory_ids:
                if isinstance(factory_ids, str):
                    target_ids = {factory_ids}
                else:
                    target_ids = set(factory_ids)
                threads_to_notify = [w for w in waiting_threads_snapshot if w.factory_id in target_ids]
            else:
                threads_to_notify = waiting_threads_snapshot

            n_to_increment = len(threads_to_notify)

            if n_to_increment == 0:
                return

            self._buffer_or_grant(n_to_increment)
            if self._bias_threshold is None:
                self._cond.notify_all_and_call(
                    factory_ids=factory_ids,
                    awaited_caller=awaited_caller,
                    callback=callback,
                )
            else:
                self._attempt_bias_flush_all(factory_ids, awaited_caller, callback)  # <── added

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any):
        """
        Context manager exit method. Automatically releases one permit upon exiting
        the `with` block, regardless of whether an exception occurred.

        Args:
            exc_type (Any): The exception type (if an exception was raised in the `with` block).
            exc_val (Any): The exception value.
            exc_tb (Any): The exception traceback.
        """
        self.release()

    def get_all_waiters(self) -> list[Any]:
        """
        Returns a snapshot of all `Waiter` objects currently blocking on this lock's
        internal `SmartCondition`. Each `Waiter` object contains details about
        the waiting thread, including its `factory_id`.

        Returns:
            list[Any]: A list of `Waiter` objects. Returns an empty list if the
                       lock is disposed or no threads are waiting.
        """
        if self._disposed or self._cond is None:
            return []
        return self._cond.get_all_waiters()

    def get_all_logged_factory_ids(self) -> list[str]:
        """
        Returns a copy of all unique `factory_id`s that have attempted to acquire
        this lock since its initialization. This log can be useful for debugging
        or monitoring thread participation.

        Returns:
            list[str]: A list of unique string IDs.
        """
        return list(self._log_ids)  # Return a copy to prevent external modification

    def increase_permits(self, n: int = 1) -> None:
        """
        Increases the number of available permits by `n` and notifies any
        waiting threads. This effectively adds more capacity to the semaphore.

        Args:
            n (int): The number of permits to add. Must be non-negative.

        Raises:
            ValueError: If `n` is a negative value.
        """
        if n < 0:
            raise ValueError("Cannot increase permits by a negative value.")

        with self._cond:
            self._buffer_or_grant(n)
            if self._bias_threshold is None:
                self._cond.notify(n=n)
            else:  # bias ON
                self._attempt_bias_flush(n)

    def decrease_permits(self, n: int = 1) -> None:
        """
        Decreases the number of available permits by `n`. This operation
        can reduce the capacity of the semaphore. It will raise a `ValueError`
        if attempting to decrease more permits than are currently available.

        Args:
            n (int): The number of permits to remove. Must be non-negative.

        Raises:
            ValueError: If `n` is a negative value, or if `n` is greater than
                        the current number of available permits.
        """
        if n < 0:
            raise ValueError("Cannot decrease permits by a negative value.")

        with self._cond:
            if n > self._value:
                raise ValueError(f"Cannot decrease {n} permits; only {self._value} available.")
            self._value -= n

    def wait_for_permit(self, timeout: Optional[float] = None) -> bool:
        """
        A convenience method to acquire a permit, specifically for blocking waits,
        and provides logging of the outcome. This is a wrapper around `acquire(blocking=True)`.

        Args:
            timeout (Optional[float]): The maximum time (in seconds) to wait.
                                       If None, wait indefinitely.

        Returns:
            bool: True if a permit was successfully acquired, False if the timeout expired.
        """
        return self.acquire(blocking=True, timeout=timeout)

    def release_permit(self,
                       n: int = 1,
                       factory_ids: Optional[Union[str, Iterable[str]]] = None
    ) -> None:
        """
        A convenience method to release permits, providing logging of the action.
        This is a wrapper around the `release()` method.

        Args:
            n (int): The number of permits to release.
            factory_ids (Union[str, Iterable[str]], optional): A single factory ID (string)
                                                               or an iterable of factory IDs
                                                               to specifically notify.
        """
        self.release(n=n, factory_ids=factory_ids)

    def get_all_waiting_factory_ids(self) -> list[str]:
        """
        Retrieves a list of `factory_id` strings for all threads that are
        currently blocked and waiting to acquire a permit from this lock.

        Returns:
            list[str]: A list of string ULIDs (or "MainThread") representing
                       the waiting threads. Returns an empty list if the lock
                       is disposed or no threads are waiting.
        """
        if self._disposed or self._cond is None:
            return []
        return self._cond.get_all_waiting_factory_ids()