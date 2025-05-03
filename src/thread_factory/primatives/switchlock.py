import threading
import time
from typing import Optional, Union, Iterable
from thread_factory.utils import IDisposable
from thread_factory.primatives.smart_condition import SmartCondition

class SwitchLock(IDisposable):
    """
    A dynamic, 'smart' semaphore that can:
      - Increase or decrease permits at runtime.
      - Acquire/release permits in a semaphore-like fashion.
      - Optionally do targeted factory_ids for wakeups (via SmartCondition).
      - If disposed, all waiting threads are unblocked and acquire() returns False.
    """

    def __init__(self, value: int = 1):
        """
        Initialize the SwitchLock with a starting number of 'permits'.

        :param value: The initial number of available permits (>= 0).
        """
        super().__init__()
        # Validation: the initial number of permits cannot be negative.
        if value < 0:
            raise ValueError("SwitchLock initial value must be >= 0")

        # SmartCondition is a specialized condition that uses .factory_id from threads
        # and supports targeted wake-ups. We use this for all blocking/waiting logic.
        self._cond = SmartCondition()

        # The current permit count (like a normal semaphore).
        self._value = value

    @property
    def condition(self) -> SmartCondition:
        """
        Provide access to the underlying SmartCondition if external code
        needs to do custom wait/notify beyond the standard acquire/release usage.
        """
        return self._cond

    def acquire(self,
                blocking: bool = True,
                timeout: Optional[float] = None
    ) -> bool:
        """
        Acquire a permit:
          - If self._value > 0, consume one and return True immediately.
          - Otherwise, block (or wait up to 'timeout' seconds) unless disposed.
          - If disposed while waiting, return False immediately.

        :param blocking: If False, don't block; immediately return True if a permit
                         is available, or False otherwise.
        :param timeout:  How many seconds to wait for a permit if blocking=True.
                         If None, wait indefinitely (unless disposed).
        :return: True if we successfully acquired a permit;
                 False if we timed out, were disposed, or no permit was found.
        """
        # If the user sets blocking=False but also provides a timeout, that is contradictory.
        # We cannot do a timed wait in non-blocking mode, so we raise an error.
        if not blocking and timeout is not None:
            raise ValueError("Can't specify timeout if 'blocking=False'")

        # Use the condition as a context manager => automatically acquire/release its lock.
        with self._cond:
            # If the lock is disposed before we even start, we fail fast.
            if self.disposed:
                return False

            # -----------------------------
            # Non-blocking case:
            # -----------------------------
            if not blocking:
                # If there's a permit available now, consume it and return True.
                if self._value > 0:
                    self._value -= 1
                    return True
                # Otherwise, immediately fail with False.
                return False

            # -----------------------------
            # Blocking case:
            # -----------------------------
            # We'll compute an endtime if a timeout was specified.
            endtime = None
            if timeout is not None:
                # If the user gave a non-positive timeout (e.g. 0 or negative),
                # then we effectively do an immediate check:
                if timeout <= 0:
                    if self._value > 0:
                        self._value -= 1
                        return True
                    return False
                # Otherwise, we calculate the future point in time we'll stop waiting.
                endtime = time.time() + timeout

            # We loop until a permit is available OR we time out OR we get disposed.
            while self._value == 0:
                # If disposed in the meantime, fail.
                if self.disposed:
                    return False

                # If a timeout is set, check how much time remains.
                if endtime is not None:
                    remaining = endtime - time.time()
                    # If we've run out of time, return False immediately.
                    if remaining <= 0:
                        return False
                    # Otherwise, wait with a specific timeout.
                    got_it = self._cond.wait(timeout=remaining)
                else:
                    # If no timeout, wait indefinitely.
                    got_it = self._cond.wait()

                # We woke up from waiting. Could be due to a notify, spurious wake, or disposal.
                if self.disposed:
                    # If disposed, fail with False.
                    return False
                if not got_it:
                    # not got_it => we timed out or got a spurious wake.
                    # If there's still no permit after re-check, return False.
                    if self._value == 0:
                        return False

            # If we exit the loop, there's a permit available => decrement the count and succeed.
            self._value -= 1
            return True

    # So we can use the lock in a `with SwitchLock():` block, which calls acquire() on entry.
    __enter__ = acquire

    def release(self,
                n: int = 1,
                factory_ids: Optional[Union[int, Iterable[int]]] = None
    ) -> None:
        """
        Release 'n' permits. If threads are waiting:
         - If factory_ids is None, do a normal FIFO notify for up to n threads.
         - If factory_ids is an int or iterable, only wake matching threads (targeted).

        :param n: How many permits to release at once. Must be >= 1.
        :param factory_ids: If specified, only wake threads with matching .factory_id sets.
                            If None, a normal FIFO wake of up to n waiters.
        """
        if n < 1:
            raise ValueError("n must be >= 1")

        with self._cond:
            # Add 'n' to our permit count
            self._value += n
            # Notify up to n waiters, possibly filtered by factory_ids
            self._cond.notify(n=n, factory_ids=factory_ids)

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        If used in a `with SwitchLock():` block, automatically release one permit upon exit.
        """
        self.release()

    def increase_permits(self, n: int = 1) -> None:
        """
        Increase the number of available permits by n (same as calling release(n) with no targeting).

        :param n: How many additional permits to add.
        """
        if n < 0:
            raise ValueError("Cannot increase permits by a negative value")

        with self._cond:
            self._value += n
            print(f"[SwitchLock] Increased permits by {n}, total={self._value}")
            # Wake up to n waiting threads in FIFO order
            self._cond.notify(n=n)

    def decrease_permits(self, n: int = 1) -> None:
        """
        Decrease the number of available permits by n, must not go below zero.

        :param n: How many permits to remove.
        :raises ValueError: If we attempt to remove more permits than currently available.
        """
        if n < 0:
            raise ValueError("Cannot decrease permits by a negative value")

        with self._cond:
            if n > self._value:
                raise ValueError("Cannot decrease more permits than available")
            self._value -= n
            print(f"[SwitchLock] Decreased permits by {n}, total={self._value}")

    def wait_for_permit(self, timeout: Optional[float] = None) -> bool:
        """
        A convenience method that calls acquire(blocking=True, timeout=...),
        then logs success/failure to the console.

        :param timeout: How many seconds to wait for a permit. If None, wait indefinitely.
        :return: True if we acquired a permit, False if timed out or the lock was disposed.
        """
        success = self.acquire(blocking=True, timeout=timeout)
        if success:
            print(f"[SwitchLock] Permit acquired! Remaining: {self._value}")
        else:
            print(f"[SwitchLock] Timed out or disposed while waiting for permit.")
        return success

    def release_permit(self,
                       n: int = 1,
                       factory_ids: Optional[Union[int, Iterable[int]]] = None
    ) -> None:
        """
        A convenience method equivalent to calling release(n, factory_ids=...),
        plus logs the event.

        :param n: Number of permits to release.
        :param factory_ids: If specified, only threads with matching .factory_id are awoken.
        """
        self.release(n=n, factory_ids=factory_ids)
        print(f"[SwitchLock] Permit released! Total: {self._value}")

    def get_all_waiting_factory_ids(self) -> list[int]:
        """
        Returns a flat list of factory IDs from threads currently blocked in acquire().

        :return: List of .factory_id from all waiting threads.
                 If disposed or _cond is None, return an empty list.
        """
        if self.disposed or self._cond is None:
            return []
        return self._cond.get_all_waiting_factory_ids()

    def dispose(self):
        """
        Dispose of the SwitchLock, waking any waiters so they can exit gracefully.
        Any thread currently in acquire() will see self.disposed=True and return False.

        After dispose(), the lock is no longer valid for normal usage.
        """
        if self.disposed:
            return
        self.disposed = True
        # Wake up everyone so they can see that we've been disposed
        with self._cond:
            self._cond.notify_all()
        print("[SwitchLock] Disposed.")
