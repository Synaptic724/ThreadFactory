import functools
import threading
import warnings
from copy import deepcopy
from typing import Any, Callable, Generic, Iterable, Iterator, Optional, Set, TypeVar
from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.utilities.interfaces.disposable import IDisposable

# Type variable _T is used for generic type hinting. This allows the ConcurrentSet
# to hold elements of any single type, maintaining type safety.
_T = TypeVar("_T")

#region ConcurrentSet
class ConcurrentSet(Generic[_T], IDisposable):
    """Thread‑safe, optionally *freezeable* hash‑set implementation.

    This class provides a concurrent-safe wrapper around Python's built-in `set`.
    It uses a reentrant lock (`threading.RLock`) to protect the underlying set
    during mutations, ensuring that multiple threads can safely interact with
    the set without data corruption.

    Key Design Points:
    -----------------
    • **RLock + freeze flag**: The core of thread safety relies on a `threading.RLock`.
      However, to optimize for read-heavy workloads, a `_freeze` flag is introduced.
      When the set is frozen via the `freeze()` method, read operations (like checking
      membership or iteration) can proceed without acquiring the lock, significantly
      improving performance under high read concurrency. Mutating operations (`add`,
      `remove`, etc.) are blocked when frozen, raising a `TypeError` to indicate
      an incorrect state usage early in the development process.
    • **Rich set algebra**: Standard set operations, both those returning new sets
      (`|`, `&`, `-`, `^`) and those modifying the set in-place (`|=`, `&=`, `-=`, `^=`),
      are implemented or forwarded to internal helpers. These implementations ensure
      that the operations are performed safely under the lock and respect the frozen state.
    • **Disposable / context‑manager**: The class implements the `IDisposable` interface,
      following a pattern where resources (in this case, the internal set's data) can
      be explicitly cleaned up using the `dispose()` method. It also supports the
      context manager protocol (`with ConcurrentSet(...) as cs:`), although using the
      context manager is strongly discouraged for normal operations as it exposes the
      raw internal set, bypassing the thread-safe interface. Its primary intended use
      is for advanced scenarios or explicit resource management patterns.
    """

    __slots__ = IDisposable.__slots__ + ["_lock", "_set", "_freeze"]
# region Construction & state helpers
    def __init__(self, initial: Optional[Iterable[_T]] = None) -> None:
        """Initialize a new ConcurrentSet instance.

        This constructor sets up the necessary components for the concurrent set:
        the reentrant lock, the underlying built-in set, and the freeze flag.

        Args:
            initial: An optional iterable of initial elements to populate the set with
                     upon creation. If `None`, an empty set is created. The elements
                     from the iterable are added to the internal set during initialization
                     before any other operations can occur, so thread safety isn't a
                     concern within the `__init__` method itself.
        """
        # Call the parent class constructor if applicable (e.g., IDisposable)
        super().__init__()

        self._lock = threading.RLock()

        # Attempt to create the internal set from the initial iterable. If `initial`
        try:
            self._set: Set[_T] = set(initial) if initial is not None else set()
        except TypeError as e:
            raise TypeError(f"ConcurrentSet can only store hashable elements. {e}")

        # Initialize the freeze flag. When `True`, the set is considered immutable
        # for external operations (mutating methods will raise TypeError), and
        # read operations can skip locking.
        self._freeze: bool = False

    def dispose(self) -> None:
        """Clear internal data and mark the ConcurrentSet as disposed.

        This method releases the resources held by the set, primarily by clearing
        the underlying built-in set. Once disposed, the set should not be used
        further.

        This method is idempotent; calling it multiple times has no additional effect
        after the first call. It is also thread-safe, using the internal lock
        to protect the clearing operation and the `disposed` flag update.
        """
        # Check if the set has already been disposed. The `getattr` with a default
        # handles the case where the `disposed` attribute might not exist yet
        # during initialization or in error scenarios, although it's set in __init__.
        if not getattr(self, "_disposed", False):
            # Acquire the lock before clearing the internal set and updating the flag.
            with self._lock:
                # Clear the underlying built-in set, releasing references to its elements.
                self._set.clear()
                # Mark the set as disposed. This flag is checked in the outer `if`.
                self._disposed = True
            # Issue a warning to inform the user that the set has been disposed.
            # This is a helpful indicator if the set is accidentally used after disposal.
            warnings.warn("Your ConcurrentSet has been disposed and should not be used further.", UserWarning)
