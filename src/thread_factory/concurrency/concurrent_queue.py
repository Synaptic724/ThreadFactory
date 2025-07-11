import functools
import threading
import warnings
from collections import deque
from copy import deepcopy
from typing import (
    Any,
    Callable,
    Deque,
    Generic,
    Iterable,
    Iterator,
    Optional,
    TypeVar,
)
from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.utilities.interfaces.disposable import IDisposable
from thread_factory.utilities.exceptions import Empty

_T = TypeVar("_T")

class ConcurrentQueue(Generic[_T], IDisposable):
    """
    A thread-safe FIFO queue implementation using an underlying deque,
    a reentrant lock for synchronization, and an atomic counter for fast
    retrieval of the number of items.

    This class mimics common queue behaviors (enqueue, dequeue, peek, etc.).
    It is designed for Python 3.13+ No-GIL environments (though it will
    work fine in standard Python as well).
    """
    __slots__ = IDisposable.__slots__ + ["_lock", "_deque"]
    def __init__(
        self,
        initial: Optional[Iterable[_T]] = None
    ) -> None:
        """
        Initialize the ConcurrentQueue.

        Args:
            initial (Iterable[_T], optional):
                An iterable of initial items. Defaults to an empty list if None is given.
        """
        super().__init__()
        if initial is None:
            initial = []
        self._lock: threading.RLock = threading.RLock()
        self._deque: Deque[_T] = deque(initial)


    def dispose(self) -> None:
        """
        Dispose (clear) this ConcurrentQueue, releasing its contents.

        Once disposed, `_disposed` becomes True and the internal dict is cleared.
        No further usage checks are enforced, so the user must avoid calling
        other methods after disposal.

        This method is idempotent — multiple calls won't cause errors.
        """
        if not self._disposed:
            with self._lock:
                self._deque.clear()
            self._disposed = True
        warnings.warn(
            "Your ConcurrentQueue has been disposed and should not be used further. ",
            UserWarning
        )

    def enqueue(self, item: _T) -> None:
        """
        Add an item to the end of the queue (FIFO).

        Args:
            item (_T): The item to enqueue.
        """
        with self._lock:
            self._deque.append(item)

    def dequeue(self) -> _T:
        """
        Remove and return an item from the front of the queue.

        Raises:
            IndexError: If the queue is empty.

        Returns:
            _T: The item dequeued.
        """
        with self._lock:
            if not self._deque:
                raise Empty("dequeue from empty ConcurrentQueue")
            return self._deque.popleft()

    def peek(self) -> _T:
        """
        Return (but do not remove) the item at the front of the queue.

        Raises:
            IndexError: If the queue is empty.

        Returns:
            _T: The item at the front of the queue.
        """
        try:
            if not self._deque:
                raise Empty("peek from empty ConcurrentQueue")
            return self._deque[0]
        except IndexError:
            raise Empty("peek from empty ConcurrentQueue")

    def __len__(self) -> int:
        """
        Return the number of items in the queue, using the atomic counter.

        Returns:
            int: The current size of the queue.
        """
        return len(self._deque)

    def __bool__(self) -> bool:
        """
        Return True if the queue is non-empty.

        Returns:
            bool: True if non-empty, False otherwise.
        """
        return len(self._deque) != 0

    def __iter__(self) -> Iterator[_T]:
        """
        Return an iterator over a shallow copy of the internal deque.
        This prevents issues if the queue is modified during iteration.

        Returns:
            Iterator[_T]: An iterator over the items in the queue snapshot.
        """
        with self._lock:
            return iter(list(self._deque))

    def clear(self) -> None:
        """
        Remove all items from the queue.
        """
        with self._lock:
            self._deque.clear()

    def __repr__(self) -> str:
        """
        Return the official string representation of the ConcurrentQueue.
        """
        with self._lock:
            return f"{self.__class__.__name__}({list(self._deque)!r})"

    def __str__(self) -> str:
        """
        Return the informal string representation (like a list of items).
        """
        with self._lock:
            return str(list(self._deque))

    def copy(self) -> "ConcurrentQueue[_T]":
        """
        Return a shallow copy of the ConcurrentQueue.

        Returns:
            ConcurrentQueue[_T]: A new ConcurrentQueue with the same items.
        """
        with self._lock:
            return ConcurrentQueue(initial=list(self._deque))

    def __copy__(self) -> "ConcurrentQueue[_T]":
        """
        Return a shallow copy (for the built-in copy.copy(...)).

        Returns:
            ConcurrentQueue[_T]: A copy of this ConcurrentQueue.
        """
        return self.copy()

    def __deepcopy__(self, memo: dict) -> "ConcurrentQueue[_T]":
        """
        Return a deep copy of the ConcurrentQueue.

        Args:
            memo (dict): Memoization dictionary for deepcopy.

        Returns:
            ConcurrentQueue[_T]: A deep copy of this ConcurrentQueue.
        """
        with self._lock:
            return ConcurrentQueue(
                initial=deepcopy(list(self._deque), memo)
            )

    def empty(self):
        """
        Return True if the queue has no items.

        Returns:
            bool: True if the queue is empty, False otherwise.
        """
        with self._lock:
            return len(self._deque) == 0

    def is_empty(self) -> bool:
        """
        Return True if the queue has no items.

        Returns:
            bool: True if the queue is empty, False otherwise.
        """
        with self._lock:
            return len(self._deque) == 0

    def steal_batch(self, max_items: int = 4) -> ConcurrentList[_T]:
        """
        Atomically steal up to `max_items` from the tail of the queue.

        This is used in work-stealing contexts where idle threads pull
        work from the end (LIFO) of another thread's queue. Returned
        tasks are reversed to maintain correct execution order (FIFO).

        Args:
            max_items (int): Maximum number of items to steal.

        Returns:
            ConcurrentList[_T]: The stolen items, ordered for FIFO execution.
        """
        with self._lock:
            stolen = []
            for _ in range(min(max_items, len(self._deque))):
                stolen.append(self._deque.pop())
            stolen.reverse()  # FIFO preservation
            return ConcurrentList(initial=stolen)

    def to_concurrent_list(self) -> "ConcurrentList[_T]":
        """
        Return a shallow copy of the queue as a ConcurrentList.

        Returns:
            concurrent_list.ConcurrentList[_T]:
                A concurrency list containing all items currently in the queue.
        """

        with self._lock:
            return ConcurrentList(list(self._deque))

    def batch_update(self, func: Callable[[Deque[_T]], None]) -> None:
        """
        Perform a batch update on the queue under a single lock acquisition.
        This method allows multiple operations to be performed atomically.

        Args:
            func (Callable[[Deque[_T]], None]):
                A function that accepts the internal deque as its only argument.
                The function should perform all necessary mutations.
        """
        with self._lock:
            func(self._deque)

    def map(self, func: Callable[[_T], Any]) -> "ConcurrentQueue[Any]":
        """
        Apply a function to all elements and return a new ConcurrentQueue.

        Args:
            func (callable): The function to apply to each item.

        Returns:
            ConcurrentQueue[Any]: A new queue with func applied to each element.
        """
        with self._lock:
            mapped = list(map(func, self._deque))
        return ConcurrentQueue(initial=mapped)

    def filter(self, func: Callable[[_T], bool]) -> "ConcurrentQueue[_T]":
        """
        Filter elements based on a function and return a new ConcurrentQueue.

        Args:
            func (callable): The filter function returning True if item should be kept.

        Returns:
            ConcurrentQueue[_T]: A new queue containing only elements where func(item) is True.
        """
        with self._lock:
            filtered = list(filter(func, self._deque))
        return ConcurrentQueue(initial=filtered)

    def remove_item(self, item: _T) -> bool:
        """
        Remove the first occurrence of the item by identity (memory reference).

        Args:
            item (_T): The item to remove.

        Returns:
            bool: True if the item was found and removed, False otherwise.
        """
        with self._lock:
            for i, current in enumerate(self._deque):
                if current is item:
                    del self._deque[i]
                    return True
        return False

    def reduce(self, func: Callable[[Any, _T], Any], initial: Optional[Any] = None) -> Any:
        """
        Apply a function of two arguments cumulatively to the items of the queue.

        Args:
            func (Callable[[Any, _T], Any]): Function of the form func(accumulator, item).
            initial (optional): Starting value.

        Returns:
            Any: The reduced value.

        Raises:
            TypeError: If the queue is empty and no initial value is provided.

        Example:
            def add(acc, x):
                return acc + x
            total = concurrent_queue.reduce(add, 0)
        """
        with self._lock:
            items_copy = list(self._deque)

        if not items_copy and initial is None:
            raise TypeError("reduce() of empty ConcurrentQueue with no initial value")

        if initial is None:
            return functools.reduce(func, items_copy)
        else:
            return functools.reduce(func, items_copy, initial)


    # -----------------------------------------------------------------------------------
    # Disposable Implementation
    # -----------------------------------------------------------------------------------
    def __enter__(self):
        """
        Enter the runtime context.

        - Acquires the internal lock for direct access.
        - Allows `with ConcurrentQueue(...) as cc:` style usage.
        - WARNING: Using the context manager bypasses the thread-safe method interface.
                   You are now responsible for ensuring correct multithreaded behavior.
        """
        warnings.warn(
            "Direct access to the internals via the context manager bypasses "
            "the thread-safe interface. Use with extreme caution.",
            UserWarning
        )
        self._lock.acquire()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """
        Exit the runtime context.

        Responsibilities:
          - Releases the internal lock acquired in `__enter__()`.
          - Automatically calls `dispose()` to ensure the object is cleaned up.
          - This pattern ensures the object is safely disposed even if an exception
            occurs within the `with` block.

        Notes:
          - The object should be considered invalid after exiting the context.
          - This design mimics resource safety patterns seen in systems like C#'s `IDisposable`
            and C++ RAII.
          - Users are free to manage `dispose()` manually if they choose not to use the
            context manager.

        Args:
            exc_type: Exception type (if raised).
            exc_val: Exception value (if raised).
            exc_tb: Exception traceback (if raised).
        """
        self._lock.release()
        self.dispose()

