import threading
from collections import deque
from copy import deepcopy
import functools
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
from ...ThreadFactory.Threading.List import ConcurrentList
from utils.exceptions import Empty

_T = TypeVar("_T")

class ConcurrentStack(Generic[_T]):
    """
    A thread-safe LIFO stack implementation using an underlying deque,
    a reentrant lock for synchronization, and an atomic counter for fast
    retrieval of the number of items.

    This class mimics common stack behaviors (push, pop, peek, etc.).
    It is designed for Python 3.13+ No-GIL environments (though it will
    work fine in standard Python as well).
    """

    def __init__(
            self,
            initial: Optional[Iterable[_T]] = None
    ) -> None:
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
        with self._lock:
            if not self._deque:
                raise Empty("peek from empty ConcurrentStack")
            return self._deque[-1]

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
                A concurrent list containing all items currently in the stack.
        """
        with self._lock:
            return ConcurrentList(list(self._deque))

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
