import dataclasses
import threading
import time
import ulid
from typing import Callable, List, Optional, Tuple, Union, Any

# Assuming these imports are available from your project structure
from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.utils.coordination.package import Pack
from thread_factory.utils.interfaces.disposable import IDisposable
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
        self.fork_callable = None


class SignalFork(IDisposable):
    """
    A non-blocking, concurrent fork dispatcher that signals a controller
    and executes a callback upon completion.

    This class behaves like a standard Fork, immediately dispatching threads
    to available callables. When the very last callable slot is used, it will
    trigger a one-time callback and notify an optional controller that its
    work is done.
    """

    __slots__ = [
        "_list_of_forks", "_forks_closed", "_rotate_selectors",
        "_selector_step", "_selector_step_counter", "_selector_lock",
        "_id", "_callback", "_controller", "_callback_executed"
    ]

    def __init__(self,
                 number_of_forks: int,
                 callables: List[Tuple[int, Union[Callable, Pack]]],
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
        """Fully disposes the fork and unregisters from the controller."""
        if self._disposed:
            return
        with self._selector_lock:
            self._disposed = True
            self._forks_closed = True
            for unit in self._list_of_forks:
                unit.dispose()
            self._list_of_forks.clear()

            # --- FINAL POLISH: Unregister from controller on dispose ---
            # This prevents the controller from holding a dead reference.
            if self._controller and hasattr(self._controller, 'unregister'):
                try:
                    self._controller.unregister(self)
                except Exception:
                    pass

    def reset(self) -> None:
        """Resets the fork for reuse, including the callback execution flag."""
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
        Routes the calling thread through an available fork unit and triggers
        the callback and controller notification upon completion.
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
        """A unique identifier for this instance."""
        return self._id

    def _get_object_details(self) -> ConcurrentDict[str, Any]:
        """Prepares a summary for controller registration."""
        return ConcurrentDict({
            'name': 'signal_fork',
            'commands': ConcurrentDict({
                'dispose': self.dispose,
                'reset': self.reset,
            })
        })

    def _select_fork_unit(self) -> Optional[ForkUnit]:
        """Selects an available ForkUnit using a time-based scan split."""
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
        """Selects an available ForkUnit using a round-robin step counter."""
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