import threading
from typing import Any, Optional, Type
import ulid
from thread_factory.utilities.interfaces.cleanable import Cleanable
class Outcome(Cleanable):
    """
    A lightweight, self-contained, Future-like object to hold the eventual
    result or exception to a unit of work.

    This object is thread-safe.
    """

    def __init__(self):
        super().__init__()
        self._task_id: Optional[ulid.ULID] = None
        self._result: Any = None
        self._exception: Optional[Exception] = None
        self._is_done: bool = False
        self._condition = threading.Condition()

    def cleanup(self):
        """
        cleanups of the Outcome, unblocking any waiting threads with an error.
        """
        if self.cleaned:
            return

        self._cleaned = True # Mark as cleaned immediately

        if self._condition: # Ensure condition exists before using
            with self._condition:
                # Only set cleaning exception if the outcome was NOT already completed by a result/exception
                if not self._is_done:
                    self._exception = RuntimeError("Outcome was cleaned.") # Standardized error message
                    self._is_done = True # Mark as done due to cleaning
                    self._condition.notify_all()

        # Purge the result reference regardless of prior state, as per user's requirement.
        self._result = None
        # _exception is NOT set to None here if it was set by set_exception,
        # but it IS set to RuntimeError("Outcome was cleaned.") if not _is_done.
        self._condition = None # Clear the condition object LAST

    def set_result(self, result: Any) -> None:
        """
        Sets the successful result for this outcome and notifies waiting threads.

        Raises:
            RuntimeError: If the outcome has already been set or cleaned.
        """
        if self.cleaned:
            raise RuntimeError("Cannot set result on a cleaned Outcome.")

        with self._condition:
            if self._is_done:
                return
            self._result = result
            self._is_done = True
            self._condition.notify_all()

    def set_exception(self, exception: Exception) -> None:
        """
        Sets the exception for this outcome and notifies waiting threads.

        Raises:
            RuntimeError: If the outcome has already been set or cleaned.
        """
        if self.cleaned:
            raise RuntimeError("Cannot set exception on a cleaned Outcome.")

        with self._condition:
            if self._is_done:
                return
            self._exception = exception
            self._is_done = True
            self._condition.notify_all()

    def result(self, timeout: Optional[float] = None) -> Any:
        """
        Waits for the outcome to be ready and returns its result.

        If the task failed, this method re-raises the exception that occurred.
        If the timeout is reached, it raises a TimeoutError.
        """
        # If cleaned, _result is purged. So, accessing result() means
        # either an original exception or a cleaning error.
        if self.cleaned:
            if self._exception is not None:
                raise self._exception
            raise RuntimeError("Outcome was cleaned.") # If no specific exception, raise generic cleaning error

        # If _condition is None, it implies cleaning.
        if self._condition is None:
            if self._exception is not None:
                raise self._exception
            raise RuntimeError("Outcome was cleaned.")

        with self._condition:
            if not self._is_done:
                if not self._condition.wait_for(lambda: self._is_done or self.cleaned, timeout=timeout):
                    raise TimeoutError(f"Timed out after {timeout}s waiting for outcome.")

            # After waiting, if cleaned and not completed by a task, raise cleaning error
            if self.cleaned and not self._is_done:
                if self._exception is not None:
                    raise self._exception
                raise RuntimeError("Outcome was cleaned.")

            # If done by task completion (and not cleaned, or cleaned after completion but _result was not purged)
            if self._exception is not None:
                raise self._exception
            return self._result # This will return the result if it was set and not purged by cleanup.

    @property
    def done(self) -> bool:
        """Returns True if the outcome has been set."""
        if self.cleaned:
            return True
        if self._condition is None:
            return True
        with self._condition:
            return self._is_done

    def exception(self) -> Optional[Exception]:
        """Returns the exception object if the task failed, otherwise None."""
        # If cleaned, return the stored exception (if any) or the cleaning error.
        if self.cleaned:
            return self._exception or RuntimeError("Outcome was cleaned.")

        if self._condition is None:
            return self._exception or RuntimeError("Outcome was cleaned.")

        with self._condition:
            if not self._is_done:
                self._condition.wait()
            return self._exception
