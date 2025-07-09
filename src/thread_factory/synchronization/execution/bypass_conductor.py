import threading, ulid
from typing import Callable, Optional, List, Any, Union
from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.synchronization.primitives.dynaphore import Dynaphore
from thread_factory.synchronization.primitives.signal_barrier import SignalBarrier
from thread_factory.utilities.coordination.package import Pack
from thread_factory.utilities.interfaces.disposable import IDisposable
from thread_factory.utilities.coordination.outcome import Outcome


class BypassConductor(IDisposable):
    """
    BypassConductor
    -----------
    A limited-entry execution gate that runs a pre-bound callable up to N times.

    Features:
    ---------
    • Callable is supplied at construction.
    • Up to `limit` threads may execute the callable; others skip.
    • Each successful execution returns an Outcome tracking result or exception.

    Args:
        func (Union[Callable, list[Callable]]):
            A synchronous function or a list of functions to execute in a pipeline.
            If a single callable, it can accept arguments passed via *args and **kwargs.
        limit (int):
            Maximum number of allowed executions.
        *args:
            Positional args to pass to the callable if it's a single item.
        **kwargs:
            Keyword args to pass to the callable if it's a single item.

    Example:
    --------
    >>> def log_task(): print("Task complete")
    >>> conductor = BypassConductor(log_task, limit=3)
    >>> outcome = conductor.transit()
    """

    __slots__ = IDisposable.__slots__ + [
        "_limit", "_count", "_lock", "_collapsed", "_outcomes", "_func",
        "_dynaphore", "_threshold_sema", "_outcome_set", "_id"
    ]

    def __init__(self, func: Union[Union[Callable[..., Any], Pack], list[Union[Callable[..., Any], Pack]],
    ConcurrentList[Union[Callable[..., Any], Pack]]], limit: int = 1):
        super().__init__()
        if limit < 0:
            raise ValueError("Limit must be non-negative")

        # --- Callable Handling ---
        packified_result = Pack.bundle(func)
        if isinstance(packified_result, Pack):
            self._func = [packified_result]
        else: # It must be a ConcurrentList[Package] because Pack.Packify guarantees valid output
            self._func = packified_result

        # --- Synchronization Primitives ---
        self._lock = threading.RLock()
        self._dynaphore: Dynaphore = Dynaphore(limit)
        self._threshold_sema: SignalBarrier = SignalBarrier(limit, reusable=True)

        # --- State Management ---
        self._id: str = str(ulid.ULID())
        self._limit: int = limit
        self._count: int = 0
        self._collapsed: bool = False
        self._outcome_set = False

        # --- Outcomes Storage ---
        self._outcomes: ConcurrentList[Outcome] = ConcurrentList()


    def dispose(self):
        """
        Disposes internal structures and clears all state.

        Behavior:
            - Disables further access.
            - Frees the dynaphore and threshold barrier.
            - Clears the outcomes list.
        """
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

    def _try_claim_slot(self) -> bool:
        """
        Attempt to atomically claim a slot for execution.

        Returns:
            bool: True if this thread successfully claimed a slot and is allowed to proceed;
                  False if the gate is collapsed or all slots are used.
        """
        # A quick unlocked check for performance on a busy gate
        if self._collapsed or self._count >= self._limit:
            return False

        with self._lock:
            # The definitive, locked check
            if self._collapsed or self._count >= self._limit:
                return False
            self._count += 1
            return True

    def transit(self):
        """
        Attempts to claim a slot and run the callable pipeline.

        Returns:
            None: No value is returned. Results are stored internally and accessed via `.outcomes()`.

        Behavior:
            - Only `limit` threads may pass through.
            - Each thread runs all steps in the pipeline sequentially.
            - A thread waits at a barrier between steps to ensure all threads sync up before moving forward.
            - After the final step, the gate is collapsed.
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

                    # Debugging the arguments passed to the function
                    print(
                        f"Running stage {item} with args: {self._func[item]._args} and kwargs: {self._func[item]._kwargs}")
                    # Execute one stage of the pipeline
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
        """
        Increases the number of available execution slots.

        Args:
            n (int): Number of new permits to add.

        Raises:
            ValueError: If n is negative.
        """
        if n < 0:
            raise ValueError("Cannot increase by negative")
        self._dynaphore.increase_permits(n)
        with self._lock:
            self._limit += n
            self._threshold_sema.set_threshold(self._limit)

    def decrease_limit(self, n: int = 1):
        """
        Decreases the number of available execution slots.

        Args:
            n (int): Number of permits to remove.

        Raises:
            ValueError: If n is negative.
        """
        if n < 0:
            raise ValueError("Cannot decrease by negative")
        self._dynaphore.decrease_permits(n)
        with self._lock:
            self._limit = max(0, self._limit - n)
            self._threshold_sema.set_threshold(self._limit)


    def _increase_count(self):
        """
        Internal method to increment the number of active executions.

        Raises:
            RuntimeError: If incrementing would exceed the allowed limit.
        """
        with self._lock:
            if self._count >= self._limit:
                raise RuntimeError("Count exceeds limit")
            self._count += 1

    def _decrement_count(self):
        """
        Internal method to decrement the number of active executions.
        Called after thread completes its pipeline.
        """
        with self._lock:
            if self._count > 0:
                self._count -= 1

    def _set_result(self, result: Any):
        """
        Records a successful result for this pipeline stage.

        Args:
            result (Any): The return value of the executed function.
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
        Records an exception raised during pipeline execution.

        Args:
            e (Exception): The exception thrown by a pipeline stage.
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
        """
        Collapses the gate, preventing any new threads from entering.
        This can be triggered manually or after the final stage completes.
        """
        with self._lock:
            self._collapsed = True

    def reset(self, new_limit: Optional[int] = None):
        """
        Resets the conductor to its original state or a new limit.

        Args:
            new_limit (Optional[int]):
                If provided, sets a new limit on executions.

        Raises:
            ValueError: If the new limit is negative.
        """
        with self._lock:
            self._count = 0
            if new_limit is not None:
                if new_limit < 0:
                    raise ValueError("New limit must be non-negative")
                self._limit = new_limit
            self._collapsed = False
            self._outcomes.clear()

    def outcomes(self) -> ConcurrentList[Outcome]:
        """
        Retrieve the list of outcomes recorded so far.

        Returns:
            List[Outcome]: A list of result/exception Outcome objects, one per stage.
        """
        return self._outcomes