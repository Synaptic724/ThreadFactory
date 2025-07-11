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
from thread_factory.concurrency import ConcurrentList
from thread_factory.utilities.interfaces.disposable import IDisposable
from thread_factory.utilities.exceptions import Empty

_T = TypeVar("_T")

class ConcurrentStack(Generic[_T], IDisposable):
    """
    A thread-safe LIFO stack implementation using an underlying deque,
    a reentrant lock for synchronization, and an atomic counter for fast
    retrieval of the number of items.

    This class mimics common stack behaviors (push, pop, peek, etc.).
    It is designed for Python 3.13+ No-GIL environments (though it will
    work fine in standard Python as well).
    """
    __slots__ = IDisposable.__slots__ + ["_lock", "_deque"]
    def __init__(
            self,
            initial: Optional[Iterable[_T]] = None
    ) -> None:
        super().__init__()
        """
        Initialize the ConcurrentStack.

        Args:
            initial (Iterable[_T], optional):
                An iterable of initial items. Defaults to an empty list if None is given.
        """
        if initial is None:
            initial = []
        self._lock: threading.RLock = threading.RLock()
        self._deque: Deque[_T] = deque(initial)

    def dispose(self) -> None:
        """
        Dispose (clear) this ConcurrentStack, releasing its contents.

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
            "Your ConcurrentStack has been disposed and should not be used further. ",
            UserWarning
        )


    def push(self, item: _T) -> None:
        """
        Push an item onto the top of the stack (LIFO).

        Args:
            item (_T): The item to push.
        """
        with self._lock:
            self._deque.append(item)

    def pop(self) -> _T:
        """
        Remove and return an item from the top of the stack.

        Raises:
            IndexError: If the stack is empty.

        Returns:
            _T: The item popped.
        """
        with self._lock:
            if not self._deque:
                raise Empty("pop from empty ConcurrentStack")
            return self._deque.pop()

    def peek(self) -> _T:
        """
        Return (but do not remove) the item at the top of the stack.

        Raises:
            IndexError: If the stack is empty.

        Returns:
            _T: The item at the top of the stack.
        """
        try:
            if not self._deque:
                raise Empty("peek from empty ConcurrentStack")
            return self._deque[-1]
        except IndexError:
            raise Empty("peek from empty ConcurrentStack")

    def __len__(self) -> int:
        """
        Return the number of items in the stack, using the atomic counter.

        Returns:
            int: The current size of the stack.
        """
        return len(self._deque)

    def __bool__(self) -> bool:
        """
        Return True if the stack is non-empty.

        Returns:
            bool: True if non-empty, False otherwise.
        """
        return len(self._deque) != 0

    def __iter__(self) -> Iterator[_T]:
        """
        Return an iterator over a shallow copy of the internal deque.
        This prevents issues if the stack is modified during iteration.

        Note: The iteration order here will be from bottom to top (front of the deque
        to the back of the deque), which is effectively left-to-right in the underlying
        deque. Adjust if you want top-to-bottom iteration.
        """
        with self._lock:
            return iter(list(self._deque))

    def clear(self) -> None:
        """
        Remove all items from the stack.
        """
        with self._lock:
            self._deque.clear()

    def __repr__(self) -> str:
        """
        Return the official string representation of the ConcurrentStack.
        """
        with self._lock:
            return f"{self.__class__.__name__}({list(self._deque)!r})"

    def __str__(self) -> str:
        """
        Return the informal string representation (like a list of items).
        """
        with self._lock:
            return str(list(self._deque))

    def copy(self) -> "ConcurrentStack[_T]":
        """
        Return a shallow copy of the ConcurrentStack.

        Returns:
            ConcurrentStack[_T]: A new ConcurrentStack with the same items.
        """
        with self._lock:
            return ConcurrentStack(initial=list(self._deque))

    def __copy__(self) -> "ConcurrentStack[_T]":
        """
        Return a shallow copy (for the built-in copy.copy(...)).

        Returns:
            ConcurrentStack[_T]: A copy of this ConcurrentStack.
        """
        return self.copy()


    def is_empty(self) -> bool:
        """
        Check if the stack is empty.

        Returns:
            bool: True if the stack is empty, False otherwise.
        """
        with self._lock:
            return len(self._deque) == 0

    def __deepcopy__(self, memo: dict) -> "ConcurrentStack[_T]":
        """
        Return a deep copy of the ConcurrentStack.

        Args:
            memo (dict): Memoization dictionary for deepcopy.

        Returns:
            ConcurrentStack[_T]: A deep copy of this ConcurrentStack.
        """
        with self._lock:
            return ConcurrentStack(
                initial=deepcopy(list(self._deque), memo)
            )

    def to_concurrent_list(self) -> "ConcurrentList[_T]":
        """
        Return a shallow copy of the stack as a ConcurrentList.

        Returns:
            ConcurrentList[_T]:
                A concurrency list containing all items currently in the stack.
        """
        with self._lock:
            return ConcurrentList(list(self._deque))

    def steal_batch(self, max_items: int = 4) -> ConcurrentList[_T]:
        """
        Atomically steal up to `max_items` from the head of the stack.

        This is used in work-stealing contexts where idle threads pull
        work from the front (FIFO) of another thread's stack. Returned
        tasks are reversed to maintain correct execution order (LIFO).

        Args:
            max_items (int): Maximum number of items to steal.

        Returns:
            ConcurrentList[_T]: The stolen items, ordered for FIFO execution.
        """
        with self._lock:
            stolen = []
            for _ in range(min(max_items, len(self._deque))):
                stolen.append(self._deque.popleft())
            stolen.reverse()  # FIFO preservation
            return ConcurrentList(initial=stolen)

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

    def batch_update(self, func: Callable[[Deque[_T]], None]) -> None:
        """
        Perform a batch update on the stack under a single lock acquisition.
        This method allows multiple operations to be performed atomically.

        Args:
            func (Callable[[Deque[_T]], None]):
                A function that accepts the internal deque as its only argument.
                The function should perform all necessary mutations.
        """
        with self._lock:
            func(self._deque)

    def map(self, func: Callable[[_T], Any]) -> "ConcurrentStack[Any]":
        """
        Apply a function to all elements and return a new ConcurrentStack.

        Args:
            func (callable): The function to apply to each item.

        Returns:
            ConcurrentStack[Any]: A new stack with func applied to each element.
        """
        with self._lock:
            mapped = list(map(func, self._deque))
        return ConcurrentStack(initial=mapped)

    def filter(self, func: Callable[[_T], bool]) -> "ConcurrentStack[_T]":
        """
        Filter elements based on a function and return a new ConcurrentStack.

        Args:
            func (callable): The filter function returning True if item should be kept.

        Returns:
            ConcurrentStack[_T]: A new stack containing only elements where func(item) is True.
        """
        with self._lock:
            filtered = list(filter(func, self._deque))
        return ConcurrentStack(initial=filtered)

    def reduce(self, func: Callable[[Any, _T], Any], initial: Optional[Any] = None) -> Any:
        """
        Apply a function of two arguments cumulatively to the items of the stack.

        Args:
            func (Callable[[Any, _T], Any]): Function of the form func(accumulator, item).
            initial (optional): Starting value.

        Returns:
            Any: The reduced value.

        Raises:
            TypeError: If the stack is empty and no initial value is provided.

        Example:
            def add(acc, x):
                return acc + x
            total = concurrent_stack.reduce(add, 0)
        """
        with self._lock:
            items_copy = list(self._deque)

        if not items_copy and initial is None:
            raise TypeError("reduce() of empty ConcurrentStack with no initial value")

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
        - Allows `with ConcurrentStack(...) as cc:` style usage.
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
