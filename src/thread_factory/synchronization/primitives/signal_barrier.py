import threading
from typing import Optional, Callable, Any, Dict
import ulid
from thread_factory.utils.interfaces.disposable import IDisposable
from thread_factory.utils.coordination.package import Pack

# Assuming Controller is in a file that can be imported
# from thread_factory.controller import Controller


class SignalBarrier(IDisposable):
    """
    SignalBarrier
    ------------------
    A reusable, synchronization primitive that acts like a *count-to-N barrier*.
    Once a predefined number of threads (the `threshold`) have called `wait()`, all
    waiting threads are released simultaneously. This release can occur automatically
    or be manually triggered, depending on the configuration.

    💡 Core Features:
    -----------------
    • **Count-based Trigger**: Threads block until the `threshold` number of waiters is reached.
    • **Optional Reusability**: Can be configured to reset after releasing all threads.
    • **Manual Release Option**: Allows controller or external caller to trigger release manually.
    • **Controller Integration**: Emits lifecycle events and supports remote invocation.
    • **Timeout-aware**: Threads can specify a timeout for `wait()`.

    🔁 Reusable Behavior:
    ---------------------
    If `reusable=True`, once all waiting threads pass the barrier, the internal count is
    reset automatically and the semaphore becomes ready for reuse. The last thread to pass
    is responsible for resetting the internal state.

    🔐 Manual Release:
    ------------------
    If `manual_release=True`, the barrier is *not* released automatically when the threshold is met.
    Instead, a manual call to `release()` is required to proceed.

    🔧 Controller Integration:
    --------------------------
    When integrated with a Controller instance:
    • Self-registers on creation.
    • Emits the following events:
        - "THRESHOLD_MET": When the threshold is first reached.
        - "SEMAPHORE_RELEASED": When threads are actually unblocked.
    • Supports command-based control via:
        - `release()`, `reset()`, `set_threshold()`, `is_spent()`, `notify_all_override()`, `dispose()`
    • Provides a `signal_callback` hook (e.g., `controller.on_wait_starting`) to signal blocking activity.

    ⚙ Parameters:
    -------------
    threshold (int):
        Number of threads required to reach the release point.
    callback (Optional[Callable[[], None]]):
        A function invoked once when the threshold is reached (before releasing threads).
    reusable (bool):
        If True, the semaphore resets itself after each full release cycle. Default is False.
    manual_release (bool):
        If True, prevents automatic release and requires an explicit call to `release()`.
    controller (Optional[Controller]):
        A `Controller` instance used for central management and event emission.
    signal_callback (Optional[Callable[[str], None]]):
        A hook called just before a thread blocks in `wait()`. Typically used to notify a controller.

    🚨 Exceptions:
    --------------
    Raises ValueError if `threshold <= 0`.

    🧪 Typical Use Case:
    --------------------
        # With 5 threads
        semaphore = SignalBarrier(threshold=5, reusable=True)

        def worker():
            print("Thread waiting")
            semaphore.wait()
            print("Thread released")

        # Start 5 threads to trigger threshold
        for _ in range(5):
            threading.Thread(target=worker).start()
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

        self._lock = threading.RLock()
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


    def dispose(self):
        """
        Releases all resources and unblocks waiting threads.

        This method marks the semaphore as disposed and removes references
        to callbacks and controllers. All currently waiting threads are notified
        and allowed to exit.

        This method is idempotent and safe to call multiple times.
        """
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

    # --- Controller Contract Properties ---

    @property
    def id(self) -> str:
        """
        Returns the unique ULID identifier for this semaphore.

        This ID is used for identification during controller integration,
        event tracking, and external control through the command interface.

        Returns:
            str: A globally unique ULID string.
        """
        return self._id

    def _get_object_details(self) -> Dict[str, Any]:
        """
        Provides controller-compatible metadata and command bindings.

        This allows the `Controller` to register the object, invoke its
        commands remotely, and subscribe to events.

        Returns:
            Dict[str, Any]: A dictionary with keys:
                - 'name': A string descriptor of the object ("threshold_semaphore").
                - 'commands': A dictionary mapping command names to bound methods.
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

    def is_spent(self) -> bool:
        """
        Indicates whether the semaphore has already been released
        and is no longer usable (unless reusable=True).

        Returns:
            bool: True if the threshold was reached and the semaphore
                  has been released in a non-reusable configuration.
        """
        return self._released and not self._reusable

    def notify_all_override(self) -> None:
        """
        Forcibly releases all threads currently waiting on the semaphore.

        This bypasses the threshold logic. It's typically used by the
        controller or external system to override the normal wait logic.

        Emits:
            Controller event: "SEMAPHORE_RELEASED"

        Notes:
            If reusable=True, resets the counter after releasing.
        """
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
        """
        Manually releases the semaphore when `manual_release=True`.

        This should be called *after* the threshold has been met.

        Emits:
            Controller event: "SEMAPHORE_RELEASED"

        Notes:
            Has no effect unless `manual_release=True` and the internal
            count has reached the configured threshold.
        """
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
        """
        Dynamically updates the required thread count to trigger release.

        Args:
            new_threshold (int): The new threshold value (> 0).

        Raises:
            ValueError: If `new_threshold <= 0`.

        Behavior:
            - If the new threshold is already met and not in manual mode,
              the semaphore will auto-release immediately.
        """
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
        """
        Manually resets the semaphore for reuse.

        This resets the internal counter and clears the released flag,
        regardless of current state. Should only be used when the semaphore
        is not in use or all waiters have already exited.
        """
        with self._condition:
            self._count = 0
            self._released = False

    # In the SignalBarrier class...

    def wait(self, timeout: Optional[float] = None) -> bool:
        """
        Blocks the calling thread until the threshold is met and release is triggered.

        Args:
            timeout (Optional[float]): Optional timeout in seconds. If specified,
                the thread will unblock after the timeout even if the semaphore
                hasn't been released.

        Returns:
            bool: True if the semaphore was released and the thread passed through.
                  False if the wait timed out or the semaphore was disposed before release.

        Behavior:
            - Increments the internal count on entry.
            - If the threshold is reached:
                • Invokes `callback` (if provided).
                • Emits "THRESHOLD_MET" event to the controller.
                • Either auto-releases or waits for `release()`, depending on configuration.
            - If `signal_callback` is defined and the thread will block, it is invoked.
            - If reusable=True, the last thread to exit resets the state for the next cycle.

        Notes:
            - If the semaphore has already been released and is not reusable, the call returns immediately.
            - If disposed, the thread unblocks with a return value of False.

        Exceptions:
            - All internal exceptions in callbacks or controller logic are caught and logged silently.
        """
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