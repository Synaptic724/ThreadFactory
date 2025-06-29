import functools
import inspect
import threading
from typing import Callable, Optional, List, Any, Union
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
        "_limit", "_count", "_lock", "_collapsed", "_outcomes", "_func",
        "_dynaphore", "_threshold_sema", "_outcome_set"
    ]

    def __init__(self, func: Union[Callable, list[Callable]], limit: int = 1, *args, **kwargs):
        """
        Initializes the gate with a callable or a list of callables.

        Args:
            func (Union[Callable, list[Callable]]): A synchronous function or a list
                                                     of functions to execute in a pipeline.
                                                     If a single callable, it can accept arguments
                                                     passed via *args and **kwargs.
            limit (int): Maximum number of allowed executions.
            *args: Positional args to pass to the callable if it's a single item.
            **kwargs: Keyword args to pass to the callable if it's a single item.
        """
        super().__init__()

        if limit < 0:
            raise ValueError("Limit must be non-negative")

        # --- Check if it's a single callable and wrap it in a list with bound arguments ---
        if callable(func):
            # If it's a single callable, bind its parameters using functools.partial
            self._func = [functools.partial(func, *args, **kwargs)]
        elif isinstance(func, list):
            if not all(callable(f) for f in func):
                raise TypeError("Provided list must contain only callables.")
            # If it's a list, assume callables are already pre-bound if they need arguments
            self._func = func
        else:
            raise TypeError("Provided 'func' must be a callable or a list of callables.")

        # --- Check for coroutine functions on all items in the list ---
        for f in self._func:
            if inspect.iscoroutinefunction(f):
                raise TypeError("TransitGate does not support coroutine functions.")

        self._limit = limit
        self._count = 0
        self._lock = threading.RLock()
        self._collapsed = False
        self._outcomes: List[Outcome] = []
        self._dynaphore = Dynaphore(limit)
        self._threshold_sema = ThresholdSemaphore(limit)

        self._outcome_set = False

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

        # Acquire the dynaphore to limit concurrent executions
        for item in range(len(self._func)):
            self._dynaphore.acquire()
            try:
                self._set_result(self._func[item]())
            except Exception as e:
                self._set_exception(e)
            finally:
                with self._lock:
                    self._count -= 1

            self._dynaphore.release()
            self._threshold_sema.wait()
            self._outcome_set = False
        self._collapsed = True
        return None

    def increase_limit(self, n: int = 1):
        if n < 0:
            raise ValueError("Cannot increase by negative")
        self._dynaphore.increase_permits(n)
        with self._lock:
            self._limit += n
            self._threshold_sema.set_threshold(self._limit)

    def _increase_count(self):
        """
        Increments the count of active executions.
        This is called internally before each callable execution.
        """
        with self._lock:
            if self._count >= self._limit:
                raise RuntimeError("Count exceeds limit")
            self._count += 1

    def _decrement_count(self):
        """
        Decrements the count of active executions.
        This is called internally after each callable execution.
        """
        with self._lock:
            if self._count > 0:
                self._count -= 1
            if self._count < 0:
                raise RuntimeError("Count cannot be negative")

    def decrease_limit(self, n: int = 1):
        if n < 0:
            raise ValueError("Cannot decrease by negative")
        self._dynaphore.decrease_permits(n)
        with self._lock:
            self._limit = max(0, self._limit - n)
            self._threshold_sema.set_threshold(self._limit)

    def _set_result(self, result: Any):
        """
        Sets the result of the callable execution.
        This method is called internally after the callable completes.
        """
        if self._outcome_set:
            return
        with self._lock:
            if self._outcome_set:
                return
            self._outcome_set = True
            outcome = Outcome()
            outcome.set_result(result)
            self._outcomes.append(outcome)

    def _set_exception(self, e: Exception):
        """
        Sets the exception of the callable execution.
        This method is called internally if the callable raises an exception.
        """
        if self._outcome_set:
            return
        with self._lock:
            if self._outcome_set:
                return
            self._outcome_set = True
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
            self._threshold_sema.dispose()
            self._threshold_sema = None