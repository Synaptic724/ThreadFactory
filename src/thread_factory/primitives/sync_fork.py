import dataclasses
import threading
import time
from typing import Callable, List, Optional, Tuple
import inspect

# --------------------------------------------------------------------------- #
#                               Support Structs                               #
# --------------------------------------------------------------------------- #

@dataclasses.dataclass(slots=True)
class ForkUnit:
    """
    Represents a single entry point (or 'gate') in a Fork.

    Each ForkUnit wraps:
    - `fork_callable`: A user-defined function to execute.
    - `usage_cap`: Max number of threads that can execute this unit.
    - `gate`: True once this unit has hit its usage cap.
    - `gate_uses`: Tracks how many threads have used it.
    - `lock`: Thread-safe protection for atomic usage claims.

    Used internally by SyncFork to coordinate slot-based callable execution.
    """

    fork_callable: Callable
    usage_cap: int
    lock: threading.Lock = dataclasses.field(default_factory=threading.RLock)
    gate: bool = False
    gate_uses: int = 0


# --------------------------------------------------------------------------- #
#                                 SyncFork                                    #
# --------------------------------------------------------------------------- #

class SyncFork:
    """
    A concurrent fork dispatcher with barrier semantics.

    Each thread claims a slot in a callable. Once the total number of slots across
    all callables is filled, all threads are released simultaneously to execute
    their assigned callables.

    Supports custom stride-based distribution (selector_step), optional reuse, and
    precise slot accounting. This is a zero-return system — callables must bind
    and store their state locally or in bound closures.

    Usage example:
    >>> fork = SyncFork(2, [(2, task_a), (2, task_b)])
    >>> # Call use_fork() from 4 threads
    """

    __slots__ = [
        "_list_of_forks", "_reusable", "_forks_closed", "_selector_step",
        "_selector_step_counter", "_selector_lock", "_threading_event",
        "_route_count", "_blocked_thread_count"
    ]

    # ---------------------------- Construction ---------------------------- #

    def __init__(
        self,
        number_of_forks: int,
        callables: List[Tuple[int, Callable]],
        reusable: bool = False,
        selector_step: int = 1,
    ):
        # --- Validate input ------------------------------------------------ #
        if number_of_forks != len(callables):
            raise ValueError("The number of forks must match the number of callables.")

        for i, item in enumerate(callables):
            if not isinstance(item, tuple) or len(item) != 2:
                raise TypeError(f"Tuple (usage_cap, Callable) expected at index {i}, got {item!r}")
            cap, fn = item
            if not isinstance(cap, int):
                raise TypeError(f"usage_cap at index {i} must be int, got {type(cap).__name__}")
            if not callable(fn):
                raise TypeError(f"Callable expected at index {i}, got {type(fn).__name__}")
            if inspect.iscoroutinefunction(fn):
                raise TypeError(f"Coroutine functions not supported (index {i}: {fn.__name__})")

        # --- Init internal state ------------------------------------------ #
        self._threading_event = threading.Event()  # Shared barrier event
        self._list_of_forks: List[ForkUnit] = [
            ForkUnit(fork_callable=fn, usage_cap=cap) for cap, fn in callables
        ]

        self._reusable = reusable
        self._forks_closed = False
        self._selector_step = max(1, selector_step)
        self._selector_step_counter = 0
        self._selector_lock = threading.RLock()
        self._blocked_thread_count = 0

        self._detect_number_of_routes()

    # ---------------------------- Internals ------------------------------ #

    def _detect_number_of_routes(self) -> None:
        """
        Calculates the total number of slots across all fork units.
        Used to determine when the barrier is full.
        """
        self._route_count = sum(u.usage_cap for u in self._list_of_forks)

    def _select_fork_unit_step(self) -> Optional[ForkUnit]:
        """
        Selector for the next available fork unit.

        Walks forward from the current cursor, scanning each unit once.
        If an available unit is found, the cursor jumps ahead by `selector_step`
        to increase distribution fairness under contention.

        Returns:
            - A usable ForkUnit, or
            - None if all are exhausted
        """
        if self._forks_closed and not self._reusable:
            return None

        length = len(self._list_of_forks)
        with self._selector_lock:
            start = self._selector_step_counter % length

        for offset in range(length):
            idx = (start + offset) % length
            unit = self._list_of_forks[idx]

            if not unit.gate and unit.gate_uses < unit.usage_cap:
                with self._selector_lock:
                    self._selector_step_counter = idx + self._selector_step
                return unit

        # No units left — close the fork
        self._forks_closed = True
        return None

    # ----------------------------- API ----------------------------------- #

    def reset(self) -> None:
        """
        Reset the SyncFork for another round.

        Only works if `reusable=True`.
        Resets:
        - Gate state on all units
        - Selector index
        - Blocked thread counter
        - Threading event
        """
        if not self._reusable:
            return

        for unit in self._list_of_forks:
            with unit.lock:
                unit.gate_uses = 0
                unit.gate = False

        with self._selector_lock:
            self._selector_step_counter = 0
            self._blocked_thread_count = 0
            self._forks_closed = False

        self._threading_event.clear()
        self._detect_number_of_routes()

    def use_fork(self) -> None:
        """
        Attempts to enter a fork unit.

        Each thread:
        - Selects a valid ForkUnit
        - Claims a usage slot
        - Waits until all slots are filled
        - Executes the assigned callable

        This is a blocking, barrier-synced operation. All threads are released
        simultaneously once the total number of slots (`_route_count`) is claimed.

        If exhausted and not reusable, raises RuntimeError.
        """
        if self._forks_closed and not self._reusable:
            raise RuntimeError("All forks are at capacity.")

        while True:
            unit = self._select_fork_unit_step()
            if unit is None:
                # No slots available or temporarily locked
                if self._forks_closed and not self._reusable:
                    raise RuntimeError("All forks are at capacity.")
                time.sleep(0.0005)
                continue

            # --- Attempt to claim the unit's slot atomically --- #
            with unit.lock:
                if unit.gate_uses >= unit.usage_cap:
                    continue  # Lost race, try again

                unit.gate_uses += 1
                if unit.gate_uses >= unit.usage_cap:
                    unit.gate = True

            # --- Update global blocked count and fire barrier --- #
            with self._selector_lock:
                self._blocked_thread_count += 1
                if self._blocked_thread_count >= self._route_count:
                    self._forks_closed = True
                    self._threading_event.set()

            # --- Wait for all other threads to arrive --- #
            self._threading_event.wait()

            # --- Execute the assigned callable --- #
            try:
                unit.fork_callable()
            except Exception as exc:
                # Optional: escalate or log
                print(f"[SyncFork] Callable {unit.fork_callable} raised: {exc!r}")
            return
