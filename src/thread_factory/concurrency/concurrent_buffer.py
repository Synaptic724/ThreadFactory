import functools
import threading
import time
import warnings
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

from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.utilities.interfaces.disposable import IDisposable
from thread_factory.utilities.exceptions import Empty

_T = TypeVar("_T")

#TODO : Implement per object locks to see if we can distribute contention between each call for arrays and deques

class _Shard(Generic[_T], IDisposable):
    """
    _Shard is an internal component representing a lock-protected queue (deque)
    inside a sharded concurrent buffer.

    Each shard:
    - Maintains its own double-ended queue (deque) to store items.
    - Tracks its length and the timestamp of its head item via shared memory arrays.
    - Provides thread-safe enqueue, dequeue, and peek operations.

    This design reduces contention by allowing multiple runtime to work on separate shards
    independently while still providing approximate global FIFO behavior.
    """

    __slots__ =  IDisposable.__slots__ + ["_lock", "_queue", "_length_array", "_time_array", "_index"]
    def __init__(self, len_array: array, time_array: array, index: int) -> None:
        """
        Initialize a new shard.

        Args:
            len_array (array): Shared array (uint64) tracking the length of each shard.
            time_array (array): Shared array (uint64) storing the timestamp of the head of each shard.
            index (int): This shard's index within the shared arrays.
        """
        super().__init__()
        # Thread-safe lock to protect internal state of this shard.
        self._lock = threading.RLock()
        # Internal deque to hold (timestamp, item) tuples.
        self._queue: Deque[tuple[int, _T]] = deque()
        # Shared arrays (used by parent buffer to globally track shard states).
        self._length_array = len_array
        self._time_array = time_array
        self._index = index

    def dispose(self) -> None:
        """
        Dispose of this shard by clearing all items and marking it as unusable.

        Notes:
            - Safe to call multiple times (idempotent).
            - Required to release resources when integrated with a Disposable system.
        """
        with self._lock:
            if not self._disposed:
                self._queue.clear()
                self._length_array[self._index] = 0
                self._set_time_value(0)
                self._disposed = True

    def _increase_length_value(self) -> None:
        """
        Increments this shard's length counter in the shared length array.
        Called whenever an item is enqueued.
        """
        self._length_array[self._index] += 1

    def _decrease_length_value(self) -> None:
        """
        Decrements this shard's length counter in the shared length array.
        Called whenever an item is dequeued.
        """
        self._length_array[self._index] -= 1

    def _set_time_value(self, value: int) -> None:
        """
        Updates this shard's head timestamp in the shared time array.

        Args:
            value (int): The new timestamp value (monotonic nanoseconds)
                         or 0 if the shard is empty.
        """
        self._time_array[self._index] = value

    def dequeue_item(self) -> _T:
        """
        Removes and returns the oldest item from this shard.

        Returns:
            _T: The dequeued item.

        Raises:
            Empty: If the shard is empty (race condition scenario).
        """
        with self._lock:
            if not self._queue:
                raise Empty("dequeue from empty ConcurrentBuffer (race condition)")

            # Remove the head item.
            self._decrease_length_value()
            timestamp, item = self._queue.popleft()

            # Update shard timestamp to reflect new head (or 0 if empty).
            if self._queue:
                self._set_time_value(self._queue[0][0])
            else:
                self._set_time_value(0)

            return item

    def enqueue_item(self, item: _T) -> None:
        """
        Enqueues an item into this shard.

        Args:
            item (_T): The item to enqueue.
        """
        with self._lock:
            now = time.monotonic_ns()
            # If this is the first item, update shard timestamp.
            if not self._queue:
                self._set_time_value(now)
            self._queue.append((now, item))
            self._increase_length_value()

    def peek(self) -> _T:
        """
        Returns the oldest item without removing it.

        Returns:
            _T: The oldest item (copied).

        Raises:
            Empty: If the shard is empty.
        """
        with self._lock:
            if not self._queue:
                raise Empty("peek from empty ConcurrentBuffer")
            # Return a copy of the oldest item to avoid leaking references.
            return copy(self._queue[0][1])

    def __iter__(self) -> Iterator[_T]:
        """
        Returns an iterator over all items in the shard.

        Items are yielded in insertion order.
        This is a snapshot taken under lock, but iteration itself is outside the lock.

        Returns:
            Iterator[_T]: Iterator over items.
        """
        with self._lock:
            return iter([item for (_, item) in self._queue])

    def clear(self) -> None:
        """
        Removes all items from this shard and resets length and timestamp metadata.
        """
        with self._lock:
            self._queue.clear()
            self._length_array[self._index] = 0
            self._set_time_value(0)

    def __enter__(self):
        """
        Enter the runtime context related to this object.
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Exit the runtime context related to this object.
        Automatically disposes of the shard.
        """
        self.dispose()


