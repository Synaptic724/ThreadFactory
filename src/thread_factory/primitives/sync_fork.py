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
    - `usage_cap`: Maximum number of threads allowed to use this unit.
    - `gate`: Marks whether this unit is exhausted (True when max uses are hit).
    - `gate_uses`: Tracks how many times this unit has been used.
    - `lock`: A thread-safe lock protecting the state of this unit.
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
    A concurrent fork dispatcher / barrier hybrid.

    See doc-string above the original class for full behaviour description.
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
        # --- Validate ----------------------------------------------------- #
        if number_of_forks != len(callables):
            raise ValueError(
                "The number of forks must match the number of callables."
            )

        for i, item in enumerate(callables):
            if not isinstance(item, tuple) or len(item) != 2:
                raise TypeError(
                    f"Tuple (usage_cap, Callable) expected at index {i}, got {item!r}"
                )
            cap, fn = item
            if not isinstance(cap, int):
                raise TypeError(
                    f"usage_cap at index {i} must be int, got {type(cap).__name__}"
                )
            if not callable(fn):
                raise TypeError(
                    f"Callable expected at index {i}, got {type(fn).__name__}"
                )
            if inspect.iscoroutinefunction(fn):
                raise TypeError(
                    f"Coroutine functions not supported (index {i}: {fn.__name__})"
                )

        # --- Init --------------------------------------------------------- #
        self._threading_event = threading.Event()
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
        """Re‐compute total capacity for this fork group."""
        self._route_count = sum(u.usage_cap for u in self._list_of_forks)

    def _select_fork_unit_step(self) -> Optional[ForkUnit]:
        """
        Fair selection with arbitrary stride.
        We *scan sequentially* to guarantee full coverage,
        then jump the cursor ahead by `self._selector_step`
        so the next thread starts at a different slot.
        """
        if self._forks_closed and not self._reusable:
            return None

        length = len(self._list_of_forks)

        # Snapshot the current cursor
        with self._selector_lock:
            start = self._selector_step_counter % length

        # 🔍 1) Sweep every unit exactly once
        for offset in range(length):
            idx = (start + offset) % length
            unit = self._list_of_forks[idx]

            if not unit.gate and unit.gate_uses < unit.usage_cap:
                # 🔀 2) Move the cursor forward by `selector_step`
                with self._selector_lock:
                    self._selector_step_counter = idx + self._selector_step
                return unit

        # No capacity left
        self._forks_closed = True
        return None


    # ----------------------------- API ----------------------------------- #

    def reset(self) -> None:
        """Reset the fork for another round (only if `reusable=True`)."""
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
        Claim a slot, block until *every* slot is claimed, then run the callable.
        """
        if self._forks_closed and not self._reusable:
            raise RuntimeError("All forks are at capacity.")

        while True:
            unit = self._select_fork_unit_step()
            if unit is None:
                # Either exhausted or temporarily lost race. Small back-off helps.
                if self._forks_closed and not self._reusable:
                    raise RuntimeError("All forks are at capacity.")
                time.sleep(0.0005)
                continue

            # ----------------- Claim the slot atomically ------------------ #
            with unit.lock:
                if unit.gate_uses >= unit.usage_cap:
                    # Lost the race for this unit; retry selection
                    continue

                unit.gate_uses += 1
                if unit.gate_uses >= unit.usage_cap:
                    unit.gate = True

            # ---------------- Barrier bookkeeping ------------------------ #
            with self._selector_lock:
                self._blocked_thread_count += 1
                if self._blocked_thread_count >= self._route_count:
                    self._forks_closed = True  # <— NEW: satisfies reusable-fork test
                    self._threading_event.set()

            # --------------- Wait for the release signal ------------------ #
            self._threading_event.wait()

            # ----------------- Execute the callable ---------------------- #
            try:
                unit.fork_callable()
            except Exception as exc:                 # noqa: BLE001
                # If you want to surface per-thread exceptions, comment-in the next line
                # raise  # or store somewhere – left to your design choice
                print(f"[SyncFork] Callable {unit.fork_callable} raised: {exc!r}")

            return
