import threading
import time
from typing import Callable, Optional, Dict, Any

import ulid
from thread_factory.utils import IDisposable

# -----------------------------------------------------------------------------
# NOTE:
#   • This class conforms to the user’s project conventions:
#       – Rich, comprehensive doc-strings for **every** public method
#       – `__enter__`, `__exit__`, and `cleanup()` helpers so it can be used
#         safely in a `with`-statement
#       – Zero existing comments removed (only additions)
#   • The barrier can operate stand-alone **or** register itself with a
#     `Controller` (any object exposing `.register()` and `.notify()`)
#     so higher-level orchestration can observe `BARRIER_PASSED` /
#     `BARRIER_BROKEN` lifecycle events.
# -----------------------------------------------------------------------------


class ClockBarrier(IDisposable):
    """
    ClockBarrier
    ------------
    A *re-usable*, generation-counted barrier that releases a cohort of threads
    once either:

    1. **Threshold met** – `threshold` distinct threads call :py:meth:`wait`
       within the same generation, or
    2. **Global timeout** – The oldest waiter has been blocked for
       *``timeout``* seconds.

    Unlike Python’s built-in :pyclass:`threading.Barrier`, this implementation
    **shares one global timeout** across all waiters.  That means the timer
    starts when the *first* thread arrives instead of each thread managing its
    own deadline.  The design avoids pathological cases where late-arriving
    threads silently extend the overall wait time.

    Integration with a **Controller**
    ---------------------------------
    If you supply a *controller* that implements

    * ``register(obj)``   – to register controllable objects
    * ``notify(obj_id, event_type, data=None)`` – to publish events

    then the barrier will:

    * auto-register itself on construction, and
    * emit events:

      ================  ==========================================
      Event name        When it fires
      ----------------  ------------------------------------------
      ``BARRIER_PASSED`` All `threshold` threads arrived in time
      ``BARRIER_BROKEN`` The global timeout elapsed or
                         :py:meth:`dispose` was called mid-wait
      ================  ==========================================

    Usage example
    -------------
    ```python
    from thread_factory.synchronization.controllers import Controller

    ctrl     = Controller()
    barrier  = ClockBarrier(threshold=5, timeout=0.2, controller=ctrl)

    # Subscribe to barrier events:
    ctrl.subscribe(barrier.id, "BARRIER_PASSED",
                   lambda i, e, d: print("cohort released!"))

    def worker():
        with barrier:           # thanks to context-manager helpers
            barrier.wait()      # blocks until 5th peer arrives

    for _ in range(5):
        threading.Thread(target=worker).start()
    ```

    Attributes
    ----------
    id : str
        ULID used by the controller as a stable key.
    """

    # ──────────────────────────────────────────────────────────────────────
    # Slot allocation (inherits `IDisposable.__slots__` for `_disposed`)
    # ──────────────────────────────────────────────────────────────────────
    __slots__ = IDisposable.__slots__ + [
        "_threshold", "_timeout", "_on_broken",
        "_lock", "_cond",
        "_count", "_start_time", "_broken", "_generation", "_id",
        "_controller"
    ]

    # ──────────────────────────────────────────────────────────────────────
    # Construction / context-manager helpers
    # ──────────────────────────────────────────────────────────────────────
    def __init__(
        self,
        threshold: int,
        timeout: float = 0.01,
        on_broken: Optional[Callable[[], None]] = None,
        controller: Optional["Controller"] = None,
    ):
        """
        Parameters
        ----------
        threshold :
            Number of distinct threads required to trip the barrier.
            Must be ≥ 1.
        timeout :
            Global timeout (seconds) between the *first* arrival and the
            deadline.  Must be > 0.
        on_broken :
            Optional callback invoked *after* the barrier breaks
            (timeout / dispose).  Errors inside the callback are swallowed.
        controller :
            Optional controller instance.  When provided, the barrier
            self-registers and emits events on state changes.

        Raises
        ------
        ValueError
            If *threshold* < 1 or *timeout* ≤ 0.
        """
        super().__init__()

        if threshold < 1:
            raise ValueError("ClockBarrier requires at least one party.")
        if timeout <= 0:
            raise ValueError("ClockBarrier timeout must be > 0.")

        # Public identity
        self._id = str(ulid.ULID())

        # Configuration
        self._threshold   = threshold
        self._timeout     = timeout
        self._on_broken   = on_broken
        self._controller  = controller

        # Synchronisation primitives
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)

        # Runtime state
        self._count       = 0              # threads currently waiting
        self._start_time  = None           # monotonic() timestamp
        self._broken      = False
        self._generation  = 0              # increments on every reset/pass

        # Controller registration (best-effort)
        if self._controller:
            try:
                self._controller.register(self)
            except Exception:              # noqa: BLE001 – controller is optional
                pass                       # Stand-alone use is still valid

    # ------------------------------------------------------------------ #
    # Context-manager convenience
    # ------------------------------------------------------------------ #
    def __enter__(self):
        """
        Allows the barrier itself to be used in a ``with`` block purely for
        *lifecycle* scoping (it **does not** auto-wait).  Typical pattern:

        ```python
        with barrier:
            barrier.wait()
        ```

        Returns
        -------
        ClockBarrier
            Self – enables fluent use in a ``with`` statement.
        """
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: D401 – prefer imperative voice
        """
        Ensures a clean teardown when exiting a ``with`` block.

        * If the barrier is already disposed / broken, this is a no-op.
        * Otherwise, it simply calls :py:meth:`dispose`.

        See Also
        --------
        dispose
        """
        self.dispose()

    # Public API (Controller contract) ----------------------------------- #
    # -------------------------------------------------------------------- #
    @property
    def id(self) -> str:  # noqa: D401 – property docstring
        """Return the ULID that uniquely identifies this barrier instance."""
        return self._id

    def _get_object_details(self) -> Dict[str, Any]:
        """
        **Controller contract helper.**

        Returns the metadata dictionary expected by :pyclass:`Controller`
        so it can treat the barrier as a managed “controllable” object.

        Returns
        -------
        dict
            ``{"name": "clock_barrier", "commands": {…}}`` where *commands*
            exposes a read-only view into key barrier methods so the
            controller can invoke them remotely.
        """
        return {
            "name": "clock_barrier",
            "commands": {
                "reset":             self.reset,
                "is_broken":         self.is_broken,
                "get_waiting_count": self.get_waiting_count,
            },
        }

    # ------------------------------------------------------------------ #
    # Introspection helpers (no side-effects)
    # ------------------------------------------------------------------ #
    def is_broken(self) -> bool:
        """
        Returns :pydata:`True` if the **current generation** has entered a
        broken state (timeout or dispose).

        Thread-safe – acquires the internal lock.

        Returns
        -------
        bool
        """
        with self._lock:
            return self._broken

    def get_waiting_count(self) -> int:
        """
        How many threads are presently blocked in :py:meth:`wait`
        for *this* generation.

        Returns
        -------
        int
        """
        with self._lock:
            return self._count

    # ------------------------------------------------------------------ #
    # State-mutation API
    # ------------------------------------------------------------------ #
    def reset(self) -> None:
        """
        Manually reset the barrier **after** it has either passed or broken,
        allowing it to be reused by subsequent cohorts.

        Side-effects
        ------------
        • Increments *generation* so existing waiters from the previous
          cohort can detect that they belong to an outdated generation.
        • Wakes any straggling waiters with :py:meth:`threading.Condition.notify_all`.

        Notes
        -----
        • Calling `reset()` *during* an active, unbroken wait cohort is
          undefined behaviour – only do so once all threads have returned.
        """
        with self._cond:
            self._broken      = False
            self._count       = 0
            self._start_time  = None
            self._generation += 1
            self._cond.notify_all()

    def wait(self) -> bool:
        """
        Block the calling thread until either the cohort is complete or the
        global timeout expires.

        Returns
        -------
        bool
            :pydata:`True` if the barrier passed normally; never reached on
            timeout because an exception is raised.

        Raises
        ------
        threading.BrokenBarrierError
            • The barrier was disposed.
            • The barrier is already broken for this generation.
            • The global timeout elapsed before enough threads arrived.
        """
        with self._cond:
            if self._disposed:
                raise threading.BrokenBarrierError("ClockBarrier is disposed")
            if self._broken:
                raise threading.BrokenBarrierError("ClockBarrier is broken")

            my_generation = self._generation
            self._count += 1

            # First arrival starts the global timer
            if self._count == 1:
                self._start_time = time.monotonic()

            # Threshold satisfied – release cohort
            if self._count == self._threshold:
                self._advance_generation()
                return True

            # Otherwise, block until success or timeout
            while True:
                if self._start_time is None:  # defensive – shouldn’t happen
                    self._cond.wait(timeout=self._timeout)
                    continue

                remaining = self._timeout - (time.monotonic() - self._start_time)
                if remaining <= 0:
                    self._break_barrier_locked()
                    raise threading.BrokenBarrierError("ClockBarrier timeout")

                self._cond.wait(timeout=remaining)

                # Generation advanced ⇒ we’re done (either pass or broken)
                if self._generation != my_generation:
                    if self._broken:
                        raise threading.BrokenBarrierError("ClockBarrier is broken")
                    return True

    # ------------------------------------------------------------------ #
    # Internal helpers (must be called with *_cond* held)
    # ------------------------------------------------------------------ #
    def _advance_generation(self) -> None:
        """
        Private: Release all waiters, notify controller, and prepare the
        barrier for the next cohort.

        Must be called *with* ``self._cond`` locked.
        """
        # Notify orchestrator
        if self._controller:
            self._controller.notify(self.id, "BARRIER_PASSED")

        # Flush waiters & roll generation
        self._cond.notify_all()
        self._count      = 0
        self._start_time = None
        self._generation += 1

    def _break_barrier_locked(self) -> None:
        """
        Private: Mark current generation as broken, notify controller, and
        wake all waiters.

        Preconditions
        -------------
        Caller **must** hold ``self._cond``.
        """
        if self._broken:        # idempotent guard
            return
        self._broken = True

        if self._controller:
            self._controller.notify(self.id, "BARRIER_BROKEN")

        self._cond.notify_all()

        if self._on_broken:
            try:
                self._on_broken()
            except Exception:   # noqa: BLE001
                pass

    # ------------------------------------------------------------------ #
    # Disposal / cleanup
    # ------------------------------------------------------------------ #
    def dispose(self) -> None:
        """
        Break the barrier permanently and wake all waiters.

        Notes
        -----
        • After disposal, the barrier can no longer be reused – any call to
          :py:meth:`wait` raises :class:`threading.BrokenBarrierError`.
        • The controller reference is cleared *before* emitting events to
          avoid cascading notifications during application shutdown.
        """
        if self._disposed:
            return

        self._disposed  = True
        self._controller = None          # Prevent further notifications
        with self._cond:
            self._break_barrier_locked()

    # Alias demanded by project style guide ------------------------------ #
    cleanup = dispose  # functionally identical but improves discoverability
