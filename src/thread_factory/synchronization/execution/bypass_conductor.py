import functools
import inspect
import threading
from typing import Callable, Optional, List, Any, Union
import ulid
from thread_factory.synchronization.primitives.dynaphore import Dynaphore
from thread_factory.synchronization.primitives.threshold_semaphore import ThresholdSemaphore
from thread_factory.utils import IDisposable, Outcome


class BypassConductor(IDisposable):
    """
    BypassConductor
    -----------
    A limited-entry execution gate that runs a pre-bound callable up to N times.

    Features:
    • Callable is supplied at construction.
    • Up to `limit` threads may execute the callable; others skip.
    • Each successful execution returns an Outcome tracking result or exception.

    Args:
        func (Union[Callable, list[Callable]]): A synchronous function or a list
                                                 of functions to execute in a pipeline.
                                                 If a single callable, it can accept arguments
                                                 passed via *args and **kwargs.
        limit (int): Maximum number of allowed executions.
        *args: Positional args to pass to the callable if it's a single item.
        **kwargs: Keyword args to pass to the callable if it's a single item.

    Example Use:
    >>> def log_task(): print("Task complete")
    >>> conductor = BypassConductor(log_task, limit=3) # Changed TransitGate to BypassConductor
    >>> outcome = conductor.transit() # Changed gate.transit()
    """

    __slots__ = IDisposable.__slots__ + [
        "_limit", "_count", "_lock", "_collapsed", "_outcomes", "_func",
        "_dynaphore", "_threshold_sema", "_outcome_set", "_id"
    ]

    def __init__(self, func: Union[Callable, list[Callable]], limit: int = 1, *args, **kwargs):
        super().__init__()

        if limit < 0:
            raise ValueError("Limit must be non-negative")

        if callable(func):
            self._func = [functools.partial(func, *args, **kwargs)]
        elif isinstance(func, list):
            if not all(callable(f) for f in func):
                raise TypeError("Provided list must contain only callables.")
            self._func = func
        else:
            raise TypeError("Provided 'func' must be a callable or a list of callables.")

        for f in self._func:
            # Updated type error to reflect the correct class name
            if inspect.iscoroutinefunction(f):
                raise TypeError("BypassConductor does not support coroutine functions.")

        self._id = str(ulid.ULID())
        self._limit = limit
        self._count = 0
        self._lock = threading.RLock()
        self._collapsed = False
        self._outcomes: List[Outcome] = []
        self._dynaphore = Dynaphore(limit)
        self._threshold_sema = ThresholdSemaphore(limit, reusable=True)
        self._outcome_set = False

    # --- NEW HELPER METHOD TO FIX RACE CONDITION ---
    def _try_claim_slot(self) -> bool:
        """Atomically checks for a slot and claims it if available."""
        # A quick unlocked check for performance on a busy gate
        if self._collapsed or self._count >= self._limit:
            return False

        with self._lock:
            # The definitive, locked check
            if self._collapsed or self._count >= self._limit:
                return False
            self._count += 1
            return True

    # --- REVISED transit() METHOD ---
    def transit(self):
        """
        Attempts to claim a slot and run the callable pipeline.

        Returns:
            None: This method's return is for bypassing; results are in `.outcomes()`.
        """
        if self._disposed:
            return None

        # Atomically check and claim a slot. If it fails, we bypass.
        if not self._try_claim_slot():
            return None

        # If we get here, a slot is successfully claimed.
        # We must decrement the count when done, so we use a finally block.
        try:
            for item in range(len(self._func)):
                self._dynaphore.acquire()
                try:
                    # Execute one stage of the pipeline
                    self._set_result(self._func[item]())
                except Exception as e:
                    self._set_exception(e)
                finally:
                    # Release the dynaphore, allowing another thread to start this stage
                    self._dynaphore.release()

                # Wait at the barrier for all other participating threads
                # to complete this stage before starting the next one.
                self._threshold_sema.wait()
                self._outcome_set = False  # Reset for the next stage

            # The first thread to complete the whole pipeline collapses the gate
            self._collapsed = True

        finally:
            # This now correctly executes exactly ONCE per thread that entered.
            self._decrement_count()

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
            if self._dynaphore:
                self._dynaphore.dispose()
                self._dynaphore = None
            if self._threshold_sema:
                self._threshold_sema.dispose()
                self._threshold_sema = None