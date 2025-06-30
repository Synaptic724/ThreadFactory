import threading
import ulid
from typing import Callable, Optional
from thread_factory.primitives.signal_condition import SignalCondition
from thread_factory.utils.interfaces.disposable import IDisposable


class SignalLatch(IDisposable):
    """
    SignalLatch
    -----------
    A blocking latch that *signals* an external observer **before** each thread
    actually blocks. Internally, it leverages `SignalCondition` for its
    wait/notify mechanisms but offers a simplified API:

    -   ``wait()``: Fires configured callbacks/notifications, then blocks the calling thread.
    -   ``open()``: Releases all currently waiting threads and keeps the latch
        permanently open.
    -   ``reset()``: Closes the latch, causing subsequent ``wait()`` calls to block.
    -   ``is_open()``: Checks if the latch is currently open.

    Parameters
    ----------
    signal_callback : Callable[[str, bool], None], optional
        A generic function invoked as ``signal_callback(self.id, self.signal_value)``
        right before a thread is suspended in ``wait()``. This is a general-purpose
        notification mechanism. Defaults to ``None``.
    signal_value : bool
        The boolean value forwarded with every invocation of ``signal_callback``
        and exposed via the ``signal_value`` property for direct controller inspection.
        Defaults to ``True``.
    cond : SignalCondition, optional
        An existing ``SignalCondition`` instance to use internally. If ``None``,
        a new one will be created.
    controller : object, optional
        An optional controller object that will be directly notified by the latch.
        If the controller has a ``register_latch(latch: 'SignalLatch')`` method,
        it will be called during initialization, allowing the controller to store
        references to the latch's control methods (e.g., open, reset).
        The controller should also have a ``notify_controller(latch: 'SignalLatch')``
        method, which will be called just before a thread blocks in `wait()`.
    """

    __slots__ = [
        "_id",
        "_cond",
        "_open",
        "_signal_callback",
        "_signal_value",
        "_lock",
        "_disposed",
        "_controller",
    ]

    def __init__(
            self,
            signal_callback: Optional[Callable[[str, bool], None]] = None,
            signal_value: bool = True,
            cond: Optional[SignalCondition] = None,
            controller: Optional[object] = None,
    ):
        super().__init__()
        self._id: str = str(ulid.ULID())
        self._cond: SignalCondition = cond or SignalCondition()
        self._open: bool = False
        self._signal_callback = signal_callback
        self._signal_value = signal_value
        self._lock = threading.RLock()
        self._disposed = False
        self._controller = controller

        # Register this latch instance with the controller, if provided.
        if self._controller:
            try:
                # The controller is expected to have a method to register the latch.
                # This is a cleaner Inversion of Control pattern.
                self._controller.register(self)
            except AttributeError:
                # Silently fail if the controller does not support registration.
                # A warning could be logged here for debugging.
                # print(f"Warning: Controller {self._controller} does not have 'register_latch(latch)' method.")
                pass
            except Exception as e:
                # Log any other exceptions during registration.
                # print(f"Error registering latch with controller {self._id}: {e}")
                pass

    @property
    def id(self) -> str:
        """
        Returns the unique ULID identifier for this latch.
        """
        return self._id

    @property
    def signal_value(self) -> bool:
        """
        Returns the boolean value that is passed with the signal callback.
        """
        return self._signal_value

    def wait(self, timeout: float | None = None) -> bool:
        """
        Fires the generic ``signal_callback`` (if provided) and notifies the
        direct ``controller`` (if provided), then blocks until this latch is opened.

        Returns `True` if the latch was opened, `False` if the wait timed out.
        """
        if self._disposed:
            raise RuntimeError("SignalLatch has been disposed")

        # Before waiting, check if the latch is already open.
        # This check is crucial and must be done before signaling.
        with self._cond:
            if self._open:
                return True

        # If not open, proceed with signaling.
        # Path 1: Invoke the generic signal callback.
        if self._signal_callback:
            try:
                self._signal_callback(self._id, self._signal_value)
            except Exception:
                # Log or handle exceptions from user code silently.
                pass

        # Path 2: Invoke the direct controller's specific method.
        if self._controller:
            try:
                # Pass the latch instance itself to the controller for state inspection.
                self._controller.notify_controller(self)
            except AttributeError:
                # Silently fail if the controller doesn't have the method.
                pass
            except Exception:
                # Log or handle exceptions from user code silently.
                pass

        # Acquire the internal condition lock and proceed to block.
        with self._cond:
            # Re-check the _open flag in case it was changed between the first
            # check and acquiring the lock. This is a critical double-check.
            if self._open:
                return True
            return self._cond.wait_for(lambda: self._open, timeout=timeout)

    def open(self):
        """
        Opens the latch and permanently releases all waiting threads.
        This method is idempotent.
        """
        if self._disposed:
            return
        with self._cond:
            if self._open:
                return
            self._open = True
            self._cond.notify_all()

    def reset(self):
        """
        Resets the latch to the *closed* state, allowing it to be reused.
        """
        if self._disposed:
            raise RuntimeError("Cannot reset a disposed SignalLatch")
        with self._cond:
            self._open = False

    def is_open(self) -> bool:
        """
        Checks if the latch is currently in the open state.
        """
        # No lock needed for a simple boolean read if atomicity is guaranteed.
        # However, using the lock ensures the most up-to-date state is read
        # relative to other operations.
        with self._cond:
            return self._open

    def dispose(self):
        """
        Disposes the latch, releasing all blocked threads and preventing
        further use. This action is irreversible.
        """
        if self._disposed:
            return

        with self._lock:  # Outer lock for the dispose process
            if self._disposed:
                return
            self._disposed = True

        with self._cond:
            # Mark as open to ensure all waiters pass immediately.
            self._open = True
            self._cond.notify_all()

        # Dispose the internal SignalCondition, cleaning up its resources.
        if hasattr(self._cond, 'dispose'):
            self._cond.dispose()

        # Clear references to aid garbage collection and prevent accidental use.
        self._signal_callback = None
        self._signal_value = None
        self._controller = None