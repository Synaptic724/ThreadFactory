import threading
import time
from typing import Any, Optional, Type
from thread_factory.utils.interfaces.disposable import IDisposable

class Outcome(IDisposable):
    """
    A lightweight, self-contained, Future-like object to hold the eventual
    result or exception of a unit of work.

    This object is thread-safe.
    """
    def __init__(self):
        super().__init__()
        self._result: Any = None
        self._exception: Optional[Exception] = None
        self._is_done: bool = False
        self._condition = threading.Condition()

    def set_result(self, result: Any) -> None:
        """

        Sets the successful result for this outcome and notifies waiting threads.

        Raises:
            RuntimeError: If the outcome has already been set.
        """
        with self._condition:
            if self._is_done:
                raise RuntimeError("Outcome has already been set.")
            self._result = result
            self._is_done = True
            self._condition.notify_all()

    def set_exception(self, exception: Exception) -> None:
        """
        Sets the exception for this outcome and notifies waiting threads.

        Raises:
            RuntimeError: If the outcome has already been set.
        """
        with self._condition:
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

        Args:
            timeout (Optional[float]): The maximum time in seconds to wait for the result.

        Returns:
            Any: The result of the successful operation.

        Raises:
            Exception: The exception that was raised by the operation.
            TimeoutError: If the wait times out.
        """
        with self._condition:
            if not self._is_done:
                # Wait for the outcome to be set
                if not self._condition.wait_for(lambda: self._is_done, timeout=timeout):
                    raise TimeoutError(f"Timed out after {timeout}s waiting for outcome.")

            # Once ready, check for an exception and raise it
            if self._exception is not None:
                raise self._exception

            # Otherwise, return the successful result
            return self._result

    @property
    def done(self) -> bool:
        """Returns True if the outcome has been set."""
        with self._condition:
            return self._is_done

    def exception(self) -> Optional[Exception]:
        """Returns the exception object if the task failed, otherwise None."""
        with self._condition:
            if not self._is_done:
                 # To be consistent with concurrent.futures.Future,
                 # we should wait for the task to be done.
                 self._condition.wait()
            return self._exception