# endregion
# region Freeze control
    def freeze(self) -> None:
        """**Freeze** the set.

        Once frozen, attempts to call mutating methods (`add`, `remove`, `update`,
        in-place algebra operators like `|=`, etc.) will result in a `TypeError`.
        This state indicates that the set is intended for read-only access.

        The primary benefit of freezing is enabling lock-free reads. When the set
        is frozen, methods like `__contains__`, `__len__`, and `__iter__` directly
        access the internal `_set` without acquiring the lock, as its contents are
        guaranteed not to change while frozen.

        This method is thread-safe as it acquires the internal lock to update
        the `_freeze` flag atomically.
        """
        # Acquire the lock before modifying the shared `_freeze` flag. This ensures
        # that no other thread is simultaneously freezing, unfreezing, or performing
        # a locked mutation when the flag is being changed.
        with self._lock:
            self._freeze = True

    def unfreeze(self) -> None:
        """Unfreeze the set, re-enabling mutations.

        After calling `unfreeze()`, mutating methods can be called again. Read
        operations will revert to acquiring the lock (or creating a locked copy)
        to ensure thread safety, as the underlying set's contents may now change
        due to concurrent mutations.

        This method is thread-safe as it acquires the internal lock to update
        the `_freeze` flag atomically.
        """
        # Acquire the lock before modifying the shared `_freeze` flag.
        with self._lock:
            self._freeze = False

    @property
    def is_frozen(self) -> bool:  # noqa: D401 – property docstring is short
        """Return ``True`` if the set is currently frozen (read-only mode).

        This property provides a way to check the current state of the freeze flag.
        It does **not** acquire the internal lock because reading a boolean flag
        like `_freeze` is an atomic operation in Python, and its value represents
        a state that is only changed while the lock is held in `freeze()` and
        `unfreeze()`. Thus, checking the flag itself is safe without a lock.
        """
        return self._freeze
# endregion
# region Core CRUD operations
    def _ensure_mutable(self) -> None:
        """Internal helper to check if the set is frozen and raise TypeError if it is.

        This method is called by all mutating methods before attempting any
        modification of the underlying `_set`. It enforces the contract that
        a frozen set is read-only.
        """
        if self._freeze:
            # If the set is frozen, raise a TypeError to signal that mutation
            # is not allowed in this state.
            raise TypeError("Cannot modify a frozen ConcurrentSet")

    def add(self, item: _T) -> None:
        """Add *item* to the set.

        If the item is already present, this method has no effect. This is
        consistent with the behavior of Python's built-in `set.add()`.

        This operation is thread-safe as it first checks the freeze state and
        then acquires the internal lock before performing the addition.
        """
        # First, check if the set is frozen. If it is, _ensure_mutable will raise TypeError.
        self._ensure_mutable()
        # Acquire the lock before modifying the shared internal set. This prevents
        # race conditions with other threads attempting to add, remove, or clear items.
        with self._lock:
            # Perform the add operation on the underlying built-in set.
            self._set.add(item)

    def remove(self, item: _T) -> None:
        """Remove *item* from the set.

        Raises ``KeyError`` if the item is not present in the set. This behavior
        matches Python's built-in `set.remove()`.

        This operation is thread-safe as it first checks the freeze state and
        then acquires the internal lock before performing the removal.
        """
        # First, check if the set is frozen.
        self._ensure_mutable()
        # Acquire the lock before modifying the shared internal set.
        with self._lock:
            # Perform the remove operation on the underlying built-in set.
            self._set.remove(item)

    def discard(self, item: _T) -> None:
        """Remove *item* from the set if it is present.

        If the item is not present, this method does nothing and does not raise
        an error (unlike `remove()`). This behavior matches Python's built-in
        `set.discard()`.

        This operation is thread-safe as it first checks the freeze state and
        then acquires the internal lock before attempting the discard.
        """
        # First, check if the set is frozen.
        self._ensure_mutable()
        # Acquire the lock before modifying the shared internal set.
        with self._lock:
            # Perform the discard operation on the underlying built-in set.
            self._set.discard(item)

    def clear(self) -> None:
        """Remove **all** elements from the set.

        After calling this method, the set will be empty.

        This operation is thread-safe as it first checks the freeze state and
        then acquires the internal lock before clearing the set.
        """
        # First, check if the set is frozen.
        self._ensure_mutable()
        # Acquire the lock before modifying the shared internal set.
        with self._lock:
            # Perform the clear operation on the underlying built-in set.
            self._set.clear()
