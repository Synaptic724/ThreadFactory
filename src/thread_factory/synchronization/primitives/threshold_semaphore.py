import threading
from typing import Optional, Callable, Any, Dict
import ulid
from thread_factory.utils import IDisposable


# Assuming Controller is in a file that can be imported
# from thread_factory.controller import Controller


class ThresholdSemaphore(IDisposable):
    """
    ThresholdSemaphore
    ------------------
    A reusable barrier-like semaphore that unblocks all waiting threads once
    a predefined threshold is reached.

    This class can be used standalone or optionally integrated with a Controller
    for centralized management and observation.

    Parameters:
        threshold (int): Number of threads required to trigger release.
        callback (Optional[Callable[[], None]]): Hook for standalone use when threshold is reached.
        reusable (bool): If True, resets after triggering (default: False).
        manual_release (bool): If True, waits after threshold until release() is called.
        controller (Optional[Controller]): An optional Controller instance to register with.
        signal_callback (Optional[Callable[[str], None]]): A function to call with the
            semaphore's ID just before a thread blocks. Typically, this is the
            controller's `on_wait_starting` method.
    """
    __slots__ = IDisposable.__slots__ + [
        "_threshold", "_callback", "_reusable", "_manual_release",
        "_lock", "_condition", "_count", "_released", "_id",
        "_controller", "_signal_callback"
    ]

    def __init__(
            self,
            threshold: int,
            callback: Optional[Callable[[], None]] = None,
            reusable: bool = False,
            manual_release: bool = False,
            controller: Optional['Controller'] = None,
            signal_callback: Optional[Callable[[str], None]] = None
    ):
        super().__init__()
        if threshold <= 0:
            raise ValueError("Threshold must be greater than 0")

        self._id = str(ulid.ULID())
        self._threshold = threshold
        self._callback = callback
        self._reusable = reusable
        self._manual_release = manual_release

        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._count = 0
        self._released = False

        # --- Controller Integration ---
        self._controller = controller
        self._signal_callback = signal_callback

        if self._controller:
            try:
                self._controller.register(self)
            except Exception:
                # Fail silently if registration fails, maintaining standalone functionality.
                pass

    # --- Controller Contract Properties ---

    @property
    def id(self) -> str:
        """Returns the unique ULID identifier for this semaphore."""
        return self._id

    def _get_object_details(self) -> Dict[str, Any]:
        """
        Returns metadata and commands for controller integration.
        """
        return {
            'name': 'threshold_semaphore',
            'commands': {
                'release': self.release,
                'reset': self.reset,
                'set_threshold': self.set_threshold,
                'is_spent': self.is_spent,
                'notify_all_override': self.notify_all_override,
                'dispose': self.dispose
            }
        }

    # --- Core Methods (with integration) ---

    def dispose(self):
        with self._lock:
            if self._disposed:
                return
            self._disposed = True
            # Clean up references
            self._controller = None
            self._signal_callback = None
            self._callback = None

        with self._condition:
            self._condition.notify_all()

    def is_spent(self) -> bool:
        """Returns True if the semaphore has been used and is not reusable."""
        return self._released and not self._reusable

    def notify_all_override(self) -> None:
        """Forcibly releases all waiting threads."""
        with self._condition:
            if self._disposed or self._released:
                return

            self._released = True
            if self._controller:
                self._controller.notify(self.id, "SEMAPHORE_RELEASED")

            if self._reusable:
                self._count = 0

            self._condition.notify_all()

    def release(self) -> None:
        """Manually releases threads when in manual_release mode."""
        with self._condition:
            if self._disposed or self._released:
                return

            # Only release if in manual mode and the threshold has been met
            if self._manual_release and self._count >= self._threshold:
                self._released = True
                if self._controller:
                    self._controller.notify(self.id, "SEMAPHORE_RELEASED")
                self._condition.notify_all()

    def set_threshold(self, new_threshold: int):
        """Dynamically changes the required threshold."""
        if new_threshold <= 0:
            raise ValueError("Threshold must be greater than 0")

        with self._condition:
            if self._disposed: return
            self._threshold = new_threshold

            if self._count >= self._threshold and not self._manual_release and not self._released:
                self._released = True
                if self._controller:
                    self._controller.notify(self.id, "SEMAPHORE_RELEASED")
                self._condition.notify_all()

    def reset(self):
        """Resets the semaphore for a new cycle."""
        with self._condition:
            self._count = 0
            self._released = False

    # In the ThresholdSemaphore class...

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Waits until the threshold is reached and released."""
        if self.is_spent():
            return False  # Corrected from our last session

        with self._condition:
            if self._disposed:
                return False

            self._count += 1

            if self._count == self._threshold:
                if self._callback:
                    try:
                        self._callback()
                    except Exception:
                        pass

                if self._controller:
                    self._controller.notify(self.id, "THRESHOLD_MET")

                if not self._manual_release:
                    self._released = True
                    if self._controller:
                        self._controller.notify(self.id, "SEMAPHORE_RELEASED")
                    self._condition.notify_all()

            if not self._released and self._signal_callback:
                try:
                    self._signal_callback(self.id)
                except Exception:
                    pass

            was_released = self._condition.wait_for(lambda: self._released or self._disposed, timeout=timeout)

            # ---- START: REVISED REUSABLE LOGIC ----
            if was_released and self._reusable:
                # Each thread decrements the counter as it passes the barrier.
                self._count -= 1
                # The very last thread to pass is responsible for resetting the
                # semaphore for the next group.
                if self._count == 0:
                    self._released = False
            # ---- END: REVISED REUSABLE LOGIC ----

            return was_released and not self._disposed