import threading
import atomics
from collections import deque
from copy import deepcopy
import functools
import warnings
from typing import (
    Any,
    Callable,
    Deque,
    Generic,
    Iterable,
    Iterator,
    List,
    Optional,
    TypeVar,
)
from Threading.List import ConcurrentList

# We'll use a generic type variable for items stored in the queue.
_T = TypeVar("_T")

class ConcurrentQueue(Generic[_T]):
    """
    A thread-safe FIFO queue implementation using an underlying deque,
    a reentrant lock for synchronization, and an atomic counter for fast,
    lock-free retrieval of the number of items.

    This class mimics common queue behaviors (enqueue, dequeue, peek, etc.).
    It is designed for Python 3.13+ No-GIL environments (though it will
    work fine in standard Python as well).
    """

    def __init__(
        self,
        initial: Optional[Iterable[_T]] = None,
        width: int = 8
    ) -> None:
        """
        Initialize the ConcurrentQueue.

        Args:
            initial (Iterable[_T], optional):
                An iterable of initial items. Defaults to an empty list if None is given.
            width (int, optional):
                Bit width for the atomic counter (default is 8 for 64-bit).
                This parameter controls the maximum value the counter can hold.
                A width of 8 bits allows a maximum count of 2**8 - 1 = 255,
                while a width of 16 allows 2**16 - 1 = 65535, and so on.
                Choosing a smaller width can save memory, but it limits the
                total number of items the bag can hold. If the counter
                reaches its maximum value, further additions will wrap around
                (behaving like modulo arithmetic), potentially leading to
                incorrect results for the total count. The default of 8 is
                generally sufficient for moderately sized bags.
        """
        if initial is None:
            initial = []
        self._lock: threading.RLock = threading.RLock()
        self._deque: Deque[_T] = deque(initial)

        # Atomic counter to track the size (i.e., number of items)
        self.counter = atomics.atomic(width=width, atype=atomics.INT)
        self.counter.store(len(self._deque))

    def enqueue(self, item: _T) -> None:
        """
        Add an item to the end of the queue (FIFO).

        Args:
            item (_T): The item to enqueue.
        """
        with self._lock:
            self._deque.append(item)
            self.counter.fetch_add(1)

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
                raise IndexError("dequeue from empty ConcurrentQueue")
            item = self._deque.popleft()
            self.counter.fetch_sub(1)
            return item

    def peek(self) -> _T:
        """
        Return (but do not remove) the item at the front of the queue.

        Raises:
            IndexError: If the queue is empty.

        Returns:
            _T: The item at the front of the queue.
        """
        with self._lock:
            if not self._deque:
                raise IndexError("peek from empty ConcurrentQueue")
            return self._deque[0]

    def __len__(self) -> int:
        """
        Return the number of items in the queue, using the atomic counter.

        Returns:
            int: The current size of the queue.
        """
        return self.counter.load()

    def __bool__(self) -> bool:
        """
        Return True if the queue is non-empty.

        Returns:
            bool: True if non-empty, False otherwise.
        """
        return self.counter.load() != 0

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
            self.counter.store(0)

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

    def to_concurrent_list(self) -> "concurrent_list.ConcurrentList[_T]":
        """
        Return a shallow copy of the queue as a ConcurrentList.

        Returns:
            concurrent_list.ConcurrentList[_T]:
                A concurrent list containing all items currently in the queue.
        """
        # We assume that `concurrent_list` is already imported from your `Threading` package
        # and that concurrent_list.ConcurrentList is a valid class.
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
            self.counter.store(len(self._deque))

    # ---------- Optional Functional Methods (similar to map/filter/reduce) ----------

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

    # ---------- Optional "Atomic" element operations ----------

    def atomic_update(self, index: int, func: Callable[[_T], _T]) -> None:
        """
        Atomically update the element at the given index using a function,
        similar to 'ConcurrentList'.

        WARNING: Queues typically do not expose random access.
        You might prefer queue-oriented operations instead.

        Args:
            index (int): The index to update (0-based from the front).
            func (Callable[[_T], _T]): A function taking the current value and returning a new value.

        Raises:
            IndexError: If index is out of range.
            TypeError: If index is not an integer or func is not callable.
        """
        if not isinstance(index, int):
            raise TypeError("index must be an integer")
        if not callable(func):
            raise TypeError("func must be callable")

        with self._lock:
            size = len(self._deque)
            if index < 0 or index >= size:
                raise IndexError("ConcurrentQueue index out of range")

            # Convert to list to perform indexed update (O(n) for large queues).
            temp_list = list(self._deque)
            temp_list[index] = func(temp_list[index])
            self._deque = deque(temp_list)

    def atomic_swap(self, index1: int, index2: int) -> None:
        """
        Atomically swap two elements by index.

        WARNING: This is not typical queue behavior, but included for completeness.

        Args:
            index1 (int): The first index.
            index2 (int): The second index.

        Raises:
            IndexError: If either index is out of range.
            TypeError: If either index is not an integer.
        """
        if not isinstance(index1, int) or not isinstance(index2, int):
            raise TypeError("indices must be integers")

        with self._lock:
            size = len(self._deque)
            if index1 < 0 or index1 >= size or index2 < 0 or index2 >= size:
                raise IndexError("ConcurrentQueue index out of range")

            temp_list = list(self._deque)
            temp_list[index1], temp_list[index2] = temp_list[index2], temp_list[index1]
            self._deque = deque(temp_list)
