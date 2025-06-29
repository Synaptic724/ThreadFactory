import inspect
from typing import Callable, List, Optional, Union, Any
from thread_factory.utils import IDisposable
from thread_factory.utils.coordination.outcome import Outcome


# Assuming Outcome class is available
# from .outcome import Outcome

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

        if self.outcomes:
            for outcome in self.outcomes:
                outcome.dispose()

        self.tasks.clear()
        self.outcomes.clear()

        self.tasks = None
        self.outcomes = None
        self.threshold = None
        self.count = None
        self.ready = None
        self._disposed = True


    def reset(self):
        """Resets the group's state for a new run."""
        if self.disposed:
            return
        self.count = 0
        self.ready = False
        self._released_once = False
        self.outcomes = [Outcome() for _ in self.tasks]

    @property
    def results(self) -> List[Any]:
        """A convenience property to get only the successful results."""
        if self.disposed:
            return []
        successful = []
        for outcome in self.outcomes:
            if outcome.done and outcome.exception() is None:
                successful.append(outcome.result())
        return successful

    @property
    def exceptions(self) -> List[Exception]:
        """A convenience property to get only the exceptions."""
        if self.disposed:
            return []
        errors = []
        for outcome in self.outcomes:
            if outcome.done and outcome.exception() is not None:
                errors.append(outcome.exception())
        return errors