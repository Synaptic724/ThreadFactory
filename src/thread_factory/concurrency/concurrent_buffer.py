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
        self._lock = threading.RLock()
        self._queue: Deque[(tuple, _T)] = deque()
        self._length_array = len_array
        self._time_array = time_array
        self._index = index

    def _increase_length_value(self):
        self._length_array[self._index] += 1

    def _decrease_length_value(self):
        self._length_array[self._index] -= 1

    def _set_time_value(self, value: int):
        # FIX: write to the time array instead of the length array.
        self._time_array[self._index] = value

    def dequeue_item(self) -> _T:
        with self._lock:
            if not self._queue:
                raise Empty("dequeue from empty ConcurrentBuffer (race condition)")
            self._decrease_length_value()
            return_item = self._queue.popleft()
            if self._queue:
                self._set_time_value(self._queue[0][0])
            else:
                self._set_time_value(0)
            # Return only the item part (index 1 of the tuple)
            return return_item[1]

    def enqueue_item(self, item: _T) -> None:
        with self._lock:
            now = time.monotonic_ns()
            self._set_time_value(now)  # update timestamp in the time array
            self._queue.append((now, item))
            self._increase_length_value()

    def peek(self) -> Optional[_T]:
        with self._lock:
            if not self._queue:
                raise Empty("peek from empty ConcurrentBuffer")
            return copy(self._queue[0][1])

    def __iter__(self) -> List[Any]:
        with self._lock:
            return [item for (_, item) in self._queue]

    def clear(self) -> None:
        with self._lock:
            self._queue.clear()
            self._length_array[self._index] = 0
            self._set_time_value(0)


class ConcurrentBuffer(Generic[_T]):
    """
    A thread-safe, *mostly* FIFO buffer implementation using multiple internal
    deques (shards). Items are tagged with a timestamp upon enqueue.
    """

    def __init__(
        self,
        number_of_shards: int = 6,
        initial: Optional[Iterable[_T]] = None,
    ) -> None:
        if initial is None:
            initial = []

        self._length_array = array("Q", [0] * number_of_shards)  # holds the length of each shard
        self._time_array = array("Q", [0] * number_of_shards)    # holds the timestamp for each shard

        self._shards: List[_Shard[_T]] = [_Shard(self._length_array, self._time_array, i) for i in range(number_of_shards)]
        self._num_shards = number_of_shards

        # Distribute initial items (randomly) to shards
        for item in initial:
            self.enqueue(item)

    def enqueue(self, item: _T) -> None:
        shard_idx = random.randint(0, self._num_shards - 1)
        shard = self._shards[shard_idx]
        shard.enqueue_item(item)

    def dequeue(self) -> _T:
        min_ts = None
        min_idx = None

        for i, ts in enumerate(self._time_array):
            if ts > 0 and (min_ts is None or ts < min_ts):
                min_ts = ts
                min_idx = i
        if min_idx is None:
            raise Empty("dequeue from empty ConcurrentBuffer")
        return self._shards[min_idx].dequeue_item()

    def peek(self, index: Optional[int] = None) -> _T:
        # If no index is provided, return the oldest item.
        if index is None:
            return self.peek_oldest()
        return self._shards[index].peek()

    def peek_oldest(self) -> _T:
        min_ts = None
        min_idx = None
        for i, ts in enumerate(self._time_array):
            if ts > 0 and (min_ts is None or ts < min_ts):
                min_ts = ts
                min_idx = i
        if min_idx is None:
            raise Empty("peek from empty ConcurrentBuffer")
        return self._shards[min_idx].peek()

    def __len__(self) -> int:
        return sum(self._length_array)

    def __bool__(self) -> bool:
        return len(self) != 0

    def __iter__(self) -> Iterator[_T]:
        items_copy = []
        for shard in self._shards:
            items_copy.extend(shard.__iter__())
        return iter(items_copy)

    def clear(self) -> None:
        for shard in self._shards:
            shard.clear()

    def __repr__(self) -> str:
        total_len = len(self)
        valid_tags = [ts for ts in self._time_array if ts > 0]
        earliest_tag = min(valid_tags) if valid_tags else None
        return f"{self.__class__.__name__}(size={total_len}, earliest_tag={earliest_tag})"

    def __str__(self) -> str:
        all_items = list(self)
        return str(all_items)

    def copy(self) -> "ConcurrentBuffer[_T]":
        items_copy = list(self)
        return ConcurrentBuffer(
            number_of_shards=self._num_shards,
            initial=items_copy)

    def __copy__(self) -> "ConcurrentBuffer[_T]":
        return self.copy()

    def __deepcopy__(self, memo: dict) -> "ConcurrentBuffer[_T]":
        with threading.Lock():
            all_items = list(self)
            deep_items = deepcopy(all_items, memo)
            return ConcurrentBuffer(
                number_of_shards=self._num_shards,
                initial=deep_items)


    def to_concurrent_list(self) -> "ConcurrentList[_T]":
        items_copy = list(self)
        return ConcurrentList(items_copy)

    def batch_update(self, func: Callable[[List[_T]], None]) -> None:
        # Allow batch_update regardless of producer mode.
        all_items: List[_T] = list(self)
        func(all_items)
        self.clear()
        for item in all_items:
            self.enqueue(item)

    def map(self, func: Callable[[_T], Any]) -> "ConcurrentBuffer[Any]":
        items_copy = list(self)
        mapped = list(map(func, items_copy))
        return ConcurrentBuffer(
            number_of_shards=self._num_shards,
            initial=mapped)

    def filter(self, func: Callable[[_T], bool]) -> "ConcurrentBuffer[_T]":
        items_copy = list(self)
        filtered = list(filter(func, items_copy))
        return ConcurrentBuffer(number_of_shards=self._num_shards,
            initial=filtered)

    def remove_item(self, item: _T) -> bool:
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
        items_copy = list(self)
        if not items_copy and initial is None:
            raise TypeError("reduce() of empty ConcurrentBuffer with no initial value")
        if initial is None:
            return functools.reduce(func, items_copy)
        else:
            return functools.reduce(func, items_copy, initial)