class ConcurrentBuffer(Generic[_T], IDisposable):
    """
    A thread-safe, *mostly* FIFO buffer implementation using multiple internal
    deques (shards). Items are tagged with a timestamp upon enqueue.

    This buffer aims to provide better concurrency than a single-lock queue
    in low to moderate contention scenarios by distributing items across
    multiple internal shards, each with its own lock.

    This concurrency object does NOT guarantee strict FIFO ordering across shards.
    It generally performs well in moderate concurrency scenarios. For extreme
    concurrency or high contention, consider other structures.

    **NOTE**: This buffer is not designed for high-contention scenarios.
    ConcurrentQueue or ConcurrentStack outperform this object in heavy contention.
    DO NOT EXCEED 20 THREADS OVERALL (for producer and consumer pattern) WHEN USING THIS OBJECT.

    The rule of thumb is to use half as many shards as total runtime (producer + consumer).
    e.g., 10 runtime => 5 shards.

    This class now implements a Disposable pattern, allowing you to dispose
    of it explicitly or via a `with` statement when it's no longer needed.
    """
    __slots__ = IDisposable.__slots__ + ["_shards", "_length_array", "_time_array", "_num_shards", "_mid", "_left_range", "_right_range", "_shard_indices"]

    def __init__(
        self,
        number_of_shards: int = 4,
        initial: Optional[Iterable[_T]] = None,
    ) -> None:
        """
        Initializes a new ConcurrentBuffer.

        Args:
            number_of_shards (int, optional):
                The number of internal shards to use. Defaults to 4.
            initial (Optional[Iterable[_T]], optional):
                An optional iterable of items to initialize the buffer with.
                Defaults to None.

        Raises:
            ValueError: If number_of_shards < 1 or is odd when > 1.
        """
        super().__init__()
        if initial is None:
            initial = []

        if number_of_shards < 1:
            raise ValueError("number_of_shards must be at least 1")
        if number_of_shards > 1 and number_of_shards % 2 != 0:
            raise ValueError("number_of_shards must be even if greater than 1")

        # Shared arrays: length per shard, timestamp of the earliest item per shard
        self._length_array = array("Q", [0] * number_of_shards)
        self._time_array = array("Q", [0] * number_of_shards)

        # Create the shard objects
        self._shards: List[_Shard[_T]] = [
            _Shard(self._length_array, self._time_array, i)
            for i in range(number_of_shards)
        ]
        self._num_shards = number_of_shards

        # For distributing loads, half the shards in "left" range, half in "right".
        self._mid = number_of_shards // 2
        self._left_range = range(0, self._mid)
        self._right_range = range(self._mid, number_of_shards)

        # Keep track of shard indices for possible scanning logic
        self._shard_indices = list(range(number_of_shards))

        # Initialize with any provided items
        for item in initial:
            self.enqueue(item)

    def dispose(self) -> None:
        """
        Disposes of this ConcurrentBuffer, releasing all internal resources.

        Responsibilities:
          - Disposes each internal shard by clearing their queues and resetting their counters.
          - Resets the shared `_length_array` and `_time_array` used for shard coordination.
          - Marks this object as disposed (`self.disposed = True`).

        Behavior:
          - This method is idempotent: multiple calls will have no adverse effects after the first.
          - Once disposed, the buffer should be considered permanently invalid.
          - No post-disposal protection is enforced — correct usage is left to the caller's responsibility.

        Notes:
          - A warning is emitted when disposal occurs to signal that the buffer has been destroyed.
          - This follows the explicit resource control philosophy common in high-performance and systems programming.

        Example:
            with ConcurrentBuffer(...) as buf:
                ...
            # buffer is automatically disposed here
        """
        if not self._disposed:
            # Dispose all shards and reset internal arrays
            for shard in self._shards:
                shard.dispose()
            self._length_array = array("Q", [0] * self._num_shards)
            self._time_array = array("Q", [0] * self._num_shards)
            self._disposed = True

            # Notify user that buffer is no longer valid
            warnings.warn(
                "ConcurrentBuffer has been disposed and should not be used further.",
                UserWarning
            )

    def enqueue(self, item: _T) -> None:
        """
        Adds a new item to the buffer.

        Args:
            item (_T): The item to add
        """

        if self._num_shards == 1:
            # Only one shard, so just enqueue there.
            shard_idx = 0
        else:
            # Use a "flip" bit from time.monotonic_ns() to decide whether
            # to pick from left or right range, then pick the shard with min length.
            flip = time.monotonic_ns() & 1
            scan_range = self._left_range if flip == 0 else self._right_range
            shard_idx = min(scan_range, key=lambda i: self._length_array[i])

        self._shards[shard_idx].enqueue_item(item)

    def dequeue(self) -> _T:
        """
        Removes and returns the oldest item from the buffer based on the timestamp
        at the head of each shard.

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

        # If no non-empty shard is found, the buffer is empty
        if min_idx is None:
            raise Empty("dequeue from empty ConcurrentBuffer")

        # Dequeue the item from the shard with the oldest timestamp.
        return self._shards[min_idx].dequeue_item()

    def peek(self, index: Optional[int] = None) -> _T:
        """
        Returns the oldest item from the buffer without removing it.

        If an index is provided, this peeks into the specific shard. Otherwise,
        it finds the shard with the overall oldest item.

        Args:
            index (Optional[int], optional):
                The index of the shard to peek into. If None, returns the oldest
                item across all shards.

        Raises:
            Empty: If the buffer is empty or the specified shard is empty.

        Returns:
            _T: The oldest item in the buffer (copied).
        """

        if index is not None:
            # Peek the specific shard
            return self._shards[index].peek()
        else:
            # Peek across all shards for the oldest item
            return self.peek_oldest()

    def peek_oldest(self) -> _T:
        """
        Returns the oldest item across all shards without removing it.

        Raises:
            Empty: If the buffer is empty.

        Returns:
            _T: The oldest item in the buffer (copied).
        """
        min_ts = None
        min_idx = None

        # Iterate to find the oldest (lowest) timestamp
        for i, ts in enumerate(self._time_array):
            if ts > 0 and (min_ts is None or ts < min_ts):
                min_ts = ts
                min_idx = i

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
        Returns an iterator over all items in the buffer. The order is not guaranteed
        to be strictly FIFO across shards.

        Returns:
            Iterator[_T]: An iterator over the items.
        """
        items_copy: List[_T] = []
        # Collect items from each shard
        for shard in self._shards:
            items_copy.extend(shard.__iter__())
        return iter(items_copy)

    def clear(self) -> None:
        """
        Removes all items from the buffer.
        """
        for shard in self._shards:
            shard.clear()

    def __repr__(self) -> str:
        """
        Returns a string representation of the buffer,
        including the total size and the timestamp of the earliest item.

        Returns:
            str: A string representation.
        """
        if self._disposed:
            return f"<{self.__class__.__name__} [DISPOSED]>"

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
        if self._disposed:
            return f"<{self.__class__.__name__} [DISPOSED]>"
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
            initial=items_copy
        )

    def __copy__(self) -> "ConcurrentBuffer[_T]":
        """
        Supports the copy.copy() operation.
        """
        return self.copy()

    def __deepcopy__(self, memo: dict) -> "ConcurrentBuffer[_T]":
        """
        Supports the copy.deepcopy() operation.

        Args:
            memo (dict): Memoization dictionary for deepcopy.

        Returns:
            ConcurrentBuffer[_T]: A deep copy of this ConcurrentBuffer.
        """
        # Lock here if needed to prevent concurrent structural changes
        with threading.Lock():
            all_items = list(self)
            deep_items = deepcopy(all_items, memo)
            return ConcurrentBuffer(
                number_of_shards=self._num_shards,
                initial=deep_items
            )

    def to_concurrent_list(self) -> "ConcurrentList[_T]":
        """
        Converts the buffer's contents to a ConcurrentList.

        Returns:
            ConcurrentList[_T]:
                A new ConcurrentList containing the same items.
        """
        items_copy = list(self)
        return ConcurrentList(items_copy)

    def batch_update(self, func: Callable[[List[_T]], None]) -> None:
        """
        Applies a function to all items in the buffer as a batch,
        then clears and re-enqueues the updated items.

        Args:
            func (Callable[[List[_T]], None]):
                A function that takes a list of items and modifies it in place.
        """
        all_items: List[_T] = list(self)
        func(all_items)
        self.clear()
        for item in all_items:
            self.enqueue(item)

    def map(self, func: Callable[[_T], Any]) -> "ConcurrentBuffer[Any]":
        """
        Applies a function to each item in the buffer and returns
        a new ConcurrentBuffer with the transformed items.

        Args:
            func (Callable[[_T], Any]): The function to apply to each item.

        Returns:
            ConcurrentBuffer[Any]: A new ConcurrentBuffer with the mapped items.
        """
        items_copy = list(self)
        mapped = list(map(func, items_copy))
        return ConcurrentBuffer(
            number_of_shards=self._num_shards,
            initial=mapped
        )

    def filter(self, func: Callable[[_T], bool]) -> "ConcurrentBuffer[_T]":
        """
        Filters the items in the buffer based on a given predicate
        and returns a new ConcurrentBuffer with the filtered items.

        Args:
            func (Callable[[_T], bool]): The predicate function to filter items.

        Returns:
            ConcurrentBuffer[_T]: A new ConcurrentBuffer with the filtered items.
        """
        items_copy = list(self)
        filtered = list(filter(func, items_copy))
        return ConcurrentBuffer(
            number_of_shards=self._num_shards,
            initial=filtered
        )

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
        Applies a function of two arguments cumulatively to the items of the buffer,
        from left to right, to reduce the buffer to a single value.

        Args:
            func (Callable[[Any, _T], Any]):
                The function to apply, taking the accumulator and the current item.
            initial (Optional[Any], optional):
                The initial value for the accumulator. Defaults to None.

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

    def __enter__(self):
        """
        Enter the runtime context (`with ConcurrentBuffer(...) as buf:`).

        Behavior:
          - Simply returns `self`.
          - Disposal will automatically be triggered upon exiting the `with` block.

        Notes:
          - Unlike some concurrency objects, this context manager does not acquire
            or manage locks. It is purely for deterministic disposal.
          - This keeps it lightweight and composable.

        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Exit the runtime context for this ConcurrentBuffer.

        Responsibilities:
          - Automatically calls `dispose()` upon exiting, regardless of whether
            the block exits normally or via an exception.
          - Guarantees that internal resources are released exactly once.

        Parameters:
            exc_type (Optional[Type[BaseException]]): Exception type, if raised.
            exc_val (Optional[BaseException]): Exception instance, if raised.
            exc_tb (Optional[TracebackType]): Traceback, if raised.

        Notes:
          - Once exited, the buffer is invalid and should not be used.
          - This behavior is consistent with RAII and IDisposable patterns.

        Example:
            with ConcurrentBuffer(...) as buf:
                ... # safe usage
            # disposed automatically here
        """
        self.dispose()
