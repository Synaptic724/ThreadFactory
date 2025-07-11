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
    Internal shard class for storing items in a local deque with its own lock.

    Each shard contributes:
      - A deque to hold items.
      - A lock (`RLock`) to ensure thread-safe operations within this shard.
      - A shared array reference to track the shard's length at index `_index`.

    Shards are used in tandem by `ConcurrentCollection` (or similar structures) to
    reduce contention by distributing load across multiple locked deques rather
    than one global lock. There is no guarantee of global ordering across shards,
    only FIFO within each shard.

    Disposal:
      - `dispose()` clears the deque and zeroes out the associated entry
        in the shared length array. Once disposed, the shard should not be reused.
    """

    __slots__ = IDisposable.__slots__ + ['_lock', '_queue', '_length_array', '_index']

    def __init__(self, len_array: array, index: int) -> None:
        """
        Initialize a new shard.

        Args:
            len_array (array):
                A shared array (type 'Q') tracking the length of each shard in the parent collection.
            index (int):
                This shard's position (index) in the shared length array.
        """
        super().__init__()
        # Lock to ensure thread-safe access to _queue.
        self._lock = threading.RLock()

        # The internal deque storing items for this shard.
        self._queue: Deque[_T] = deque()

        # Reference to the shared length array in the parent collection.
        self._length_array = len_array

        # Index in the shared length array for this particular shard.
        self._index = index

    def dispose(self) -> None:
        """
        Clears the shard's data and marks it as disposed.

        This method is idempotent; multiple calls have no further effect.
        """
        with self._lock:
            if not self._disposed:
                self._queue.clear()
                self._length_array[self._index] = 0
                self._disposed = True

    def _increase_length_value(self) -> None:
        """
        Increments the length counter for this shard in the shared length array.

        Called whenever we add a new item to the shard.
        """
        self._length_array[self._index] += 1

    def _decrease_length_value(self) -> None:
        """
        Decrements the length counter for this shard in the shared length array.

        Called whenever we remove an item from the shard.
        """
        self._length_array[self._index] -= 1

    def pop_item(self) -> _T:
        """
        Removes and returns the front (oldest) item from this shard.

        This is the FIFO operation at the shard level.

        Raises:
            Empty: If the shard is empty.

        Returns:
            _T: The item removed from the front of the shard.
        """
        with self._lock:
            if not self._queue:
                raise Empty("pop from empty ConcurrentCollection shard (race condition)")
            self._decrease_length_value()
            return self._queue.popleft()

    def add_item(self, item: _T) -> None:
        """
        Adds a new item to the end (back) of this shard.

        Args:
            item (_T): The element to store.
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
                raise Empty("peek from empty ConcurrentCollection")
            return copy(self._queue[0])

    def __iter__(self) -> Iterator[_T]:
        """
        Provides an iterator over items in this shard in insertion order.

        Note:
            This locks the shard briefly to snapshot its contents,
            then returns an iterator over that snapshot.
        """
        with self._lock:
            return iter(list(self._queue))

    def clear(self) -> None:
        """
        Empties the shard's deque and resets its length count to 0.

        Future operations (add/push) may still occur if the shard isn't disposed.
        """
        with self._lock:
            self._queue.clear()
            self._length_array[self._index] = 0

    def __enter__(self):
        """
        Allows usage via a `with` statement, returning the shard itself.
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Calls dispose upon exiting the context manager scope.
        """
        self.dispose()


