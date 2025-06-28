# src/thread_factory/primitives/clock_barrier.py

import threading
import time
from typing import Callable, Optional
from thread_factory.utils import IDisposable


class ClockBarrier(IDisposable):
    """
    ClockBarrier
    ------------
    A reusable synchronization barrier with a *global timeout*.

    This barrier starts a wall-clock countdown when the first thread arrives.
    If exactly `parties` threads reach the barrier before the timeout,
    all threads are released and the barrier resets for the next generation.

    If the timeout expires before all parties arrive:
    - The barrier is marked as broken.
    - All waiting threads (and any future ones) raise BrokenBarrierError.
    - An optional `on_broken` callback is triggered once.

    Parameters:
    -----------
    parties : int
        The number of threads required for the barrier to pass.
    timeout : float
        Maximum allowed time (in seconds) between the first and last thread.
    on_broken : Callable[[], None], optional
        Optional callback executed once if the barrier breaks.

    Notes:
    ------
    - Call `reset()` to reuse the barrier after a timeout.
    - Automatically resets after a successful pass.
    - Thread-safe via a single internal lock.
    - Calling `dispose()` will break the barrier and wake all waiters.
    """
    __slots__ = IDisposable.__slots__ + [
        "_parties", "_timeout", "_on_broken",
        "_lock", "_cond",
        "_count", "_start_time", "_broken", "_generation"
    ]
    def __init__(
        self,
        parties: int,
        timeout: float = 0.01,
        on_broken: Optional[Callable[[], None]] = None,
    ):
        super().__init__()

        if parties < 1:
            raise ValueError("ClockBarrier requires at least one party.")
        if timeout <= 0:
            raise ValueError("ClockBarrier timeout must be > 0.")

        self._parties = parties
        self._timeout = timeout
        self._on_broken = on_broken
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)

        # Internal state
        self._count = 0
        self._start_time = None
        self._broken = False
        self._generation = 0

    def is_broken(self) -> bool:
        """
        Returns True if the barrier is currently broken.
        """
        with self._lock:
            return self._broken

    def get_waiting_count(self) -> int:
        """
        Returns the number of threads currently blocked at the barrier.
        """
        with self._lock:
            return self._count

    def reset(self) -> None:
        """
        Resets the barrier state to allow reuse after a break.
        Safe to call even if the barrier isn't broken.
        """
        with self._cond:
            self._broken = False
            self._count = 0
            self._start_time = None
            self._generation += 1
            self._cond.notify_all()

    def wait(self) -> bool:
        """
        Waits until enough threads arrive at the barrier or timeout is reached.

        Returns:
            True if the barrier passed successfully.

        Raises:
            BrokenBarrierError if the timeout expires or the barrier is already broken.
        """
        with self._cond:
            if self._broken:
                raise threading.BrokenBarrierError("ClockBarrier timeout")

            my_generation = self._generation
            self._count += 1

            if self._count == 1:
                # First thread starts the timer
                self._start_time = time.monotonic()

            if self._count == self._parties:
                # All required threads have arrived
                self._advance_generation()
                return True

            while True:
                remaining = self._timeout - (time.monotonic() - self._start_time)
                if remaining <= 0:
                    self._break_barrier_locked()
                    raise threading.BrokenBarrierError("ClockBarrier timeout")

                self._cond.wait(timeout=remaining)

                # Determine whether we were released due to success or failure
                if self._generation != my_generation:
                    if self._broken:
                        raise threading.BrokenBarrierError("ClockBarrier timeout")
                    return True

    def _advance_generation(self) -> None:
        """
        Resets state and releases all waiters after a successful pass.
        """
        self._cond.notify_all()
        self._count = 0
        self._start_time = None
        self._generation += 1

    def _break_barrier_locked(self) -> None:
        """
        Marks the barrier as broken and notifies all waiters.
        This method must be called with the condition lock held.
        """
        if self._broken:
            return
        self._broken = True
        self._cond.notify_all()
        if self._on_broken:
            try:
                self._on_broken()
            except Exception:
                pass

    def dispose(self) -> None:
        """
        Breaks the barrier and wakes all waiters.
        Safe to call multiple times.
        """
        if self._disposed:
            return
        self._disposed = True
        with self._cond:
            self._break_barrier_locked()
