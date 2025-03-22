import threading
from copy import deepcopy
import functools
from src.Threading.Dict import ConcurrentDict
from typing import (
    Any,
    Callable,
    Dict,
    Generic,
    Iterator,
    List,
    Optional,
    TypeVar
)

class Empty(Exception):
    """ Exception raised by Bag when its empty. """
    def __init__(self, *args, **kwargs):
        pass

_T = TypeVar("_T")

class ConcurrentBag(Generic[_T]):
    """
    A thread-safe multiset ("bag") implementation using:
    - a dict from item -> integer count
    - a reentrant lock for synchronization

    Items can appear multiple times, unlike a standard set. This class
    is designed for Python 3.13+ No-GIL environments (though it will
    work fine in standard Python as well).
    """

    def __init__(self, initial: Optional[List[_T]] = None) -> None:
        """
        Initialize the ConcurrentBag.

        Args:
            initial (list of _T, optional):
                A list (or iterable turned into a list) of initial items
                to add to the bag.
        """
        if initial is None:
            initial = []
        self._lock = threading.RLock()
        # Dictionary to store item -> count
        self._bag: Dict[_T, int] = {}

        # Add initial items
        for item in initial:
            self._bag[item] = self._bag.get(item, 0) + 1

    def add(self, item: _T) -> None:
        """
        Add one occurrence of `item` to the bag.

        Args:
            item (_T): The item to add.
        """
        with self._lock:
            self._bag[item] = self._bag.get(item, 0) + 1

    def remove(self, item: _T) -> None:
        """
        Remove one occurrence of `item` from the bag.

        Raises:
            KeyError: If the item is not present in the bag.
        """
        with self._lock:
            if item not in self._bag or self._bag[item] == 0:
                raise KeyError(f"Item {item!r} not in ConcurrentBag")
            self._bag[item] -= 1
            if self._bag[item] == 0:
                del self._bag[item]

    def discard(self, item: _T) -> None:
        """
        Remove one occurrence of `item` from the bag if present,
        but do nothing if the item is not in the bag.
        """
        with self._lock:
            if item not in self._bag or self._bag[item] == 0:
                return
            self._bag[item] -= 1
            if self._bag[item] == 0:
                del self._bag[item]

    def pop(self) -> _T:
        """
        Remove and return a single occurrence of an arbitrary item from the bag.

        Raises:
            KeyError: If the bag is empty.

        Returns:
            _T: An item that was removed.
        """
        with self._lock:
            if not self._bag:
                raise Empty("pop from empty ConcurrentBag")

            # Remove an arbitrary item. (dict iteration order is arbitrary in <3.7,
            # but typically insertion order in 3.7+, which is fine for a bag.)
            item, count = next(iter(self._bag.items()))
            if count == 1:
                del self._bag[item]
            else:
                self._bag[item] = count - 1
            return item

    def clear(self) -> None:
        """
        Remove all items from the bag.
        """
        with self._lock:
            self._bag.clear()

    def __len__(self) -> int:
        """
        Return the total number of items in the bag (the sum of all counts).
        """
        with self._lock:
            return sum(self._bag.values())

    def __bool__(self) -> bool:
        """
        Return True if the bag is non-empty.

        Returns:
            bool: True if there's at least one item, False otherwise.
        """
        return len(self) != 0

    def __contains__(self, item: object) -> bool:
        """
        Check if the bag contains at least one occurrence of `item`.

        Args:
            item (object): The item to check for.

        Returns:
            bool: True if at least one occurrence is present, else False.
        """
        with self._lock:
            return item in self._bag

    def count_of(self, item: _T) -> int:
        """
        Return how many times `item` appears in the bag.

        Args:
            item (_T): The item to count.

        Returns:
            int: The number of occurrences of this item.
        """
        with self._lock:
            return self._bag.get(item, 0)

    def __iter__(self) -> Iterator[_T]:
        """
        Return an iterator that yields each item in the bag as many times as it appears.
        This snapshot is taken under the lock, but iteration happens after the lock is released.

        Yields:
            _T: Items from the bag (including duplicates).
        """
        with self._lock:
            # Take a snapshot of the items -> counts
            snapshot = list(self._bag.items())
        for item, count in snapshot:
            for _ in range(count):
                yield item

    def unique_items(self) -> List[_T]:
        """
        Return a list of distinct items present in the bag (each item only once).

        Returns:
            List[_T]: A snapshot of all unique items.
        """
        with self._lock:
            return list(self._bag.keys())

    def __repr__(self) -> str:
        """
        Return the official string representation of the ConcurrentBag.
        """
        with self._lock:
            return f"{self.__class__.__name__}({dict(self._bag)!r})"

    def __str__(self) -> str:
        """
        Return an informal string representation of the ConcurrentBag.
        """
        with self._lock:
            return f"Bag({dict(self._bag)!r})"

    def copy(self) -> "ConcurrentBag[_T]":
        """
        Return a shallow copy of the ConcurrentBag.

        Returns:
            ConcurrentBag[_T]: A new ConcurrentBag with the same items and counts.
        """
        with self._lock:
            new_bag = ConcurrentBag()
            new_bag._bag = dict(self._bag)
        return new_bag

    def __copy__(self) -> "ConcurrentBag[_T]":
        """
        For the built-in copy.copy(...).

        Returns:
            ConcurrentBag[_T]: A shallow copy of this ConcurrentBag.
        """
        return self.copy()

    def __deepcopy__(self, memo: dict) -> "ConcurrentBag[_T]":
        """
        Return a deep copy of the ConcurrentBag.

        Args:
            memo (dict): Memoization dictionary for deepcopy.

        Returns:
            ConcurrentBag[_T]: A deep copy of this ConcurrentBag.
        """
        with self._lock:
            new_bag = ConcurrentBag()
            new_bag._bag = deepcopy(self._bag, memo)
        return new_bag

    def to_concurrent_dict(self) -> 'ConcurrentDict[_T, int]':
        """
        Return a shallow copy of the internal dictionary (item -> count).

        Returns:
            Dict[_T, int]: A standard dictionary of items to counts.
        """
        with self._lock:
            return ConcurrentDict(self._bag)

    def batch_update(self, func: Callable[[Dict[_T, int]], None]) -> None:
        """
        Perform a batch update on the bag under a single lock acquisition.
        This method allows multiple operations to be performed atomically.

        Args:
            func (Callable[[Dict[_T, int]], None]):
                A function that accepts the internal dictionary (item->count)
                as its only argument. The function should perform all necessary mutations.
        """
        with self._lock:
            func(self._bag)

    def map(self, func: Callable[[_T], _T]) -> "ConcurrentBag[_T]":
        """
        Apply a function to each item and return a new ConcurrentBag with the transformed items.
        Note that if func(x) == func(y) for multiple items, the new bag merges them.

        Args:
            func (Callable[[_T], _T]): A function to apply to each item.

        Returns:
            ConcurrentBag[_T]: A new bag with the transformed items.
        """
        with self._lock:
            # We'll create a new dict: for each (item, count),
            # we transform 'item' to 'new_item'.
            new_dict: Dict[_T, int] = {}
            for item, count in self._bag.items():
                new_item = func(item)
                new_dict[new_item] = new_dict.get(new_item, 0) + count
        new_bag = ConcurrentBag()
        new_bag._bag = new_dict
        return new_bag

    def filter(self, predicate: Callable[[_T], bool]) -> "ConcurrentBag[_T]":
        """
        Keep only items for which `predicate(item)` is True. Return a new bag.

        Args:
            predicate (Callable[[_T], bool]): A function returning True if an item
                                              should be kept, False otherwise.

        Returns:
            ConcurrentBag[_T]: A new bag containing only the items that passed the filter.
        """
        with self._lock:
            new_dict: Dict[_T, int] = {}
            for item, count in self._bag.items():
                if predicate(item):
                    new_dict[item] = count
        new_bag = ConcurrentBag()
        new_bag._bag = new_dict
        return new_bag

    def reduce(
        self,
        func: Callable[[Any, _T], Any],
        initial: Optional[Any] = None
    ) -> Any:
        """
        Apply a function of two arguments cumulatively to the items in the bag,
        ignoring item multiplicities only in how we feed them into func (that is,
        we pass items as many times as their counts).

        Args:
            func (Callable[[Any, _T], Any]): A function taking (accumulator, item).
            initial (Any, optional): A starting value for the accumulator.

        Returns:
            Any: The reduced value.

        Raises:
            TypeError: If the bag is empty and no initial value is provided.

        Example:
            # Summation of all numeric items in the bag:
            def add(acc, x):
                return acc + x
            total = concurrent_bag.reduce(add, 0)
        """
        with self._lock:
            snapshot = list(self._bag.items())

        # Expand the snapshot: each (item, count) → multiple item calls.
        expanded_items: List[_T] = []
        for item, c in snapshot:
            expanded_items.extend([item] * c)

        if not expanded_items and initial is None:
            raise TypeError("reduce() of empty ConcurrentBag with no initial value")

        if initial is None:
            return functools.reduce(func, expanded_items)
        else:
            return functools.reduce(func, expanded_items, initial)
