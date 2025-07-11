import dataclasses, threading, time, ulid
from typing import Callable, List, Optional, Tuple, Union
from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.utilities.coordination.package import Pack
from thread_factory.utilities.interfaces.disposable import IDisposable

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

    fork_callable: Optional[Union[Callable, Pack]]
    usage_cap: int
    lock: threading.Lock = dataclasses.field(default_factory=threading.RLock)
    # The 'gate' is now a consumable resource. True means it's consumed.
    gate: bool = False
    gate_uses: int = 0

    def dispose(self) -> None:
        """
        Marks this ForkUnit as disposed by sealing the gate and clearing callable.
        """
        self.fork_callable = None


class Fork(IDisposable):
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

    This fork can always be reset via `reset()` to be reused.

    ------
    Example Use
    -----------
    >>> def worker_a(): print("Worker A executed")
    >>> def worker_b(): print("Worker B executed")
    >>> fork = Fork(2, [(3, worker_a), (2, worker_b)])

    Calling `fork.use_fork()` 5 times will dispatch the workers according to
    their caps (3 and 2 uses). Further calls raise `RuntimeError`.
    Call `fork.reset()` to use it again.

    ------
    Parameters
    ----------
    number_of_forks : int
        Number of callable paths (must match the length of `callables`).

    callables : List[Tuple[int, Callable]]
        A list of tuples, each containing:
            - `usage_cap`: Max number of thread executions for this callable.
            - A synchronous function to execute.

    rotate_selectors : bool (default False)
        If True, uses a time-based selection strategy (`_select_fork_unit`).
        If False, uses a step-based selection strategy (`_select_fork_unit_step`).

    selector_step : int (default 1)
        Only applicable if `rotate_selectors` is False. This value determines
        the 'stride' or jump size for the selection process.
        - **Scanning within a call:** When a thread calls `use_fork()`, the selector
          will scan through the available `ForkUnit`s by jumping `selector_step` positions
          at a time from its current starting point, rather than checking sequentially.
        - **Next starting point:** After an available `ForkUnit` is found and used,
          the internal counter for the *next* selection's starting point will
          advance by `selector_step` from the index of the unit that was just claimed.
        A value of 1 (default) results in a simple round-robin or sequential scan.
        Larger values can help distribute usage more broadly across ForkUnits
        under high contention.

    ------
    Methods
    -------
    use_fork():
        Attempts to execute one of the available callables.

    reset():
        Resets internal counters and gates for reuse.
    """

    # Removed _reusable from __slots__
    __slots__ = ["_list_of_forks", "_forks_closed", "_rotate_selectors", "_selector_step", "_selector_step_counter", "_selector_lock", "_id"]

    def __init__(self, number_of_forks: int, callables: List[Tuple[int, Union[Callable[..., None], Pack]]],
                 rotate_selectors: bool = False, selector_step: int = 1):
        super().__init__()
        if number_of_forks != len(callables):
            raise ValueError("The number of forks must match the number of callables.")

        _packed_callables = []
        for i, (cap, fn) in enumerate(callables):
            if not isinstance(cap, int):
                raise TypeError(f"usage_cap at index {i} must be int, got {type(cap).__name__}")

            # FIX: Use Pack.bundle() here to correctly handle existing Pack instances
            # This will create a new Pack for raw callables or return the existing Pack.
            _packed_callables.append((cap, Pack.bundle(fn)))

        # Use tuple unpacking to set the individual usage_cap for each ForkUnit.
        # Use the _packed_callables list directly for initializing _list_of_forks
        self._list_of_forks: ConcurrentList[ForkUnit] = ConcurrentList([ForkUnit(fork_callable=fn, usage_cap=cap)
                                               for cap, fn in _packed_callables])
        # _reusable removed

        self._id = str(ulid.ULID())
        self._forks_closed = False
        self._rotate_selectors = rotate_selectors
        self._selector_step = selector_step
        self._selector_step_counter = 0
        self._selector_lock = threading.RLock()

    def dispose(self) -> None:
        """
        Disposes the Fork instance, releasing all resources and marking
        it as unusable. This method is idempotent and safe to call multiple times.

        After disposal:
        - All future calls to `use_fork()` will raise a RuntimeError.
        - All internal ForkUnits are marked as disposed (callable cleared).
        """
        if self._disposed:
            return

        with self._selector_lock:
            self._disposed = True
            self._forks_closed = True  # Prevent future unit acquisition

            for unit in self._list_of_forks:
                unit.dispose()

            self._list_of_forks.dispose()
            self._list_of_forks = None


    def reset(self) -> None:
        """
        Resets the state of all ForkUnits, allowing the fork to be reused.

        This method can be called after exhaustion to reset:
        - All gates (marking them as open again).
        - All usage counters.
        - The selector step counter.
        - The fork's overall closed status.

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

        # No check for self._forks_closed here, as it's handled by the caller
        # if this method returns None.

        flip = time.monotonic_ns() & 1
        mid = len(self._list_of_forks) // 2
        scan_range_1 = range(0, mid) if flip == 0 else range(mid, len(self._list_of_forks))
        scan_range_2 = range(mid, len(self._list_of_forks)) if flip == 0 else range(0, mid)


        for idx in scan_range_1:
            unit = self._list_of_forks[idx]
            with unit.lock:
                if not unit.gate and unit.gate_uses < unit.usage_cap:
                    return unit

        # If nothing found in primary range, try the backup range
        for idx in scan_range_2:
            unit = self._list_of_forks[idx]
            with unit.lock:
                if not unit.gate and unit.gate_uses < unit.usage_cap:
                    return unit

        # All forks are exhausted after attempting both ranges
        self._forks_closed = True # Mark as closed for future quick rejection
        return None

    def _select_fork_unit_step(self) -> Optional['ForkUnit']:
        # No check for self._forks_closed here, as it's handled by the caller
        # if this method returns None.

        length = len(self._list_of_forks)
        # We need the selector lock to increment the counter, not to check units.
        with self._selector_lock:
            start_index = self._selector_step_counter % length
            # The loop for checking is outside the global lock

        for i in range(length):
            idx = (start_index + i * self._selector_step) % length
            unit = self._list_of_forks[idx]

            # Acquire the unit lock to check its state.
            with unit.lock:
                if not unit.gate and unit.gate_uses < unit.usage_cap:
                    # Acquire the selector lock only when we find a unit to return.
                    with self._selector_lock:
                        # Increment selector_step_counter for the *next* selection
                        self._selector_step_counter = (idx + 1) % length # Ensure it wraps around
                        return unit

        # If the loop finishes, all forks are exhausted.
        self._forks_closed = True # Mark as closed for future quick rejection
        return None

    def use_fork(self) -> None:
        """
        Routes the calling thread through an available fork unit.

        - Prevents overuse via in-lock guards.
        - Serializes threads **within each unit** to simulate critical section behavior
          (especially important when using a single fork).
        - Maintains full parallelism **across units** because each has its own lock.

        Raises:
            RuntimeError: If no units are available.
        """

        # Removed the initial check based on _forks_closed and _reusable.
        # The primary check for exhaustion happens after attempting to select a unit.

        while True:                     # ⟳ Retry until we truly reserve a slot
            unit = (self._select_fork_unit() if self._rotate_selectors
                    else self._select_fork_unit_step())

            if unit is None:
                # This path is taken if _select_fork_unit(step) exhausted all units
                # and marked self._forks_closed = True.
                raise RuntimeError("No available forks to use, all forks are at capacity.")

            # 🛡️ Atomic reservation & execution
            with unit.lock:
                if unit.gate_uses >= unit.usage_cap:
                    # Lost the race—another thread just claimed this unit.
                    # Continue the while loop to try finding another unit.
                    continue

                unit.gate_uses += 1
                if unit.gate_uses >= unit.usage_cap:
                    unit.gate = True # Mark this specific unit as exhausted

                # Execute while still holding the unit’s lock to serialize
                # threads *on this unit* (needed for the single-fork test).
                unit.fork_callable()
                return