#endregion
#region Bulk operations & transformations

    def update(self, other: Iterable[_T]) -> None:
        """In‑place union with *other*.

        Adds all elements from the `other` iterable to this set. This is
        equivalent to the `|=` operator for sets.

        This operation is thread-safe as it first checks the freeze state and
        then acquires the internal lock before performing the update.
        """
        # First, check if the set is frozen.
        self._ensure_mutable()
        # Acquire the lock before modifying the shared internal set.
        with self._lock:
            # Perform the update operation on the underlying built-in set.
            self._set.update(other)

#region algebra helpers
    def _binary_new(self, op: Callable[[Set[_T], Set[_T]], Set[_T]], other: Iterable[_T]) -> "ConcurrentSet[_T]":
        """Internal helper for binary set operations that return a new ConcurrentSet.

        This helper is used by methods implementing operators like `|` (union),
        `&` (intersection), `-` (difference), and `^` (symmetric difference).
        It ensures that the operation is performed on a consistent snapshot of the
        internal set, respecting the freeze state.

        Args:
            op: The binary set operation function to apply (e.g., `Set.union`,
                `Set.intersection`). It should take two sets as input and return
                a new set.
            other: The iterable representing the second operand of the binary operation.

        Returns:
            A new `ConcurrentSet` containing the result of the operation.
        """
        # Get a consistent view of the internal set. If frozen, we can access `_set`
        # directly as it won't change. If not frozen, we must acquire the lock
        # and create a copy to ensure we operate on a fixed snapshot of the data,
        # avoiding race conditions with concurrent modifications.
        base_copy = self._set if self._freeze else self._copy_locked()
        # Convert the 'other' iterable into a set. This is necessary because
        # the binary set operations in Python typically operate on sets.
        other_set = set(other)
        # Perform the binary operation on the base copy and the 'other' set.
        result_set = op(base_copy, other_set)
        # Create and return a new ConcurrentSet initialized with the result.
        return ConcurrentSet(result_set)

    def _binary_inplace(self, op: Callable[[Set[_T], Set[_T]], None], other: Iterable[_T]) -> "ConcurrentSet[_T]":
        """Internal helper for in-place binary set operations that modify the set.

        This helper is used by methods implementing operators like `|=` (in-place union),
        `&=` (in-place intersection), `-=` (in-place difference), and `^=` (in-place
        symmetric difference). It ensures that the modification is performed safely
        under the lock.

        Args:
            op: The in-place binary set operation function to apply (e.g.,
                `Set.update`, `Set.intersection_update`). It should take the target
                set and another set as input and modify the target set in place.
            other: The iterable representing the second operand of the binary operation.

        Returns:
            The `self` instance, allowing for fluent chaining of operations.
        """
        # First, ensure the set is not frozen, as in-place operations are mutations.
        self._ensure_mutable()
        # Acquire the lock before modifying the shared internal set. This ensures
        # atomicity of the in-place operation with respect to other threads.
        with self._lock:
            # Convert the 'other' iterable into a set.
            other_set = set(other)
            # Perform the in-place binary operation on the underlying built-in set.
            op(self._set, other_set)
        # Return self to support the typical behavior of in-place operators in Python.
        return self
