import threading
import time
from typing import Optional, Union, Iterable
from thread_factory.utils import Disposable
from thread_factory.primatives.smart_condition import SmartCondition


class SwitchLock(Disposable):
    """
    A dynamic, 'smart' semaphore that can:
      - Increase or decrease permits at runtime.
      - Acquire/release permits in a semaphore-like fashion.
      - Optionally use targeted factory_ids for wakeups via the internal SmartCondition.

    Usage:
        lock = SwitchLock(value=2)

        # Basic semaphore usage:
        lock.acquire()   # block until permit is available
        # ... do work
        lock.release()

        # Dynamically increase or decrease permits:
        lock.increase_permits(3)
        lock.decrease_permits(2)

        # ID-targeted usage:
        lock.acquire(factory_ids=42)
        # ...
        lock.release(factory_ids=42)  # Wake a thread waiting with factory_ids=42
    """

    def __init__(self, value: int = 1):
        if value < 0:
            raise ValueError("SwitchLock initial value must be >= 0")

        self._cond = SmartCondition()
        self._value = value
        self._disposed = False

    @property
    def condition(self) -> SmartCondition:
        """
        Expose the internal SmartCondition if external code
        wants to do custom waits or notifications beyond acquire/release.
        """
        return self._cond

    def acquire(
            self,
            blocking: bool = True,
            timeout: Optional[float] = None,
            factory_ids: Optional[Union[int, Iterable[int]]] = None
    ) -> bool:
        """
        Acquire a permit, decrementing the internal counter by one.

        If the internal counter is larger than zero, decrement it immediately
        and return True. If it is zero:
          - if blocking is False, return False immediately;
          - otherwise, block (optionally with timeout) until it can succeed.

        You can specify `factory_ids` if you want this thread to only be
        awakened by a matching notify in `release()`. If `factory_ids` is
        None, standard no-targeting is used.

        Returns True if acquired successfully, False otherwise.
        """
        if not blocking and timeout is not None:
            raise ValueError("can't specify timeout for non-blocking acquire")

        rc = False
        endtime = None

        with self._cond:
            while self._value == 0:
                # If we can't block, or if we've timed out, break
                if not blocking:
                    break

                if timeout is not None:
                    if endtime is None:
                        endtime = time.time() + timeout
                    else:
                        timeout = endtime - time.time()
                        if timeout <= 0:
                            break

                # Wait using the SmartCondition
                # Only wake up if either the standard notify or a matching
                # factory_ids is used in 'release'.
                got_it = self._cond.wait(factory_ids=factory_ids, timeout=timeout)
                if not got_it:
                    # Timed out or spurious wake
                    break
            else:
                # We exit the while-loop normally if self._value > 0
                self._value -= 1
                rc = True

        return rc

    __enter__ = acquire  # for context-manager usage, same as a normal semaphore

    def release(
            self,
            n: int = 1,
            factory_ids: Optional[Union[int, Iterable[int]]] = None
    ) -> None:
        """
        Release a permit (or multiple permits, n), incrementing the counter.
        If `factory_ids` is given, only threads waiting with matching IDs
        will be awakened.

        When the counter was zero on entry and threads are waiting,
        up to 'n' of those waiters are woken.
        """
        if n < 1:
            raise ValueError("n must be at least 1")

        with self._cond:
            self._value += n

            # Let up to n threads proceed. If factory_ids is None,
            # this is a standard "notify any" approach.
            self._cond.notify(n=n, factory_ids=factory_ids)

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        If this object is used in a 'with' block like a normal semaphore,
        releasing one permit on exit.
        """
        self.release()

    # ---------------------------------------------------------------------
    #  Dynamic "increase" and "decrease" methods
    # ---------------------------------------------------------------------
    def increase_permits(self, n: int = 1) -> None:
        """
        Dynamically increase available permits and notify waiting threads.
        (Equivalent to release(n), except it always does a non-targeted wakeup.)
        """
        if n < 0:
            raise ValueError("Cannot increase permits by a negative value")

        with self._cond:
            self._value += n
            print(f"[SwitchLock] Increased permits by {n}, total={self._value}")
            # Wake up exactly n waiting threads, if any
            self._cond.notify(n=n)

    def decrease_permits(self, n: int = 1) -> None:
        """
        Dynamically decrease available permits by n.
        Must not reduce below zero.
        """
        if n < 0:
            raise ValueError("Cannot decrease permits by a negative value")

        with self._cond:
            if n > self._value:
                raise ValueError("Cannot decrease more permits than available")
            self._value -= n
            print(f"[SwitchLock] Decreased permits by {n}, total={self._value}")


    def wait_for_permit(
            self,
            timeout: Optional[float] = None,
            factory_ids: Optional[Union[int, Iterable[int]]] = None
    ) -> bool:
        """
        Block until a permit is available (a simpler acquire).
        Returns True if acquired, False if timed out.
        """
        success = self.acquire(blocking=True, timeout=timeout, factory_ids=factory_ids)
        if success:
            print(f"[SwitchLock] Permit acquired! Remaining permits: {self._value}")
        else:
            print(f"[SwitchLock] Timed out waiting for permit.")
        return success

    def release_permit(
            self,
            n: int = 1,
            factory_ids: Optional[Union[int, Iterable[int]]] = None
    ) -> None:
        """
        Release one or more permits (same as release, but more explicit name).
        Optionally specify factory_ids to wake target threads.
        """
        self.release(n=n, factory_ids=factory_ids)
        print(f"[SwitchLock] Permit released! Total permits: {self._value}")

    def get_all_waiting_factory_ids(self) -> list[int]:
        """
        Return a flat list of all factory IDs associated with threads currently
        blocked on this lock.

        This is useful for debugging, metrics, or real-time diagnostics.

        Returns:
            List[int]: A list of factory IDs (with possible duplicates).
        """
        if self._disposed or self._cond is None:
            return []
        return self._cond.get_all_waiting_factory_ids()

    # ---------------------------------------------------------------------
    #  Disposable implementation
    # ---------------------------------------------------------------------
    def dispose(self):
        """
        Dispose of the SwitchLock, releasing any resources and waking waiters
        so they can exit gracefully.
        """
        if self._disposed:
            return
        with self._cond:
            # If any threads are waiting, notify them so they can bail out
            self._cond.notify_all()
        self._disposed = True
        self._cond = None
        print("[SwitchLock] Disposed.")
