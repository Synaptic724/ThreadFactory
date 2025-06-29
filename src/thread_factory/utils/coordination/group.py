import inspect
from typing import Callable, List, Optional, Union, Any
from thread_factory.utils import IDisposable
from thread_factory.utils.coordination.outcome import Outcome

# Assuming the Outcome class from above is available

class Group(IDisposable):
    """
    Group (Data-Aware Version)
    -----
    Represents a subgroup of threads. This version is now integrated with
    the Outcome object to track the result of each of its callbacks.
    """

    def __init__(self, threshold: int, callbacks: Optional[Union[Callable, List[Callable]]] = None):
        super().__init__()
        if threshold <= 0:
            raise ValueError("Threshold must be a positive integer.")

        self.threshold = threshold
        self.callbacks: List[Callable] = []

        if callbacks is not None:
            callback_list = [callbacks] if callable(callbacks) else callbacks
            if not isinstance(callback_list, list) or not all(callable(cb) for cb in callback_list):
                 raise TypeError("callbacks must be a callable function or a list of callable functions.")

            for cb in callback_list:
                if inspect.iscoroutinefunction(cb):
                    raise TypeError("Coroutines are not supported; only synchronous callables are allowed.")
                self.callbacks.append(cb)

        # --- NEW INTEGRATION ---
        # Create a corresponding Outcome object for each callback.
        # This creates a one-to-one mapping between a task and its future result.
        self.outcomes: List[Outcome] = [Outcome() for _ in self.callbacks]

        # --- Internal State ---
        self.count = 0
        self.ready = False
        self._released_once = False

    @property
    def results(self) -> List[Any]:
        """A convenience property to get only the successful results."""
        successful = []
        for outcome in self.outcomes:
            # Only try to get the result if we know it's done and didn't fail
            if outcome.done and outcome.exception() is None:
                successful.append(outcome.result())
        return successful

    @property
    def exceptions(self) -> List[Exception]:
        """A convenience property to get only the exceptions."""
        errors = []
        for outcome in self.outcomes:
            if outcome.done and outcome.exception() is not None:
                # We can safely call exception() again as it doesn't raise
                errors.append(outcome.exception())
        return errors