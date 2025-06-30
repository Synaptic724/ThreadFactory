import dataclasses
import threading
import time
from typing import Callable, List, Optional, Tuple
import inspect

import ulid


@dataclasses.dataclass(slots=True)
class ForkUnit:
    """
    Represents a single entry point (or 'gate') in a Fork.

    Each ForkUnit wraps:
    - `fork_callable`: A user-defined function to execute.
    - `usage_cap`: Maximum number of threads allowed to use this unit.
    - `gate`: Marks whether this unit is exhausted (True when max uses are hit).
    - `gate_uses`: Tracks how many times this unit has been used.
    - `lock`: A thread-safe lock protecting the state of this unit.

    These are internal structures managed by the `Fork` system to coordinate
    concurrent access and enforce execution limits per callable.
    """

    fork_callable: Callable
    usage_cap: int
    lock: threading.Lock = dataclasses.field(default_factory=threading.RLock)
    # The 'gate' is now a consumable resource. True means it's consumed.
    gate: bool = False
    gate_uses: int = 0


class Fork:
    """
    A concurrent fork dispatcher for routing threads across multiple callables.

    This class creates a "fork" in thread execution. Each fork represents a
    callable with a usage cap (how many threads may execute it).

    When a thread calls `use_fork()`, the dispatcher:
    - Iterates over all `ForkUnit`s.
    - Locks each unit and checks if it’s still usable.
    - Executes the first available callable directly in the calling thread.
    - Tracks usage count per unit.
    - Once all units are exhausted, marks the fork as closed.

    If `reusable=True` is set, the fork can be reset via `reset()`.

    ------
    Example Use
    -----------
    >>> def worker_a(): print("Worker A executed")
    >>> def worker_b(): print("Worker B executed")
    >>> fork = Fork(2, [(3, worker_a), (2, worker_b)])

    Calling `fork.use_fork()` 5 times will dispatch the workers according to
    their caps (3 and 2 uses). Further calls raise `RuntimeError` unless reusable.

    ------
    Parameters
    ----------
    number_of_forks : int
        Number of callable paths (must match the length of `callables`).

    callables : List[Tuple[int, Callable]]
        A list of tuples, each containing:
            - `usage_cap`: Max number of thread executions for this callable.
            - A synchronous function to execute.

    reusable : bool (default False)
        If True, the fork can be reset and reused after exhaustion.

    ------
    Methods
    -------
    use_fork():
        Attempts to execute one of the available callables.

    reset():
        Resets internal counters and gates for reuse (if allowed).
    """

    # Removed _usage_cap from __slots__ as it is no longer a class-level attribute.
    __slots__ = ["_list_of_forks", "_reusable", "_forks_closed", "_rotate_selectors", "_selector_step", "_selector_step_counter", "_selector_lock", "_id"]

    def __init__(self, number_of_forks: int, callables: List[Tuple[int, Callable]], reusable: bool = False,
                 rotate_selectors: bool = False, selector_step: int = 1):
        if number_of_forks != len(callables):
            raise ValueError("The number of forks must match the number of callables.")

        # --- Validation: Ensure correct input format and callable type ---
        for i, item in enumerate(callables):
            # 1. Check if the item is a tuple and has two elements.
            if not isinstance(item, tuple) or len(item) != 2:
                raise TypeError(
                    f"Expected a tuple of (int, Callable) at index {i}, but received {type(item).__name__} or a tuple of incorrect size.")

            # 2. Check if the first element is an integer (the usage_cap).
            if not isinstance(item[0], int):
                raise TypeError(
                    f"The first element of the tuple at index {i} must be an integer, but received {type(item[0]).__name__}.")

            # 3. Check if the second element is a callable function.
            if not callable(item[1]):
                raise TypeError(
                    f"The second element of the tuple at index {i} must be a callable, but received {type(item[1]).__name__}.")

            # 4. Check if the callable is a coroutine function.
            if inspect.iscoroutinefunction(item[1]):
                raise TypeError(
                    f"Coroutine functions are not supported for ForkUnit at index {i}. Received a coroutine: {item[1].__name__}")

        # Use tuple unpacking to set the individual usage_cap for each ForkUnit.
        self._list_of_forks: List[ForkUnit] = [
            ForkUnit(fork_callable=call, usage_cap=cap) for cap, call in callables
        ]

        self._id = str(ulid.ULID())
        self._reusable = reusable
        self._forks_closed = False
        self._rotate_selectors = rotate_selectors
        self._selector_step = selector_step
        self._selector_step_counter = 0
        self._selector_lock = threading.RLock()

    def reset(self) -> None:
        """
        Resets the state of all ForkUnits, allowing the fork to be reused.

        If `reusable=True`, this method can be called after exhaustion to reset:
        - All gates (marking them as open again).
        - All usage counters.
        - The selector step counter.

        Raises:
            Nothing. Safe to call even if the fork hasn't been used.
        """

        for unit in self._list_of_forks:
            with unit.lock:
                # Reset the gate and its uses.
                unit.gate = False
                unit.gate_uses = 0
        # Reset the selector counter as well.
        self._selector_step_counter = 0
        # This state should be reset once all units have been reset.
        self._forks_closed = False

    def _select_fork_unit(self) -> Optional['ForkUnit']:
        """
        Selects an available ForkUnit using a time-based scan split.

        Uses the low bit of a monotonic clock to alternate between the first and
        second half of the list, improving concurrency and reducing contention.

        Returns:
            ForkUnit if available, otherwise None (if all units are exhausted).
        """

        if self._forks_closed and not self._reusable:
            return None

        flip = time.monotonic_ns() & 1
        mid = len(self._list_of_forks) // 2
        scan_range = range(0, mid) if flip == 0 else range(mid, len(self._list_of_forks))

        for idx in scan_range:
            unit = self._list_of_forks[idx]
            with unit.lock:
                if not unit.gate or unit.gate_uses < unit.usage_cap:
                    return unit

        # If nothing found in primary range, try the backup range
        backup_range = range(mid, len(self._list_of_forks)) if flip == 0 else range(0, mid)
        for idx in backup_range:
            unit = self._list_of_forks[idx]
            with unit.lock:
                if not unit.gate or unit.gate_uses < unit.usage_cap:
                    return unit

        # All forks are exhausted
        self._forks_closed = True
        return None

    def _select_fork_unit_step(self) -> Optional['ForkUnit']:
        """
        Selects an available ForkUnit using a rotating step index.

        Starts at the current `self._selector_step_counter` and steps through
        the list by `self._selector_step`, with wraparound. Distributes fork
        access more evenly under heavy concurrency.

        Returns:
            ForkUnit if available, otherwise None (if all units are exhausted).
        """

        if self._forks_closed and not self._reusable:
            return None

        length = len(self._list_of_forks)

        with self._selector_lock:
            start_index = self._selector_step_counter % length

            for i in range(length):
                idx = (start_index + i * self._selector_step) % length
                unit = self._list_of_forks[idx]
                with unit.lock:
                    if not unit.gate or unit.gate_uses < unit.usage_cap:
                        self._selector_step_counter = idx + 1
                        return unit

        self._forks_closed = True
        return None

    def use_fork(self) -> None:
        """
        Routes the calling thread through an available fork unit.

        - Prevents overuse via in-lock guards.
        - Serializes threads **within each unit** to simulate critical section behavior
          (especially important when using a single fork).
        - Maintains full parallelism **across units** because each has its own lock.

        Raises:
            RuntimeError: If no units are available and the fork is not reusable.
        """

        if self._forks_closed and not self._reusable:
            raise RuntimeError("Forks are closed and not reusable. Cannot use fork.")

        while True:                     # ⟳ Retry until we truly reserve a slot
            unit = (self._select_fork_unit() if self._rotate_selectors
                    else self._select_fork_unit_step())

            if unit is None:
                raise RuntimeError("No available forks to use, all forks are at capacity.")

            # 🛡️ Atomic reservation & execution
            with unit.lock:
                if unit.gate_uses >= unit.usage_cap:
                    # Lost the race—try another unit
                    continue

                unit.gate_uses += 1
                if unit.gate_uses >= unit.usage_cap:
                    unit.gate = True

                # Execute while still holding the unit’s lock to serialize
                # threads *on this unit* (needed for the single-fork test).
                unit.fork_callable()
                return
