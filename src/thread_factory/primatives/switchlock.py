import time
from typing import Optional, Union, Iterable, Any
from thread_factory.utils import IDisposable
from thread_factory.primatives.smart_condition import SmartCondition


class SwitchLock(IDisposable):
    """
    SwitchLock
    ----------
    A dynamic, "smart" semaphore implementation that provides granular control
    over permits and thread notifications. It extends standard semaphore
    functionality by allowing runtime adjustment of available permits,
    targeted thread awakening using unique identifiers (ULIDs), and
    robust disposal mechanisms.

    This lock is designed for scenarios requiring flexible synchronization,
    such as managing access to limited resources where the resource count
    can change, or coordinating groups of threads with specific needs.

    It leverages a `SmartCondition` internally for advanced thread signaling.
    """

    def __init__(self, value: int = 1):
        """
        Initializes a new SwitchLock instance.

        Args:
            value (int): The initial number of available permits. Must be a non-negative integer.

        Raises:
            ValueError: If the initial `value` is less than 0.
        """
        super().__init__()  # Initialize the IDisposable base class
        if value < 0:
            raise ValueError("SwitchLock initial value must be >= 0")

        self._cond: SmartCondition = SmartCondition()
        self._value: int = value  # Current count of available permits
        self._log_ids: list[str] = []  # Stores unique identifiers of threads that attempted to acquire the lock

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

    def acquire(self, blocking: bool = True, timeout: Optional[float] = None) -> bool:
        """
        Attempts to acquire a permit from the SwitchLock.

        If `blocking` is True, the calling thread will wait until a permit
        becomes available or the `timeout` expires. If `blocking` is False,
        the method returns immediately.

        Args:
            blocking (bool): If True, block until a permit is acquired or timeout.
                             If False, return immediately. Defaults to True.
            timeout (Optional[float]): The maximum time (in seconds) to wait if `blocking` is True.
                                       If None, wait indefinitely. This parameter cannot be used
                                       when `blocking` is False.

        Returns:
            bool: True if a permit was successfully acquired, False otherwise (e.g., timed out,
                  `blocking=False` and no permit available, or lock was disposed).

        Raises:
            ValueError: If `timeout` is specified when `blocking` is False.
        """
        if not blocking and timeout is not None:
            raise ValueError("Cannot specify 'timeout' when 'blocking' is False.")

        # Ensure the current thread has a factory_id, assigning one if missing.
        # This ID is used for targeted notifications and logging.
        thread_factory_id = self._cond._ensure_factory_id()

        # Log the factory ID of the thread attempting to acquire the lock
        if thread_factory_id not in self._log_ids:
            self._log_ids.append(thread_factory_id)

        with self._cond:  # Acquire the internal condition's lock for synchronized access
            if self._disposed:
                return False  # Cannot acquire if the lock has been disposed

            if not blocking:
                # Non-blocking attempt: check if a permit is immediately available
                if self._value > 0:
                    self._value -= 1
                    return True
                return False  # No permit available

            # Blocking attempt:
            endtime = time.time() + timeout if timeout is not None else None

            while True:
                if self._disposed:
                    return False  # Exit if disposed while waiting

                if self._value > 0:
                    self._value -= 1
                    return True  # Permit acquired

                # Calculate remaining time for timeout, if applicable
                remaining = endtime - time.time() if endtime else None
                if remaining is not None and remaining <= 0:
                    return False  # Timeout has expired

                # Wait on the internal SmartCondition. This releases the internal lock,
                # then re-acquires it upon waking or timeout.
                got_it = self._cond.wait(timeout=remaining)
                if not got_it:
                    # If wait() returned False, it implies a timeout on the condition itself.
                    # The loop will re-check the overall `remaining` time and `_value`.
                    return False # Permit was not acquired within the specified duration

    __enter__ = acquire  # Allows using the SwitchLock as a context manager (e.g., `with lock:`)

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
            self._value += n  # Increase the count of available permits
            # Notify waiting threads. SmartCondition handles the actual awakening logic.
            self._cond.notify(n=n, factory_ids=factory_ids)

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
            self._value += n
            print(f"[SwitchLock] Increased permits by {n}, total={self._value}")
            self._cond.notify(n=n)  # Notify potential waiters that permits are now available

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
            print(f"[SwitchLock] Decreased permits by {n}, total={self._value}")

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
        success = self.acquire(blocking=True, timeout=timeout)
        print(f"[SwitchLock] {'Acquired' if success else 'Timed out'} permit. Remaining: {self._value}")
        return success

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
        print(f"[SwitchLock] Released permit(s). Total: {self._value}")

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

    def dispose(self):
        """
        Disposes of the SwitchLock, releasing all its resources and
        waking up any threads currently waiting to acquire a permit.
        After disposal, the lock should no longer be used. This method is idempotent.
        """
        if self.disposed:  # Check if the lock has already been disposed
            return
        self._disposed = True  # Mark the lock as disposed
        with self._cond:
            # Notify all waiting threads so they can wake up and check the `_disposed` flag
            self._cond.notify_all()
        print("[SwitchLock] Disposed.")

