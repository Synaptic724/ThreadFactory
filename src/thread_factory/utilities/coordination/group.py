from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.concurrency.concurrent_list import ConcurrentList
from typing import List, Any, Callable, Optional, Union, Iterable
from thread_factory.utilities.interfaces.disposable import IDisposable
from thread_factory.utilities.coordination.outcome import Outcome
from thread_factory.utilities.coordination.package import Pack
import ulid


class Group(IDisposable):
    """
    Group
    -----
    A disposable, thread-safe, data-aware representation of a group of Pack-wrapped callables.
    Suitable for coordination, tracking, and organized reuse in multithreaded systems.
    Tracks outcomes per task and supports optional multi-outcome-per-task mode.
    """

    __slots__ = IDisposable.__slots__ + [
        "threshold", "tasks", "outcomes", "count",
        "ready", "_released_once", "id", "name",
        "_multiple_outcomes_per_task"
    ]

    def __init__(
        self,
        name: str,
        tasks: Optional[Union[Callable, Pack, List[Union[Callable, Pack]]]] = None,
        multiple_outcomes_per_task: bool = False
    ):
        """
        Initialize a Group of callable tasks.

        Args:
            name: A descriptive name for the group.
            tasks: A single callable/Pack or a list of them.
            multiple_outcomes_per_task: If True, allows each task to have a list of Outcome results.
        """
        super().__init__()
        self.id = str(ulid.ULID())
        self.name = name
        self._multiple_outcomes_per_task = multiple_outcomes_per_task

        if tasks is None:
            self.tasks: ConcurrentList[Pack] = ConcurrentList()
        else:
            packified_result = Pack.bundle(tasks)
            if isinstance(packified_result, Pack):
                # If bundle returned a single Pack, put it into a list
                self.tasks = ConcurrentList([packified_result])
            else:
                # If bundle returned a ConcurrentList (for iterables), use it directly
                self.tasks = packified_result

        self.outcomes: ConcurrentDict[int, Union[Outcome, ConcurrentList[Outcome]]] = ConcurrentDict()
        self.reset()

    def dispose(self):
        """
        Fully dispose the Group and its Outcomes. Clears all state and makes the object unusable.
        """
        if self.disposed:
            return

        for bucket in self.outcomes.values():
            outcomes_to_dispose = bucket if self._multiple_outcomes_per_task else [bucket]
            for outcome in outcomes_to_dispose:
                if outcome:
                    outcome.dispose()

        self.outcomes.clear()
        self.tasks.clear()
        self._disposed = True


    def __len__(self):
        """
        Return the number of tasks currently stored in the group.

        Returns:
            int: The number of registered Pack-wrapped callables.
        """
        return len(self.tasks)

    def __repr__(self):
        """
        Return a string representation of the Group.
        """
        return f"<Group name={self.name!r} id={self.id} tasks={len(self.tasks)}>"

    def __contains__(self, item: Union[Callable, Pack]) -> bool:
        """
        Check if a task is registered in the group.
        """
        return Pack.bundle(item) in self.tasks

    def __iter__(self):
        """
        Allow iteration over the group's tasks.
        """
        if self.disposed:
            return iter([])
        return iter(self.tasks)

    def register(self, task: Union[Callable, Pack]) -> int:
        """
        Register a new task dynamically after init.

        Returns:
            Index of the new task in the group.
        """
        p = Pack.bundle(task)
        if not p:
            raise TypeError(f"Invalid task: {task}")
        index = len(self.tasks)
        self.tasks.append(p)
        self.outcomes[index] = ConcurrentList() if self._multiple_outcomes_per_task else Outcome()
        return index

    def __len__(self):
        """
        Return the number of tasks currently stored in the group.

        Returns:
            int: The number of registered Pack-wrapped callables.
        """
        return len(self.tasks)

    def reset(self):
        """
        Resets the Group for reuse. Clears existing outcomes and rebuilds outcome storage.
        """
        if self.disposed:
            return

        self._dispose_outcomes()

        if self._multiple_outcomes_per_task:
            self.outcomes = ConcurrentDict({i: ConcurrentList() for i in range(len(self.tasks))})
        else:
            self.outcomes = ConcurrentDict({i: Outcome() for i in range(len(self.tasks))})

    def _dispose_outcomes(self):
        """
        Internal helper to dispose of outcomes without touching the task list.
        """
        for bucket in self.outcomes.values():
            outcomes_to_dispose = bucket if self._multiple_outcomes_per_task else [bucket]
            for outcome in outcomes_to_dispose:
                if outcome:
                    outcome.dispose()
        self.outcomes.clear()

    def _iter_outcomes(self) -> Iterable[Outcome]:
        """
        Internal helper to iterate over all Outcome objects, regardless of storage mode.
        """
        for bucket in self.outcomes.values():
            if bucket is None:
                continue
            if self._multiple_outcomes_per_task:
                yield from bucket
            else:
                yield bucket

    @property
    def results(self) -> ConcurrentList[Any]:
        """
        Get all successful results from the group's outcomes.

        Returns:
            A list of non-exceptional result values from completed outcomes.
        """
        if self.disposed:
            return ConcurrentList()

        successful = ConcurrentList()
        for outcome in self._iter_outcomes():
            if outcome and outcome.done and outcome.exception() is None:
                try:
                    successful.append(outcome.result())
                except Exception:
                    continue
        return successful

    @property
    def exceptions(self) -> ConcurrentList[Exception]:
        """
        Get all exceptions raised by tasks in the group.

        Returns:
            A list of exceptions from completed outcomes that failed.
        """
        if self.disposed:
            return ConcurrentList()

        errors = ConcurrentList()
        for outcome in self._iter_outcomes():
            if outcome and outcome.done:
                exc = outcome.exception()
                if exc and not (isinstance(exc, RuntimeError) and "disposed" in str(exc)):
                    errors.append(exc)
        return errors