# endregion
# region standard operators
    def union(self, *others: Iterable[_T]) -> "ConcurrentSet[_T]":
        """Return the union (``|``) of all provided iterables and *self*.

        This method calculates the union of the current set with one or more
        other iterables. It does not modify the original set.

        Args:
            *others: One or more iterables containing elements to include in the union.

        Returns:
            A new `ConcurrentSet` containing all unique elements from this set
            and all the `others` iterables.
        """
        # Get a consistent view of the internal set.
        result = set(self._set) if self._freeze else self._copy_locked()
        # Iterate through all provided 'others' iterables and update the result set
        # with their elements. The standard set.update() is thread-safe on the
        # temporary `result` set because it's a local copy, not shared.
        for o in others:
            result.update(o)
        # Return a new ConcurrentSet initialized with the final result set.
        return ConcurrentSet(result)

    def intersection(self, *others: Iterable[_T]) -> "ConcurrentSet[_T]":
        """Return the intersection (``&``) of all provided iterables and *self*.

        This method calculates the intersection of the current set with one or more
        other iterables. It does not modify the original set.

        Args:
            *others: One or more iterables containing elements to intersect with.

        Returns:
            A new `ConcurrentSet` containing elements that are present in this set
            AND in all of the `others` iterables.
        """
        # Get a consistent view of the internal set.
        result = set(self._set) if self._freeze else self._copy_locked()
        # Iterate through all provided 'others' iterables and perform in-place
        # intersection on the result set. The standard set.intersection_update()
        # is thread-safe on the temporary `result` set because it's a local copy.
        for o in others:
            result.intersection_update(o)
        # Return a new ConcurrentSet initialized with the final result set.
        return ConcurrentSet(result)

    def difference(self, *others: Iterable[_T]) -> "ConcurrentSet[_T]":
        """Return the difference (``-``) between *self* and all provided iterables.

        This method calculates the difference between the current set and one or more
        other iterables. It contains elements in this set that are NOT in any of
        the other iterables. It does not modify the original set.

        Args:
            *others: One or more iterables containing elements to remove from this set.

        Returns:
            A new `ConcurrentSet` containing elements that are present in this set
            but NOT in any of the `others` iterables.
        """
        # Get a consistent view of the internal set.
        result = set(self._set) if self._freeze else self._copy_locked()
        # Iterate through all provided 'others' iterables and perform in-place
        # difference on the result set. The standard set.difference_update()
        # is thread-safe on the temporary `result` set because it's a local copy.
        for o in others:
            result.difference_update(o)
        # Return a new ConcurrentSet initialized with the final result set.
        return ConcurrentSet(result)

    def symmetric_difference(self, other: Iterable[_T]) -> "ConcurrentSet[_T]":
        """Return the symmetric difference (``^``) with *other*.

        This method calculates the symmetric difference between the current set and
        exactly one other iterable. It contains elements that are in either set,
        but not in both. It does not modify the original set.

        Args:
            other: The iterable containing elements for the symmetric difference.

        Returns:
            A new `ConcurrentSet` containing elements that are in either this set
            OR the `other` iterable, but not in both.
        """
        # Leverage the internal helper `_binary_new` which handles the copying
        # and locking logic for operations that return a new set.
        return self._binary_new(lambda a, b: a.symmetric_difference(b), other)
#endregion
#region dunder algebra (new objects)
    def __eq__(self, other: Any) -> bool:
        """
        Check for equality with another object.

        This method implements the `==` operator for the ConcurrentSet.

        It compares the contents of the current set with either:
          - another ConcurrentSet instance (compared via their `.to_set()` snapshots), or
          - a standard Python `set`.

        The comparison is based purely on the set contents — thread-safety,
        frozen state, and other metadata are ignored.

        Args:
            other: The object to compare with.

        Returns:
            bool: True if the sets contain the same elements, False otherwise.
                  If the comparison is not supported, returns NotImplemented
                  so Python can delegate to the other object's `__eq__`.

        Example:
            >>> cs1 = ConcurrentSet([1, 2, 3])
            >>> cs2 = ConcurrentSet([3, 2, 1])
            >>> cs1 == cs2
            True
        """
        if isinstance(other, ConcurrentSet):
            # Compare the underlying sets of both ConcurrentSets using a consistent snapshot
            return self.to_set() == other.to_set()
        elif isinstance(other, set):
            # Compare against a raw set
            return self.to_set() == other
        # Allow Python to fall back to the right-side __eq__ if supported
        return NotImplemented

    def __ne__(self, other: Any) -> bool:
        """
        Check for inequality with another object.

        Implements the `!=` operator. Internally delegates to `__eq__` and negates the result,
        following standard Python convention for equality/inequality.

        Args:
            other: The object to compare with.

        Returns:
            bool: True if the sets are *not* equal, False otherwise.
        """
        result = self.__eq__(other)
        if result is NotImplemented:
            return NotImplemented
        return not result

    def __or__(self, other: Iterable[_T]) -> "ConcurrentSet[_T]":
        """
        Implement the `|` (bitwise OR) operator — set **union**.

        Enables usage like: `cs1 | other`

        Combines the current set with another iterable, returning a new ConcurrentSet
        that includes all unique elements from both.

        Args:
            other: An iterable of elements to union with.

        Returns:
            A new ConcurrentSet containing the union of `self` and `other`.
        """
        return self.union(other)

    def __and__(self, other: Iterable[_T]) -> "ConcurrentSet[_T]":
        """
        Implement the `&` (bitwise AND) operator — set **intersection**.

        Enables usage like: `cs1 & other`

        Returns a new ConcurrentSet containing only the elements common to both sets.

        Args:
            other: An iterable to intersect with.

        Returns:
            A new ConcurrentSet containing the intersection of `self` and `other`.
        """
        return self.intersection(other)

    def __sub__(self, other: Iterable[_T]) -> "ConcurrentSet[_T]":
        """
        Implement the `-` (subtraction) operator — set **difference**.

        Enables usage like: `cs1 - other`

        Returns a new ConcurrentSet containing the elements in `self` that are not in `other`.

        Args:
            other: An iterable of elements to exclude.

        Returns:
            A new ConcurrentSet containing the difference of `self` and `other`.
        """
        return self.difference(other)

    def __xor__(self, other: Iterable[_T]) -> "ConcurrentSet[_T]":
        """
        Implement the `^` (bitwise XOR) operator — set **symmetric difference**.

        Enables usage like: `cs1 ^ other`

        Returns a new ConcurrentSet with elements in either `self` or `other`, but not both.

        Args:
            other: An iterable to compare against.

        Returns:
            A new ConcurrentSet containing the symmetric difference.
        """
        return self.symmetric_difference(other)
