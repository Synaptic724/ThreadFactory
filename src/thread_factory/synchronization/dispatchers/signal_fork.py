import dataclasses, threading, time, ulid
from typing import Callable, List, Optional, Tuple, Union, Any
from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.utilities.coordination.package import Pack
from thread_factory.utilities.interfaces.disposable import IDisposable
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict


@dataclasses.dataclass(slots=True)
class ForkUnit:
    """Represents a single execution slot in a Fork."""
    fork_callable: Optional[Callable]
    usage_cap: int
    lock: threading.Lock = dataclasses.field(default_factory=threading.RLock)
    gate: bool = False
    gate_uses: int = 0

    def dispose(self) -> None:
        """
        Disposes the ForkUnit by clearing its associated callable.

        This method marks the unit as non-functional by removing the stored `fork_callable`.
        It does not alter the gate or usage counters, but effectively disables further execution.

        Notes:
            - This is a lightweight cleanup step typically used during `SignalFork.dispose()`.
            - Thread-safe if called within the unit's `lock`.
        """
        self.fork_callable = None


class SignalFork(IDisposable):
    """
    SignalFork
    ----------
    A fast, non-blocking fork dispatcher that distributes threads to available execution slots
    (ForkUnits), immediately executing user-provided callables. It tracks usage across all units
    and emits a one-time completion callback and optional controller notification once all
    slots are fully claimed and executed.

    Unlike synchronization-based forks (e.g., barriers or gated dispatchers), this fork allows
    threads to proceed immediately as long as an execution slot is available. It does not block
    threads until a threshold — instead, it simply executes callables directly and observes
    when the total capacity has been exhausted.

    Features
    --------
    • Thread-safe fork unit allocation with per-unit locking.
    • Optional round-robin or randomized selection of execution slots.
    • Optional callback executed once when all fork units are fully used.
    • Optional controller notification via `.notify(id, "FORK_COMPLETED")`.
    • Reusable via `.reset()` and disposable via `.dispose()`.

    Usage
    -----
    Create a SignalFork with `N` fork units, each having a `usage_cap` and callable.

    Example:
        >>> fork = SignalFork(
        ...     number_of_forks=2,
        ...     callables=[(2, lambda: print("A")), (1, lambda: print("B"))],
        ...     callback=lambda: print("All done!")
        ... )
        >>> fork.use_fork()  # Executes A
        >>> fork.use_fork()  # Executes A again
        >>> fork.use_fork()  # Executes B, triggers callback

    Parameters
    ----------
    number_of_forks : int
        The total number of callable slots (must match length of `callables`).

    callables : List[Tuple[int, Callable]]
        A list of (usage_cap, function) tuples where each function can be executed
        by up to `usage_cap` threads before being disabled.

    rotate_selectors : bool, optional
        If True, selects ForkUnits using a randomized scan-split strategy.
        If False (default), uses a round-robin stride mechanism.

    selector_step : int, optional
        Stride used in round-robin selection. Ignored if `rotate_selectors=True`.

    callback : Callable, optional
        A function executed exactly once when all ForkUnits are fully consumed.
        If provided, it will be called from the thread that triggers the final slot.

    controller : Any, optional
        An external object supporting `register()` and `notify()` methods.
        If provided, it will receive a `"FORK_COMPLETED"` notification when all work is done.

    Notes
    -----
    • This fork executes callables *immediately* — it does not block or synchronize threads.
    • Once all callables are consumed, `use_fork()` raises `RuntimeError` on future calls.
    • Use `reset()` to clear internal state and make the fork reusable.

    Raises
    ------
    ValueError:
        If the number of forks does not match the number of callables.

    TypeError:
        If a usage cap is not an integer or a callable is invalid.

    RuntimeError:
        If `use_fork()` is called after the fork is disposed or exhausted.
    """


    __slots__ = [
        "_list_of_forks", "_forks_closed", "_rotate_selectors",
        "_selector_step", "_selector_step_counter", "_selector_lock",
        "_id", "_callback", "_controller", "_callback_executed"
    ]

    def __init__(self,
                 number_of_forks: int,
                 callables: List[Tuple[int, Union[Callable[..., None], Pack]]],
                 *,  # Force subsequent args to be keyword-only
                 rotate_selectors: bool = False,
                 selector_step: int = 1,
                 callback: Optional[Callable] = None,
                 controller: Optional[Any] = None):
        super().__init__()
        if number_of_forks != len(callables):
            raise ValueError("The number of forks must match the number of callables.")

        _packed_callables = []
        for i, (cap, fn) in enumerate(callables):
            if not isinstance(cap, int):
                raise TypeError(f"usage_cap at index {i} must be int.")
            _packed_callables.append((cap, Pack.bundle(fn)))

        self._list_of_forks = ConcurrentList(
            [ForkUnit(fork_callable=fn, usage_cap=cap) for cap, fn in _packed_callables]
        )

        self._id = str(ulid.ULID())
        self._forks_closed = False
        self._rotate_selectors = rotate_selectors
        self._selector_step = max(1, selector_step)
        self._selector_step_counter = 0
        self._selector_lock = threading.RLock()

        self._callback = Pack.bundle(callback) if callback else None
        self._controller = controller
        self._callback_executed = False

        if self._controller:
            try:
                self._controller.register(self)
            except Exception:
                pass

    def dispose(self) -> None:
        """
        Fully disposes the SignalFork instance.

        This method performs complete teardown of the fork, including:
        • Marking the object as disposed to prevent further usage.
        • Releasing all held ForkUnit resources by invoking their `dispose()` methods.
        • Clearing the internal list of forks.
        • Unregistering from the controller (if registered).

        Notes:
            - Idempotent: safe to call multiple times.
            - Ensures no controller memory leaks due to lingering references.
        """
        if self._disposed:
            return
        with self._selector_lock:
            self._disposed = True
            self._forks_closed = True
            for unit in self._list_of_forks:
                unit.dispose()
            self._list_of_forks.dispose()
            self._list_of_forks = None
            self._callback = None

            # --- FINAL POLISH: Unregister from controller on dispose ---
            # This prevents the controller from holding a dead reference.
            if self._controller and hasattr(self._controller, 'unregister'):
                try:
                    self._controller.unregister(self.id)
                except Exception:
                    pass
            self._controller = None

    def reset(self) -> None:
        """
        Resets the internal state of the SignalFork, allowing reuse.

        This method:
        • Resets each ForkUnit's `gate_uses` and `gate` flags.
        • Clears the round-robin selector state.
        • Reopens the fork for new thread usage.
        • Clears the `_callback_executed` flag, enabling the callback to fire again if conditions are met.

        Raises:
            RuntimeError: If called on a disposed instance.
        """
        for unit in self._list_of_forks:
            with unit.lock:
                unit.gate = False
                unit.gate_uses = 0

        with self._selector_lock:
            self._selector_step_counter = 0
            self._forks_closed = False
            self._callback_executed = False

    def use_fork(self) -> None:
        """
        Attempts to execute a unit of work through the fork.

        Execution logic:
        • Selects a ForkUnit via round-robin or randomized scan, based on configuration.
        • Acquires the unit's lock and increments its usage count.
        • If the unit is full, continues attempting selection until all are exhausted.
        • If all ForkUnits are exhausted, triggers the callback and controller notification once.

        Raises:
            RuntimeError:
                - If the fork is disposed.
                - If all ForkUnits are at capacity.
            Any exception raised by the target `fork_callable`, unless caught internally.
        """
        if self._disposed:
            raise RuntimeError("Cannot use a disposed SignalFork.")

        while True:
            unit = self._select_fork_unit() if self._rotate_selectors else self._select_fork_unit_step()

            if unit is None:
                with self._selector_lock:
                    if self._callback and not self._callback_executed:
                        try:
                            self._callback()
                            if self._controller:
                                self._controller.notify(self.id, "FORK_COMPLETED")
                        except Exception as e:
                            if self._controller and hasattr(self._controller, 'log_error'):
                                self._controller.log_error(f"Error in SignalFork callback: {e}")
                        finally:
                            self._callback_executed = True

                raise RuntimeError("No available forks to use, all forks are at capacity.")

            with unit.lock:
                if self.disposed or unit.gate_uses >= unit.usage_cap:
                    continue

                unit.gate_uses += 1
                if unit.gate_uses >= unit.usage_cap:
                    unit.gate = True

                unit.fork_callable()
                return

    @property
    def id(self) -> str:
        """
        Returns:
            str: A ULID-based unique identifier for this SignalFork instance.

        Purpose:
            Used by controllers and external tools to reference and track this fork across its lifecycle.
        """
        return self._id

    def _get_object_details(self) -> ConcurrentDict[str, Any]:
        """
        Constructs a metadata snapshot for controller registration or introspection.

        Returns:
            ConcurrentDict[str, Any]: A dictionary with basic identity and exposed commands.

        Structure:
            {
                "name": "signal_fork",
                "commands": {
                    "dispose": self.dispose,
                    "reset": self.reset,
                }
            }

        Notes:
            - Useful for dynamic controllers or dashboards.
        """
        return ConcurrentDict({
            'name': 'signal_fork',
            'commands': ConcurrentDict({
                'dispose': self.dispose,
                'reset': self.reset,
            })
        })

    def _select_fork_unit(self) -> Optional[ForkUnit]:
        """
        Selects an available ForkUnit using a scan strategy that flips between halves of the list.

        Strategy:
            • A bit from `time.monotonic_ns()` determines scan direction (front-first or back-first).
            • If no unit is available in the first scan, fallback to the other half.
            • Marks the fork as closed (`_forks_closed = True`) if no slots remain.

        Returns:
            Optional[ForkUnit]: An available ForkUnit, or None if all are full.
        """
        if self._forks_closed: return None
        flip = time.monotonic_ns() & 1
        mid = len(self._list_of_forks) // 2
        scan_range_1 = range(0, mid) if flip == 0 else range(mid, len(self._list_of_forks))
        scan_range_2 = range(mid, len(self._list_of_forks)) if flip == 0 else range(0, mid)
        for idx in scan_range_1:
            unit = self._list_of_forks[idx]
            with unit.lock:
                if not unit.gate and unit.gate_uses < unit.usage_cap:
                    return unit
        for idx in scan_range_2:
            unit = self._list_of_forks[idx]
            with unit.lock:
                if not unit.gate and unit.gate_uses < unit.usage_cap:
                    return unit
        self._forks_closed = True
        return None

    def _select_fork_unit_step(self) -> Optional[ForkUnit]:
        """
        Selects an available ForkUnit using round-robin selection with a stride.

        Strategy:
            • Begins at `_selector_step_counter % len`.
            • Steps forward using `_selector_step`, wrapping around the list.
            • Updates `_selector_step_counter` after successful selection.

        Returns:
            Optional[ForkUnit]: An available ForkUnit if one has remaining capacity, or None otherwise.
        """
        if self._forks_closed: return None
        length = len(self._list_of_forks)
        with self._selector_lock:
            start_index = self._selector_step_counter % length
        for i in range(length):
            idx = (start_index + i * self._selector_step) % length
            unit = self._list_of_forks[idx]
            with unit.lock:
                if not unit.gate and unit.gate_uses < unit.usage_cap:
                    with self._selector_lock:
                        self._selector_step_counter = (idx + 1) % length
                        return unit
        self._forks_closed = True
        return None