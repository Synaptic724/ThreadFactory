import functools
import threading
import time
from collections import deque
from copy import deepcopy, copy
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
from array import array

from src.thread_factory.concurrency.concurrent_list import ConcurrentList
from src.thread_factory.utils import Empty

_T = TypeVar("_T")


class _Shard(Generic[_T]):
    """
    Internal shard class holding:
      - A local deque.
      - A lock to synchronize access.
    """
    __slots__ = ('_lock', '_queue', '_length_array', '_index')

    def __init__(self, len_array: array, index: int) -> None:
        """
        Initializes a new shard.

        Args:
            len_array (array): A shared array to store the length of each shard.
            index (int): The index of this shard within the shared arrays.
        """
        self._lock = threading.RLock()
        self._queue: Deque[_T] = deque()
        self._length_array = len_array
        self._index = index

    def _increase_length_value(self):
        """Increases the length counter for this shard in the shared length array."""
        self._length_array[self._index] += 1

    def _decrease_length_value(self):
        """Decreases the length counter for this shard in the shared length array."""
        self._length_array[self._index] -= 1

    def pop_item(self) -> _T:
        """
        Removes and returns the oldest item (front) from this shard.

        Raises:
            Empty: If the shard is empty.

        Returns:
            _T: The popped item from the shard.
        """
        with self._lock:
            if not self._queue:
                raise Empty("pop from empty ConcurrentCollection shard (race condition)")
            self._decrease_length_value()
            return self._queue.popleft()

    def add_item(self, item: _T) -> None:
        """
        Adds a new item to the end of this shard.

        Args:
            item (_T): The item to add.
        """
        with self._lock:
            self._queue.append(item)
            self._increase_length_value()

    def peek(self) -> _T:
        """
        Returns the front item from this shard without removing it.

        Raises:
            Empty: If the shard is empty.

        Returns:
            _T: The front item in the shard.
        """
        with self._lock:
            if not self._queue:
                raise Empty("peek from empty ConcurrentCollection shard")
            return copy(self._queue[0])

    def __iter__(self) -> Iterator[_T]:
        """
        Returns an iterator over all items in this shard.

        Returns:
            Iterator[_T]: Items within this shard.
        """
        with self._lock:
            return iter(list(self._queue))

    def clear(self) -> None:
        """Removes all items from this shard and resets its length to 0."""
        with self._lock:
            self._queue.clear()
            self._length_array[self._index] = 0