#endregion
#region in‑place dunder algebra
    def __ior__(self, other: Iterable[_T]) -> "ConcurrentSet[_T]":
        """
        Implement the `|=` in-place union operator.

        Enables usage like: `cs1 |= other`

        Adds all elements from `other` into the current set. Operates atomically.

        Args:
            other: An iterable of elements to union into the current set.

        Returns:
            self: The modified ConcurrentSet.
        """
        return self._binary_inplace(Set.update, other)

    def __iand__(self, other: Iterable[_T]) -> "ConcurrentSet[_T]":
        """
        Implement the `&=` in-place intersection operator.

        Enables usage like: `cs1 &= other`

        Retains only elements present in both `self` and `other`. Operates atomically.

        Args:
            other: An iterable to intersect with the current set.

        Returns:
            self: The modified ConcurrentSet.
        """
        return self._binary_inplace(Set.intersection_update, other)

    def __isub__(self, other: Iterable[_T]) -> "ConcurrentSet[_T]":
        """
        Implement the `-=` in-place difference operator.

        Enables usage like: `cs1 -= other`

        Removes all elements in `other` from the current set. Operates atomically.

        Args:
            other: An iterable of elements to remove.

        Returns:
            self: The modified ConcurrentSet.
        """
        return self._binary_inplace(Set.difference_update, other)

    def __ixor__(self, other: Iterable[_T]) -> "ConcurrentSet[_T]":
        """
        Implement the `^=` in-place symmetric difference operator.

        Enables usage like: `cs1 ^= other`

        Keeps only elements that are in either `self` or `other`, but not both. Operates atomically.

        Args:
            other: An iterable to compare with.

        Returns:
            self: The modified ConcurrentSet.
        """
        return self._binary_inplace(Set.symmetric_difference_update, other)
