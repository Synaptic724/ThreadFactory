import threading
import time
import ulid
from typing import Optional, Union, Iterable, Any, Callable
from thread_factory.utils import IDisposable
from thread_factory.primatives.smart_condition import SmartCondition # Assuming this is correct

class SwitchLock(IDisposable):
    """
    SwitchLock
    ----------
    A dynamic, "smart" synchronization primitive that extends traditional semaphore
    functionality with advanced control over permits and thread notifications.
    It is designed for sophisticated concurrent systems, particularly those
    involving long-lived agents or dynamic resource management.

    Key Features:
    - **Dynamic Permit Management**: Adjust the number of available permits at runtime.
    - **Targeted Notifications**: Wake specific threads or groups of threads using
      their unique `factory_id`s, leveraging the underlying `SmartCondition`.
    - **Callback Integration**: Execute custom logic when a thread is notified,
      either by the notifying thread or the awakened thread itself.
    - **Bias Control (Adaptive Permit Release)**: Intelligently buffer newly released
      permits and only make them available when a certain threshold of waiting threads
      is met. This helps prevent "thundering herd" issues and optimize resource
      allocation.
    - **Agentic Worker Integration**: Optionally trigger a 'return home' state for
      specific worker types when they block awaiting a permit, facilitating efficient
      idle state management.
    - **Robust Disposal**: Ensures clean shutdown by waking all waiting threads
      and preventing further use of the lock.

    This lock is ideal for scenarios like managing access to changing resource pools,
    orchestrating complex workflows with inter-dependent agents, or implementing
    advanced load balancing strategies.
    """

    def __init__(self, value: int = 1, return_home_on_block: bool = False, worker_type: str = "dynamic", bias_threshold: Optional[int] = None):
        """
        Initializes a new SwitchLock instance.

        Args:
            value (int): The initial number of available permits. Must be a non-negative integer.
                         These permits are immediately available for acquisition.
            return_home_on_block (bool): If True, and the acquiring thread is of the specified
                                         `worker_type` and has a `return_home` method, that method
                                         will be invoked when the thread blocks on `acquire()`.
                                         This allows agentic workers to gracefully return to an
                                         idle or main loop state while waiting for resources.
            worker_type (str): A string identifier for the type of worker thread this lock
                               is primarily intended for (e.g., "dynamic", "io_worker").
                               If `acquire()` is called by a thread whose `_worker_type`
                               attribute does not match this, a `RuntimeError` will be raised.
            bias_threshold (Optional[int]): Controls the "bias" behavior.
                                            - If `None` or `0` (default for `None`), bias is OFF.
                                              Permits are immediately available upon `release()`
                                              or `increase_permits()`.
                                            - If a positive integer, bias is ON. Newly released permits
                                              are initially buffered (`_pending_permits`) and are
                                              only made fully available (`_value`) when the number
                                              of waiting threads (plus the current acquiring thread, if applicable)
                                              exceeds this `bias_threshold`. This helps to group
                                              notifications and reduce contention.

        Raises:
            ValueError: If the initial `value` is less than 0.
        """
        super().__init__()  # Initialize the IDisposable base class
        if value < 0:
            raise ValueError("SwitchLock initial value must be >= 0")

        self._cond: SmartCondition = SmartCondition()
        self._value: int = value  # Current count of available permits
        self._log_ids: list[str] = []  # Stores unique identifiers of threads that attempted to acquire the lock
        self._return_home_on_block: bool = return_home_on_block  # Flag to control behavior when a thread blocks on the lock
        self._worker_type: str = worker_type  # Type of worker, used for strict enforcement in acquire()
        self._bias_threshold: Optional[int] = bias_threshold
        self._pending_permits: int = 0  # Permits buffered due to bias, not yet added to _value

    @property
    def return_home_on_block(self) -> bool:
        """
        Indicates whether a worker should attempt to return to its 'home' state
        when it blocks on this lock's `acquire()` method.
        """
        return self._return_home_on_block

    @return_home_on_block.setter
    def return_home_on_block(self, value: bool) -> None:
        """
        Sets whether a worker should attempt to return to its 'home' state
        when it blocks on this lock's `acquire()` method.

        Args:
            value (bool): True to enable, False to disable.
        """
        self._return_home_on_block = value

    @property
    def condition(self) -> SmartCondition:
        """
        Provides direct access to the internal `SmartCondition` object.
        This property is primarily for advanced use cases or introspection,
        allowing direct interaction with the underlying condition variable
        for highly customized signaling.

        Returns:
            SmartCondition: The internal `SmartCondition` instance used for thread signaling.
        """
        return self._cond

    def _try_bias_flush(self) -> None:
        """
        Internal method: Attempts to flush buffered permits if bias is active
        and the number of waiting threads meets or exceeds the `_bias_threshold`.
        Permits are added to `_value`, and corresponding threads are notified.
        """
        if self._bias_threshold is None or self._bias_threshold <= 0: # Bias is off or invalid
            return

        waiters = len(self._cond.get_all_waiters())
        if waiters > self._bias_threshold and self._pending_permits > 0:
            n_flushed = self._pending_permits # Capture the amount being flushed
            self._value += n_flushed
            self._pending_permits = 0
            self._cond.notify(n=n_flushed) # Notify exactly the number of permits flushed

    def _buffer_or_grant(self, n: int) -> None:
        """
        Internal method: Adds `n` permits. If bias is OFF, they are added directly
        to `_value`. If bias is ON, they are added to `_pending_permits` buffer.

        Args:
            n (int): The number of permits to add.
        """
        if self._bias_threshold is None or self._bias_threshold <= 0:  # Bias OFF
            self._value += n
            return

        # Bias ON → just buffer, don’t flush immediately
        self._pending_permits += n
        # _try_bias_flush() is NOT called here; flushing happens on acquire,
        # set_bias_threshold, or explicit bypass_bias calls.

    def _check_if_worker_type(self) -> bool:
        """
        Internal method: Checks if the current thread is of the `_worker_type`
        specified for this lock.

        Returns:
            bool: True if the current thread's `_worker_type` attribute matches
                  this lock's `_worker_type`, False otherwise.
        """
        current = threading.current_thread()
        return hasattr(current, "_worker_type") and getattr(current, "_worker_type") == self._worker_type

    def _flush_pending_permits(self, wake_all: bool = False, wake_n: Optional[int] = None) -> None:
        """
        Internal method: Moves all buffered permits from `_pending_permits` into
        `_value` and notifies waiting threads. This is used when bias is being
        disabled or explicitly bypassed.

        Args:
            wake_all (bool): If True, calls `SmartCondition.notify_all()` to wake all threads.
                             Overrides `wake_n`.
            wake_n (Optional[int]): If provided, calls `SmartCondition.notify(n=wake_n)`
                                    to wake a specific number of threads. Ignored if `wake_all` is True.
        """
        if self._pending_permits == 0:
            return

        n_flushed = self._pending_permits # Capture the amount being flushed
        self._value += n_flushed
        self._pending_permits = 0

        if wake_all:
            self._cond.notify_all()
        elif wake_n is not None:
            self._cond.notify(n=wake_n)

    def set_bias_threshold(self, threshold: Optional[int]) -> None:
        """
        Changes the bias threshold at runtime. This can dynamically alter how
        permits are made available to waiting threads.

        Args:
            threshold (Optional[int]): The new bias threshold.
                                       - `None` or `0`: Turns bias OFF. All buffered permits
                                         are immediately flushed to `_value`, and all waiting
                                         threads are notified.
                                       - Any other positive integer: Sets bias ON to this new threshold.
                                         If buffered permits exist and the current number of
                                         waiters meets or exceeds this new threshold,
                                         those buffered permits are flushed and waiting threads are notified.
        """
        with self._cond: # Ensure thread-safe modification of bias state and permit flush
            self._bias_threshold = threshold

            # --- Turn bias OFF → flush everything ---
            if threshold is None or threshold <= 0:
                self._flush_pending_permits(wake_all=True)
                return

            # --- Bias remains ON (or was just set ON) ---
            waiter_cnt = len(self._cond.get_all_waiters())
            if self._pending_permits > 0 and waiter_cnt >= threshold:
                # If conditions met, flush the buffered permits
                n_flush = self._pending_permits # Capture amount before reset
                self._flush_pending_permits(wake_n=n_flush)

    def has_factory_id(self) -> bool:
        """
        Checks if the current thread has a `_factory_id` attribute. This is
        often an indicator that the thread is managed by a factory or custom system.

        Returns:
            bool: True if the current thread has a `_factory_id` attribute, False otherwise.
        """
        thread = threading.current_thread()
        return hasattr(thread, "_factory_id") # Note: SmartCondition uses `factory_id` directly on thread, not `_factory_id`

    def set_callback(self, factory_id: str, callback: Callable[[], None]) -> None:
        """
        Registers a specific callable function (`callback`) to be executed when
        a thread identified by `factory_id` is notified by this lock (via
        `notify()` with `awaited_caller=True` or `notify_and_call()` from `SmartCondition`).

        Args:
            factory_id (str): The unique identifier of the waiting thread to bind the callback to.
            callback (Callable[[], None]): The function to execute. It must take no arguments.
        """
        self._cond.bind_callback(factory_id, callback)

    def set_default_callback(self, callback: Callable[[], None]) -> None:
        """
        Sets a fallback callback function that will be executed for any notified thread
        that does not have a specific callback bound via `set_callback()`. This also
        applies when `notify()` or `notify_all()` methods are used with `awaited_caller=True`.

        Args:
            callback (Callable[[], None]): The function to be used as the default callback.
                                          It must take no arguments.
        """
        self._cond.set_default_callback(callback)

    def _return_home(self) -> None:
        """
        Internal method: Invokes the `return_home()` method on the current thread
        if `return_home_on_block` is True and the thread exposes such a callable.
        This is typically used by agentic worker threads to yield control or
        return to an idle state while waiting for a permit.

        Raises:
            RuntimeError: If `return_home_on_block` is True but the current thread
                          does not have a callable `return_home` method.
        """
        current = threading.current_thread()
        return_home_fn = getattr(current, "return_home", None)
        if callable(return_home_fn):
            return_home_fn()
        else:
            raise RuntimeError(
                f"[SwitchLock] Current thread ({current.name}) does not have a callable 'return_home' method "
                f"while `return_home_on_block` is enabled."
            )

    def bypass_bias(self) -> None:
        """
        Forces an immediate flush of all currently buffered permits, making them
        fully available for acquisition. This also notifies all threads currently
        waiting on the lock.

        Use this method cautiously when you explicitly need to override the bias
        mechanism and ensure all waiting threads are immediately eligible to acquire.
        """
        with self._cond: # Acquire the SmartCondition's lock for synchronized state modification
            if self._pending_permits > 0:
                self._flush_pending_permits(wake_all=True)

    def acquire(self, blocking: bool = True, timeout: Optional[float] = None) -> bool:
        """
        Acquires one permit from the SwitchLock.

        Behavior depends on blocking mode, timeout, worker type, and bias:
        - **Worker Type Enforcement**: The calling thread's `_worker_type` attribute
          *must* match the `worker_type` set during `SwitchLock` initialization.
          Otherwise, a `RuntimeError` is raised.
        - **Blocking Mode**:
            - `blocking=True` (default): The thread waits until a permit is available
              or the `timeout` (if provided) expires.
            - `blocking=False`: The method returns immediately. If a permit is
              available, it's acquired; otherwise, `False` is returned.
        - **Timeout**:
            - `None`: Wait indefinitely if `blocking=True`.
            - `float`: Wait for up to this many seconds. Returns `False` if timeout
              occurs before a permit is acquired.
        - **`return_home_on_block`**: If enabled, and the thread is a recognized worker,
          its `return_home()` method is called before blocking.
        - **Bias Control**: If `bias_threshold` is active, this method is also
          responsible for checking if the number of waiting threads (including this one)
          exceeds the threshold, which then triggers a flush of any `_pending_permits`
          into `_value` and notifies waiting threads. The acquiring thread will then
          attempt to acquire one of these newly available permits.

        Args:
            blocking (bool): If True, block until a permit is acquired or timeout.
                             If False, return immediately.
            timeout (Optional[float]): The maximum time (in seconds) to wait if `blocking` is True.
                                       Cannot be set if `blocking` is False.

        Returns:
            bool: `True` if a permit was successfully acquired, `False` otherwise
                  (e.g., if `blocking=False` and no permit was available, or if
                  the `timeout` expired, or if the lock was disposed while waiting).

        Raises:
            ValueError: If `blocking` is False but `timeout` is provided.
            RuntimeError: If the calling thread's `_worker_type` does not match
                          the lock's `worker_type` or if `return_home_on_block`
                          is enabled but `return_home` is not callable on the thread.
        """
        if not blocking and timeout is not None:
            raise ValueError("Cannot provide a timeout with blocking=False.")

        # Enforce worker type restriction
        if not self._check_if_worker_type():
            raise RuntimeError(
                f"Cannot acquire SwitchLock outside of '{self._worker_type}' worker context."
                f" Current thread '{threading.current_thread().name}' does not match."
            )

        this_id = self._cond._ensure_factory_id() # Ensure the current thread has a factory_id
        if this_id not in self._log_ids:
            self._log_ids.append(this_id)

        endtime = None if timeout is None else time.time() + timeout

        with self._cond: # Acquire the SmartCondition's lock for synchronized state modification
            if self._disposed:  # Check if disposed before attempting to acquire
                return False

            while True:
                # 1. Check for disposal (important if woken by dispose while waiting)
                if self._disposed:
                    return False

                # 2. Fast-path: permit available
                if self._value > 0:
                    self._value -= 1
                    return True

                # 3. Handle non-blocking acquire
                if not blocking:
                    return False # No permit available, return immediately

                # 4. Check for timeout expiry (before potentially waiting again)
                if endtime is not None and time.time() >= endtime:
                    return False

                # 5. Optional "return home" callback for agentic workers
                if self._return_home_on_block:
                    self._return_home() # This might yield control back to the worker's main loop

                # 6. Bias flush check: Attempt to release buffered permits if conditions met
                if (
                        self._bias_threshold is not None and self._bias_threshold > 0 # Bias must be active
                        and self._pending_permits > 0 # There must be buffered permits
                        and len(self._cond.get_all_waiters()) + 1 > self._bias_threshold # Threshold crossed (including current thread)
                ):
                    n_flushed = self._pending_permits # Capture the amount being flushed
                    self._value += n_flushed
                    self._pending_permits = 0
                    self._cond.notify(n=n_flushed) # Notify exactly the number of permits flushed
                    continue # Loop back immediately to try and acquire one of the newly available permits

                # 7. Really wait: Block the current thread
                remaining = None if endtime is None else max(0, endtime - time.time())
                # _cond.wait() will temporarily release self._cond's lock
                if not self._cond.wait(timeout=remaining):
                    # Woke up due to timeout, not explicit notification
                    return False

    __enter__ = acquire  # Allows using the SwitchLock as a context manager (e.g., `with lock:`)

    def release(self,
                n: int = 1,
                factory_ids: Optional[Union[str, Iterable[str]]] = None
    ) -> None:
        """
        Releases `n` permits, making them available for other threads to acquire.
        This method primarily focuses on incrementing the permit count.

        - If bias is OFF (`bias_threshold` is `None` or `0`), the permits are
          immediately added to the available count (`_value`), and `n` waiting
          threads (optionally targeted by `factory_ids`) are notified.
        - If bias is ON (`bias_threshold` is a positive integer), the permits
          are added to the internal buffer (`_pending_permits`) and are *not*
          immediately released or notified by this method. They will be flushed
          and notifications will occur only when the bias conditions are met
          (e.g., when `acquire()` is called by a sufficient number of waiters,
          or `set_bias_threshold()` changes the bias to OFF, or `bypass_bias()` is called).

        Args:
            n (int): The number of permits to release. Must be 1 or greater.
            factory_ids (Optional[Union[str, Iterable[str]]]): A single `factory_id` string
                                                               or an iterable of `factory_id` strings.
                                                               If provided, only threads with matching IDs
                                                               will be considered for notification (if bias is OFF).
                                                               If `None`, notifications are general (FIFO).

        Raises:
            ValueError: If `n` is less than 1.
        """
        if n < 1:
            raise ValueError("Number of permits to release (n) must be >= 1.")
        if self._disposed:
            # If disposed, subsequent releases have no effect.
            # Log this if verbose logging is desired.
            return

        with self._cond:  # Acquire the internal condition's lock for synchronized state modification
            self._buffer_or_grant(n) # Add permits to buffer or directly to _value based on bias
            if self._bias_threshold is None or self._bias_threshold <= 0: # Only notify if bias is OFF
                self._cond.notify(n=n, factory_ids=factory_ids)

    def notify(self, n: int = 1, factory_ids: Optional[Union[str, Iterable[str]]] = None,
               awaited_caller: bool = False) -> None:
        """
        Notifies `n` waiting threads and makes them eligible to acquire a permit.
        This method is a more direct way to signal threads compared to `release()`,
        providing explicit control over callbacks.

        - The lock's permit count is incremented by `n` (buffered if bias is ON).
        - If bias is OFF, `n` waiting threads (optionally targeted by `factory_ids`)
          are notified. If callbacks are registered, they are executed based on `awaited_caller`.
        - If bias is ON, permits are *only buffered*. No immediate notifications
          are sent from this method; threads will only wake when bias conditions
          are met (e.g., via `acquire`'s internal flush, or `bypass_bias`).

        Args:
            n (int): The number of threads to notify and the corresponding number of
                     permits to make available (or buffer). Must be 1 or greater.
            factory_ids (Optional[Union[str, Iterable[str]]]): A single `factory_id` or an
                                                               iterable of `factory_id`s to
                                                               specifically target for notification.
            awaited_caller (bool): If True, and a callback is associated with the notified thread
                                   (via `set_callback()` or `set_default_callback()`), that callback
                                   will be executed by the *awakened thread itself* after it wakes up.
                                   If False (default), the notifying thread executes the callback.
        Raises:
            ValueError: If `n` is less than 1.
        """
        if n < 1:
            raise ValueError("Number of permits/notifications (n) must be >= 1.")
        if self._disposed:
            return

        with self._cond:  # Acquire the internal condition's lock for synchronized state modification
            self._buffer_or_grant(n) # Increment permit count or buffer permits
            if self._bias_threshold is None or self._bias_threshold <= 0: # Only notify if bias is OFF
                self._cond.notify_and_call( # Use SmartCondition's direct callback mechanism
                    n=n,
                    factory_ids=factory_ids,
                    callback=None, # Use bound/default callbacks from SmartCondition's registry
                    awaited_caller=awaited_caller
                )

    def notify_all(self, factory_ids: Optional[Union[str, Iterable[str]]] = None,
                   awaited_caller: bool = False) -> None:
        """
        Notifies all eligible waiting threads and makes permits available for them.
        This method is a broadcast signal with permit provisioning and optional callbacks.

        - The lock's permit count is incremented by the number of eligible waiters found
          (or buffered if bias is ON).
        - If bias is OFF, all eligible waiting threads (optionally filtered by `factory_ids`)
          are notified. If callbacks are registered, they are executed based on `awaited_caller`.
        - If bias is ON, permits are *only buffered*. No immediate notifications
          are sent from this method; threads will only wake when bias conditions
          are met (e.g., via `acquire`'s internal flush, or `bypass_bias`).

        Args:
            factory_ids (Optional[Union[str, Iterable[str]]]): A single `factory_id` or an
                                                               iterable of `factory_id`s to
                                                               specifically target for notification.
                                                               If `None`, all waiting threads are considered.
            awaited_caller (bool): If True, and a callback is associated with the notified thread,
                                   that callback will be executed by the *awakened thread itself*.
                                   If False (default), the notifying thread executes the callback.
        """
        if self._disposed:
            return

        with self._cond:  # Acquire the internal condition's lock for synchronized state modification
            # Get a snapshot of currently waiting threads within the lock to ensure consistency
            waiting_threads_snapshot = self._cond.get_all_waiters()

            # Determine which threads are eligible for notification
            if factory_ids:
                if isinstance(factory_ids, str):
                    target_ids = {factory_ids}
                else:
                    target_ids = set(factory_ids)
                threads_to_notify = [w for w in waiting_threads_snapshot if w.factory_id in target_ids]
            else:
                threads_to_notify = waiting_threads_snapshot

            n_to_increment = len(threads_to_notify) # Number of permits to release/buffer

            # If no eligible waiters, no permits are incremented by this call, and no notifications
            if n_to_increment == 0:
                # Log if verbose logging is enabled, but no action needed
                return

            self._buffer_or_grant(n_to_increment) # Increment permit count or buffer permits
            if self._bias_threshold is None or self._bias_threshold <= 0: # Only notify if bias is OFF
                self._cond.notify_all( # Use SmartCondition's direct callback mechanism
                    factory_ids=factory_ids,
                    awaited_caller=awaited_caller
                )

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any):
        """
        Context manager exit method. Automatically releases one permit upon exiting
        the `with` block, ensuring that permits are properly returned even if an
        exception occurred within the block.

        Args:
            exc_type (Any): The exception type (if an exception was raised in the `with` block).
            exc_val (Any): The exception value.
            exc_tb (Any): The exception traceback.
        """
        self.release()

    def get_all_waiters(self) -> list[Any]: # Keep Any for Waiter type to avoid circular imports if Waiter is in SmartCondition's file
        """
        Returns a snapshot (a copy) of all `Waiter` objects currently blocking on this
        lock's internal `SmartCondition`. Each `Waiter` object contains details
        about the waiting thread, including its `factory_id`.

        Returns:
            list[Any]: A list of `Waiter` dataclass instances. Returns an empty list
                       if the lock is disposed or no threads are waiting.
        """
        if self._disposed or self._cond is None:
            return []
        return self._cond.get_all_waiters()

    def get_all_logged_factory_ids(self) -> list[str]:
        """
        Returns a copy of all unique `factory_id` strings for threads that have
        attempted to acquire this lock since its initialization. This log can be
        useful for debugging or monitoring thread participation over time.

        Returns:
            list[str]: A list of unique string `factory_id`s.
        """
        return list(self._log_ids)  # Return a copy to prevent external modification

    def increase_permits(self, n: int = 1) -> None:
        """
        Increases the number of available permits by `n`.

        - If bias is OFF, the permits are immediately added to `_value`, and
          `n` waiting threads are notified.
        - If bias is ON, the permits are added to `_pending_permits` buffer and
          are *not* immediately released or notified by this method. Flushing
          and notifications will occur when bias conditions are met.

        Args:
            n (int): The number of permits to add. Must be non-negative.

        Raises:
            ValueError: If `n` is a negative value.
        """
        if n < 0:
            raise ValueError("Cannot increase permits by a negative value.")
        if self._disposed:
            return

        with self._cond:
            self._buffer_or_grant(n) # Add permits to buffer or directly to _value
            if self._bias_threshold is None or self._bias_threshold <= 0: # Only notify if bias is OFF
                self._cond.notify(n=n) # Notify based on the number of permits added

    def decrease_permits(self, n: int = 1) -> None:
        """
        Decreases the number of available permits by `n`. This operation
        reduces the capacity of the semaphore.

        Args:
            n (int): The number of permits to remove. Must be non-negative.

        Raises:
            ValueError: If `n` is a negative value, or if `n` is greater than
                        the current number of available permits (`_value`).
        """
        if n < 0:
            raise ValueError("Cannot decrease permits by a negative value.")
        if self._disposed:
            return

        with self._cond:
            if n > self._value:
                raise ValueError(f"Cannot decrease {n} permits; only {self._value} available.")
            self._value -= n
            # No notification needed here, as permits are being removed.
            # print(f"[SwitchLock] Decreased permits by {n}, total={self._value}") # Remove print for public API

    def wait_for_permit(self, timeout: Optional[float] = None) -> bool:
        """
        A convenience method to acquire a permit, specifically for blocking waits.
        This is a wrapper around `acquire(blocking=True)`.

        Args:
            timeout (Optional[float]): The maximum time (in seconds) to wait.
                                       If `None`, wait indefinitely.

        Returns:
            bool: True if a permit was successfully acquired, False if the timeout expired
                  or the lock was disposed.
        """
        success = self.acquire(blocking=True, timeout=timeout)
        # print(f"[SwitchLock] {'Acquired' if success else 'Timed out'} permit. Remaining: {self._value}") # Remove print for public API
        return success

    def release_permit(self,
                       n: int = 1,
                       factory_ids: Optional[Union[str, Iterable[str]]] = None
    ) -> None:
        """
        A convenience method to release permits, providing a consistent API for
        releasing a single or multiple permits. This is a wrapper around the `release()` method.

        Args:
            n (int): The number of permits to release.
            factory_ids (Optional[Union[str, Iterable[str]]]): A single `factory_id` string
                                                               or an iterable of `factory_id` strings
                                                               to specifically notify (if bias is OFF).
        """
        self.release(n=n, factory_ids=factory_ids)
        # print(f"[SwitchLock] Released permit(s). Total: {self._value}") # Remove print for public API

    def get_all_waiting_factory_ids(self) -> list[str]:
        """
        Retrieves a list of `factory_id` strings for all threads that are
        currently blocked and waiting to acquire a permit from this lock.

        Returns:
            list[str]: A list of string `factory_id`s (e.g., ULIDs or "MainThread")
                       representing the waiting threads. Returns an empty list if the
                       lock is disposed or no threads are waiting.
        """
        if self._disposed or self._cond is None:
            return []
        return self._cond.get_all_waiting_factory_ids()

    def dispose(self):
        """
        Disposes of the SwitchLock, releasing all its resources and
        waking up any threads currently waiting to acquire a permit.
        After disposal, all subsequent `acquire()` calls will immediately
        return `False`. This method is idempotent (safe to call multiple times).
        Any further operations on the disposed lock may behave unexpectedly.
        """
        if self.disposed:  # Check if the lock has already been disposed
            return
        self._disposed = True  # Mark the lock as disposed
        with self._cond:
            # Notify all waiting threads so they can wake up and check the `_disposed` flag.
            # This ensures no threads remain indefinitely blocked on the disposed lock.
            self._cond.notify_all()
        # print("[SwitchLock] Disposed.") # Remove print for public API