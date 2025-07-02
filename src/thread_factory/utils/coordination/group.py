from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.concurrency.concurrent_list import ConcurrentList
import inspect
from typing import List, Any, Callable, Optional, Union, Iterable
import ulid
from thread_factory.utils.interfaces.disposable import IDisposable
from thread_factory.utils.coordination.outcome import Outcome  # 👈 Add this for eager init

class Group(IDisposable):
    """
    A disposable, data-aware representation of a group of tasks.
    It now supports tracking a single result or multiple results per task,
    making it suitable for reusable coordination objects.
    """
    __slots__ = IDisposable.__slots__ + [
        "threshold", "tasks", "outcomes", "count",
        "ready", "_released_once", "id", "name", "_multiple_outcomes_per_task"
    ]

    def __init__(
        self,
        name: str,
        tasks: Optional[Union[Callable, List[Callable]]] = None,
        multiple_outcomes_per_task: bool = False
    ):
        """
        Initializes the Group.

        Args:
            name (str): A required name to identify this group.
            tasks (Optional): A single callable or list of callables.
            multiple_outcomes_per_task (bool): If True, allows storing multiple
                outcomes for each task. Defaults to False.
        """
        super().__init__()
        self.id = str(ulid.ULID())
        self.name = name
        self.tasks: List[Callable] = []
        self._multiple_outcomes_per_task = multiple_outcomes_per_task

        if tasks:
            task_list = [tasks] if callable(tasks) else tasks
            if not isinstance(task_list, list) or not all(callable(t) for t in task_list):
                raise TypeError("tasks must be a callable or a list of callables.")
            for task in task_list:
                if inspect.iscoroutinefunction(task):
                    raise TypeError("Coroutines are not supported.")
                self.tasks.append(task)

        self.outcomes = ConcurrentDict()
        self.reset()

    def dispose(self):
        """Fully disposes the Group and all its Outcome objects."""
        if self.disposed:
            return

        if self.outcomes:
            for bucket in self.outcomes.values():
                outcomes_to_dispose = bucket if self._multiple_outcomes_per_task else [bucket]
                if outcomes_to_dispose:
                    for outcome in outcomes_to_dispose:
                        if outcome:
                            outcome.dispose()
        self.outcomes.clear()
        self.tasks.clear()
        self._disposed = True

    def reset(self):
        """Resets the Group for reuse by clearing all outcomes."""
        if self.disposed:
            return

        if self.outcomes:
            self._dispose_outcomes()

        if self._multiple_outcomes_per_task:
            self.outcomes = ConcurrentDict({i: ConcurrentList() for i, _ in enumerate(self.tasks)})
        else:
            self.outcomes = ConcurrentDict({i: Outcome() for i, _ in enumerate(self.tasks)})  # ✅ FIXED

    def _dispose_outcomes(self):
        """Disposes only the outcomes, not the whole Group."""
        for bucket in self.outcomes.values():
            outcomes_to_dispose = bucket if self._multiple_outcomes_per_task else [bucket]
            if outcomes_to_dispose:
                for outcome in outcomes_to_dispose:
                    if outcome:
                        outcome.dispose()
        self.outcomes.clear()

    def _iter_outcomes(self) -> Iterable['Outcome']:
        """A helper to iterate through all Outcome objects regardless of storage mode."""
        if not self.outcomes:
            return

        for bucket in self.outcomes.values():
            if bucket is None:
                continue
            if self._multiple_outcomes_per_task:
                yield from bucket
            else:
                yield bucket

    @property
    def results(self) -> List[Any]:
        """Returns a list of all successful results from all tasks."""
        if self.disposed:
            return []
        successful = []
        for outcome in self._iter_outcomes():
            if outcome and outcome.done and outcome.exception() is None:
                try:
                    successful.append(outcome.result())
                except Exception:
                    pass
        return successful

    @property
    def exceptions(self) -> List[Exception]:
        """Returns a list of all exceptions from failed tasks."""
        if self.disposed:
            return []
        errors = []
        for outcome in self._iter_outcomes():
            if outcome and outcome.done:
                exc = outcome.exception()
                if exc and not (isinstance(exc, RuntimeError) and "disposed" in str(exc)):
                    errors.append(exc)
        return errors