#endregion
#endregion
# region Higher‑order helpers (map / filter / reduce)

    def map(self, func: Callable[[_T], Any]) -> "ConcurrentSet[Any]":
        """Apply a function to each element in the set and return a new ConcurrentSet.

        This method iterates over a snapshot of the set, applies the provided function
        `func` to each element, and collects the results into a new set. The original
        set is not modified.

        Args:
            func: A callable that takes one argument (an element from the set)
                  and returns a value.

        Returns:
            A new `ConcurrentSet` containing the results of applying `func` to each
            element of the original set. The order of elements in the resulting
            set is arbitrary.
        """
        # Get a consistent view of the internal set. This uses a copy if not frozen
        # to ensure that mapping occurs over a fixed set of elements, even if
        # concurrent modifications happen during the mapping process.
        base = self._set if self._freeze else self._copy_locked()
        # Use the built-in `map` function to apply the callable to each element
        # of the snapshot. `map` returns an iterator.
        mapped_iter = map(func, base)
        # Create and return a new ConcurrentSet initialized with the results from
        # the mapped iterator.
        return ConcurrentSet(mapped_iter)

    def filter(self, func: Callable[[_T], bool]) -> "ConcurrentSet[_T]":
        """Filter elements based on a predicate function and return a new ConcurrentSet.

        This method iterates over a snapshot of the set, applies the provided predicate
        function `func` to each element, and includes only those elements for which
        `func` returns `True` in a new set. The original set is not modified.

        Args:
            func: A callable that takes one argument (an element from the set)
                  and returns a boolean (`True` to keep the element, `False` to discard).

        Returns:
            A new `ConcurrentSet` containing only the elements from the original set
            for which `func` returned `True`. The order of elements in the resulting
            set is arbitrary.
        """
        # Get a consistent view of the internal set (copy if not frozen) to ensure
        # filtering occurs over a fixed set of elements.
        base = self._set if self._freeze else self._copy_locked()
        # Use the built-in `filter` function to select elements based on the callable.
        # `filter` returns an iterator.
        filtered_iter = filter(func, base)
        # Create and return a new ConcurrentSet initialized with the results from
        # the filtered iterator.
        return ConcurrentSet(filtered_iter)

    def reduce(self, func: Callable[[Any, _T], Any], initial: Optional[Any] = None) -> Any:
        """Apply a function cumulatively to the elements of the set.

        This method applies the `func` callable of two arguments (accumulator, element)
        sequentially to the elements of the set, from left to right, so as to reduce
        the set to a single value. The first argument to `func` is the accumulated value,
        and the second is the current element from the set.

        Args:
            func: A callable that takes two arguments (accumulator, current_element)
                  and returns a new accumulated value.
            initial: An optional initial value for the accumulator. If `initial` is
                     not provided, the first element of the set is used as the initial
                     value, and the reduction starts from the second element.

        Returns:
            The single accumulated value resulting from the reduction.

        Raises:
            TypeError: If the set is empty and no `initial` value is provided.
        """
        # Get a consistent view of the internal set (copy if not frozen) to ensure
        # reduction occurs over a fixed set of elements.
        base = self._set if self._freeze else self._copy_locked()
        # Check for the case of reducing an empty set without an initial value,
        # which is not allowed by functools.reduce.
        if not base and initial is None:
            raise TypeError("reduce() of empty ConcurrentSet with no initial value")

        # Perform the reduction using functools.reduce.
        if initial is not None:
            # If an initial value is provided, use it as the starting point.
            return functools.reduce(func, base, initial)
        else:
            # If no initial value is provided, start with the first element.
            # Note: The order of elements in a set is arbitrary, so the result
            # of reduce without an initial value may vary between runs or threads.
            return functools.reduce(func, base)

    # ---------------------- batch update ------------------------------
    # This method doesn't return self, although a fluent return style could be added.
    def batch_update(self, func: Callable[[Set[_T]], None]):
        """Atomically perform *many* mutations in one lock acquisition.

        This method provides a way to execute a series of modifications to the
        underlying set while holding the lock for the entire duration of the
        modification process. This is more efficient than acquiring and releasing
        the lock for each individual operation within the batch, especially for
        bulk changes.

        The provided callable `func` takes the **raw internal set** (`self._set`)
        as its only argument. You can then perform multiple operations directly
        on this set within the `func`.

        **IMPORTANT**: Because `func` receives the raw internal set, you are
        responsible for ensuring that the operations performed inside `func`
        maintain set invariants and are safe in the context of being executed
        while the lock is held. Avoid lengthy or blocking operations inside `func`.

        Args:
            func: A callable that takes one argument, which is the raw internal
                  built-in `set`, and performs mutations on it. The function
                  should not return a value (or return `None`).
        """
        # Ensure the set is not frozen before attempting a batch mutation.
        self._ensure_mutable()
        # Acquire the lock *once* for the entire duration of the batch update.
        # This ensures that no other thread can access or modify the set
        # while the operations inside `func` are being performed.
        with self._lock:
            # Execute the user-provided function, passing the raw internal set.
            func(self._set)
        # The lock is automatically released upon exiting the `with` block.