class ConcurrentCollection(Generic[_T]):
    """
    A thread-safe, high-level collection that distributes items across multiple internal
    shards (deques). Items are stored without strict global ordering, enabling parallel
    access in low-to-moderate contention scenarios.

    **Note**: This collection is not optimized for extreme contention. For very high-thread
    workloads, consider `ConcurrentQueue` or `ConcurrentStack`.

    Please follow the guideline of using roughly half the total threads as the shard count.
    For example, if you have 10 threads total, try 5 shards for balanced performance.

    Shard counts > 1 must be even for consistent internal splitting. A single shard (1) is
    allowed but odd counts > 1 will raise a `ValueError`.
    """

    def __init__(
        self,
        total_thread_count: int = 1,
        initial: Optional[Iterable[_T]] = None,
    ) -> None:
        """
        Initializes a new ConcurrentCollection.

        Args:
            number_of_shards (int, optional): The number of internal shards to use. Defaults to 4.
            initial (Optional[Iterable[_T]], optional): An optional iterable of items to initialize the collection with.
        """
        number_of_shards = max(1, total_thread_count)
        if initial is None:
            initial = []

        if number_of_shards < 1:
            raise ValueError("number_of_shards must be at least 1")
        if number_of_shards > 1 and number_of_shards % 2 != 0:
            raise ValueError("number_of_shards must be even if greater than 1")

        self._num_shards = number_of_shards
        self._length_array = array("Q", [0] * self._num_shards)
        self._shards: List[_Shard[_T]] = [
            _Shard(self._length_array, i)
            for i in range(self._num_shards)
        ]

        for item in initial:
            self.add(item)

    def add(self, item: _T) -> None:
        """
        Adds a new item to this collection.

        Args:
            item (_T): The item to add.
        """
        shard_idx = self._select_shard()
        self._shards[shard_idx].add_item(item)

    def pop(self) -> _T:
        """
        Removes and returns an item from the collection.

        Uses a short scan over shards to find any available item.

        Raises:
            Empty: If all shards are empty.
        """
        # short circular scan to avoid single shard bias
        start = self._select_shard()
        for offset in range(self._num_shards):
            idx = (start + offset) % self._num_shards
            if self._length_array[idx] > 0:
                return self._shards[idx].pop_item()
        raise Empty("pop from empty ConcurrentCollection")

    def _select_shard(self) -> int:
        """
        Selects a shard index using a bit-mixed monotonic timestamp.
        Balances distribution across all shards.
        """
        ns = time.monotonic_ns()
        # if _num_shards is a power-of-two, we could do & (mask), but we'll do modulo for general case
        return ((ns >> 3) ^ ns) % self._num_shards

    def peek(self, shard_index: Optional[int] = None) -> _T:
        """
        Returns an item from the collection without removing it.

        If shard_index is given, peeks in that specific shard. Otherwise, tries shards
        in order until it finds a non-empty one.

        Raises:
            IndexError: If shard_index is out of range.
            Empty: If the entire collection is empty or the chosen shard is empty.

        Returns:
            _T: The item found.
        """
        if shard_index is not None:
            if shard_index >= self._num_shards or shard_index < 0:
                raise IndexError("Shard index out of range")
            return self._shards[shard_index].peek()

        # no index → pick the first non-empty shard
        for shard in self._shards:
            try:
                return shard.peek()
            except Empty:
                pass
        raise Empty("peek from empty ConcurrentCollection")

    def __len__(self) -> int:
        """Returns the total item count in this collection."""
        return sum(self._length_array)

    def __bool__(self) -> bool:
        """Returns True if not empty, False otherwise."""
        return len(self) != 0

    def __iter__(self) -> Iterator[_T]:
        """
        Iterates over all items in the collection. Unordered,
        as items come in shard order, then by shard's local order.
        """
        items_copy = []
        for shard in self._shards:
            items_copy.extend(shard.__iter__())
        return iter(items_copy)

    def clear(self) -> None:
        """Clears all shards in the collection."""
        for shard in self._shards:
            shard.clear()

    def __repr__(self) -> str:
        """
        String representation showing total size and minimal shard length.
        """
        total_len = len(self)
        non_empty_lengths = [l for l in self._length_array if l > 0]
        min_shard_len = min(non_empty_lengths) if non_empty_lengths else 0
        return f"{self.__class__.__name__}(total_size={total_len}, min_shard_len={min_shard_len})"

    def __str__(self) -> str:
        """Return all items as a list string."""
        return str(list(self))

    def copy(self) -> "ConcurrentCollection[_T]":
        """
        Creates a shallow copy of the collection.
        """
        items_copy = list(self)
        return ConcurrentCollection(
            number_of_shards=self._num_shards,
            initial=items_copy
        )

    def __copy__(self) -> "ConcurrentCollection[_T]":
        """Supports copy.copy() usage."""
        return self.copy()

    def __deepcopy__(self, memo: dict) -> "ConcurrentCollection[_T]":
        """Supports copy.deepcopy() usage."""
        with threading.Lock():
            all_items = list(self)
            deep_items = deepcopy(all_items, memo)
            return ConcurrentCollection(
                number_of_shards=self._num_shards,
                initial=deep_items
            )

    def to_concurrent_list(self) -> "ConcurrentList[_T]":
        """Converts the collection's contents into a ConcurrentList."""
        items_copy = list(self)
        return ConcurrentList(items_copy)

    def batch_update(self, func: Callable[[List[_T]], None]) -> None:
        """
        Applies a function to all items (as a batch), clears, and re-adds them.
        """
        all_items: List[_T] = list(self)
        func(all_items)
        self.clear()
        for item in all_items:
            self.add(item)

    def map(self, func: Callable[[_T], Any]) -> "ConcurrentCollection[Any]":
        """
        Applies a function to each item, returning a new ConcurrentCollection with the results.
        """
        items_copy = list(self)
        mapped = list(map(func, items_copy))
        return ConcurrentCollection(
            number_of_shards=self._num_shards,
            initial=mapped
        )

    def filter(self, func: Callable[[_T], bool]) -> "ConcurrentCollection[_T]":
        """
        Filters the items based on a predicate, returning a new ConcurrentCollection with matches.
        """
        items_copy = list(self)
        filtered = [x for x in items_copy if func(x)]
        return ConcurrentCollection(
            number_of_shards=self._num_shards,
            initial=filtered
        )

    def remove_item(self, item: _T) -> bool:
        """
        Removes the *first* occurrence of `item` from the collection.

        Returns True if found and removed, False otherwise.
        """
        found = False
        new_items = []
        for current in self:
            if not found and current is item:
                found = True
            else:
                new_items.append(current)
        if found:
            self.clear()
            for i in new_items:
                self.add(i)
        return found

    def reduce(self, func: Callable[[Any, _T], Any], initial: Optional[Any] = None) -> Any:
        """
        Reduces the collection to a single value by applying `func` from left to right.
        """
        items_copy = list(self)
        if not items_copy and initial is None:
            raise TypeError("reduce() of empty ConcurrentCollection with no initial value")
        if initial is None:
            return functools.reduce(func, items_copy)
        else:
            return functools.reduce(func, items_copy, initial)
