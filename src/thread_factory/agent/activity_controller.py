import threading
import ulid
from typing import Callable, Optional
# Assuming these imports from your project structure
from thread_factory import ConcurrentDict, ConcurrentList
from thread_factory.agent.activity import Activity
from thread_factory.utils.exceptions.operation_canceled_error import OperationCanceledError


class ActivityController:
    """
    Acts as a central command and control unit for an agent's operation or job.

    This class is designed to be open-ended. While it has a fully implemented
    cooperative cancellation system, it serves as the authoritative source for
    'Activity' tokens. These tokens are the primary vehicle for sending any
    type of command or signal to a working agent, not just cancellation.

    It manages the lifecycle of an operation (e.g., signaling it to stop) and
    holds metadata about the job itself.
    """
    # A singleton instance for a controller that can never be canceled.
    # This is useful for non-cancelable operations that still require an Activity token.
    _none_controller: Optional['ActivityController'] = None
    _none_lock = threading.RLock()

    def __init__(self, is_cancelable: bool = True, **kwargs):
        """
        Initializes a new OperationalController for a specific job or operation.

        Args:
            is_cancelable (bool): If False, this controller and its activities
                                  can never enter a canceled state.
            **kwargs: Arbitrary keyword arguments that will be stored as
                      metadata for the operation (e.g., job_name, priority).
        """
        # --- State Properties ---
        self._is_cancellation_requested = False
        self._can_be_canceled = is_cancelable
        self._ulid = str(ulid.ULID())  # A unique ID for this specific operation control instance.

        # --- Thread-Safe Collections ---
        self._lock = threading.RLock()  # Ensures thread-safe access to controller state.
        self._callbacks: ConcurrentList[Callable[[], None]] = ConcurrentList()  # Callbacks to fire on cancellation.
        self._metadata = ConcurrentDict(kwargs)  # Thread-safe dictionary for metadata.

    @property
    def activity(self) -> Activity:
        """
        Issues a new Activity token linked to this controller.

        This token is the object you pass to an agent. The agent uses it to
        check for cancellation requests or to pull other dynamic commands
        that have been added to the Activity.

        Returns:
            Activity: A new token instance representing the ongoing operation.
        """
        return Activity(self, self.metadata)

    @property
    def is_cancellation_requested(self) -> bool:
        """
        Checks if the cancellation signal has been sent for this operation.

        Returns:
            bool: True if cancel() has been called, otherwise False.
        """
        with self._lock:
            return self._is_cancellation_requested

    @property
    def can_be_canceled(self) -> bool:
        """
        Gets a value indicating if this operation supports cancellation at all.

        Returns:
            bool: True if the controller was initialized to be cancelable.
        """
        return self._can_be_canceled

    def cancel(self, throw_on_first_exception: bool = False):
        """
        Broadcasts a cancellation request to all linked Activity tokens and
        executes any registered cancellation callbacks.

        This method is idempotent; calling it multiple times has no further effect.
        This is the primary mechanism for telling an agent to stop its current job.

        Args:
            throw_on_first_exception (bool): If True, an exception raised by a
                                             callback will halt execution and be
                                             re-thrown. If False, all callbacks
                                             will be attempted regardless of errors.
        """
        if not self._can_be_canceled:
            return  # Cannot cancel an uncancelable controller

        with self._lock:
            # If already canceled, do nothing.
            if self._is_cancellation_requested:
                return

            # Set the state to canceled.
            self._is_cancellation_requested = True

            # Execute all registered callbacks.
            for callback in self._callbacks:
                try:
                    callback()
                except Exception as e:
                    if throw_on_first_exception:
                        raise OperationCanceledError(f"Callback failed during cancellation: {e}") from e
                    # Otherwise, swallow the exception and continue.
                    # In a real application, you would log this error.
                    pass

            # Clear callbacks after execution as they are one-shot.
            self._callbacks.clear()

    def register_callback(self, callback: Callable[[], None]) -> None:
        """
        Registers a callback delegate that will be invoked when this operation
        is canceled.

        If the operation has already been canceled, the callback is executed immediately.

        Args:
            callback (Callable[[], None]): The function to execute on cancellation.
        """
        with self._lock:
            if self.is_cancellation_requested:
                # If cancellation has already happened, run the callback now.
                try:
                    callback()
                except Exception:
                    # Swallow exception, but log in a real-world scenario.
                    pass
            else:
                # Otherwise, add it to the list to be called later.
                self._callbacks.append(callback)

    def dispose(self):
        """
        Releases all resources used by the controller, primarily clearing any
        pending callbacks to prevent memory leaks.
        """
        with self._lock:
            self._callbacks.clear()

    @staticmethod
    def get_uncancelable() -> 'OperationalController':
        """
        Returns a shared, uncancelable OperationalController singleton.

        This is useful for operations that must not be canceled but need to
        be passed to functions that require an Activity token, ensuring
        polymorphic compatibility.

        Returns:
            OperationalController: The singleton instance that will never enter a
                                   canceled state.
        """
        with ActivityController._none_lock:
            if ActivityController._none_controller is None:
                # Create the singleton instance with the `is_cancelable` flag set to False.
                ActivityController._none_controller = ActivityController(
                    is_cancelable=False, source="uncancelable_singleton"
                )
            return ActivityController._none_controller