#endregion
# region Conversions

    def to_set(self) -> Set[_T]:
        """Return a **shallow copy** of the underlying ``set``.

        This method provides a way to get a snapshot of the set's current contents
        as a standard Python `set`. The returned set is a separate object and is
        always safe to mutate without affecting the original `ConcurrentSet`.

        The copy operation is performed safely by acquiring the lock if the set
        is not frozen, ensuring a consistent snapshot. If the set is frozen,
        accessing `_set` directly is safe.

        Returns:
            A shallow copy of the internal built-in `set`.
        """
        # Return a copy of the internal set. If frozen, access directly. If not,
        # use the internal helper `_copy_locked` to get a copy while holding the lock.
        return set(self._set) if self._freeze else self._copy_locked()

    def to_concurrent_list(self) -> "ConcurrentList[_T]":
        """Convert the ConcurrentSet to a :class:`ConcurrentList`.

        This method creates a new `ConcurrentList` containing the elements of this set.
        Note that sets are inherently unordered, so the order of elements in the
        resulting `ConcurrentList` is arbitrary and not guaranteed to be the same
        across different calls or executions, just like converting a built-in set
        to a list using `list(my_set)`.

        Requires the `ConcurrentList` class to be available (successfully imported).

        Returns:
            A new `ConcurrentList` instance containing the elements of this set.

        Raises:
            ImportError: If the `ConcurrentList` class could not be imported
                         when this module was loaded.
        """
        # Get a shallow copy of the internal set.
        set_copy = self.to_set()
        # Convert the set copy to a list and initialize a new ConcurrentList with it.
        # The list conversion handles the arbitrary ordering.
        return ConcurrentList(initial=list(set_copy))
#endregion
# region Introspection / dunder helpers

    def __contains__(self, item: Any) -> bool:
        """Implement the `in` operator to check for membership.

        This dunder method allows checking if an `item` is present in the set
        using the syntax `item in my_concurrent_set`.

        The check is performed efficiently: if the set is frozen, it accesses the
        internal set directly without locking. If not frozen, it creates a locked
        copy and checks membership in the copy to ensure a consistent result.
        """
        # Check for membership. If frozen, access _set directly. Otherwise,
        # acquire the lock and check membership in a temporary copy.
        return item in self._set if self._freeze else item in self._copy_locked()

    def __len__(self) -> int:
        """Return the number of elements in the set (implement `len()`).

        This dunder method allows getting the size of the set using the `len()`
        built-in function.

        The length is retrieved efficiently: if the set is frozen, it accesses the
        internal set's length directly. If not frozen, it creates a locked copy
        and returns the length of the copy to ensure a consistent result.
        """
        # Get the length. If frozen, access len(_set) directly. Otherwise,
        # acquire the lock and get the length of a temporary copy.
        return len(self._set) if self._freeze else len(self._copy_locked())

    def __iter__(self) -> Iterator[_T]:
        """Return an iterator over the elements (implement `iter()`).

        This dunder method allows iterating over the elements of the set, for example,
        in a `for` loop.

        To ensure thread safety, if the set is not frozen, this method returns an
        iterator over a *copy* of the internal set. This means that modifications
        made to the `ConcurrentSet` by other threads *while* iteration is in progress
        will *not* affect the iterator (it iterates over the state of the set at the
        moment `__iter__` was called). If the set is frozen, it iterates directly
        over the internal set because it's guaranteed not to change.
        """
        # Return an iterator. If frozen, iterate over _set directly. Otherwise,
        # acquire the lock and iterate over a temporary copy. Iterating over
        # a copy prevents issues if the underlying set is modified concurrently
        # by other threads while this thread is iterating.
        return iter(self._set) if self._freeze else iter(self._copy_locked())

    def __bool__(self) -> bool:  # truthiness shortcut
        """Implement truthiness testing (e.g., `if my_concurrent_set:`).

        An empty set evaluates to `False` in a boolean context, and a non-empty
        set evaluates to `True`. This dunder method provides that behavior by
        checking if the length of the set is non-zero. It leverages the `__len__`
        method, which handles the necessary locking/copying based on the freeze state.
        """
        return bool(len(self))

    def __repr__(self) -> str:
        """Return a string representation suitable for debugging (implement `repr()`).

        This dunder method is typically called by the `repr()` built-in function
        and by the interactive interpreter. It aims to return a string that, if
        evaluated, would recreate an object with the same value (though not necessarily
        the same identity or thread-safety properties).

        It includes the class name and the representation of the underlying set.
        Since the `repr()` of a built-in set is thread-safe (it creates a snapshot),
        accessing `_set!r` is safe here without an explicit lock because the `!r`
        conversion itself happens quickly on the current state.
        """
        # Use an f-string to format the output, including the class name
        # and the representation of the internal set.
        return f"{self.__class__.__name__}({self._set!r})"

    def __copy__(self) -> "ConcurrentSet[_T]":  # shallow copy protocol
        """Implement the shallow copy operation (for `copy.copy()`).

        This method is called when `copy.copy()` is used on a `ConcurrentSet` instance.
        A shallow copy creates a new `ConcurrentSet` object, but the elements within
        that new set are references to the same elements in the original set.

        Returns:
            A new `ConcurrentSet` instance that is a shallow copy of the original.
        """
        # Create a new ConcurrentSet initialized with a shallow copy of the internal set.
        # `self.to_set()` already handles getting a safe copy (locked if necessary).
        return ConcurrentSet(self.to_set())

    def __deepcopy__(self, memo: dict) -> "ConcurrentSet[_T]":
        """Implement the deep copy operation (for `copy.deepcopy()`).

        This method is called when `copy.deepcopy()` is used on a `ConcurrentSet` instance.
        A deep copy creates a new `ConcurrentSet` object, and recursively creates copies
        of the elements within the set. This is necessary if the elements themselves
        are mutable and you want the copy to be independent of the original elements.

        Args:
            memo: A dictionary used internally by `deepcopy` to keep track of
                  objects that have already been copied during the current operation
                  to avoid infinite recursion and handle shared references.

        Returns:
            A new `ConcurrentSet` instance that is a deep copy of the original.
        """
        # Create a new ConcurrentSet initialized with a deep copy of the internal set.
        # `self.to_set()` gets a shallow copy of the internal set structure.
        # `deepcopy` then handles the deep copying of the elements within that set copy.
        return ConcurrentSet(deepcopy(self.to_set(), memo))