class ConcurrentCollection(Generic[_T], IDisposable):
    """
    A thread-safe, high-level collection that distributes items across multiple
    internal shards (lock-protected deques). Each shard is independently locked,
    so multiple runtime can access different shards in parallel with minimal contention.

    Overall ordering across shards is not guaranteed to be strictly FIFO — each shard
    behaves like a small FIFO queue, but the global order is only approximate.

    Recommended Usage:
      - Ideal for up to ~20 total runtime (producers + consumers).
      - For each pair of runtime (producer/consumer), consider 1 shard as a rough guideline.
      - If heavy contention or extremely high concurrency is expected,
        consider `ConcurrentQueue` or `ConcurrentStack` instead.

    Shard Count:
      - Must be at least 1.
      - If > 1, must be even. (This helps with symmetrical partitioning in some logic.)
      - The actual number of shards used is set in the constructor, defaulting to
        the `total_thread_count` parameter if provided.

    Disposal:
      - Implemented via `dispose()`, which disposes all shards and clears shared data.
      - Refrain from using the collection once disposed.
      - `with ConcurrentCollection(...) as cc:` usage automatically calls `dispose()` on exit.
    """

    def __init__(
            self,
            total_thread_count: int = 1,
            initial: Optional[Iterable[_T]] = None,
    ) -> None:
        """
        Initializes a new ConcurrentCollection with a given number of shards
        and optional initial items.

        Args:
            total_thread_count (int, optional):
                The number of runtime you plan to use overall. Defaults to 1.
                Used to derive the shard count (same value). Must be >= 1 and
                even if > 1.
            initial (Optional[Iterable[_T]], optional):
                An optional iterable of items to initialize the collection with.

        Raises:
            ValueError: If shard count is < 1 or is an odd number > 1.
        """
        super().__init__()
        number_of_shards = max(1, total_thread_count)
        if initial is None:
            initial = []

        if number_of_shards < 1:
            raise ValueError("number_of_shards must be at least 1")
        if number_of_shards > 1 and number_of_shards % 2 != 0:
            number_of_shards += 1

        # Store shard count
        self._num_shards = number_of_shards

        # Shared array tracking the size of each shard (using unsigned 64-bit: "Q")
        self._length_array = array("Q", [0] * self._num_shards)

        # Create the shards themselves.
        self._shards: List[_Shard[_T]] = [
            _Shard(self._length_array, i)
            for i in range(self._num_shards)
        ]

        # Add initial items if provided.
        for item in initial:
            self.add(item)

    def add(self, item: _T) -> None:
        """
        Adds (pushes) an item to the collection.

        This uses `_select_shard()` to pick which shard to place the item into,
        distributing load. Each shard remains FIFO internally.

        Args:
            item (_T): The item to add.
        """
        shard_idx = self._select_shard()
        self._shards[shard_idx].add_item(item)

    def pop(self) -> _T:
        """
        Removes and returns an item from the collection (like dequeue).
        It attempts a short scan across shards to find any non-empty one.

        Raises:
            Empty: If all shards are empty.

        Returns:
            _T: The item from one of the shards.
        """
        # Start from a "random-ish" shard index and attempt to pop.
        start = self._select_shard()
        for offset in range(self._num_shards):
            idx = (start + offset) % self._num_shards
            if self._length_array[idx] > 0:
                # Found a shard with at least 1 item
                return self._shards[idx].pop_item()
        # If we never found a non-empty shard, collection is empty.
        raise Empty("pop from empty ConcurrentCollection")

    def _select_shard(self) -> int:
        """
        Select a shard index by mixing bits from `time.monotonic_ns()`.
        This helps distribute enqueues/pops across shards in a pseudo-random way.

        Returns:
            int: The chosen shard index (0 <= idx < _num_shards).
        """
        ns = time.monotonic_ns()
        # We do a small bitwise operation + modulo to produce a shard index.
        return ((ns >> 3) ^ ns) % self._num_shards

    def peek(self, shard_index: Optional[int] = None) -> _T:
        """
        Returns (but does not remove) an item from the collection.
        If `shard_index` is given, attempts to peek specifically at that shard.
        Otherwise, scans shards in order, returning from the first non-empty shard.

        Args:
            shard_index (Optional[int], optional):
                The index of the shard to peek. If None, find the first non-empty shard.

        Raises:
            IndexError: If `shard_index` is out of range.
            Empty: If the chosen shard (or all shards) is empty.

        Returns:
            _T: An item from the front of a shard.
        """
        if shard_index is not None:
            if not (0 <= shard_index < self._num_shards):
                raise IndexError("Shard index out of range")
            return self._shards[shard_index].peek()

        # No shard index provided => scan each shard in order until we find an item
        for shard in self._shards:
            try:
                return shard.peek()
            except Empty:
                # that shard was empty; keep scanning
                pass
        raise Empty("peek from empty ConcurrentCollection")

    def __len__(self) -> int:
        """
        Returns the total number of items across all shards.

        Returns:
            int: The sum of the lengths of all shards.
        """
        return sum(self._length_array)

    def __bool__(self) -> bool:
        """
        True if this collection has at least one item, False otherwise.
        """
        return len(self) != 0

    def __iter__(self) -> Iterator[_T]:
        """
        Iterates through all items in this collection, shard by shard.

        The iteration order is not strictly FIFO across shards.
        Items in the same shard are in insertion order, but
        shards themselves have no guaranteed order relative to each other.

        Yields:
            _T: Each item in the collection.
        """
        items_copy: List[_T] = []
        for shard in self._shards:
            items_copy.extend(shard.__iter__())
        return iter(items_copy)

    def clear(self) -> None:
        """
        Removes all items from all shards, resetting each shard to an empty state.
        """
        for shard in self._shards:
            shard.clear()

    def __repr__(self) -> str:
        """
        Returns a string representation showing the total size and the
        minimum non-empty shard size (for insight into load distribution).

        Example:
            ConcurrentCollection(total_size=25, min_shard_len=3)
        """
        total_len = len(self)
        non_empty_lengths = [l for l in self._length_array if l > 0]
        min_shard_len = min(non_empty_lengths) if non_empty_lengths else 0
        return f"{self.__class__.__name__}(total_size={total_len}, min_shard_len={min_shard_len})"

    def __str__(self) -> str:
        """
        Returns a string representation of all items as a list.

        Warning:
            This may be large if the collection has many items.
        """
        return str(list(self))

    def copy(self) -> "ConcurrentCollection[_T]":
        """
        Creates a shallow copy of the collection, collecting all items
        into a new `ConcurrentCollection` with the same shard count.

        Returns:
            ConcurrentCollection[_T]: The new collection containing
            copies of the current items.
        """
        items_copy = list(self)
        return ConcurrentCollection(
            total_thread_count=self._num_shards,
            initial=items_copy
        )

    def __copy__(self) -> "ConcurrentCollection[_T]":
        """
        Hook for `copy.copy()`.
        """
        return self.copy()

    def __deepcopy__(self, memo: dict) -> "ConcurrentCollection[_T]":
        """
        Hook for `copy.deepcopy()`.

        Acquires a global lock to reduce the chance of racing with mutation.
        Copies all items deeply, then builds a new ConcurrentCollection
        with those deep-copied items.
        """
        with threading.Lock():
            all_items = list(self)
            deep_items = deepcopy(all_items, memo)
            return ConcurrentCollection(
                total_thread_count=self._num_shards,
                initial=deep_items
            )

    def to_concurrent_list(self) -> "ConcurrentList[_T]":
        """
        Converts the collection's contents into a `ConcurrentList`.

        Returns:
            ConcurrentList[_T]: A new concurrent list containing all items.
        """
        items_copy = list(self)
        return ConcurrentList(items_copy)

    def batch_update(self, func: Callable[[List[_T]], None]) -> None:
        """
        Performs a 'batch update' by collecting all items, passing them
        to the provided function, clearing the shards, then re-inserting the updated items.

        Args:
            func (Callable[[List[_T]], None]):
                A function that accepts a list of items and mutates them in-place.
        """
        all_items: List[_T] = list(self)
        func(all_items)
        self.clear()
        for item in all_items:
            self.add(item)

    def map(self, func: Callable[[_T], Any]) -> "ConcurrentCollection[Any]":
        """
        Constructs a new collection by applying `func` to each item in the current collection.

        Args:
            func (Callable[[_T], Any]): The transformation function.

        Returns:
            ConcurrentCollection[Any]: A new collection with mapped items.
        """
        items_copy = list(self)
        mapped = list(map(func, items_copy))
        return ConcurrentCollection(
            total_thread_count=self._num_shards,
            initial=mapped
        )

    def filter(self, func: Callable[[_T], bool]) -> "ConcurrentCollection[_T]":
        """
        Constructs a new collection containing only items for which
        `func(item)` is True.

        Args:
            func (Callable[[_T], bool]): The predicate to apply.

        Returns:
            ConcurrentCollection[_T]: A new collection with the filtered items.
        """
        items_copy = list(self)
        filtered = [x for x in items_copy if func(x)]
        return ConcurrentCollection(
            total_thread_count=self._num_shards,
            initial=filtered
        )

    def remove_item(self, item: _T) -> bool:
        """
        Removes the *first* occurrence of `item` from the collection (by identity check).

        This is an O(n) operation since it reconstructs the entire collection.

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
                self.add(i)
        return found

    def reduce(self, func: Callable[[Any, _T], Any], initial: Optional[Any] = None) -> Any:
        """
        Reduces the collection into a single value by iterating over all items in shard order
        and applying `func(acc, item)` cumulatively.

        Args:
            func (Callable[[Any, _T], Any]):
                A two-argument function with signature func(accumulator, item).
            initial (Optional[Any], optional):
                An initial accumulator value. If None and the collection is empty,
                a TypeError is raised (mirroring the built-in reduce behavior).

        Returns:
            Any: The final accumulated result.
        """
        items_copy = list(self)
        if not items_copy and initial is None:
            raise TypeError("reduce() of empty ConcurrentCollection with no initial value")
        if initial is None:
            return functools.reduce(func, items_copy)
        else:
            return functools.reduce(func, items_copy, initial)

    # -----------------------------------------------------------------------------------
    # Disposable Implementation
    # -----------------------------------------------------------------------------------
    def dispose(self) -> None:
        """
        Disposes of this ConcurrentCollection and releases its resources.

        Responsibilities:
          - Disposes all internal shards, which will clear their internal queues and reset their length counters.
          - Resets the internal `_length_array` to zeroed values.
          - Marks the collection as disposed via the `self.disposed` flag.

        Behavior:
          - This method is idempotent. Calling `dispose()` multiple times is safe and will have no effect after the first call.
          - Once disposed, the collection is considered invalid and should not be used further.
          - This follows a typical deterministic disposal pattern (inspired by .NET's `IDisposable`), ensuring explicit control over resource lifetime.

        Notes:
          - Unlike some patterns, this implementation does NOT prevent method calls after disposal.
            It is the user's responsibility to ensure that no further use is made of the object after it is disposed.
        """
        if not self._disposed:
            for shard in self._shards:
                shard.dispose()
            self._length_array = array("Q", [0] * self._num_shards)
            self._disposed = True

        warnings.warn(
            "Your ConcurrentCollection has been disposed and should not be used further. ",
            UserWarning
        )

    def __enter__(self):
        """
        Enters the context manager for this ConcurrentCollection.

        Usage:
            with ConcurrentCollection(...) as cc:
                # Work with cc
                ...

        Behavior:
          - Returns `self` to be used inside the `with` block.
          - Context blocks are optional and purely syntactic sugar if you want deterministic disposal.

        Notes:
          - Entering the context does NOT acquire or release any locks by itself (unlike some other concurrent structures).
          - Disposal will still be automatically invoked on exit (via `__exit__()`).
          - You are expected to manually manage thread safety through the collection's own thread-safe methods.
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Exits the context manager for this ConcurrentCollection.

        Responsibilities:
          - Automatically calls `dispose()` to ensure cleanup of internal resources,
            even if an exception was raised inside the `with` block.
          - This guarantees that the collection and all its shards are safely released
            without requiring explicit calls to `dispose()`.

        Args:
            exc_type (type): The exception type (if an exception was raised).
            exc_val (Exception): The exception instance (if raised).
            exc_tb (traceback): The traceback object (if raised).

        Notes:
          - This pattern guarantees deterministic cleanup.
          - After exiting the context, the collection is no longer valid.
          - You can still call `dispose()` manually outside the context if preferred.
        """
        self.dispose()
