from __future__ import annotations
import threading
import copy
from contextlib import contextmanager
from typing import Any, Callable, Generic, Iterator, Optional, TypeVar
from thread_factory.utilities.interfaces.isync import ISync

T = TypeVar("T")
R = TypeVar("R")


class SyncRef(ISync, Generic[T]):
    """
    SyncRef(obj)
    ============

    A thread-safe mutable reference to any Python object.

    This class allows atomic read/write access, in-place mutation,
    and transactional control over the wrapped value. It supports
    compare-and-set, lambda-based transformation, and deep copying
    for safe inter-thread communication.

    Common use cases include:

    - Shared mutable state across threads
    - Agent memory cells
    - Snapshot-style history
    - Dynamic live references (`SyncRef[List[Task]]`, etc.)

    Examples:
    ---------
    >>> ref = SyncRef({"key": 42})
    >>> ref.update(lambda d: d.update({"key": 99}))
    >>> with ref.locked() as obj:
    ...     obj["other"] = 100
    >>> snapshot = ref.get()
    >>> ref.cas(snapshot, {"key": 0})
    """

    __slots__ = ("_value", "_lock")

    def __init__(self, obj: T):
        """
        Initialize a thread-safe reference to any object.

        Parameters:
            obj (T): The object to wrap.
        """
        self._value = obj
        self._lock = threading.RLock()

    @classmethod
    def _coerce(cls, val):
        """Internal ISync helper – no coercion is needed for SyncRef."""
        return val

    def _unwrap_other(self, other):
        """Unwrap a Sync wrapper to access its raw value."""
        return other.get() if ISync._is_sync(other) else other

    def get(self) -> T:
        """
        Return a snapshot of the current value.

        Returns:
            T: A thread-safe read of the internal value.
        """
        with self._lock:
            return self._value

    snapshot = property(get)
    """Alias for `get()` – read-only snapshot of the internal value."""

    def set(self, obj: T) -> None:
        """
        Replace the internal value with a new object.

        Parameters:
            obj (T): The new value to store.
        """
        with self._lock:
            self._value = obj

    def update(self, mutator: Callable[[T], Any]) -> T:
        """
        Atomically mutate the internal value in place.

        The provided function receives the current value and can mutate it.
        Avoid reentrant calls to the same SyncRef within this function.

        Parameters:
            mutator (Callable[[T], Any]): A function that modifies the internal value.

        Returns:
            T: The mutated value (same reference).
        """
        with self._lock:
            mutator(self._value)
            return self._value

    def modify(self, fn: Callable[[T], R]) -> R:
        """
        Apply a functional update: store and return the result.

        Equivalent to: new_val = fn(old_val); set(new_val)

        Parameters:
            fn (Callable[[T], R]): A transformer function.

        Returns:
            R: The new value.
        """
        with self._lock:
            new_val = fn(self._value)
            self._value = new_val
            return new_val

    def cas(self, expected: T, new: T) -> bool:
        """
        Compare-and-set: if current value is `expected` (by identity),
        replace it with `new`.

        Parameters:
            expected (T): Expected object reference (not equality).
            new (T): Replacement if matched.

        Returns:
            bool: True if replacement occurred.
        """
        with self._lock:
            if self._value is expected:
                self._value = new
                return True
            return False

    def swap(self, new: T) -> T:
        """
        Replace the value and return the old one.

        Parameters:
            new (T): New value to store.

        Returns:
            T: Previous stored value.
        """
        with self._lock:
            old = self._value
            self._value = new
            return old

    def transform(self, fn: Callable[[T], R]) -> R:
        """
        Read-only application of a function to the stored value.

        Parameters:
            fn (Callable[[T], R]): A transformation function.

        Returns:
            R: The result of applying the function.
        """
        with self._lock:
            return fn(self._value)

    map = transform
    """Alias for `transform()` – supports functional pipelines."""

    @contextmanager
    def locked(self) -> Iterator[T]:
        """
        Context manager that locks the object and yields the live reference.

        Example:
            >>> with ref.locked() as obj:
            ...     obj["key"] = 1

        Yields:
            T: The internal object (locked during use).
        """
        with self._lock:
            yield self._value

    def __enter__(self) -> T:
        """
        Enter a manual locking context using `with ref as obj:`.

        Returns:
            T: The internal value (locked).
        """
        self._lock.acquire()
        return self._value

    def __exit__(self, exc_type, exc, tb) -> bool:
        """
        Exit the lock context. Propagates exceptions.

        Returns:
            bool: False – do not suppress exceptions.
        """
        self._lock.release()
        return False

    def __repr__(self) -> str:
        """String representation of the SyncRef."""
        return f"SyncRef({self.get()!r})"

    def __eq__(self, other: Any) -> bool:
        """Equality comparison based on stored value."""
        if ISync._is_sync(other):
            return self.get() == other.get()
        return self.get() == other

    def __hash__(self) -> int:
        """
        Hash the contained object if possible.
        Fallbacks to `id()` if not hashable.
        """
        try:
            return hash(self.get())
        except TypeError:
            return id(self)

    def __getstate__(self) -> dict:
        """
        Return the pickled state.

        Returns:
            dict: A deep copy of the internal value.
        """
        return {"_value": copy.deepcopy(self.get())}

    def __setstate__(self, state: dict):
        """
        Restore from a pickled state. A fresh lock is always created.

        Parameters:
            state (dict): Pickled state with key '_value'.
        """
        self._value = state["_value"]
        self._lock = threading.RLock()
