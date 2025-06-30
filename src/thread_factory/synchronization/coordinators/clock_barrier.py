import threading
import time
from typing import Callable, Optional, Dict, Any
import ulid
from thread_factory.utils import IDisposable


# Assuming Controller is available for type hinting
# from thread_factory.synchronization.controllers.controller import Controller

class ClockBarrier(IDisposable):
    """
    ClockBarrier
    ------------
    A reusable synchronization barrier with a *global timeout* that can be
    observed and controlled by a Controller.
    """
    __slots__ = IDisposable.__slots__ + [
        "_threshold", "_timeout", "_on_broken",
        "_lock", "_cond",
        "_count", "_start_time", "_broken", "_generation", "_id",
        "_controller"  # Added for controller integration
    ]

    def __init__(
            self,
            threshold: int,
            timeout: float = 0.01,
            on_broken: Optional[Callable[[], None]] = None,
            controller: Optional['Controller'] = None,
    ):
        super().__init__()

        if threshold < 1:
            raise ValueError("ClockBarrier requires at least one party.")
        if timeout <= 0:
            raise ValueError("ClockBarrier timeout must be > 0.")

        self._id = str(ulid.ULID())
        self._threshold = threshold
        self._timeout = timeout
        self._on_broken = on_broken
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)

        # Internal state
        self._count = 0
        self._start_time = None
        self._broken = False
        self._generation = 0

        # --- Controller Integration ---
        self._controller = controller
        if self._controller:
            try:
                self._controller.register(self)
            except Exception:
                # Allow standalone use if registration fails
                pass

    # --- Controller Contract ---
    @property
    def id(self) -> str:
        """The unique identifier for this component."""
        return self._id

    def _get_object_details(self) -> Dict[str, Any]:
        """Provides commands and metadata for the Controller."""
        return {
            'name': 'clock_barrier',
            'commands': {
                'reset': self.reset,
                'is_broken': self.is_broken,
                'get_waiting_count': self.get_waiting_count,
            }
        }

    # --- Existing Methods (with modifications for notifications) ---

    def is_broken(self) -> bool:
        """Returns True if the barrier is currently broken."""
        with self._lock:
            return self._broken

    def get_waiting_count(self) -> int:
        """Returns the number of threads currently blocked at the barrier."""
        with self._lock:
            return self._count

    def reset(self) -> None:
        """Resets the barrier state to allow reuse after a break."""
        with self._cond:
            self._broken = False
            self._count = 0
            self._start_time = None
            self._generation += 1
            self._cond.notify_all()

    def wait(self) -> bool:
        """
        Waits until enough threads arrive at the barrier or timeout is reached.
        """
        with self._cond:
            if self._disposed:
                raise threading.BrokenBarrierError("ClockBarrier is disposed")
            if self._broken:
                raise threading.BrokenBarrierError("ClockBarrier is broken")

            my_generation = self._generation
            self._count += 1

            if self._count == 1:
                self._start_time = time.monotonic()

            if self._count == self._threshold:
                self._advance_generation()  # This will notify and reset
                return True

            while True:
                # This check prevents a race condition if start_time is not yet set
                if self._start_time is None:
                    self._cond.wait(timeout=self._timeout)
                    continue

                remaining = self._timeout - (time.monotonic() - self._start_time)
                if remaining <= 0:
                    self._break_barrier_locked()
                    raise threading.BrokenBarrierError("ClockBarrier timeout")

                self._cond.wait(timeout=remaining)

                if self._generation != my_generation:
                    if self._broken:
                        raise threading.BrokenBarrierError("ClockBarrier is broken")
                    return True

    def _advance_generation(self) -> None:
        """Resets state, notifies controller, and releases all waiters."""
        # Notify Controller of success
        if self._controller:
            self._controller.notify(self.id, "BARRIER_PASSED")

        self._cond.notify_all()
        self._count = 0
        self._start_time = None
        self._generation += 1

    def _break_barrier_locked(self) -> None:
        """Marks barrier as broken, notifies controller, and wakes waiters."""
        if self._broken:
            return
        self._broken = True

        # Notify Controller of failure
        if self._controller:
            self._controller.notify(self.id, "BARRIER_BROKEN")

        self._cond.notify_all()
        if self._on_broken:
            try:
                self._on_broken()
            except Exception:
                pass

    def dispose(self) -> None:
        """Breaks the barrier and wakes all waiters."""
        if self._disposed:
            return
        self._disposed = True
        self._controller = None  # Clear controller reference
        with self._cond:
            self._break_barrier_locked()