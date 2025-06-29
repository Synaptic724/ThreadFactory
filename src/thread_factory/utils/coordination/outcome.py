import threading
import time
from typing import Any, Optional, Type

import ulid

from thread_factory.utils.interfaces.disposable import IDisposable


class Outcome(IDisposable):
    """
    A lightweight, self-contained, Future-like object to hold the eventual
    result or exception of a unit of work.

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

        with self._condition:
            # If the outcome is not yet set, we set it to an error state.
            # This is crucial to unblock any threads waiting on .result().
            if not self._is_done:
                self._exception = RuntimeError("Outcome was disposed before it could be completed.")
                self._is_done = True
                # Notify all waiting threads that the outcome is now "done".
                self._condition.notify_all()

        # Nullify references to release resources
        self._result = None
        self._exception = None
        self._condition = None
        self._disposed = True

    def set_result(self, result: Any) -> None:
        """
        Sets the successful result for this outcome and notifies waiting threads.

        Raises:
            RuntimeError: If the outcome has already been set or disposed.
        """
        with self._condition:
            if self.disposed:
                raise RuntimeError("Cannot set result on a disposed Outcome.")
            if self._is_done:
                raise RuntimeError("Outcome has already been set.")
            self._result = result
            self._is_done = True
            self._condition.notify_all()

    def set_exception(self, exception: Exception) -> None:
        """
        Sets the exception for this outcome and notifies waiting threads.

        Raises:
            RuntimeError: If the outcome has already been set or disposed.
        """
        with self._condition:
            if self.disposed:
                raise RuntimeError("Cannot set exception on a disposed Outcome.")
            if self._is_done:
                raise RuntimeError("Outcome has already been set.")
            self._exception = exception
            self._is_done = True
            self._condition.notify_all()

    def result(self, timeout: Optional[float] = None) -> Any:
        """
        Waits for the outcome to be ready and returns its result.

        If the task failed, this method re-raises the exception that occurred.
        If the timeout is reached, it raises a TimeoutError.
        """
        if self.disposed:
            raise RuntimeError("Cannot get result from a disposed Outcome.")

        with self._condition:
            if not self._is_done:
                if not self._condition.wait_for(lambda: self._is_done or self.disposed, timeout=timeout):
                    raise TimeoutError(f"Timed out after {timeout}s waiting for outcome.")

            # If disposed while waiting
            if self.disposed and not self._is_done:
                raise RuntimeError("Outcome was disposed while waiting for result.")

            if self._exception is not None:
                raise self._exception
            return self._result

    @property
    def done(self) -> bool:
        """Returns True if the outcome has been set."""
        if self.disposed:
            return True
        with self._condition:
            return self._is_done

    def exception(self) -> Optional[Exception]:
        """Returns the exception object if the task failed, otherwise None."""
        if self.disposed:
            return self._exception or RuntimeError("Outcome was disposed.")

        with self._condition:
            if not self._is_done:
                self._condition.wait()
            return self._exception