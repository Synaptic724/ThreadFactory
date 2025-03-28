import functools
import threading
import warnings
from copy import deepcopy
from typing import (
    Any,
    Callable,
    Dict,
    Generic,
    Iterable,
    Iterator,
    List,
    Mapping,
    Optional,
    Tuple,
    TypeVar,
    Union,
)

_K = TypeVar("_K")
_V = TypeVar("_V")

class ConcurrentDict(Generic[_K, _V]):
    """
    A thread-safe dictionary implementation using:
      - An underlying Python dict
      - A reentrant lock (RLock) for synchronization

    This class mimics many behaviors of a native Python dict, including
    common utility methods. It is designed for Python 3.13+ No-GIL
    environments (though it will also work fine in standard Python).
    """

    def __init__(
        self,
        initial: Optional[Union[Mapping[_K, _V], Iterable[Tuple[_K, _V]]]] = None
    ) -> None:
        """
        Initialize the ConcurrentDict.

        Args:
            initial (Mapping[_K, _V] or Iterable of (_K, _V), optional):
                Initial data for the dictionary. Can be another dictionary,
                or an iterable of (key, value) pairs.
        """
        if initial is None:
            initial = {}
        # Convert 'initial' to a dict:
        # - If it's already dict-like, dict(...) copies it.
        # - If it's an iterable of (key, value) pairs, dict(...) will handle that as well.
        self._dict: Dict[_K, _V] = dict(initial)
        self._lock: threading.RLock = threading.RLock()

    def __getitem__(self, key: _K) -> _V:
        """
        Get an item by key.

        Args:
            key (_K): The key to retrieve.

        Returns:
            _V: The value associated with the key.

        Raises:
            KeyError: If the key is not in the dict.
        """
        with self._lock:
            return self._dict[key]

    def __setitem__(self, key: _K, value: _V) -> None:
        """
        Set the item for the specified key.

        Args:
            key (_K): The key to set.
            value (_V): The new value to store.
        """
        with self._lock:
            self._dict[key] = value

    def __delitem__(self, key: _K) -> None:
        """
        Delete an item by key.

        Args:
            key (_K): The key to delete.

        Raises:
            KeyError: If the key is not in the dict.
        """
        with self._lock:
            del self._dict[key]

    def __contains__(self, key: object) -> bool:
        """
        Check if a key is in the dict.

        Args:
            key (object): The key to check.

        Returns:
            bool: True if key is in the dictionary, False otherwise.
        """
        with self._lock:
            return key in self._dict

    def __len__(self) -> int:
        """
        Return the number of items in the dictionary.

        Returns:
            int: The number of key-value pairs in the dict.
        """
        with self._lock:
            return len(self._dict)

    def __bool__(self) -> bool:
        """
        Return True if the dict is non-empty.

        Returns:
            bool: True if there is at least one item, False otherwise.
        """
        return len(self) != 0

    def __iter__(self) -> Iterator[_K]:
        """
        Return an iterator over the keys in a shallow copy.
        This prevents 'dictionary changed size during iteration' errors.

        Returns:
            Iterator[_K]: An iterator over the keys.
        """
        with self._lock:
            return iter(list(self._dict.keys()))

    def __repr__(self) -> str:
        """
        Return the official string representation of the ConcurrentDict.
        """
        with self._lock:
            return f"{self.__class__.__name__}({self._dict!r})"

    def __str__(self) -> str:
        """
        Return the informal string representation of the ConcurrentDict.
        """
        with self._lock:
            return str(self._dict)

    def __eq__(self, other: object) -> bool:
        """
        Check equality with another ConcurrentDict or a standard dict.

        Args:
            other (object): The dictionary (or dict-like) to compare.

        Returns:
            bool: True if they have the same keys and values, otherwise False.
        """
        if isinstance(other, ConcurrentDict):
            # Lock both to compare safely
            with self._lock, other._lock:
                return self._dict == other._dict
        elif isinstance(other, dict):
            with self._lock:
                return self._dict == other
        return False

    def __ne__(self, other: object) -> bool:
        """
        Check inequality with another dict-like object.

        Args:
            other (object): The dictionary (or dict-like) to compare.

        Returns:
            bool: True if not equal, False otherwise.
        """
        return not self.__eq__(other)

    def clear(self) -> None:
        """
        Remove all items from the dict.
        """
        with self._lock:
            self._dict.clear()

    def get(self, key: _K, default: Optional[_V] = None) -> Optional[_V]:
        """
        Return the value for key if it exists, else default.

        Args:
            key (_K): The key to look up.
            default (_V, optional): The default if key is not found.

        Returns:
            _V or None: Value if present, else default.
        """
        with self._lock:
            return self._dict.get(key, default)

    def pop(self, key: _K, default: Optional[_V] = None) -> _V:
        """
        Remove the specified key and return its value.
        If the key is not found, return default if given, otherwise raise KeyError.

        Args:
            key (_K): The key to pop.
            default (_V, optional): The value to return if key is missing.

        Returns:
            _V: The popped value.

        Raises:
            KeyError: If the key is missing and no default was provided.
        """
        with self._lock:
            if key in self._dict:
                return self._dict.pop(key)
            if default is not None:
                return default
            raise KeyError(key)

    def popitem(self) -> Tuple[_K, _V]:
        """
        Remove and return an arbitrary (key, value) pair.
        Raises KeyError if the dict is empty.

        Returns:
            (key, value) as a tuple.

        Raises:
            KeyError: If the dictionary is empty.
        """
        with self._lock:
            if not self._dict:
                raise KeyError("popitem(): dictionary is empty")
            return self._dict.popitem()

    def setdefault(self, key: _K, default: Optional[_V] = None) -> Optional[_V]:
        """
        If key is in the dict, return its value.
        If not, insert key with a value of default and return default.

        Args:
            key (_K): The key to set if missing.
            default (_V, optional): The value to store if key is missing.

        Returns:
            _V or None: The existing or newly set value.
        """
        with self._lock:
            return self._dict.setdefault(key, default)

    def update(
        self,
        other: Optional[Union[Mapping[_K, _V], Iterable[Tuple[_K, _V]]]] = None,
        **kwargs: _V
    ) -> None:
        """
        Update the dict with the key/value pairs from other, overwriting existing keys.
        Return None.

        update() accepts either another dictionary, an iterable of key/value pairs,
        or keyword arguments.

        Args:
            other (Mapping[_K, _V] or Iterable of (_K, _V), optional):
                Another dict or iterable of (key, value) pairs.
            **kwargs: Additional key-value pairs provided as keyword arguments.
        """
        if other is None:
            other = {}
        with self._lock:
            # Process 'other'
            if hasattr(other, "keys"):
                # Mapping-like
                for k in other.keys():  # type: ignore
                    self._dict[k] = other[k]  # type: ignore
            else:
                # Iterable of (key, value)
                for k, v in other:  # type: ignore
                    self._dict[k] = v

            # Process additional kwargs
            for k, v in kwargs.items():
                self._dict[k] = v

    def keys(self) -> List[_K]:
        """
        Return a list of the dictionary's keys (in a copy).

        Returns:
            List[_K]: A list of the keys.
        """
        with self._lock:
            return list(self._dict.keys())

    def values(self) -> List[_V]:
        """
        Return a list of the dictionary's values (in a copy).

        Returns:
            List[_V]: A list of the values.
        """
        with self._lock:
            return list(self._dict.values())

    def items(self) -> List[Tuple[_K, _V]]:
        """
        Return a list of (key, value) pairs (in a copy).

        Returns:
            List[Tuple[_K, _V]]: A list of all key-value pairs.
        """
        with self._lock:
            return list(self._dict.items())

    def copy(self) -> "ConcurrentDict[_K, _V]":
        """
        Return a shallow copy of the ConcurrentDict.

        Returns:
            ConcurrentDict[_K, _V]: A new ConcurrentDict with copied items.
        """
        with self._lock:
            return ConcurrentDict(initial=self._dict.copy())

    def __copy__(self) -> "ConcurrentDict[_K, _V]":
        """
        For the built-in copy.copy(...).

        Returns:
            ConcurrentDict[_K, _V]: A shallow copy of this ConcurrentDict.
        """
        return self.copy()

    def __deepcopy__(self, memo: dict) -> "ConcurrentDict[_K, _V]":
        """
        Return a deep copy of the ConcurrentDict.

        Args:
            memo (dict): Memoization dictionary for deepcopy.

        Returns:
            ConcurrentDict[_K, _V]: A deep copy of this ConcurrentDict.
        """
        with self._lock:
            return ConcurrentDict(initial=deepcopy(self._dict, memo))

    def __enter__(self) -> Dict[_K, _V]:
        """
        Enter the runtime context and acquire the lock.

        Returns:
            Dict[_K, _V]: The *internal dict* (use with extreme caution,
            as you bypass thread safety).
        """
        warnings.warn(
            "Direct access to the internal dictionary via the context manager bypasses "
            "the thread-safe interface. Use with extreme caution.",
            UserWarning
        )
        self._lock.acquire()
        return self._dict

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """
        Exit the runtime context and release the lock.
        """
        self._lock.release()

    def to_dict(self) -> Dict[_K, _V]:
        """
        Return a shallow copy of the internal dictionary.

        Returns:
            Dict[_K, _V]: A standard Python dict with the same keys and values.
        """
        with self._lock:
            return dict(self._dict)

    def batch_update(self, func: Callable[[Dict[_K, _V]], None]) -> None:
        """
        Perform a batch update on the dict under a single lock acquisition.
        This allows multiple operations to be performed atomically.

        Args:
            func (Callable[[Dict[_K, _V]], None]):
                A function that accepts the internal dict as its only argument.
                The function should perform all necessary mutations.
        """
        with self._lock:
            func(self._dict)

    def map(self, func: Callable[[_K, _V], Tuple[_K, _V]]) -> "ConcurrentDict[_K, _V]":
        """
        Apply a function to each (key, value) pair and return a new ConcurrentDict
        with the transformed results.

        Args:
            func (Callable[[_K, _V], Tuple[_K, _V]]]):
                A function that takes (key, value) and returns a new (key, value) pair.

        Returns:
            ConcurrentDict[_K, _V]: A new dictionary with transformed pairs.
        """
        with self._lock:
            new_items: List[Tuple[_K, _V]] = []
            for k, v in self._dict.items():
                new_items.append(func(k, v))
        return ConcurrentDict(initial=new_items)

    def filter(self, func: Callable[[_K, _V], bool]) -> "ConcurrentDict[_K, _V]":
        """
        Filter items based on a predicate function and return a new ConcurrentDict.

        Args:
            func (Callable[[_K, _V], bool]):
                A function that takes (key, value) and returns True to keep
                the item, or False to discard it.

        Returns:
            ConcurrentDict[_K, _V]:
                A new dictionary containing only items where func(key, value) is True.
        """
        with self._lock:
            new_items: List[Tuple[_K, _V]] = []
            for k, v in self._dict.items():
                if func(k, v):
                    new_items.append((k, v))
        return ConcurrentDict(initial=new_items)

    def reduce(
        self,
        func: Callable[[Any, Tuple[_K, _V]], Any],
        initial: Optional[Any] = None
    ) -> Any:
        """
        Apply a function of two arguments cumulatively to the dict items
        (in some iteration order).

        Args:
            func (Callable[[Any, (key, value)], Any]):
                A function that takes (accumulator, (key, value)).
            initial (Any, optional):
                Starting value of the accumulator.

        Returns:
            Any: The reduced value.

        Raises:
            TypeError: If the dict is empty and no initial value is provided.

        Example:
            # Sum of all values
            def add_values(acc, item):
                k, v = item
                return acc + v

            total = concurrent_dict.reduce(add_values, 0)
        """
        with self._lock:
            items_copy = list(self._dict.items())

        if not items_copy and initial is None:
            raise TypeError("reduce() of empty ConcurrentDict with no initial value")

        def pairwise_reduce(acc: Any, kv: Tuple[_K, _V]) -> Any:
            return func(acc, kv)

        if initial is None:
            return functools.reduce(pairwise_reduce, items_copy)
        else:
            return functools.reduce(pairwise_reduce, items_copy, initial)