#endregion
#region Private helpers & resource lifecycle

    def _copy_locked(self) -> Set[_T]:
        """Internal helper to return a shallow copy of the internal set while holding the lock.

        This method is used by read operations (`__contains__`, `__len__`, `__iter__`,
        `to_set`, etc.) when the set is *not* frozen. It ensures that the copy is made
        atomically under the protection of the lock, guaranteeing that the copy
        represents a consistent state of the set at that moment, even if other threads
        are trying to modify the set concurrently.
        """
        # Acquire the internal lock.
        with self._lock:
            # Return a shallow copy of the underlying built-in set.
            return self._set.copy()
#endregion
#region With Statement

    def __enter__(self):  # noqa: D401 – simple docstring
        """Context manager entry. Acquires the internal lock.

        **WARNING**: Using the context manager this way provides direct access
        to the internal `ConcurrentSet` object *while the lock is held*. Any
        operations performed directly on the object *outside* the public
        thread-safe methods must be carefully considered to avoid violating
        thread safety or object invariants. This is primarily intended for
        advanced scenarios or specific resource management patterns, not
        general set operations.
        """
        # Issue a warning to strongly discourage typical use of the context manager.
        warnings.warn(
            "Direct access to the internals via the context manager bypasses "
            "the thread‑safe interface. Use with extreme caution.",
            UserWarning,
        )
        # Acquire the internal reentrant lock. This lock will be held until __exit__ is called.
        self._lock.acquire()
        # Return the ConcurrentSet instance itself, allowing operations within the 'with' block.
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit. Releases the internal lock and disposes the set.

        This method is called when exiting the `with` block, either normally or
        due to an exception. It is crucial for releasing the acquired resource
        (the lock).

        It also calls `dispose()` to clean up the set's contents, reinforcing
        the idea that using the context manager might be tied to a resource's
        lifecycle management.
        """
        # Release the internal lock, allowing other threads to acquire it.
        self._lock.release()
        # Call the dispose method to clean up the set's internal state.
        # Note that dispose() itself is idempotent and thread-safe.
        self.dispose()

#endregion
#endregion