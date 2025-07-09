import threading
from typing import Any, Optional, Type
import ulid
from thread_factory.utilities.interfaces.disposable import IDisposable
class Outcome(IDisposable):
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

    def dispose(self):
        """
        Disposes of the Outcome, unblocking any waiting threads with an error.
        """
        if self.disposed:
            return

        self._disposed = True # Mark as disposed immediately

        if self._condition: # Ensure condition exists before using
            with self._condition:
                # Only set disposal exception if the outcome was NOT already completed by a result/exception
                if not self._is_done:
                    self._exception = RuntimeError("Outcome was disposed.") # Standardized error message
                    self._is_done = True # Mark as done due to disposal
                    self._condition.notify_all()

        # Purge the result reference regardless of prior state, as per user's requirement.
        self._result = None
        # _exception is NOT set to None here if it was set by set_exception,
        # but it IS set to RuntimeError("Outcome was disposed.") if not _is_done.
        self._condition = None # Clear the condition object LAST

    def set_result(self, result: Any) -> None:
        """
        Sets the successful result for this outcome and notifies waiting threads.

        Raises:
            RuntimeError: If the outcome has already been set or disposed.
        """
        if self.disposed:
            raise RuntimeError("Cannot set result on a disposed Outcome.")

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
            RuntimeError: If the outcome has already been set or disposed.
        """
        if self.disposed:
            raise RuntimeError("Cannot set exception on a disposed Outcome.")

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
        # If disposed, _result is purged. So, accessing result() means
        # either an original exception or a disposal error.
        if self.disposed:
            if self._exception is not None:
                raise self._exception
            raise RuntimeError("Outcome was disposed.") # If no specific exception, raise generic disposal error

        # If _condition is None, it implies disposal.
        if self._condition is None:
            if self._exception is not None:
                raise self._exception
            raise RuntimeError("Outcome was disposed.")

        with self._condition:
            if not self._is_done:
                if not self._condition.wait_for(lambda: self._is_done or self.disposed, timeout=timeout):
                    raise TimeoutError(f"Timed out after {timeout}s waiting for outcome.")

            # After waiting, if disposed and not completed by a task, raise disposal error
            if self.disposed and not self._is_done:
                if self._exception is not None:
                    raise self._exception
                raise RuntimeError("Outcome was disposed.")

            # If done by task completion (and not disposed, or disposed after completion but _result was not purged)
            if self._exception is not None:
                raise self._exception
            return self._result # This will return the result if it was set and not purged by dispose.

    @property
    def done(self) -> bool:
        """Returns True if the outcome has been set."""
        if self.disposed:
            return True
        if self._condition is None:
            return True
        with self._condition:
            return self._is_done

    def exception(self) -> Optional[Exception]:
        """Returns the exception object if the task failed, otherwise None."""
        # If disposed, return the stored exception (if any) or the disposal error.
        if self.disposed:
            return self._exception or RuntimeError("Outcome was disposed.")

        if self._condition is None:
            return self._exception or RuntimeError("Outcome was disposed.")

        with self._condition:
            if not self._is_done:
                self._condition.wait()
            return self._exception
