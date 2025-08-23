import threading, ulid, time
from typing import Callable, Optional, Dict, Any, Union
from thread_factory.utilities.interfaces.disposable import IDisposable
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.utilities.coordination.package import Pack

class ClockBarrier(IDisposable):
    """
    A reusable, generation-counted barrier that releases threads once:

    1. `threshold` threads call `wait` within the same generation.
    2. A global timeout elapses since the first thread's arrival.

    Unlike Python’s built-in `threading.Barrier`, this implementation uses a global timeout shared by all threads,
    preventing late arrivals from extending the wait time.

    Events emitted when:
    - `BARRIER_PASSED`: Threshold is met.
    - `BARRIER_BROKEN`: Timeout occurs or barrier is disposed.

    Attributes:
        id (str): Unique identifier (ULID) for this barrier instance.
        threshold (int): Number of threads required to release the barrier.
        timeout (float): Global timeout (seconds) from the first arrival.
        on_broken (Optional[Callable]): Callback triggered when the barrier is broken.
        controller (Optional[Controller]): Controller instance to register and notify.
    """
    __slots__ = IDisposable.__slots__ + [
        "_threshold", "_timeout", "_on_broken",
        "_lock", "_cond",
        "_count", "_start_time", "_broken", "_generation", "_id",
        "_controller"
    ]
    def __init__(
        self,
        threshold: int,
        timeout: float = 0.01,
        on_broken: Optional[Union[Callable[..., None], Pack]] = None,
        controller: Optional["Controller"] = None,
    ):
        """
        Initializes the ClockBarrier instance.

        Args:
            threshold (int): Number of threads required to trip the barrier. Must be ≥ 1.
            timeout (float): Global timeout in seconds from the first thread arrival to the deadline. Must be > 0.
            on_broken (Optional[Union[Callable[..., None], Pack]]): Optional callback invoked after the barrier breaks (timeout or dispose).
            controller (Optional["Controller"]): Optional controller instance to register the barrier and emit events.

        Raises:
            ValueError: If threshold < 1 or timeout <= 0.
        """

        super().__init__()

        if threshold < 1:
            raise ValueError("ClockBarrier requires at least one party.")
        if timeout <= 0:
            raise ValueError("ClockBarrier timeout must be > 0.")

        # Public identity
        self._id: str = str(ulid.ULID())

        # Configuration
        self._threshold: int = threshold
        self._timeout: float = timeout
        self._on_broken: Union[Callable[..., None], Pack] = Pack.bundle(on_broken) if on_broken else None
        self._controller: 'Controller'  = controller

        # Synchronisation primitives
        self._lock: threading.RLock = threading.RLock()
        self._cond: threading.Condition = threading.Condition(self._lock)

        # Runtime state
        self._count: int = 0              # threads currently waiting
        self._start_time: Optional[float] = None           # monotonic() timestamp
        self._broken: bool = False
        self._generation: int = 0              # increments on every reset/pass

        # Controller registration (best-effort)
        if self._controller:
            try:
                self._controller.register(self)
            except Exception:
                pass

    def dispose(self) -> None:
        """
        Dispose of the ClockBarrier, marking it as disposed and breaking the barrier permanently.
        Once disposed, the barrier can no longer be used, and any waiting threads will raise a `BrokenBarrierError`.

        Notes:
            After disposal, the barrier is no longer usable. Calls to `wait()` will raise `BrokenBarrierError`.
            The controller reference is cleared before emitting events to avoid cascading notifications during shutdown.
        """
        if self._disposed:
            return

        self._disposed  = True
        with self._cond:
            self._break_barrier_locked()
            self._cond.notify_all()  # Wake all waiting threads

        if self._controller:
            self._controller.notify(self.id, "DISPOSED")
        if self._controller and hasattr(self._controller, 'unregister'):
            try:
                self._controller.unregister(self.id)
            except Exception:
                pass
            self._controller = None
        self._on_broken = None

    def __enter__(self):
        """
        Allows the barrier to be used as a context manager for lifecycle scoping (does not auto-wait).
        Typical pattern:

        Returns:
        ClockBarrier: Returns self for context management.
        """
        return self

    def __exit__(self, exc_type, exc, tb):
        """
        Ensures a clean teardown when exiting a context manager block.

        If the barrier is already disposed or broken, this method is a no-op.
        Otherwise, it calls `dispose()` to clean up resources.

        See Also:
            dispose
        """
        self.dispose()

    @property
    def id(self) -> str:
        """
        Returns the unique ULID that identifies this barrier instance.

        Returns:
            str: The unique identifier of the barrier.
        """
        return self._id

    def _get_object_details(self) -> ConcurrentDict[str, Any]:
        """
        Provides the metadata for the barrier, used by the controller for dynamic interaction.

        Returns:
            dict: A dictionary with the barrier's name and commands available for the controller to invoke.
        """
        return ConcurrentDict({
            "name": "clock_barrier",
            "commands": ConcurrentDict({
                "reset":             self.reset,
                "is_broken":         self.is_broken,
                "get_waiting_count": self.get_waiting_count,
            }),
        })

    def release(self) -> None:
        """
        Forcefully breaks the barrier for the current generation, releasing all
        currently waiting threads.

        Each waiting thread will raise a `threading.BrokenBarrierError`.
        This is useful for administrative shutdown or error handling when you
        need to unblock waiters without disposing the entire barrier.

        This operation is idempotent; calling it on an already broken or
        disposed barrier has no effect.
        """
        with self._cond:
            if self._broken or self._disposed:
                return

            # Use the existing internal helper to perform the break logic.
            self._break_barrier_locked()

    def is_broken(self) -> bool:
        """
        Returns `True` if the **current generation** has entered a
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

    def reset(self) -> None:
        """
        Manually reset the barrier **after** it has either passed or broken,
        allowing it to be reused by subsequent cohorts.

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
        self._broken     = False
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
            except Exception:
                pass