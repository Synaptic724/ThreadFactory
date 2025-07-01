import inspect
from typing import Callable, List, Optional, Union, Any
from thread_factory.utils import IDisposable
from thread_factory.utils.coordination.outcome import Outcome

class Group(IDisposable):
    """
    Group (Data-Aware and Disposable Version)
    -----
    Represents a subgroup of threads. This version tracks the outcome of each of
    its tasks and provides a dispose method for explicit cleanup.
    """

    def __init__(self, threshold: int, tasks: Optional[Union[Callable, List[Callable]]] = None):
        """
        Args:
            threshold (int): The number of threads required for this group to be ready.
            tasks (Optional): A single function or a list of functions to be executed.
        """
        super().__init__()
        if threshold <= 0:
            raise ValueError("Threshold must be a positive integer.")

        self.threshold = threshold
        self.tasks: List[Callable] = []

        if tasks is not None:
            task_list = [tasks] if callable(tasks) else tasks
            if not isinstance(task_list, list) or not all(callable(cb) for cb in task_list):
                # Ensure the error message string matches exactly in tests
                raise TypeError("tasks must be a callable function or a list of callable functions.")

            for task in task_list:
                if inspect.iscoroutinefunction(task):
                    raise TypeError("Coroutines are not supported; only synchronous callables are allowed.")
                self.tasks.append(task)

        self.outcomes: List[Outcome] = [Outcome() for _ in self.tasks]

        self.count = 0
        self.ready = False
        self._released_once = False

    def dispose(self):
        """
        Disposes of the Group and all its contained Outcome objects.
        """
        if self.disposed:
            return

        # Dispose all Outcome objects if they exist BEFORE clearing the list or nullifying self.outcomes
        if self.outcomes:
            for outcome in self.outcomes:
                if outcome: # Ensure outcome is not None before calling dispose
                    outcome.dispose()

        # Clear lists and nullify references to aid garbage collection
        if self.tasks:
            self.tasks.clear()
        if self.outcomes: # Check if outcomes list still exists before clearing
            self.outcomes.clear()

        self.tasks = None
        self.outcomes = None
        self.threshold = None
        self.count = None
        self.ready = None
        self._released_once = None # This line is correct and should set it to None
        self._disposed = True


    def reset(self):
        """Resets the group's state for a new run."""
        if self.disposed:
            return
        self.count = 0
        self.ready = False
        self._released_once = False
        # Dispose existing Outcome objects before creating new ones
        if self.outcomes:
            for outcome in self.outcomes:
                if outcome:
                    outcome.dispose()
        # Re-initialize outcomes list with new Outcome objects
        self.outcomes = [Outcome() for _ in self.tasks]

    @property
    def results(self) -> List[Any]:
        """A convenience property to get only the successful results."""
        if self.disposed:
            return []
        successful = []
        for outcome in self.outcomes:
            # Check if outcome is not None (after dispose it could be)
            # and if it's done and has no exception
            if outcome and outcome.done and outcome.exception() is None:
                try:
                    successful.append(outcome.result())
                except Exception:
                    # If result() raises an exception (e.g., if disposed after done check),
                    # just skip this outcome.
                    pass
        return successful

    @property
    def exceptions(self) -> List[Exception]:
        """A convenience property to get only the exceptions."""
        if self.disposed:
            return []
        errors = []
        for outcome in self.outcomes:
            # Check if outcome is not None
            # and if it's done and has an exception
            if outcome and outcome.done: # Check if done first
                exc = outcome.exception()
                # Filter out the generic RuntimeError("Outcome was disposed.")
                # This check ensures we only collect actual task-generated exceptions.
                if exc is not None and not (isinstance(exc, RuntimeError) and str(exc) == "Outcome was disposed."):
                    try:
                        errors.append(exc)
                    except Exception:
                        # If exception() raises an exception (e.g., if disposed after done check),
                        # just skip this outcome.
                        pass
        return errors