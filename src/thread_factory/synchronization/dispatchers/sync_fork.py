import dataclasses
import threading
from multiprocessing.synchronize import RLock
from typing import Callable, List, Optional, Tuple, Union
import inspect
import ulid
from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.utilities.coordination.package import Pack
from thread_factory.utilities.interfaces.disposable import IDisposable

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

    fork_callable: Union[Callable[..., None], Pack] | None
    usage_cap: int
    lock: threading.Lock = dataclasses.field(default_factory=threading.RLock)
    gate: bool = False
    gate_uses: int = 0


    def dispose(self) -> None:
        """
        Marks this ForkUnit as disposed by sealing the gate and clearing callable.
        """
        self.fork_callable = None


# --------------------------------------------------------------------------- #
#                                 SyncFork                                    #
# --------------------------------------------------------------------------- #

class SyncFork(IDisposable):  # SyncFork now inherits from IDisposable
    """
    A concurrent fork dispatcher with barrier semantics and optional timeout.

    Each thread claims a slot in a callable. Once the total number of slots across
    all callables is filled, all threads are released simultaneously to execute
    their assigned callables.

    If a `timeout_duration` is provided, the first thread to enter the barrier
    will act as a monitor, and if the barrier is not filled within the timeout,
    all waiting threads will be released with a RuntimeError indicating a timeout.

    Supports custom stride-based distribution (selector_step) and precise slot
    accounting. This is a zero-return system — callables must bind and store
    their state locally or in bound closures.

    This SyncFork can always be reset via `reset()` to be reused for subsequent
    batches of concurrent tasks.

    Usage example:
    >>> fork = SyncFork(2, [(2, task_a), (2, task_b)], timeout_duration=5.0)
    >>> # Call use_fork() from 4 threads
    >>> # After completion, call fork.reset() to reuse for another batch.
    """

    __slots__ = [
        "_list_of_forks", "_forks_closed", "_selector_step",
        "_selector_step_counter", "_selector_lock", "_threading_event",
        "_route_count", "_blocked_thread_count", "_id",
        "_timeout_duration", "_timed_out", "_scout"  # Added timeout related slots
    ]

    def __init__(
            self,
            number_of_forks: int,
            callables: List[Tuple[int, Union[Callable[..., None], Pack]]],
            selector_step: int = 1,
            timeout_duration: Optional[float] = None,  # New optional timeout parameter
    ):
        super().__init__()  # Initialize IDisposable
        # Validate input
        if number_of_forks != len(callables):
            raise ValueError("The number of forks must match the number of callables.")

        for i, item in enumerate(callables):
            if not isinstance(item, tuple) or len(item) != 2:
                raise TypeError(f"Tuple (usage_cap, Callable) expected at index {i}, got {item!r}")
            cap, fn = item
            if not isinstance(cap, int):
                raise TypeError(f"usage_cap at index {i} must be int, got {type(cap).__name__}")

        if timeout_duration is not None and (not isinstance(timeout_duration, (int, float)) or timeout_duration <= 0):
            raise ValueError("timeout_duration must be a positive number or None.")

        # Use tuple unpacking to set the individual usage_cap for each ForkUnit.
        # Use the _packed_callables list directly for initializing _list_of_forks
        self._list_of_forks: ConcurrentList[ForkUnit] = ConcurrentList([ForkUnit(fork_callable=Pack.bundle(fn), usage_cap=cap)
                                               for cap, fn in callables])
        # Init internal state
        self._id = str(ulid.ULID())
        self._forks_closed: bool = False
        self._selector_step = max(1, selector_step)
        self._selector_step_counter: int = 0
        self._blocked_thread_count: int = 0
        self._timeout_duration: float = timeout_duration
        self._timed_out = False  # Flag set by Scout if timeout occurs

        # --- Synchronization state --- #
        self._threading_event = threading.Event()  # Shared barrier event for all threads
        self._selector_lock: threading.RLock = threading.RLock()  # Protects _blocked_thread_count and _selector_step_counter
        self._scout: Optional['Scout'] = None  # Scout instance for barrier timeout
        self._detect_number_of_routes()

    def dispose(self) -> None:
        """
        Disposes the SyncFork instance. Releases all resources and makes it unusable.
        Idempotent: safe to call multiple times.

        After disposal:
        - All future use of `use_fork()` raises RuntimeError.
        - All `ForkUnit`s are explicitly disposed (clearing their callables).
        - The internal threading event is triggered to release any waiting threads.
        - If a Scout was in use, it is also disposed.
        """
        if self._disposed:
            return

        with self._selector_lock:
            self._disposed = True
            self._forks_closed = True
            self._threading_event.set()  # Wake anything waiting

            # Dispose Scout if present
            if self._scout:
                self._scout.dispose()
                self._scout = None

            # Dispose all ForkUnits to clear callables
            for unit in self._list_of_forks:
                unit.dispose()

            self._list_of_forks.clear()

    def _scout_predicate(self) -> bool:
        """
        Predicate for the Scout to check if the barrier has been met.
        This callable is invoked by Scout while holding Scout's internal condition lock.
        It must acquire SyncFork's selector lock to check the count.
        """
        with self._selector_lock:
            return self._blocked_thread_count >= self._route_count

    def _handle_scout_timeout(self) -> None:
        """
        Callback for Scout when the barrier timeout occurs.
        Executed by the thread running Scout.monitor().
        This method will signal all waiting threads to exit with a timeout error.
        """
        with self._selector_lock:
            if not self._timed_out:  # Prevent double-signaling if somehow raced
                self._timed_out = True
                self._forks_closed = True  # Mark fork as closed due to timeout
                self._threading_event.set()  # Release all threads waiting at the barrier
            # print(f"[SyncFork] Barrier timed out after {self._timeout_duration}s.") # Removed print for clean test output

    def _handle_scout_success(self) -> None:
        """
        Callback for Scout when the barrier is met before timeout.
        This generally means the last thread to arrive set the event naturally.
        """
        # In this design, the natural flow of SyncFork (last thread sets _threading_event.set())
        # is the primary success path. This callback isn't strictly needed for behavior,
        # but could be used for logging/debugging if desired. For now, it's a no-op.
        pass


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
        # If forks are already closed (e.g., due to previous timeout or exhaustion)
        if self._forks_closed:
            return None

        length = len(self._list_of_forks)
        with self._selector_lock:
            start = self._selector_step_counter % length

        for offset in range(length):
            idx = (start + offset) % length
            unit = self._list_of_forks[idx]

            # Check unit under its own lock to avoid contention on unit state
            with unit.lock:
                if not unit.gate and unit.gate_uses < unit.usage_cap:
                    with self._selector_lock:  # Acquire selector lock to update global counter
                        self._selector_step_counter = (idx + self._selector_step) % length  # Ensure wrap-around
                    return unit

        # No units left — all are exhausted.
        self._forks_closed = True
        return None


    def reset(self) -> None:
        """
        Reset the SyncFork for another round.

        Resets:
        - Gate state on all units
        - Selector index
        - Blocked thread counter
        - Threading event
        - Overall fork closed status
        - Timeout flags and associated Scout instance.

        This method is always available to reset the SyncFork for reuse.
        """
        if self._disposed:
            raise RuntimeError("Cannot reset a disposed SyncFork.")

        for unit in self._list_of_forks:
            with unit.lock:
                unit.gate_uses = 0
                unit.gate = False

        with self._selector_lock:
            self._selector_step_counter = 0
            self._blocked_thread_count = 0
            self._forks_closed = False  # Ensure the fork is open for new operations
            self._timed_out = False  # Reset timeout flag

        self._threading_event.clear()  # Clear the barrier event for the next cycle

        # Reset the Scout if it exists
        if self._scout:
            self._scout.reset()

        self._detect_number_of_routes()  # Re-calculate route count, though usually static
        # ─────────────────────────── helper: scout ping ──────────────────────── #

    def _ping_scout(self) -> None:
        """
        Wake the Scout (if present) **without** holding `_selector_lock`,
        preventing lock‐order inversion that could dead-lock monitor & workers.
        """
        scout = self._scout
        if scout is None:
            return
        # Acquire Scout’s condition in isolation
        with scout._condition:
            scout._condition.notify_all()

        # ─────────────────────────────── use_fork ────────────────────────────── #

    def use_fork(self) -> None:
        """
        Enter the SyncFork barrier, claim a slot, wait for the barrier,
        then run the assigned callable.  (Docstring unchanged.)
        """
        from thread_factory.synchronization.coordinators.scout import Scout

        if self._disposed:
            raise RuntimeError("Cannot use a disposed SyncFork.")
        if self._timed_out:
            raise RuntimeError("SyncFork barrier timed out.")
        if self._forks_closed:
            raise RuntimeError("All forks are at capacity or barrier has already closed.")

        # STEP 1 ─ pick a ForkUnit
        selected_unit: Optional[ForkUnit] = None
        while selected_unit is None:
            unit_candidate = self._select_fork_unit_step()
            if unit_candidate is None:
                raise RuntimeError("No available forks to use, all forks are at capacity.")

            with unit_candidate.lock:
                if unit_candidate.gate_uses >= unit_candidate.usage_cap:
                    continue  # lost race – retry
                selected_unit = unit_candidate
                selected_unit.gate_uses += 1
                if selected_unit.gate_uses >= selected_unit.usage_cap:
                    selected_unit.gate = True  # unit exhausted

        # Flags used outside lock-scope
        start_scout = False
        defer_increment = False

        # STEP 2 ─ enter barrier bookkeeping
        with self._selector_lock:
            first_thread = (self._blocked_thread_count == 0)

            # Scout handling
            if first_thread and self._timeout_duration is not None:
                if self._scout is None:
                    self._scout = Scout(
                        predicate=self._scout_predicate,
                        timeout_duration=self._timeout_duration,
                        on_timeout_callable=self._handle_scout_timeout,
                        on_success_callable=self._handle_scout_success,
                        autoreset_on_exit=False,
                    )
                else:
                    self._scout.reset()
                start_scout = True

            # single-slot optimisation
            if self._route_count == 1:
                defer_increment = True
            else:
                self._blocked_thread_count += 1

            # barrier met?
            if self._blocked_thread_count >= self._route_count:
                self._forks_closed = True
                self._threading_event.set()

        # 🔔 scout ping outside selector lock (dead-lock free)
        self._ping_scout()

        # STEP 3 ─ run Scout monitor if we are designated
        if start_scout:
            self._scout.monitor()

        # single-slot increment after Scout returned
        if defer_increment:
            with self._selector_lock:
                self._blocked_thread_count += 1
                if self._blocked_thread_count >= self._route_count:
                    self._forks_closed = True
                    self._threading_event.set()
            self._ping_scout()  # possible final ping

        # STEP 4 ─ wait for barrier
        self._threading_event.wait()

        # STEP 5 ─ post-barrier checks
        with self._selector_lock:
            if self._disposed:
                raise RuntimeError("Cannot use a disposed SyncFork.")
            if self._timed_out:
                raise RuntimeError("SyncFork barrier timed out.")

        # STEP 6 ─ execute assigned callable
        selected_unit.fork_callable()