import threading, ulid
from typing import Optional, Callable, Any, Dict, Union

from thread_factory.synchronization import SignalController
from thread_factory.utilities.interfaces.disposable import IDisposable
from thread_factory.synchronization.primitives.transit_condition import TransitCondition
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.utilities.coordination.package import Pack

class TransitBarrier(IDisposable):
    """
    TransitBarrier
    ------------------
    A reusable, controllable barrier that synchronizes threads based on a predefined threshold.
    Once the threshold number of threads has called `wait()`, the barrier releases all waiting threads simultaneously.

    When in manual mode and managed by a Controller, the barrier signals the Controller upon reaching its threshold and
    waits for a command to proceed. The barrier can also trigger a custom action (referred to as `transit`) once the threshold is met.

    Key Features:
    -------------
    • **Threshold-Based Synchronization**: Threads wait until the threshold number of threads have reached the barrier.
    • **Auto-Release or Manual Release**: The barrier can either auto-release threads once the threshold is met or wait for an explicit `release()` call.
    • **Controller Integration**: Supports integration with a Controller for remote management and event broadcasting.
    • **Custom Transit Action**: A custom `transit` action can be executed when the threshold is met, or a one-time action can be provided.
    • **Reusability**: If `reusable=True`, the barrier resets automatically after each complete release cycle.
    • **Timeout Support**: Threads can specify a timeout for waiting at the barrier.

    Parameters:
    -----------
    threshold (int):
        The number of threads required to trigger the release and transit action. Must be greater than 0.
    transit (Optional[Union[Callable[..., None], Pack]]):
        A callable function or a `Pack` containing the action to execute once the threshold is met.
    reusable (bool):
        If `True`, the barrier will reset after the release, making it reusable for subsequent groups of threads. Default is `False`.
    manual_release (bool):
        If `True`, the barrier requires an explicit call to `release()` after the threshold is met. Default is `False` (auto-release).
    controller (Optional['Controller']):
        An optional `Controller` instance for managing the barrier and broadcasting events.

    Notes:
    ------
    - In **manual mode**, threads remain blocked after the threshold is met until the `release()` method is explicitly called.
    - In **auto-release mode**, the barrier will automatically release all waiting threads once the threshold is met.
    - **Reusability** allows the barrier to reset and be reused after a full release cycle, but is ignored when `manual_release=True`.
    """

    __slots__ = IDisposable.__slots__ + [
        "_threshold", "_transit", "_reusable", "_manual_release",
        "_lock", "_condition", "_count", "_released", "_transit_fired",
        "_id", "_controller"
    ]

    # In your TransitBarrier class in transit_barrier.py

    def __init__(
            self,
            threshold: int,
            transit: Optional[Union[Callable[..., None], Pack]] = None,
            reusable: bool = False,
            manual_release: bool = False,
            controller: Optional['SignalController'] = None
    ):
        super().__init__()
        if threshold <= 0:
            raise ValueError("Threshold must be greater than 0")

        self._id = str(ulid.ULID())
        self._threshold: int = threshold
        self._transit: Union[Callable[..., None], Pack] = Pack.bundle(transit) if transit else None
        self._reusable: bool = reusable
        self._manual_release: bool = manual_release

        self._lock: threading.RLock = threading.RLock()
        self._condition: TransitCondition = TransitCondition(self._lock)
        self._count: int = 0
        self._released: bool = False
        self._transit_fired: bool = False

        self._controller: 'SignalController' = controller
        if self._controller:
            try:
                # FIX: Register the object instance 'self', not its ID string.
                self._controller.register(self)
            except Exception:
                # In a real app, you would log this failure.
                pass
    def dispose(self):
        """
        Disposes the TransitBarrier and unblocks all waiting threads.

        After disposal:
        - All future `wait()` calls will immediately return False.
        - The internal controller reference is cleared.
        - All pending threads are notified and released.
        - Callable references (`_transit`) are nulled for GC friendliness.
        - The object is marked as disposed and is no longer usable.
        """
        if self._disposed:
            return

        self._disposed = True

        # Clear all state under lock to avoid race conditions
        with self._condition:
            self._condition.notify_all()

        self._condition.dispose()
        self._condition = None

        # Null out any strong reference types
        self._transit = None
        if self._controller and hasattr(self._controller, 'unregister'):
            try:
                self._controller.unregister(self.id)
            except Exception:
                pass
        self._controller = None

    @property
    def id(self) -> str:
        """
        The unique identifier for this component.
        """
        return self._id

    def _get_object_details(self) -> ConcurrentDict[str, Any]:
        """
        Provides metadata and command hooks for integration with a controller.

        Returns:
            A dictionary containing:
                - name: Logical name of this component.
                - commands: Callable controller-accessible methods.
        """
        return ConcurrentDict({
            'name': 'transit_barrier',
            'commands': ConcurrentDict({
                'release': self.release,
                'reset': self.reset,
                'is_spent': self.is_spent,
                'get_waiter_count': self._condition.find_waiter_count,
                'release_with_action': self.release_with_action,
                # Re-added for production compatibility
                'notify_all_override': self.notify_all_override,
            })
        })

    def release_with_action(self, callback: Optional[Union[Callable[..., None], Pack]] = None) -> None:
        """
        Forcibly releases all waiting threads using a custom transit action.

        If a callback is provided, it replaces the default transit logic for
        this release. This method bypasses the threshold condition and emits
        immediately, useful in override scenarios.

        Args:
            callback: Optional one-time callable to invoke upon release.
        """
        with self._lock:
            if self._disposed or self._released:
                return

            self._released = True
            if (final_action := callback or self._transit):
                final_action = Pack.bundle(final_action)

            self._condition.notify_all(final_action)

    def notify_all_override(self) -> None:
        """
        Immediately releases all threads without waiting for the threshold.

        Uses the default transit action if it hasn't already been fired. This
        method is intended for emergency overrides or controller-level resets.
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
        Manually releases all threads if the threshold is met.

        This method only applies when `manual_release` is True. If the barrier
        is ready (i.e., thread count matches threshold) and not yet released,
        it fires the transit action (if not already fired) and unblocks all
        waiting threads.
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
        Waits at the barrier until the release condition is met or timeout occurs.

        Behavior:
        - If `manual_release` is False and the threshold is met, the first thread
          triggers release and runs the transit action (if any).
        - If `manual_release` is True, the controller is notified on threshold,
          but threads remain blocked until `.release()` is called externally.
        - If `reusable` is True, the barrier resets after the last thread exits.

        Args:
            timeout: Optional timeout (in seconds) to wait.

        Returns:
            True if released successfully, False if disposed or timed out.
        """
        if self.is_spent():
            return False

        if self._count < self._threshold and not self._released:
            if self._controller:
                self._controller.notify(self.id, "WAIT_STARTING")

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

    def is_spent(self) -> bool:
        """
        Checks if the barrier has already been triggered and is non-reusable.

        Returns:
            True if the barrier has been released and `reusable` is False.
        """
        return self._released and not self._reusable

    def reset(self) -> None:
        """
        Resets the internal state of the barrier for another cycle.

        Only effective if `reusable` is True. Clears all counters, flags,
        and transit state so the barrier can be used again.
        """
        with self._lock:
            self._count = 0
            self._released = False
            self._transit_fired = False