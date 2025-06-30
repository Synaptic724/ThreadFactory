import threading
from typing import Optional, Callable, Any, Dict
import ulid

from thread_factory.utils import IDisposable
from thread_factory.synchronization.primitives.transit_condition import TransitCondition


# Assuming your Controller class is available for type hinting
# from thread_factory.synchronization.controllers.controller import Controller


class TransitBarrier(IDisposable):
    """
    TransitBarrier
    ------------------
    A reusable, controllable barrier that executes a `transit` action.
    When in manual mode and managed by a Controller, it signals the
    Controller upon reaching its threshold and waits for a command.
    """
    __slots__ = IDisposable.__slots__ + [
        "_threshold", "_transit", "_reusable", "_manual_release",
        "_lock", "_condition", "_count", "_released", "_transit_fired",
        "_id", "_controller"
    ]

    def __init__(
            self,
            threshold: int,
            transit: Optional[Callable[[], None]] = None,
            reusable: bool = False,
            manual_release: bool = False,
            controller: Optional['Controller'] = None
    ):
        super().__init__()
        if threshold <= 0:
            raise ValueError("Threshold must be greater than 0")

        self._id = str(ulid.ULID())
        self._threshold = threshold
        self._transit = transit
        self._reusable = reusable
        self._manual_release = manual_release

        self._lock = threading.RLock()
        self._condition = TransitCondition(self._lock)
        self._count = 0
        self._released = False
        self._transit_fired = False

        self._controller = controller
        if self._controller:
            try:
                self._controller.register(self)
            except Exception:
                pass

    @property
    def id(self) -> str:
        """The unique identifier for this component."""
        return self._id

    def _get_object_details(self) -> Dict[str, Any]:
        """Provides the commands and metadata for the Controller."""
        return {
            'name': 'transit_barrier',
            'commands': {
                'release': self.release,
                'reset': self.reset,
                'is_spent': self.is_spent,
                'get_waiter_count': self._condition.find_waiter_count,
                'release_with_action': self.release_with_action,
                # Re-added for production compatibility
                'notify_all_override': self.notify_all_override,
            }
        }

    def release_with_action(self, callback: Optional[Callable[[], None]] = None) -> None:
        """
        Forcibly releases all waiting threads, executing an optional,
        one-time callback that overrides the default transit action.
        """
        with self._lock:
            if self._disposed or self._released:
                return

            self._released = True
            final_action = callback or self._transit
            self._condition.notify_all(final_action)

    # --- Method re-added for production compatibility ---
    def notify_all_override(self) -> None:
        """
        Immediately releases all waiting threads regardless of threshold,
        using the default transit action.
        """
        with self._lock:
            if self._disposed or self._released:
                return
            self._released = True
            # The _transit_fired check ensures the main transit action
            # isn't queued multiple times unnecessarily.
            if not self._transit_fired:
                self._transit_fired = True
                self._condition.notify_all(self._transit)
            else:
                self._condition.notify_all()

    def release(self) -> None:
        """
        Manually releases threads using the default transit action,
        if in manual_release mode and the threshold is met.
        """
        with self._condition:
            if self._disposed:
                return
            if self._manual_release and self._count >= self._threshold and not self._released:
                self._released = True
                if not self._transit_fired:
                    self._transit_fired = True
                    self._condition.notify_all(self._transit)
                else:
                    self._condition.notify_all()

    # In your TransitBarrier class

    def wait(self, timeout: Optional[float] = None) -> bool:
        """
        Waits at the barrier. In manual mode, it notifies the controller
        when the threshold is met and continues waiting for a command.
        """
        if self.is_spent():
            return False

        with self._condition:
            if self._released:
                return True

            if self._disposed:
                return False

            self._count += 1

            if self._count == self._threshold:
                if self._manual_release:
                    if self._controller:
                        self._controller.notify(self.id, "THRESHOLD_MET")
                else:
                    # This is the auto-release path
                    if not self._released:
                        self._released = True
                        final_action = None
                        if not self._transit_fired:
                            self._transit_fired = True
                            final_action = self._transit

                        # Notify all other waiting threads
                        self._condition.notify_all(final_action)

                        # FIX: The triggering thread must also execute the action
                        if final_action:
                            try:
                                final_action()
                            except Exception:
                                # Suppress exceptions in callbacks to not crash the barrier
                                pass

                    return True

            # All other threads wait here
            released = self._condition.wait(timeout=timeout)

            if self._disposed:
                return False

            if released and self._reusable:
                self._count -= 1
                if self._count == 0:
                    self._released = False
                    self._transit_fired = False

            return released

    def dispose(self):
        """Disposes the barrier and unblocks all threads."""
        if self._disposed:
            return
        self._disposed = True
        with self._condition:
            self._condition.notify_all()
        self._controller = None

    def is_spent(self) -> bool:
        """Returns True if the barrier is not reusable and has already been released."""
        return self._released and not self._reusable

    def reset(self) -> None:
        """Resets the barrier for reuse, if it is reusable."""
        with self._lock:
            self._count = 0
            self._released = False
            self._transit_fired = False