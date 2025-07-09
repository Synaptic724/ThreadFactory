import dataclasses, threading, ulid
from typing import Callable, List, Optional, Tuple, Any, Dict, Union
from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.synchronization.coordinators.scout import Scout
from thread_factory.utilities.interfaces.disposable import IDisposable
from thread_factory.utilities.coordination.package import Pack


@dataclasses.dataclass(slots=True)
class ForkUnit:
    """
    Represents an execution slot inside a SyncSignalFork.

    Attributes
    ----------
    fork_callable : Callable
        User-supplied function to execute once the barrier releases.
    usage_cap : int
        Maximum number of threads allowed to claim this unit.
    lock : threading.Lock
        Protects `gate_uses` & `gate`.
    gate : bool
        Becomes *True* when the usage cap is reached.
    gate_uses : int
        Current number of threads that have claimed this unit.
    """
    fork_callable: Optional[Union[Callable[..., None], Pack]]
    usage_cap: int
    lock: threading.Lock = dataclasses.field(default_factory=threading.RLock)
    gate: bool = False
    gate_uses: int = 0

    def dispose(self) -> None:
        """
        Marks this ForkUnit as disposed by sealing the gate and clearing callable.
        """
        self.fork_callable = None


class SyncSignalFork(IDisposable):
    """
    SyncSignalFork
    --------------
    Slot-based fork dispatcher **with controller hooks** and **manual-release**
    semantics.

    Threads *claim* slots in the provided `(usage_cap, callable)` list.  When
    **all** slots across **all** callables are claimed, the fork:

    • Executes `callback` (if any).
    • Emits ``"THRESHOLD_MET"`` via the controller (if supplied).
    • If *manual_release=False* → immediately releases all waiters and emits
      ``"SEMAPHORE_RELEASED"``.
    • If *manual_release=True*  → **blocks** until someone calls
      :py:meth:`release`, which then fires the same event.

    Optional timeout enforcement is handled by a :class:`Scout` helper.  A
    timeout raises :class:`RuntimeError` in *all* participating threads.

    Controller command map
    ----------------------
    If a controller is supplied at construction, it can remotely invoke:

    * ``release`` – Manual release (only honoured when *manual_release=True*).
    * ``reset``   – Prepare the fork for the next cohort.
    * ``dispose`` – Tear everything down.

    Parameters
    ----------
    number_of_forks :
        Must equal ``len(callables)``.
    callables :
        List of ``(usage_cap:int, fn:Callable)`` tuples.
    selector_step :
        Stride for round-robin slot assignment (≥ 1).
    timeout_duration :
        Global timeout (seconds) for the barrier; *None* disables timeout.
    manual_release :
        If *True*, the barrier waits for an explicit :py:meth:`release`.
    callback :
        Invoked exactly once when all slots are claimed.
    controller :
        Optional orchestration controller exposing ``register`` / ``notify``.
    signal_callback :
        Hook called by each blocking thread **once** before it sleeps
        (e.g., ``controller.on_wait_starting``).
    """

    __slots__ = [
        "_list_of_forks", "_forks_closed", "_selector_step",
        "_selector_step_counter", "_selector_lock", "_threading_event",
        "_route_count", "_blocked_thread_count", "_id",
        "_timeout_duration", "_timed_out", "_scout",
        "_manual_release", "_released",
        "_callback", "_controller", "_signal_callback"
    ]

    def __init__(
            self,
            number_of_forks: int,
            callables: List[Tuple[int, Union[Callable[..., None], Pack]]],
            *,
            selector_step: int = 1,
            timeout_duration: Optional[float] = None,
            manual_release: bool = False,
            callback: Optional[Union[Callable[..., None], Pack]] = None,
            controller: Optional["Controller"] = None,
            signal_callback: Optional[Union[Callable[..., None], Pack]] = None,
    ):
        super().__init__()

        # ----------------- validation ----------------- #
        if number_of_forks != len(callables):
            raise ValueError("number_of_forks must match len(callables).")

        # Fix: Create a new list to store the packed callables.
        # Modifying a list while iterating over it, although possible with reassignment,
        # can sometimes be less clear or lead to subtle bugs if not careful.
        # Creating a new list ensures the original input isn't unintentionally altered,
        # and it makes the packing process explicit.
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

        if timeout_duration is not None and (timeout_duration <= 0):
            raise ValueError("timeout_duration must be > 0 or None.")

        # ----------------- immutable config ----------------- #
        self._id: str = str(ulid.ULID())
        self._manual_release: bool = bool(manual_release)
        self._callback: Optional[Union[Callable[..., None], Pack]] = Pack.bundle(callback) if callback else None
        self._controller = controller
        self._signal_callback: Union[Callable[..., None], Pack] = Pack.bundle(signal_callback) if signal_callback else None

        # ----------------- state ----------------- #
        self._threading_event = threading.Event()
        self._selector_step = max(1, selector_step)
        self._selector_step_counter = 0
        self._selector_lock = threading.RLock()
        self._blocked_thread_count = 0
        self._forks_closed = False
        self._released = False
        self._timeout_duration = timeout_duration
        self._timed_out = False
        self._scout: Optional[Scout] = None  # Assuming Scout manages the timeout logic
        self._detect_number_of_routes()

        if self._controller:
            try:
                self._controller.register(self)
            except Exception:
                pass

    def dispose(self) -> None:
        """
        Dispose the SyncSignalFork instance and release all held resources.

        This method:
        • Sets `_disposed = True` to block future usage.
        • Releases all waiting threads via `_threading_event`.
        • Disposes all ForkUnits by clearing their callables.
        • Disposes the Scout (if active).
        • Unregisters from the controller (if provided).

        This method is idempotent and can be safely called multiple times.
        """

        if self._disposed:
            return

        with self._selector_lock:
            self._disposed = True
            self._forks_closed = True
            self._threading_event.set()

            if self._scout:
                self._scout.dispose()
                self._scout = None

            for unit in self._list_of_forks:
                unit.dispose()

            self._list_of_forks.clear()

            # Optional: unregister from controller
            if self._controller:
                try:
                    self._controller.unregister(self.id)
                except Exception:
                    pass

    @property
    def id(self) -> str:  # noqa: D401
        """
        Returns the ULID identifier for this fork.

        Used as a unique key when interacting with an external controller.
        """

        return self._id

    def _get_object_details(self) -> ConcurrentDict[str, Any]:
        """
        Returns a dictionary of metadata about this object.

        Used for controller registration or introspection. Exposes:
        • name: Identifier string.
        • commands: Public methods that can be triggered by controller (release, reset, dispose).
        """

        return ConcurrentDict({
            "name": "sync_signal_fork",
            "commands": ConcurrentDict({
                "release": self.release,
                "reset":   self.reset,
                "dispose": self.dispose,
            }),
        })

    def _detect_number_of_routes(self) -> None:
        """
        Computes the total number of slot claims across all ForkUnits.

        Sets `_route_count` which determines the barrier threshold.
        """

        self._route_count = sum(u.usage_cap for u in self._list_of_forks)

    def _select_fork_unit_step(self) -> Optional[ForkUnit]:
        """
        Selects the next available ForkUnit based on round-robin logic.

        Returns:
            ForkUnit if a slot is available; None if all units are exhausted.

        Updates `_selector_step_counter` to maintain stride distribution.
        """

        if self._forks_closed:
            return None

        length = len(self._list_of_forks)
        with self._selector_lock:
            start = self._selector_step_counter % length

        for offset in range(length):
            idx = (start + offset) % length
            unit = self._list_of_forks[idx]
            with unit.lock:
                if not unit.gate and unit.gate_uses < unit.usage_cap:
                    with self._selector_lock:
                        self._selector_step_counter = (idx + self._selector_step) % length
                    return unit

        self._forks_closed = True
        return None

    # ---------------- Scout predicates/callbacks ---------------- #
    def _scout_predicate(self) -> bool:
        """
        Returns True if the barrier condition has been met (all slots claimed).

        Used as a predicate for the Scout's timeout monitoring.
        """

        with self._selector_lock:
            return self._blocked_thread_count >= self._route_count

    def _handle_scout_timeout(self) -> None:
        """
        Called by the Scout if the barrier is not filled within the timeout window.

        Triggers timeout behavior:
        • Sets `_timed_out = True`
        • Closes the fork
        • Releases all waiting threads
        """

        with self._selector_lock:
            if not self._timed_out:
                self._timed_out = True
                self._forks_closed = True
                self._threading_event.set()

    def _handle_scout_success(self) -> None:
        """
        Called by the Scout if the barrier is filled before timeout.

        Currently a no-op, but can be extended for logging or diagnostics.
        """
        pass

    def use_fork(self) -> None:
        """
        Claim a slot, wait for the barrier, and execute the assigned callable.

        This method is called by each participating thread. It:
        • Acquires a slot from the available ForkUnits.
        • Tracks progress toward the barrier threshold.
        • Starts the Scout if timeout logic is enabled.
        • Optionally calls `callback` and notifies the controller.
        • Waits on `_threading_event` for the release signal.
        • Executes the selected callable once the barrier is released.

        Raises:
            RuntimeError: If disposed, timed out, or fork is closed and released.
        """

        if self._disposed:
            raise RuntimeError("Cannot use a disposed SyncSignalFork.")
        if self._timed_out:
            raise RuntimeError("SyncSignalFork barrier timed out.")
        if self._forks_closed and self._released:
            raise RuntimeError("All forks are at capacity or barrier already released.")

        # ----------- pick & claim a unit ----------- #
        selected_unit: Optional[ForkUnit] = None
        while selected_unit is None:
            unit_candidate = self._select_fork_unit_step()
            if unit_candidate is None:
                raise RuntimeError("No available forks to use.")
            with unit_candidate.lock:
                if unit_candidate.gate_uses >= unit_candidate.usage_cap:
                    continue
                selected_unit = unit_candidate
                selected_unit.gate_uses += 1
                if selected_unit.gate_uses >= selected_unit.usage_cap:
                    selected_unit.gate = True

        # ----------- scout ownership & counter ----------- #
        run_scout = False
        defer_increment = False
        with self._selector_lock:
            first_thread = (self._blocked_thread_count == 0)

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
                run_scout = True

                if self._route_count == 1:
                    defer_increment = True
                else:
                    self._blocked_thread_count += 1
            else:
                self._blocked_thread_count += 1

            # ---------- threshold met ---------- #
            if self._blocked_thread_count >= self._route_count:
                if self._controller:
                    self._controller.notify(self.id, "THRESHOLD_MET")
                if self._callback:
                    try:
                        self._callback()
                    except Exception:
                        pass

                if not self._manual_release:
                    self._released = True
                    self._forks_closed = True
                    self._threading_event.set()
                    if self._controller:
                        self._controller.notify(self.id, "SEMAPHORE_RELEASED")
                # else wait for external .release()

                if self._scout:
                    with self._scout._condition:
                        self._scout._condition.notify_all()

        # ----------- run scout ----------- #
        if run_scout:
            self._scout.monitor()
            if defer_increment:
                with self._selector_lock:
                    self._blocked_thread_count += 1
                    if self._blocked_thread_count >= self._route_count:
                        if self._controller:
                            self._controller.notify(self.id, "THRESHOLD_MET")
                        if self._callback:
                            try:
                                self._callback()
                            except Exception:
                                pass
                        if not self._manual_release:
                            self._released = True
                            self._forks_closed = True
                            self._threading_event.set()
                            if self._controller:
                                self._controller.notify(self.id, "SEMAPHORE_RELEASED")
                        if self._scout:
                            with self._scout._condition:
                                self._scout._condition.notify_all()

        # ----------- wait for release / timeout ----------- #
        if self._signal_callback and not self._threading_event.is_set():
            try:
                self._signal_callback(self.id)
            except Exception:
                pass

        self._threading_event.wait()
        with self._selector_lock:
            if self._disposed:
                raise RuntimeError("SyncSignalFork disposed while waiting.")
            if self._timed_out:
                raise RuntimeError("SyncSignalFork barrier timed out.")

        # ----------- execute callable ----------- #
        selected_unit.fork_callable()

    def release(self) -> None:
        """
        Manually releases the barrier (only if `manual_release=True`).

        Sets `_released = True`, unblocks all waiting threads,
        and notifies the controller via `"SEMAPHORE_RELEASED"`.
        """

        if not self._manual_release:
            return
        with self._selector_lock:
            if self._released or self._disposed:
                return
            self._released = True
            self._forks_closed = True
            self._threading_event.set()
            if self._controller:
                self._controller.notify(self.id, "SEMAPHORE_RELEASED")

    def reset(self) -> None:
        """
        Resets internal state, allowing the fork to be reused for another cycle.

        Resets:
        • ForkUnit gate flags and counters
        • Selector step index
        • Blocked thread count and barrier flags
        • Scout state (if applicable)

        Raises:
            RuntimeError: If called on a disposed instance.
        """
        if self._disposed:
            raise RuntimeError("Cannot reset a disposed SyncSignalFork.")

        for unit in self._list_of_forks:
            with unit.lock:
                unit.gate = False
                unit.gate_uses = 0

        with self._selector_lock:
            self._selector_step_counter = 0
            self._blocked_thread_count = 0
            self._forks_closed = False
            self._released = False
            self._timed_out = False

        self._threading_event.clear()

        if self._scout:
            self._scout.exit_monitor()
            # Wake any blocked scout monitors from previous run
            with self._scout._condition:
                self._scout._condition.notify_all()
