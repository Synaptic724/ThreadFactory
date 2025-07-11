import threading
import ulid
from typing import Callable, Optional, Any, Dict, Union
from thread_factory.synchronization.controllers.signal_controller import SignalController
from thread_factory.synchronization.primitives.transit_condition import TransitCondition
from thread_factory.utilities.interfaces.disposable import IDisposable
from thread_factory.utilities.coordination.package import Pack
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict


class SignalLatch(IDisposable):
    """
    SignalLatch or SignalGate
    ===========
    A *one-shot* (but reusable) latch/gate that blocks threads until it is explicitly
    opened.  Just before a thread goes to sleep it can “signal” an external
    observer — typically a **Controller** — so orchestration layers know the
    thread is about to wait.

    Integration with a Controller
    ------------------------------
    If you supply a controller that exposes the usual

    * ``register(obj)`` and
    * ``notify(obj_id, event_type, data=None)``

    methods, the latch will:

    • **Self-register** on construction.
    • Fire *optional* notifications from *your* `signal_callback`.
      The recommended pattern is to pass
      `controller.on_wait_starting` as that callback.

    Recommended event taxonomy
    ~~~~~~~~~~~~~~~~~~~~~~~~~~
    The latch itself does **not** hard-code calls to `controller.notify()`
    (it keeps concerns separated), but a common scheme is:

    ================  ==========================================
    Event             Typical emitter & semantics
    ----------------  ------------------------------------------
    ``WAIT_STARTING`` `signal_callback` just before blocking
    ``LATCH_OPENED``  Your application code right after `.open()`
    ``LATCH_RESET``   Your code after `.reset()`
    ================  ==========================================

    Context-manager semantics
    -------------------------
    Each instance implements ``__enter__`` / ``__exit__`` so you can:

    ```python
    with latch:
        if not latch.wait(timeout=2.0):
            raise TimeoutError("Yo, still closed after 2 s")
    ```
    """

    # ──────────────────────────────────────────────────────────────────
    # Slots (inherits `_disposed` from IDisposable)
    # ──────────────────────────────────────────────────────────────────
    __slots__ = IDisposable.__slots__ + [
        "_id", "_cond", "_open",
        "_signal_callback", "_lock", "_controller"
    ]

    # ──────────────────────────────────────────────────────────────────
    # Construction
    # ──────────────────────────────────────────────────────────────────
    def __init__(
        self,
        signal_callback: Optional[Union[Callable[..., None], Pack]] = None,
        cond: Optional[TransitCondition] = None,
        controller: Optional["Controller"] = None,
    ):
        """
        Parameters
        ----------
        signal_callback :
            Callable invoked **once per waiting thread** *just before* it blocks.
            Receives this latch's ULID string.  Use it to update diagnostics
            or call controller helpers (e.g., ``controller.on_wait_starting``).
        cond :
            An existing :class:`TransitCondition` instance to reuse; if *None*
            a fresh one is created.
        controller :
            Optional orchestration controller.  When provided the latch
            self-registers so remote code can invoke its commands.

        Notes
        -----
        Exceptions raised inside *signal_callback* are swallowed to guarantee
        that latched threads still block cleanly.
        """
        super().__init__()

        self._id: str = str(ulid.ULID())
        self._cond: TransitCondition = cond or TransitCondition()
        self._open: bool = False
        self._signal_callback: Union[Callable[..., None], Pack] = signal_callback if signal_callback is None else Pack.bundle(signal_callback)
        self._lock = threading.RLock()
        self._controller: 'Controller' = controller

        # Auto-register with controller (best-effort)
        if self._controller:
            try:
                self._controller.register(self)
            except Exception:
                pass

    def dispose(self) -> None:
        """
        Release all blocked threads **permanently**; further operations raise.

        Notes
        -----
        • Once disposed, :py:meth:`open` and :py:meth:`reset` are ignored.
        • The internal :class:`TransitCondition` is also disposed to free
          resources.
        """
        if self._disposed:
            return
        with self._lock:
            if self._disposed:
                return
            self._disposed = True

        # Wake any waiters immediately
        with self._cond:
            self._open = True
            self._cond.notify_all()

        # Tear down internals
        self._cond.dispose()
        self._signal_callback = None
        if self._controller:
            try:
                self._controller.notify(self.id, "DISPOSED")
                if hasattr(self._controller, 'unregister'):
                    self._controller.unregister(self.id)
            except Exception:
                # It's good practice to never let cleanup fail silently
                # In a real app, you might log this error.
                pass
            finally:
                # Ensure the reference is cleared even if notify/unregister fails
                self._controller = None


    # ──────────────────────────────────────────────────────────────────
    # Controller contract helpers
    # ──────────────────────────────────────────────────────────────────
    def set_external_controller(self, controller: 'SignalController'):
        """
        Sets an external SignalController to manage this CommandCenter.
        This allows the CommandCenter to be controlled remotely.
        """
        if not isinstance(controller, SignalController):
            raise TypeError("Expected a SignalController instance.")
        self._controller = controller
        if self._controller:
            try:
                self._controller.register(self)
            except Exception:
                pass

    @property
    def id(self) -> str:  # noqa: D401
        """
        ULID that uniquely identifies this latch.
        """
        return self._id

    def _get_object_details(self) -> ConcurrentDict[str, Any]:
        """
        Metadata dictionary expected by the project’s :class:`Controller`.

        Returns
        -------
        dict
            Contains a human-readable *name* and a *commands* map exposing
            safe operations that the controller may invoke.
        """
        return ConcurrentDict({
            "name": "latch",
            "commands": ConcurrentDict({
                "open":   self.open,
                "reset":  self.reset,
                "is_open": self.is_open,
                "dispose": self.dispose,
            }),
        })

    # ──────────────────────────────────────────────────────────────────
    # Context-manager & cleanup helpers
    # ──────────────────────────────────────────────────────────────────
    def __enter__(self):
        """Enable ``with SignalLatch() as latch: ...`` syntax."""
        return self

    def __exit__(self, exc_type, exc, tb):
        """Ensure the latch is disposed when exiting a ``with`` block."""
        self.dispose()

    #cleanup = dispose  # alias to satisfy user style guide

    # ──────────────────────────────────────────────────────────────────
    # Core latch operations
    # ──────────────────────────────────────────────────────────────────
    def closed(self, timeout: Optional[float] = None) -> bool:
        """
        Block until :py:meth:`open` is called or *timeout* elapses.

        Parameters
        ----------
        timeout :
            Maximum seconds to wait; *None* means wait indefinitely.

        Returns
        -------
        bool
            • **True**  – Latch opened.
            • **False** – Timed out.

        Raises
        ------
        RuntimeError
            If the latch has already been disposed.
        """
        if self._disposed:
            raise RuntimeError(f"SignalLatch '{self.id}' has been disposed.")

        # Fast-path: already open → no signalling required.
        with self._cond:
            if self._open:
                return True

        # Fire external callback (controller hook, metrics, etc.)
        if self._signal_callback:
            try:
                self._signal_callback(self._id)
            except Exception:       # noqa: BLE001 – never let callback kill us
                pass

        # Block until opened or timeout.
        with self._cond:
            return self._cond.wait_for(lambda: self._open, timeout=timeout)

    def open(self) -> None:
        """
        Idempotently open the latch and wake **all** waiting threads.

        If the latch is already open or disposed, this is a no-op.
        """
        if self._disposed:
            return
        with self._cond:
            if not self._open:
                self._open = True
                self._cond.notify_all()

    def reset(self) -> None:
        """
        Close the latch again so it can be reused for a new cohort.

        Raises
        ------
        RuntimeError
            If you attempt to reset a disposed latch.
        """
        if self._disposed:
            raise RuntimeError(f"Cannot reset a disposed SignalLatch ('{self.id}').")
        with self._cond:
            self._open = False

    def is_open(self) -> bool:
        """
        Check whether the latch is currently open.

        Returns
        -------
        bool
        """
        return self._open


SignalGate = SignalLatch  # Alias for backward compatibility