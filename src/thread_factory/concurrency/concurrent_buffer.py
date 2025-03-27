import functools
import random
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
      - Metadata (length, head_tag) to support approximate ordering.
    """

    def __init__(self, len_array: array, time_array: array, index: int) -> None:
        """
        Initializes a new shard.

        Args:
            len_array (array): A shared array to store the length of each shard.
            time_array (array): A shared array to store the timestamp of the head of each shard.
            index (int): The index of this shard within the shared arrays.
        """
        # Lock to protect access to the internal deque and metadata.
        self._lock = threading.RLock()
        # The internal deque to store items within this shard. Each item is stored as a tuple (timestamp, item).
        self._queue: Deque[(tuple, _T)] = deque()
        # Shared array holding the current length of all shards.
        self._length_array = len_array
        # Shared array holding the timestamp of the earliest item in each shard.
        self._time_array = time_array
        # The index of this shard in the shared arrays.
        self._index = index

    def _increase_length_value(self):
        """Increases the length counter for this shard in the shared length array."""
        self._length_array[self._index] += 1

    def _decrease_length_value(self):
        """Decreases the length counter for this shard in the shared length array."""
        self._length_array[self._index] -= 1

    def _set_time_value(self, value: int):
        """Sets the timestamp for this shard in the shared time array."""
        # FIX: write to the time array instead of the length array.
        self._time_array[self._index] = value

    def dequeue_item(self) -> _T:
        """
        Removes and returns the oldest item from this shard.

        Raises:
            Empty: If the shard is empty.

        Returns:
            _T: The oldest item in the shard.
        """
        with self._lock:
            if not self._queue:
                raise Empty("dequeue from empty ConcurrentBuffer (race condition)")
            self._decrease_length_value()
            return_item = self._queue.popleft()
            # Update the timestamp in the shared array if the queue is not empty
            if self._queue:
                self._set_time_value(self._queue[0][0])
            else:
                self._set_time_value(0)
            # Return only the item part (index 1 of the tuple)
            return return_item[1]

    def enqueue_item(self, item: _T) -> None:
        """
        Adds a new item to the end of this shard.

        Args:
            item (_T): The item to add.
        """
        with self._lock:
            now = time.monotonic_ns()
            self._set_time_value(now)  # update timestamp in the time array
            self._queue.append((now, item))
            self._increase_length_value()

    def peek(self) -> Optional[_T]:
        """
        Returns the oldest item from this shard without removing it.

        Raises:
            Empty: If the shard is empty.

        Returns:
            Optional[_T]: The oldest item in the shard, or None if empty (though Empty exception is raised).
        """
        with self._lock:
            if not self._queue:
                raise Empty("peek from empty ConcurrentBuffer")
            return copy(self._queue[0][1])

    def __iter__(self) -> List[Any]:
        """
        Returns a list containing all items in this shard.

        Returns:
            List[Any]: A list of items in the shard.
        """
        with self._lock:
            return [item for (_, item) in self._queue]

    def clear(self) -> None:
        """Removes all items from this shard and resets its length and timestamp."""
        with self._lock:
            self._queue.clear()
            self._length_array[self._index] = 0
            self._set_time_value(0)


class ConcurrentBuffer(Generic[_T]):
    """
    A thread-safe, *mostly* FIFO buffer implementation using multiple internal
    deques (shards). Items are tagged with a timestamp upon enqueue.

    This buffer aims to provide better concurrency than a single-lock queue
    in low to moderate contention scenarios by distributing items across
    multiple internal shards, each with its own lock.

    This concurrency object does not guarantee strict FIFO ordering across shards.
    It also performs quite well in low to moderate concurrency scenarios.

    **NOTE**: This buffer is not designed for high-contention scenarios.
    ConcurrentQueue or ConcurrentStack Outperforms this object in high-contention scenarios.

    4-6 Shards have given quite good results in most scenarios with under 10 threads, it can
    outperform the ConcurrentQueue in some scenarios by 2x
    """

    def __init__(
        self,
        number_of_shards: int = 4,
        initial: Optional[Iterable[_T]] = None,
    ) -> None:
        """
        Initializes a new ConcurrentBuffer.

        Args:
            number_of_shards (int, optional): The number of internal shards to use. Defaults to 4.
            initial (Optional[Iterable[_T]], optional): An optional iterable of items to initialize the buffer with. Defaults to None.
        """
        if initial is None:
            initial = []

        # Shared array to store the current length of each shard. Using an array for efficiency.
        self._length_array = array("Q", [0] * number_of_shards)
        # Shared array to store the timestamp of the earliest item in each shard.
        self._time_array = array("Q", [0] * number_of_shards)

        # Create the internal shards. Each shard gets a reference to the shared length and time arrays.
        self._shards: List[_Shard[_T]] = [_Shard(self._length_array, self._time_array, i) for i in range(number_of_shards)]
        # The total number of shards.
        self._num_shards = number_of_shards

        # Distribute initial items (randomly) to shards to balance the load.
        for item in initial:
            self.enqueue(item)

    def enqueue(self, item: _T) -> None:
        """
        Adds a new item to the buffer. The item is randomly assigned to one of the internal shards.

        Args:
            item (_T): The item to add.
        """
        # Choose a random shard to enqueue the item into. This helps distribute the load.
        shard_idx = random.randint(0, self._num_shards - 1)
        shard = self._shards[shard_idx]
        shard.enqueue_item(item)

    def dequeue(self) -> _T:
        """
        Removes and returns the oldest item from the buffer based on the timestamp.

        Raises:
            Empty: If the buffer is empty.

        Returns:
            _T: The oldest item in the buffer.
        """
        min_ts = None
        min_idx = None

        # Iterate through the timestamps of the head of each shard to find the oldest.
        for i, ts in enumerate(self._time_array):
            # Consider only shards that are not empty (timestamp > 0).
            if ts > 0 and (min_ts is None or ts < min_ts):
                min_ts = ts
                min_idx = i
        # If no non-empty shard is found.
        if min_idx is None:
            raise Empty("dequeue from empty ConcurrentBuffer")
        # Dequeue the item from the shard with the oldest timestamp.
        return self._shards[min_idx].dequeue_item()

    def peek(self, index: Optional[int] = None) -> _T:
        """
        Returns the oldest item from the buffer without removing it.

        Args:
            index (Optional[int], optional): The index of the shard to peek into. If None, peeks at the oldest item across all shards. Defaults to None.

        Raises:
            Empty: If the buffer is empty.

        Returns:
            _T: The oldest item in the buffer.
        """
        # If no index is provided, return the oldest item across all shards.
        if index is None:
            return self.peek_oldest()
        return self._shards[index].peek()

    def peek_oldest(self) -> _T:
        """
        Returns the oldest item from the buffer without removing it.

        Raises:
            Empty: If the buffer is empty.

        Returns:
            _T: The oldest item in the buffer.
        """
        min_ts = None
        min_idx = None
        # Iterate through the timestamps of the head of each shard to find the oldest.
        for i, ts in enumerate(self._time_array):
            # Consider only shards that are not empty (timestamp > 0).
            if ts > 0 and (min_ts is None or ts < min_ts):
                min_ts = ts
                min_idx = i
        # If no non-empty shard is found.
        if min_idx is None:
            raise Empty("peek from empty ConcurrentBuffer")
        return self._shards[min_idx].peek()

    def __len__(self) -> int:
        """
        Returns the total number of items in the buffer.

        Returns:
            int: The total number of items.
        """
        return sum(self._length_array)

    def __bool__(self) -> bool:
        """
        Returns True if the buffer is not empty, False otherwise.

        Returns:
            bool: True if the buffer has items, False otherwise.
        """
        return len(self) != 0

    def __iter__(self) -> Iterator[_T]:
        """
        Returns an iterator over all items in the buffer. The order is not guaranteed to be strictly FIFO across shards.

        Returns:
            Iterator[_T]: An iterator over the items.
        """
        items_copy = []
        # Iterate through each shard and extend the list with its items.
        for shard in self._shards:
            items_copy.extend(shard.__iter__())
        return iter(items_copy)

    def clear(self) -> None:
        """Removes all items from the buffer."""
        for shard in self._shards:
            shard.clear()

    def __repr__(self) -> str:
        """
        Returns a string representation of the buffer.

        Returns:
            str: A string representation including size and the timestamp of the earliest item.
        """
        total_len = len(self)
        valid_tags = [ts for ts in self._time_array if ts > 0]
        earliest_tag = min(valid_tags) if valid_tags else None
        return f"{self.__class__.__name__}(size={total_len}, earliest_tag={earliest_tag})"

    def __str__(self) -> str:
        """
        Returns a string representation of all items in the buffer (as a list).

        Returns:
            str: A string representation of the items.
        """
        all_items = list(self)
        return str(all_items)

    def copy(self) -> "ConcurrentBuffer[_T]":
        """
        Creates a shallow copy of the ConcurrentBuffer.

        Returns:
            ConcurrentBuffer[_T]: A new ConcurrentBuffer with the same items.
        """
        items_copy = list(self)
        return ConcurrentBuffer(
            number_of_shards=self._num_shards,
            initial=items_copy)

    def __copy__(self) -> "ConcurrentBuffer[_T]":
        """Supports the copy.copy() operation."""
        return self.copy()

    def __deepcopy__(self, memo: dict) -> "ConcurrentBuffer[_T]":
        """Supports the copy.deepcopy() operation."""
        with threading.Lock():
            all_items = list(self)
            deep_items = deepcopy(all_items, memo)
            return ConcurrentBuffer(
                number_of_shards=self._num_shards,
                initial=deep_items)

    def to_concurrent_list(self) -> "ConcurrentList[_T]":
        """
        Converts the buffer's contents to a ConcurrentList.

        Returns:
            ConcurrentList[_T]: A new ConcurrentList containing the same items.
        """
        items_copy = list(self)
        return ConcurrentList(items_copy)

    def batch_update(self, func: Callable[[List[_T]], None]) -> None:
        """
        Applies a function to all items in the buffer as a batch, then clears and re-enqueues the updated items.

        Args:
            func (Callable[[List[_T]], None]): A function that takes a list of items and modifies it in place.
        """
        # Allow batch_update regardless of producer mode.
        all_items: List[_T] = list(self)
        func(all_items)
        self.clear()
        for item in all_items:
            self.enqueue(item)

    def map(self, func: Callable[[_T], Any]) -> "ConcurrentBuffer[Any]":
        """
        Applies a function to each item in the buffer and returns a new ConcurrentBuffer with the results.

        Args:
            func (Callable[[_T], Any]): The function to apply to each item.

        Returns:
            ConcurrentBuffer[Any]: A new ConcurrentBuffer with the mapped items.
        """
        items_copy = list(self)
        mapped = list(map(func, items_copy))
        return ConcurrentBuffer(
            number_of_shards=self._num_shards,
            initial=mapped)

    def filter(self, func: Callable[[_T], bool]) -> "ConcurrentBuffer[_T]":
        """
        Filters the items in the buffer based on a given predicate and returns a new ConcurrentBuffer with the filtered items.

        Args:
            func (Callable[[_T], bool]): The predicate function to filter items.

        Returns:
            ConcurrentBuffer[_T]: A new ConcurrentBuffer with the filtered items.
        """
        items_copy = list(self)
        filtered = list(filter(func, items_copy))
        return ConcurrentBuffer(number_of_shards=self._num_shards,
            initial=filtered)

    def remove_item(self, item: _T) -> bool:
        """
        Removes the first occurrence of a specific item from the buffer.

        Args:
            item (_T): The item to remove.

        Returns:
            bool: True if the item was found and removed, False otherwise.
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
                self.enqueue(i)
        return found

    def reduce(self, func: Callable[[Any, _T], Any], initial: Optional[Any] = None) -> Any:
        """
        Applies a function of two arguments cumulatively to the items of the buffer, from left to right, so as to reduce the buffer to a single value.

        Args:
            func (Callable[[Any, _T], Any]): The function to apply.
            initial (Optional[Any], optional): The initial value. Defaults to None.

        Raises:
            TypeError: If the buffer is empty and no initial value is provided.

        Returns:
            Any: The reduced value.
        """
        items_copy = list(self)
        if not items_copy and initial is None:
            raise TypeError("reduce() of empty ConcurrentBuffer with no initial value")
        if initial is None:
            return functools.reduce(func, items_copy)
        else:
            return functools.reduce(func, items_copy, initial)