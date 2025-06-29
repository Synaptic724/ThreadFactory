import inspect
import threading
import time
from typing import Optional, Callable, List, Union, Any
from thread_factory.utils import IDisposable
from thread_factory.utils.coordination.outcome import Outcome


class Conductor(IDisposable):
    """
    Conductor (V2.3 - Final, Corrected)
    ------------------------------
    A reusable, data-aware barrier that executes tasks and captures their outcomes
    once a predefined threshold of threads is reached.
    """
    __slots__ = IDisposable.__slots__ + [
        "threshold", "tasks", "reusable", "manual_release",
        "_timeout", "_raise_on_timeout", "outcomes",
        "_lock", "_condition", "_count", "_released", "_broken", "_start_time"
    ]

    def __init__(
            self,
            threshold: int,
            tasks: Optional[Union[Callable, List[Callable]]] = None,
            reusable: bool = False,
            manual_release: bool = False,
            timeout: Optional[float] = None,
            raise_on_timeout: bool = False
    ):
        super().__init__()
        if threshold <= 0:
            raise ValueError("Threshold must be a positive integer.")

        self.threshold = threshold
        self.reusable = reusable
        self.manual_release = manual_release
        self._timeout = timeout
        self._raise_on_timeout = raise_on_timeout

        self.tasks: List[Callable] = []
        if tasks:
            task_list = [tasks] if callable(tasks) else tasks
            if not isinstance(task_list, list) or not all(callable(cb) for cb in task_list):
                raise TypeError("tasks must be a callable function or a list of callables.")

            for task in task_list:
                if inspect.iscoroutinefunction(task):
                    raise TypeError("Coroutines are not supported; only synchronous callables are allowed.")
                self.tasks.append(task)

        self.outcomes: List[Outcome] = [Outcome() for _ in self.tasks]
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._count = 0
        self._released = False
        self._broken = False
        self._start_time = None

    def dispose(self):
        if self._disposed: return
        with self._condition:
            self._disposed = True
            for outcome in self.outcomes: outcome.dispose()
            self.outcomes.clear()
            self._broken = True
            self._released = True
            self._condition.notify_all()

    def reset(self):
        for o in self.outcomes: o.dispose()
        self.outcomes = [Outcome() for _ in self.tasks]
        self._released = False
        self._broken = False
        self._start_time = None
        self._count = 0

    @property
    def results(self) -> List[Any]:
        if self._disposed: return []
        return [o.result() for o in self.outcomes if o.done and o.exception() is None]

    @property
    def exceptions(self) -> List[Exception]:
        if self._disposed: return []
        return [o.exception() for o in self.outcomes if o.done and o.exception() is not None]

    def is_spent(self) -> bool:
        return self._released and not self.reusable

    def release(self) -> None:
        with self._condition:
            if self._disposed: return
            if self.manual_release and self._count >= self.threshold and not self._released:
                self._released = True
                self._condition.notify_all()

    def notify_all_override(self) -> None:
        with self._condition:
            if self._disposed or self._released: return
            self._released = True
            self._broken = True
            self._condition.notify_all()

    def wait(self, timeout: Optional[float] = None) -> bool:
        with self._condition:
            if self._disposed: return False
            if self._broken: return False
            if self._released and not self.reusable: return True

            if self._start_time is None: self._start_time = time.monotonic()

            self._count += 1

            if self._count == self.threshold and not self._released:
                for i, task in enumerate(self.tasks):
                    outcome = self.outcomes[i]
                    try:
                        result = task()
                        outcome.set_result(result)
                    except Exception as e:
                        outcome.set_exception(e)

                if not self.manual_release:
                    self._released = True
                    self._condition.notify_all()

            effective_timeout = timeout if timeout is not None else self._timeout
            remaining = effective_timeout
            if self._start_time is not None and effective_timeout is not None:
                elapsed = time.monotonic() - self._start_time
                remaining = max(0, effective_timeout - elapsed)

            was_released = self._condition.wait_for(
                lambda: self._released or self._disposed, timeout=remaining
            )

            # *** THE FIX: Capture the state BEFORE any reset logic runs. ***
            is_broken_on_exit = self._broken

            if not was_released and not self._disposed:
                self._broken = True
                self._released = True
                self._condition.notify_all()
                if self._raise_on_timeout:
                    raise TimeoutError(f"Conductor wait timed out after {effective_timeout}s.")

            if self.reusable and self._released:
                self._count -= 1
                if self._count == 0:
                    self.reset()

            return was_released and not self._disposed and not is_broken_on_exit