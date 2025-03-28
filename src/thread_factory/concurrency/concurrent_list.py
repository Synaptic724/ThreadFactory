import functools
import threading
import warnings
from copy import deepcopy
from typing import Any, Callable, Iterable, Optional, List, TypeVar, Generic

_T = TypeVar('_T')

class ConcurrentList(Generic[_T]):
    """
    A thread-safe list implementation using an underlying Python list,
    a reentrant lock for synchronization, and an atomic counter for fast,
    lock-free retrieval of the length.

    This class mimics many of the behaviors of a native Python list,
    including slicing, in-place operators, and common utility methods.
    It is designed for Python 3.13+ No-GIL environments.
    """

    def __init__(self, initial: Optional[Iterable[_T]] = None) -> None:
        """
        Initialize the ConcurrentList.

        Args:
            initial (Iterable[_T], optional): An iterable to initialize the list.
        """
        self._lock = threading.RLock()
        self._list: List[_T] = list(initial) if initial else []

    def __getitem__(self, index: int | slice) -> _T | List[_T]:
        """
        Get an item or a slice from the list.

        If ``index`` is an integer, this returns a single item.
        If ``index`` is a slice, this returns a shallow copy of that slice.

        Args:
            index (int or slice): The index or slice.

        Returns:
            _T or List[_T]:
                - A single item if index is an integer.
                - A shallow copy of the slice if index is a slice.

        Raises:
            IndexError: If the index is out of range.
        """
        with self._lock:
            if isinstance(index, int):
                try:
                    return self._list[index]
                except IndexError:
                    raise IndexError("ConcurrentList index out of range")
            else:  # slice
                # Return a shallow copy of the slice
                return self._list[index].copy()

    def __setitem__(self, index: int | slice, value: _T | Iterable[_T]) -> None:
        """
        Set an item or slice in the list.

        If ``index`` is an integer, this sets a single item at that index.
        If ``index`` is a slice, this replaces that slice with the contents of ``value``.

        For slice assignment, adjusts the atomic counter appropriately.

        Args:
            index (int or slice): The index or slice.
            value (_T or Iterable[_T]): The new value(s).

        Raises:
            IndexError: If the index is out of range.
        """
        with self._lock:
            if isinstance(index, int):
                try:
                    # If value is an iterable, type checkers might complain, so ignore for brevity
                    self._list[index] = value  # type: ignore
                except IndexError:
                    raise IndexError("ConcurrentList index out of range")
            else:
                old_slice = self._list[index]
                # Ensure we're assigning a list if it's an iterable, or treat as single item
                if isinstance(value, Iterable) and not isinstance(value, str):
                    value_list = list(value)
                else:
                    # Fallback if someone calls slice assignment with a single non-iterable
                    # You could also just raise TypeError here if you prefer stricter behavior
                    value_list = [value]  # type: ignore
                self._list[index] = value_list

    def __delitem__(self, index: int | slice) -> None:
        """
        Delete an item or slice from the list.

        If `index` is an integer, deletes the single element at that index.
        If `index` is a slice, deletes all elements in that slice.

        Args:
            index (int or slice): The index or slice to delete.

        Raises:
            IndexError: If the index is out of range (for int index).
        """
        with self._lock:
            try:
                del self._list[index]
            except IndexError:
                # Only raise a custom message for int index, slices behave differently
                if isinstance(index, int):
                    raise IndexError("ConcurrentList index out of range")
                else:
                    # Re-raise slice-related errors (could be ValueError or IndexError)
                    raise

    def append(self, item: _T) -> None:
        """
        Append an item to the end of the list.

        Args:
            item (_T): The item to append.
        """
        with self._lock:
            self._list.append(item)

    def extend(self, items: Iterable[_T]) -> None:
        """
        Extend the list by appending elements from the iterable.

        Args:
            items (Iterable[_T]): An iterable of items to add.

        Raises:
            TypeError: If items is not iterable (e.g., if it's None).
        """
        with self._lock:
            for x in items:
                self._list.append(x)

    def insert(self, index: int, item: _T) -> None:
        """
        Insert an item at the specified index.

        Args:
            index (int): The index at which to insert.
            item (_T): The item to insert.

        Raises:
            IndexError: If the index is out of range (depending on desired behavior).
        """
        with self._lock:
            # Python's list.insert clamps the index if out of range, but you can raise if you prefer
            self._list.insert(index, item)

    def remove(self, item: _T) -> None:
        """
        Remove the first occurrence of an item from the list.

        Args:
            item (_T): The item to remove.

        Raises:
            ValueError: If the item is not found.
        """
        with self._lock:
            try:
                self._list.remove(item)
            except ValueError:
                raise ValueError(f"'{item}' not in ConcurrentList")

    def pop(self, index: int = -1) -> _T:
        """
        Remove and return the item at the given index (default is last).

        Args:
            index (int, optional): The index to pop. Defaults to -1.

        Returns:
            _T: The popped item.

        Raises:
            IndexError: If the list is empty or index is out of range.
        """
        with self._lock:
            if not self._list:
                raise IndexError("pop from empty ConcurrentList")
            try:
                return self._list.pop(index)
            except IndexError:
                raise IndexError("ConcurrentList index out of range for pop")

    def clear(self) -> None:
        """
        Remove all items from the list.
        """
        with self._lock:
            self._list.clear()

    def __len__(self) -> int:
        """
        Return the number of items in the list using the atomic counter.

        Returns:
            int: The current size of the list.
        """
        return len(self._list)

    def __iter__(self) -> Iterable[_T]:
        """
        Return an iterator over a shallow copy of the list.
        """
        with self._lock:
            return iter(self._list.copy())

    def __contains__(self, item: Any) -> bool:
        """
        Check if an item is in the list.

        Args:
            item (Any): The item to check for.

        Returns:
            bool: True if the item is present, False otherwise.
        """
        with self._lock:
            return item in self._list

    def __repr__(self) -> str:
        """
        Return the official string representation of the ConcurrentList.
        """
        with self._lock:
            return f"{self.__class__.__name__}({self._list!r})"

    def __str__(self) -> str:
        """
        Return the informal string representation of the ConcurrentList.
        """
        with self._lock:
            return str(self._list)

    def __eq__(self, other: Any) -> bool:
        """
        Check equality with another ConcurrentList or a standard list.

        Args:
            other (Any): The object to compare.

        Returns:
            bool: True if equal, False otherwise.
        """
        if isinstance(other, ConcurrentList):
            # Acquire locks in a defined order to avoid deadlocks
            if id(self) < id(other):
                first, second = self, other
            else:
                first, second = other, self
            with first._lock, second._lock:
                return self._list == other._list
        elif isinstance(other, list):
            with self._lock:
                return self._list == other
        return False

    def __ne__(self, other: Any) -> bool:
        """
        Check inequality with another ConcurrentList or a standard list.
        """
        return not self.__eq__(other)

    def __bool__(self) -> bool:
        """
        Return True if the list is non-empty.
        """
        return len(self._list) != 0

    def __reversed__(self) -> Iterable[_T]:
        """
        Return a reverse iterator over a copy of the list.
        """
        with self._lock:
            return reversed(self._list.copy())

    def __iadd__(self, other: Iterable[_T]) -> 'ConcurrentList[_T]':
        """
        Implements in-place addition (+=).

        Args:
            other (Iterable[_T]): The iterable to extend with.

        Returns:
            ConcurrentList[_T]: self
        """
        self.extend(other)
        return self

    def __imul__(self, n: int) -> 'ConcurrentList[_T]':
        """
        Implements in-place multiplication (*=).

        Args:
            n (int): The multiplier.

        Returns:
            ConcurrentList[_T]: self

        Raises:
            TypeError: If n is not an integer.
        """
        if not isinstance(n, int):
            raise TypeError("can't multiply sequence by non-int of type '{}'".format(type(n).__name__))
        with self._lock:
            self._list *= n
        return self

    def __mul__(self, n: int) -> 'ConcurrentList[_T]':
        """
        Implements multiplication (*).

        Args:
            n (int): The multiplier.

        Returns:
            ConcurrentList[_T]: A new ConcurrentList with the elements repeated.

        Raises:
            TypeError: If n is not an integer.
        """
        if not isinstance(n, int):
            raise TypeError("can't multiply sequence by non-int of type '{}'".format(type(n).__name__))
        with self._lock:
            return ConcurrentList(initial=self._list * n)

    def __rmul__(self, n: int) -> 'ConcurrentList[_T]':
        """
        Implements reverse multiplication.
        """
        return self.__mul__(n)

    def index(self, item: Any, start: int = 0, end: Optional[int] = None) -> int:
        """
        Return first index of value.

        Args:
            item (Any): The item to find.
            start (int, optional): Start index for search.
            end (int, optional): End index for search.

        Returns:
            int: The index of the item.

        Raises:
            ValueError: If the item is not present.
        """
        with self._lock:
            return self._list.index(item, start, end if end is not None else len(self._list))

    def count(self, item: Any) -> int:
        """
        Return the number of occurrences of a value.

        Args:
            item (Any): The item to count.

        Returns:
            int: The number of occurrences.
        """
        with self._lock:
            return self._list.count(item)

    def __copy__(self) -> 'ConcurrentList[_T]':
        """
        Return a shallow copy of the ConcurrentList.
        """
        with self._lock:
            return ConcurrentList(initial=self._list.copy())

    def __deepcopy__(self, memo: dict) -> 'ConcurrentList[_T]':
        """
        Return a deep copy of the ConcurrentList.

        Args:
            memo (dict): Memoization dictionary for deepcopy.

        Returns:
            ConcurrentList[_T]: A deep copy of this ConcurrentList.
        """
        with self._lock:
            return ConcurrentList(initial=deepcopy(self._list, memo))

    def __enter__(self) -> List[_T]:
        """
        Enter the runtime context and acquire the lock.

        Returns:
            List[_T]: The internal list (use with extreme caution as it bypasses thread safety).
        """
        warnings.warn(
            "Direct access to the internal list via the context manager bypasses the thread-safe interface. "
            "Use with extreme caution.",
            UserWarning
        )
        self._lock.acquire()
        return self._list

    def __exit__(self, exc_type: Optional[type], exc_val: Optional[BaseException], exc_tb: Optional[object]) -> None:
        """
        Exit the runtime context and release the lock.
        """
        self._lock.release()

    def to_list(self) -> List[_T]:
        """
        Return a shallow copy of the internal list.

        Returns:
            List[_T]: A copy of the list.
        """
        with self._lock:
            return list(self._list)

    def batch_update(self, func: Callable[[List[_T]], None]) -> None:
        """
        Perform a batch update on the list under a single lock acquisition.
        This method allows multiple operations to be performed atomically.

        Args:
            func (Callable[[List[_T]], None]): A function that accepts the internal list as its only argument.
                                               The function should perform all necessary mutations.
        """
        with self._lock:
            func(self._list)

    def sort(self, key: Optional[Callable[[_T], Any]] = None, reverse: bool = False) -> None:
        """
        Sort the list in-place.

        Args:
            key (Callable[[_T], Any], optional): A function used to extract a comparison key.
            reverse (bool, optional): If True, the list elements are sorted as if each comparison were reversed.
        """
        with self._lock:
            self._list.sort(key=key, reverse=reverse)

    def reverse(self) -> None:
        """
        Reverse the elements of the list in-place.
        """
        with self._lock:
            self._list.reverse()

    def map(self, func: Callable[[_T], Any]) -> 'ConcurrentList[Any]':
        """
        Apply a function to all elements and return a new ConcurrentList.

        Args:
            func (Callable[[_T], Any]): The function to apply.

        Returns:
            ConcurrentList[Any]: A new ConcurrentList with the function applied to each element.
        """
        with self._lock:
            return ConcurrentList(initial=list(map(func, self._list.copy())))

    def filter(self, func: Callable[[_T], bool]) -> 'ConcurrentList[_T]':
        """
        Filter elements based on a function and return a new ConcurrentList.

        Args:
            func (Callable[[_T], bool]): The filter function.

        Returns:
            ConcurrentList[_T]: A new ConcurrentList containing only elements where func(element) is True.
        """
        with self._lock:
            return ConcurrentList(initial=list(filter(func, self._list.copy())))

    def reduce(self, func: Callable[[Any, _T], Any], initial: Optional[Any] = None) -> Any:
        """
        Apply a function of two arguments cumulatively to the items of the list.

        Args:
            func (Callable[[Any, _T], Any]): Function to apply.
            initial (Any, optional): Starting value.

        Returns:
            Any: The reduced value.

        Raises:
            TypeError: If the list is empty and no initial value is provided.
        """
        with self._lock:
            snapshot = self._list.copy()
        # Once copied, we can reduce outside the lock
        if initial is None:
            return functools.reduce(func, snapshot)
        else:
            return functools.reduce(func, snapshot, initial)


    def update(self, other: Iterable[_T]) -> None:
        """
        Update the list with elements from another iterable.

        Args:
            other (Iterable[_T]): The iterable to update from.
        """
        with self._lock:
            self._list.extend(other)
