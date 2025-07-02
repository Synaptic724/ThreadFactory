import inspect
from typing import List, Any, Callable, Optional, Union
import ulid
from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.utils.interfaces.disposable import IDisposable
from thread_factory.utils.coordination.outcome import Outcome


class Group(IDisposable):
    """
    Group
    -----
    A disposable, data-aware representation of a thread subgroup within a larger coordination structure.

    This object defines a threshold (number of threads required to activate it),
    executes a list of callable tasks, and tracks the result or exception of each via Outcome objects.

    The group supports explicit disposal, safe reuse via reset(), and inspection of results and exceptions.

    Usage Example:
    --------------
    >>> g = Group(threshold=3, tasks=[lambda: 1+1, lambda: 2+2])
    >>> g.tasks[0]()  # Execute first task manually (in a real system, this would be parallelized)
    >>> print(g.results)
    """

    __slots__ = IDisposable.__slots__ + [
        "threshold", "tasks", "outcomes", "count",
        "ready", "_released_once", "id", "name"
    ]

    def __init__(
        self,
        threshold: int,
        tasks: Optional[Union[Callable, List[Callable]]] = None,
        name: Optional[str] = None
    ):
        """
        Initializes the Group with a threshold and optional list of tasks.

        Args:
            threshold (int): Number of threads required for this group to become active.
            tasks (Optional): A single callable or list of callables to be executed by this group.
            name (Optional[str]): Optional name identifier for logging or referencing this group.

        Raises:
            ValueError: If threshold is not a positive integer.
            TypeError: If tasks is not a callable or list of callables.
        """
        super().__init__()
        if threshold <= 0:
            raise ValueError("Threshold must be a positive integer.")

        self.id = str(ulid.ULID())
        self.name = name or self.id
        self.threshold = threshold
        self.tasks: List[Callable] = []

        if tasks:
            task_list = [tasks] if callable(tasks) else tasks
            if not isinstance(task_list, list) or not all(callable(t) for t in task_list):
                raise TypeError("tasks must be a callable or a list of callables.")
            for task in task_list:
                if inspect.iscoroutinefunction(task):
                    raise TypeError("Coroutines are not supported.")
                self.tasks.append(task)

        self.outcomes = ConcurrentList([Outcome() for _ in self.tasks])
        self.count = 0
        self.ready = False
        self._released_once = False

    def dispose(self):
        """
        Fully disposes the Group and all Outcome objects it owns.

        This method clears all references to aid garbage collection.
        After disposal, calling methods like `results` or `exceptions` will return empty lists.
        """
        if self.disposed:
            return

        if self.outcomes:
            for outcome in self.outcomes:
                if outcome:
                    outcome.dispose()

        if self.tasks:
            self.tasks.clear()
        if self.outcomes:
            self.outcomes.clear()

        self.tasks = None
        self.outcomes = None
        self.threshold = None
        self.count = None
        self.ready = None
        self._released_once = None
        self._disposed = True

    def reset(self):
        """
        Resets the Group to its initial state for reuse.

        Disposes all Outcome objects and re-creates new ones for each task.
        Does not alter the tasks or the threshold.
        """
        if self.disposed:
            return
        self.count = 0
        self.ready = False
        self._released_once = False
        if self.outcomes:
            for outcome in self.outcomes:
                if outcome:
                    outcome.dispose()
        self.outcomes = ConcurrentList([Outcome() for _ in self.tasks])

    @property
    def results(self) -> List[Any]:
        """
        Returns:
            List[Any]: A list of results from tasks that completed successfully (no exception raised).
        """
        if self.disposed:
            return []
        successful = []
        for outcome in self.outcomes:
            if outcome and outcome.done and outcome.exception() is None:
                try:
                    successful.append(outcome.result())
                except Exception:
                    pass
        return successful

    @property
    def exceptions(self) -> List[Exception]:
        """
        Returns:
            List[Exception]: A list of exceptions from tasks that failed.

        Notes:
            Disposes often raise a `RuntimeError("Outcome was disposed.")`. This is filtered out.
        """
        if self.disposed:
            return []
        errors = []
        for outcome in self.outcomes:
            if outcome and outcome.done:
                exc = outcome.exception()
                if exc is not None and not (
                    isinstance(exc, RuntimeError) and str(exc) == "Outcome was disposed."
                ):
                    try:
                        errors.append(exc)
                    except Exception:
                        pass
        return errors
