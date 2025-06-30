import threading
import ulid
from typing import Callable, Optional, Any, Dict
from thread_factory.synchronization.primitives.transit_condition import TransitCondition
from thread_factory.utils.interfaces.disposable import IDisposable

class SignalLatch(IDisposable):
    """
    A blocking latch that can signal an external observer before blocking.
    It is designed to be managed by an optional, generic Controller.

    Args:
        signal_callback: A function to call with the latch's ID just
                         before a thread blocks. Defaults to None.
        cond: An optional, existing SignalCondition to use internally.
        controller: An optional Controller instance to register with. If provided,
                    you should also pass a controller method (like
                    controller.on_wait_starting) as the signal_callback.
    """
    def __init__(
        self,
        signal_callback: Optional[Callable[[str], None]] = None,
        cond: Optional[TransitCondition] = None,
        controller: Optional['Controller'] = None,
    ):
        """
        Initializes the SignalLatch.


        """
        super().__init__()
        self._id: str = str(ulid.ULID())
        self._cond: TransitCondition = cond or TransitCondition()
        self._open: bool = False
        self._signal_callback = signal_callback
        self._lock = threading.RLock()
        self._controller = controller

        # Automatically register with the controller upon creation.
        if self._controller:
            try:
                self._controller.register(self)
            except Exception as e:
                pass


    @property
    def id(self) -> str:
        """Returns the unique ULID identifier for this latch."""
        return self._id

    def _get_object_details(self) -> Dict[str, Any]:
        """
        Returns the metadata and commands for this latch, fulfilling the
        controller's integration contract.
        """
        return {
            'name': 'latch',
            'commands': {
                'open': self.open,
                'reset': self.reset,
                'is_open': self.is_open,
                'dispose': self.dispose,
            }
        }

    # --- Core Latch Functionality ---

    def wait(self, timeout: Optional[float] = None) -> bool:
        """
        Blocks until this latch is opened. Fires a signal_callback with the
        latch's ID if provided, just before blocking.

        Returns:
            True if the latch was opened, False if the wait timed out.
        """
        if self._disposed:
            raise RuntimeError(f"SignalLatch '{self.id}' has been disposed.")

        # First, check if the latch is already open to avoid unnecessary signaling.
        with self._cond:
            if self._open:
                return True

        # If we are about to block, fire the callback.
        if self._signal_callback:
            try:
                # The callback signature is now simpler.
                self._signal_callback(self._id)
            except Exception:
                # Swallow exceptions from user callbacks to prevent crashing.
                pass

        # Now, enter the wait state.
        with self._cond:
            # Re-check in case the latch was opened between the first check and now.
            # This handles a classic race condition.
            return self._cond.wait_for(lambda: self._open, timeout=timeout)

    def open(self):
        """Opens the latch and releases all waiting threads. This is idempotent."""
        if self._disposed:
            return
        with self._cond:
            if not self._open:
                self._open = True
                self._cond.notify_all()

    def reset(self):
        """Resets the latch to the closed state, allowing it to be reused."""
        if self._disposed:
            raise RuntimeError(f"Cannot reset a disposed SignalLatch ('{self.id}').")
        with self._cond:
            self._open = False

    def is_open(self) -> bool:
        """Checks if the latch is currently in the open state."""
        return self._open

    def dispose(self):
        """
        Disposes the latch, releasing all blocked threads and preventing
        further use. This action is irreversible.
        """
        if self._disposed:
            return
        with self._lock:
            if self._disposed:
                return
            self._disposed = True

        with self._cond:
            self._open = True
            self._cond.notify_all()

        self._cond.dispose()
        self._signal_callback = None
        self._controller = None