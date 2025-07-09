import threading
from typing import Callable, Optional, Union
import ulid
from thread_factory.utilities.interfaces.disposable import IDisposable
from thread_factory.utilities.coordination.package import Pack


class Scout(IDisposable):
    """
    Scout
    -----
    A blocking, single-entry utility for a calling thread to monitor a given
    predicate callable with a defined timeout. It executes callbacks based on
    whether the predicate becomes True within the timeout or if the timeout
    is reached. It ensures only one thread can perform monitoring at a time.

    It acts as a 'latch': once a monitoring cycle completes (success or timeout),
    it remains 'latched' (inactive) unless explicitly reset via `reset()` or
    configured with `autoreset_on_exit=True`.

    It uses a threading.Condition internally for its waiting mechanism,
    where the predicate is evaluated under the condition's lock.
    Args:
        predicate (Callable[[], bool]): A callable that takes no arguments and returns a boolean.
                                       The Scout will wait for this predicate to return True.
                                       This callable will be invoked while holding the Scout's
                                       internal condition lock.
        timeout_duration (float): The maximum time (in seconds) to wait for the predicate to become True.
        on_timeout_callable (Callable): Mandatory function to call if the timeout is reached.
        on_success_callable (Optional[Callable]): Optional function to call if the predicate becomes True within the timeout.
        autoreset_on_exit (bool): If True, the Scout will automatically re-arm itself after each cycle
                                  (success or timeout). If False, it completes one cycle and becomes latched,
                                  requiring explicit `reset()` for reuse. Defaults to False.
    """
    __slots__ = IDisposable.__slots__ + [
        "_id", "_predicate", "_timeout_duration", "_on_timeout_callable",
        "_on_success_callable", "_autoreset_on_exit", "_condition",
        "_is_active_monitoring", "_monitoring_cycle_completed", "_id",
        "_exit_monitoring"
    ]
    def __init__(
            self,
            predicate: Union[Callable[..., bool], Pack],
            timeout_duration: float,
            on_timeout_callable: Union[Callable[..., None], Pack],
            on_success_callable: Optional[Union[Callable[..., None], Pack]] = None,
            autoreset_on_exit: bool = False,
    ):
        """

        """
        super().__init__()  # Initialize _disposed = False
        if not isinstance(timeout_duration, (int, float)) or timeout_duration <= 0:
            raise ValueError("timeout_duration must be a positive number.")
        if not callable(on_timeout_callable):
            raise TypeError("on_timeout_callable must be a callable function.")
        if not callable(predicate):
            raise TypeError("predicate must be a callable function.")
        if on_success_callable is not None and not callable(on_success_callable):
            raise TypeError("on_success_callable must be a callable function or None.")

        self._exit_monitoring = False  # True if the Scout is disposed
        self._id = str(ulid.ULID())
        self._predicate = Pack.bundle(predicate) if predicate else None
        self._timeout_duration = timeout_duration
        self._on_timeout_callable = Pack.bundle(on_timeout_callable) if on_timeout_callable else None
        self._on_success_callable = Pack.bundle(on_success_callable) if on_success_callable else None
        self._autoreset_on_exit = autoreset_on_exit

        # Use a Condition to manage exclusive entry, active status, and the predicate wait.
        self._condition = threading.Condition()
        self._is_active_monitoring = False  # True if a thread is currently inside monitor()
        self._monitoring_cycle_completed = False  # True if a cycle has finished (latch state)

    def dispose(self) -> None:
        """
        Disposes the Scout instance. This makes it permanently unusable.
        All resources are released. Does NOT call super().dispose().
        """
        # Per user request, do not call super().dispose()
        if self._disposed:
            return  # Already disposed, do nothing

        with self._condition:
            self._disposed = True
            # Clear internal state and references
            self._is_active_monitoring = False
            self._monitoring_cycle_completed = False
            self._predicate = None  # Release reference
            self._on_timeout_callable = None  # Release reference
            self._on_success_callable = None  # Release reference
            # The Condition object itself can't be truly 'disposed' but references are cleared.
            self._condition.notify_all()  # Notify any waiting threads that it's disposed
            # No need to acquire/release lock again for the final cleanup within the with block.


    def exit_monitor(self):
        """
        Marks the Scout as disposed, effectively exiting any ongoing monitoring.
        """
        with self._condition:
            self._is_active_monitoring = True
            self._condition.notify_all()


    def monitor(self) -> bool:
        """
        Causes the calling thread to monitor the predicate for the timeout_duration.
        Executes callbacks based on outcome. If another thread is already monitoring,
        or if the Scout is latched (and not autoresetting), this method will
        return False immediately, indicating it could not enter.

        Returns:
            bool: True if monitoring started and the predicate became True.
                  False if monitoring started and timeout occurred.
                  False if the Scout was already active, disposed, or latched.
        """
        success = False
        with self._condition:  # Acquire lock to manage entry and state
            if self._disposed:
                return False

            if self._is_active_monitoring:
                return False  # Or raise an error, depending on desired behavior

            if self._monitoring_cycle_completed and not self._autoreset_on_exit:
                return False

            # Claim this monitoring slot
            self._is_active_monitoring = True
            # For a new cycle, clear completion flag unless it's auto-resetting
            # and already clear.
            self._monitoring_cycle_completed = False

        try:
            with self._condition:  # Re-acquire lock for the wait_for predicate evaluation
                # Perform the actual wait on the predicate using the Condition.
                # The predicate callable will be invoked internally by wait_for()
                # while holding _condition's lock.
                predicate_became_true = self._condition.wait_for(
                    lambda: self._exit_monitoring or self._predicate(),
                    timeout=self._timeout_duration
                )

            with self._condition:  # Re-acquire lock to update active status and call callbacks
                if predicate_became_true:
                    success = True
                    if self._on_success_callable:
                        try:
                            self._on_success_callable()
                        except Exception as e:
                            pass
                else:
                    # Timeout occurred (predicate did not become true)
                    success = False
                    try:
                        self._on_timeout_callable()  # Mandatory
                    except Exception as e:
                        pass
        finally:
            with self._condition:  # Ensure reset on exit, even if callbacks failed
                self._is_active_monitoring = False  # Release the active monitoring slot
                if not self._autoreset_on_exit:
                    self._monitoring_cycle_completed = True  # Latch the Scout
                self._condition.notify_all()  # Notify any threads waiting for state changes (e.g., in is_active())

        return success

    def reset(self) -> None:
        """
        Resets the Scout, making it ready for a new monitoring cycle.
        This is only necessary if `autoreset_on_exit` was set to False
        and a previous `monitor()` call completed.
        """
        with self._condition:
            if self._disposed:
                raise RuntimeError("Cannot reset a disposed Scout.")

            # Reset all flags that control entry and cycle state
            self._is_active_monitoring = False
            self._is_active_monitoring = False
            self._monitoring_cycle_completed = False
            self._condition.notify_all()  # Notify any threads that were waiting for state change

    def is_active(self) -> bool:
        """
        Checks if a thread is currently performing monitoring via this Scout instance.

        Returns:
            bool: True if a thread is inside the monitor() method, False otherwise.
        """
        with self._condition:
            return self._is_active_monitoring

    def is_latched(self) -> bool:
        """
        Checks if the Scout has completed a monitoring cycle and is latched (not ready for
        a new cycle) and `autoreset_on_exit` is False.

        Returns:
            bool: True if latched and not auto-resetting, False otherwise.
        """
        with self._condition:
            return self._monitoring_cycle_completed and not self._autoreset_on_exit

    def __repr__(self):
        status = "Active" if self.is_active() else "Idle"
        if self._disposed:
            status = "Disposed"
        elif self.is_latched():
            status = "Latched"

        predicate_name = self._predicate.__name__ if hasattr(self._predicate, '__name__') else repr(self._predicate)
        return (f"<Scout(predicate={predicate_name}, "
                f"timeout={self._timeout_duration}s, "
                f"autoreset={self._autoreset_on_exit}, "
                f"status='{status}')>")