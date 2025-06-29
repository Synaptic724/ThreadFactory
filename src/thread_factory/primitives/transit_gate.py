import functools
import inspect
import threading
from typing import Callable, Optional, List, Any
from thread_factory.primitives.dynaphore import Dynaphore
from thread_factory.primitives.threshold_semaphore import ThresholdSemaphore
from thread_factory.utils import IDisposable, Outcome


class TransitGate(IDisposable):
    """
    TransitGate
    -----------
    A limited-entry execution gate that runs a pre-bound callable up to N times.

    Features:
    • Callable is supplied at construction.
    • Up to `limit` threads may execute the callable; others skip.
    • Each successful execution returns an Outcome tracking result or exception.

    Example Use:
    >>> def log_task(): print("Task complete")
    >>> gate = TransitGate(log_task, limit=3)
    >>> outcome = gate.transit()
    """

    __slots__ = IDisposable.__slots__ + [
        "_limit", "_count", "_lock", "_collapsed", "_outcomes", "_func"
    ]

    def __init__(self, func: list[Callable], limit: int = 1):
        """
        Initializes the gate with a callable that takes no arguments.

        Args:
            func (Callable): Synchronous function to execute. This function must not
                             require any arguments.
            limit (int): Maximum number of allowed executions.
        """
        super().__init__()

        if limit < 0:
            raise ValueError("Limit must be non-negative")
        if not callable(func):
            raise TypeError("Provided object is not callable.")
        if inspect.iscoroutinefunction(func):
            raise TypeError("TransitGate does not support coroutine functions.")

        self._limit = limit
        self._count = 0
        self._lock = threading.RLock()
        self._collapsed = False
        self._outcomes: List[Outcome] = []
        self._dynaphore = Dynaphore(limit)
        self._threshold_sema = ThresholdSemaphore(limit)

        # Store the callable directly, without binding arguments
        self._func: list[Callable] = func

    def transit(self):
        """
        Attempts to transit through the gate and run the callable.

        Returns:
            Outcome: If allowed and executed.
            None: If skipped due to limit or collapse.
        """
        if self._disposed:
            return None

        with self._lock:
            if self._collapsed or self._count >= self._limit:
                return None
            self._count += 1
            outcome = Outcome()
            self._outcomes.append(outcome)

        for item in range(len(self._func)):
            self._dynaphore.acquire()
            try:
                self._set_result(self._func())
            except Exception as e:
                self._set_exception(e)
            finally:
                with self._lock:
                    self._count -= 1

        self._collapsed = True


    def increase_limit(self, n: int = 1):
        if n < 0:
            raise ValueError("Cannot increase by negative")
        self._dynaphore.increase_permits(n)
        with self._lock:
            self._limit += n

    def decrease_limit(self, n: int = 1):
        if n < 0:
            raise ValueError("Cannot decrease by negative")
        self._dynaphore.decrease_permits(n)
        with self._lock:
            self._limit = max(0, self._limit - n)

    def _set_result(self, result: Any):
        """
        Sets the result of the callable execution.
        This method is called internally after the callable completes.
        """
        with self._lock:
            outcome = Outcome()
            outcome.set_result(result)
            self._outcomes.append(outcome)

    def _set_exception(self, e: Exception):
        """
        Sets the exception of the callable execution.
        This method is called internally if the callable raises an exception.
        """
        with self._lock:
            outcome = Outcome()
            outcome.set_exception(e)
            self._outcomes.append(outcome)

    def collapse(self):
        with self._lock:
            self._collapsed = True

    def reset(self, new_limit: Optional[int] = None):
        with self._lock:
            self._count = 0
            if new_limit is not None:
                if new_limit < 0:
                    raise ValueError("New limit must be non-negative")
                self._limit = new_limit
            self._collapsed = False
            self._outcomes.clear()

    def outcomes(self) -> List[Outcome]:
        """Returns all outcome objects recorded so far."""
        return self._outcomes

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        with self._lock:
            self._collapsed = True
            self._outcomes.clear()
            self._dynaphore.dispose()
            self._dynaphore = None