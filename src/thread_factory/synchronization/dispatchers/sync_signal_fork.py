import dataclasses
import inspect
import threading
import ulid
from typing import Callable, List, Optional, Tuple

from thread_factory.utils import IDisposable


# Assume these dependencies are available in the project scope.
# from thread_factory.controllers import SignalController
# from thread_factory.synchronization.coordinators.scout import Scout
# from thread_factory.utils import IDisposable


@dataclasses.dataclass(slots=True)
class ForkUnit:
    """A support structure representing a single callable entry point in a fork.

    Each ForkUnit encapsulates a user-defined function and tracks its usage,
    ensuring that no more than `usage_cap` threads can execute it per cycle.
    It uses its own lock for thread-safe updates to its usage count.

    Attributes:
        fork_callable (Callable): The function to be executed by a thread.
        usage_cap (int): The maximum number of times the callable can be used.
        lock (threading.RLock): A lock to protect access to `gate` and `gate_uses`.
        gate (bool): A flag that becomes True once `usage_cap` is reached.
        gate_uses (int): The current number of times this unit has been claimed.
    """
    fork_callable: Callable
    usage_cap: int
    lock: threading.Lock = dataclasses.field(default_factory=threading.RLock)
    gate: bool = False
    gate_uses: int = 0


class SyncSignalFork(IDisposable):
    """A concurrent, slot-based dispatcher with controller integration.

    SyncSignalFork acts as a synchronization barrier where a predefined number
    of threads must "claim a slot" in one of several provided callables. Once all
    available slots across all callables are filled, the barrier is lifted,
    and all waiting threads execute their assigned callable simultaneously.

    This class enhances the core `SyncFork` concept by integrating with the
    `SignalController` framework, enabling advanced orchestration, monitoring,
and remote control.

    ---
    Modes of Operation
    ---
    1.  **Automatic Mode (`manual_release=False`)**:
        This is the default behavior. The fork operates independently. When
        the last thread claims its slot, the barrier is immediately released.
        If a controller is present, it will still receive notifications for
        observational purposes.

    2.  **Manual Mode (`manual_release=True`)**:
        In this mode, the fork becomes a controllable primitive. When the last
        thread claims its slot, the fork notifies the controller that its
        threshold has been met (`THRESHOLD_MET`) but **does not** release the
        waiting threads. It holds them until the `SignalController` issues a
        `release` command.

    ---
    Controller Integration
    ---
    When a `SignalController` instance is provided, `SyncSignalFork` will:
    - **Self-Register**: Automatically register itself with the controller on creation.
    - **Expose Commands**: Make methods like `release`, `reset`, and `dispose`
      available for remote invocation via the controller.
    - **Emit Events**: Notify the controller of key lifecycle events:
        - `THRESHOLD_MET`: Fired when all slots are claimed and the fork is ready.
        - `FORK_RELEASED`: Fired when threads are actually unblocked.
        - `FORK_TIMEOUT_FAILURE`: Fired if the barrier times out.
        - `RESET`: Fired when the `reset()` method is called.

    Attributes:
        id (str): The unique ULID identifier for this fork instance.
    """
    __slots__ = [
        "_list_of_forks", "_forks_closed", "_selector_step",
        "_selector_step_counter", "_selector_lock", "_threading_event",
        "_route_count", "_blocked_thread_count", "_id",
        "_timeout_duration", "_timed_out", "_scout",
        # --- Controller integration slots ---
        "_controller", "_manual_release", "_signal_callback"
    ]

    def __init__(
            self,
            number_of_forks: int,
            callables: List[Tuple[int, Callable]],
            selector_step: int = 1,
            timeout_duration: Optional[float] = None,
            controller: Optional['SignalController'] = None,
            manual_release: bool = False,
            signal_callback: Optional[Callable[[str], None]] = None,
    ):
        """Initializes the SyncSignalFork.

        Args:
            number_of_forks (int): The number of callables provided. Must match `len(callables)`.
            callables (List[Tuple[int, Callable]]): A list where each tuple contains
                the usage capacity (int) and the function (Callable) for a fork.
            selector_step (int): The step size for the internal selector to distribute
                threads among available callables. Defaults to 1.
            timeout_duration (Optional[float]): If set, the barrier will time out
                and raise an error if not filled within this many seconds.
            controller (Optional[SignalController]): The controller instance for
                orchestration and eventing.
            manual_release (bool): If True, enables manual mode where a controller
                command is required to release the barrier. Defaults to False.
            signal_callback (Optional[Callable[[str], None]]): A function to call
                just before a thread begins to wait. Typically used to notify a
                controller (e.g., `controller.on_wait_starting`).

        Raises:
            ValueError: If `number_of_forks` doesn't match the length of `callables`,
                or if `timeout_duration` is not a positive number.
            TypeError: If items in `callables` are not valid tuples or if a
                coroutine function is provided.
        """
        super().__init__()

        # --- Input Validation ---
        if number_of_forks != len(callables):
            raise ValueError("The number of forks must match the number of callables.")
        # (Further validation of callables and timeout is assumed)

        # --- Core State ---
        self._threading_event = threading.Event()
        self._list_of_forks: List[ForkUnit] = [
            ForkUnit(fork_callable=fn, usage_cap=cap) for cap, fn in callables
        ]
        self._id = str(ulid.ULID())
        self._forks_closed = False
        self._selector_step = max(1, selector_step)
        self._selector_step_counter = 0
        self._selector_lock = threading.RLock()
        self._blocked_thread_count = 0
        self._detect_number_of_routes()

        # --- Timeout State ---
        self._timeout_duration = timeout_duration
        self._timed_out = False
        self._scout: Optional['Scout'] = None # Manages the timeout logic

        # --- Controller Integration State ---
        self._controller = controller
        self._manual_release = manual_release
        self._signal_callback = signal_callback
        if self._controller:
            try:
                # Attempt to self-register with the provided controller.
                self._controller.register(self)
            except (ValueError, TypeError) as e:
                # Log or handle the case where registration might fail,
                # allowing the fork to still function in a degraded/standalone mode.
                self._controller.logger.warning(
                    f"Failed to register SyncSignalFork {self.id} with controller: {e}"
                )
                pass

    # ---------------------------- #
    #    Controller Integration    #
    # ---------------------------- #

    @property
    def id(self) -> str:
        """Returns the unique, immutable identifier for this fork instance."""
        return self._id

    def _get_object_details(self) -> dict:
        """Provides object metadata and commands for the SignalController.

        This method fulfills the contract required by the `SignalController`
        for registration, allowing it to discover and invoke the fork's commands.

        Returns:
            A dictionary containing the object's name and its command interface.
        """
        return {
            'name': 'sync_signal_fork',
            'commands': {
                'release': self.release,
                'reset': self.reset,
                'is_spent': self.is_spent,
                'get_waiter_count': lambda: self._blocked_thread_count,
                'dispose': self.dispose,
            }
        }

    # ---------------------------- #
    #          Core API            #
    # ---------------------------- #

    def release(self) -> None:
        """Manually releases all waiting threads at the barrier.

        This method is the designated command for the `SignalController` to
        use when the fork is in `manual_release` mode. It has no effect if
        called in automatic mode or before the threshold is met.
        """
        with self._selector_lock:
            # Proceed only if in manual mode and the fork is full.
            if self._manual_release and self._blocked_thread_count >= self._route_count:
                # Check if the event hasn't already been set to avoid redundant notifications.
                if not self._threading_event.is_set():
                    self._forks_closed = True
                    self._threading_event.set()
                    if self._controller:
                        # Notify the controller that the release was successful.
                        self._controller.notify(self.id, "FORK_RELEASED")

    def use_fork(self) -> None:
        """Enters the fork, claims a slot, waits, and executes the callable.

        This is the main entry point for threads using the fork.

        ---
        Workflow
        ---
        1.  **Pre-flight Check**: Validates that the fork is not disposed, timed out,
            or already closed.
        2.  **Claim Slot**: Atomically selects an available `ForkUnit` and
            increments its usage count.
        3.  **Signal Intent**: If a `signal_callback` is provided, it's called
            to notify the controller that this thread is about to wait.
        4.  **Barrier Logic**: The global blocked thread count is incremented.
            If this thread is the last one to arrive:
            a. It notifies the controller that `THRESHOLD_MET`.
            b. In automatic mode, it sets the release event immediately.
            c. In manual mode, it does nothing, deferring release to the controller.
        5.  **Wait**: The thread blocks on an internal event until it's set by
            either automatic release, a manual `release()` command, or `dispose()`.
        6.  **Post-wait Check**: After waking, the thread re-checks for disposal
            or timeout to ensure safe execution.
        7.  **Execute**: The thread finally runs its assigned callable. Any
            exceptions from the callable will propagate.

        Raises:
            RuntimeError: If the fork is disposed, has timed out, is already at
                          capacity, or is disposed while the thread is waiting.
        """
        # Step 1: Pre-flight Check
        if self._disposed or self._timed_out or self._forks_closed:
            if self._disposed: raise RuntimeError("Cannot use a disposed SyncSignalFork.")
            if self._timed_out: raise RuntimeError("SyncSignalFork barrier timed out.")
            raise RuntimeError("All forks are at capacity or the barrier has already closed.")

        # Step 2: Claim Slot
        selected_unit = self._claim_unit()

        # Step 3: Signal Intent to Wait
        if self._signal_callback:
            try:
                self._signal_callback(self.id)
            except Exception as e:
                # Prevent callback failures from crashing the thread.
                if self._controller:
                    self._controller.logger.error(
                        f"Error in signal_callback for {self.id}: {e}", exc_info=True
                    )

        # Step 4: Barrier Logic
        with self._selector_lock:
            self._blocked_thread_count += 1
            is_last_thread = (self._blocked_thread_count >= self._route_count)

            if is_last_thread:
                # The fork is now full and ready.
                if self._controller:
                    self._controller.notify(self.id, "THRESHOLD_MET")

                # Handle release based on the configured mode.
                if not self._manual_release:
                    self._forks_closed = True
                    self._threading_event.set()
                    if self._controller:
                        self._controller.notify(self.id, "FORK_RELEASED")

                # If a Scout is active, wake it immediately since the condition is met.
                if self._scout:
                    with self._scout._condition:
                        self._scout._condition.notify_all()

        # Step 5: Wait
        self._threading_event.wait()

        # Step 6: Post-wait Check
        with self._selector_lock:
            if self._disposed: raise RuntimeError("SyncSignalFork was disposed while waiting.")
            if self._timed_out: raise RuntimeError("SyncSignalFork barrier timed out while waiting.")

        # Step 7: Execute
        selected_unit.fork_callable()

    def reset(self) -> None:
        """Resets the fork's state, allowing it to be used for another cycle.

        This method resets all usage counters, flags, and the internal barrier
        event, making the fork instance reusable. It is thread-safe.
        """
        if self._disposed:
            raise RuntimeError("Cannot reset a disposed SyncSignalFork.")

        with self._selector_lock:
            # Reset all ForkUnits to their initial state.
            for unit in self._list_of_forks:
                with unit.lock:
                    unit.gate_uses = 0
                    unit.gate = False

            # Reset the global state of the fork.
            self._selector_step_counter = 0
            self._blocked_thread_count = 0
            self._forks_closed = False
            self._timed_out = False

            # Clear the event to create a new barrier for the next cycle.
            self._threading_event.clear()

            # Reset the timeout mechanism if it exists.
            if self._scout:
                self._scout.reset()

            # Notify the controller that a reset occurred.
            if self._controller:
                self._controller.notify(self.id, "RESET")

    def is_spent(self) -> bool:
        """Checks if the fork is closed and cannot be used without a reset."""
        return self._forks_closed

    def dispose(self) -> None:
        """Releases all resources, unblocks waiting threads, and makes the fork unusable.

        This method is idempotent, so it is safe to call multiple times.
        """
        if self._disposed:
            return

        with self._selector_lock:
            self._disposed = True
            self._forks_closed = True # Prevent new threads from entering.
            self._threading_event.set() # Unblock any currently waiting threads.

            # Safely dispose of sub-components.
            if self._scout:
                self._scout.dispose()
                self._scout = None

            # Clear internal collections to release memory.
            self._list_of_forks.clear()

            # Detach from the controller to prevent further interaction.
            self._controller = None

    # ---------------------------- #
    #      Internal Helpers        #
    # ---------------------------- #

    def _claim_unit(self) -> ForkUnit:
        """Atomically finds and claims an available slot in a ForkUnit.

        This helper encapsulates the logic for selecting a unit and updating
        its state in a thread-safe manner to prevent race conditions.

        Returns:
            The ForkUnit that was successfully claimed.

        Raises:
            RuntimeError: If no fork units are available.
        """
        while True:
            # Select a candidate unit.
            unit_candidate = self._select_fork_unit_step()
            if unit_candidate is None:
                raise RuntimeError("No available forks to use; all are at capacity.")

            # Attempt to claim the candidate under its own lock.
            with unit_candidate.lock:
                if not unit_candidate.gate:
                    # Success! The slot is ours.
                    unit_candidate.gate_uses += 1
                    if unit_candidate.gate_uses >= unit_candidate.usage_cap:
                        unit_candidate.gate = True # This was the last slot.
                    return unit_candidate
                # If we get here, another thread claimed the last slot in this
                # unit between selection and locking. Loop again to find another.

    def _select_fork_unit_step(self) -> Optional[ForkUnit]:
        """Selects the next potentially available fork unit using a stride.

        This method iterates through the list of forks to find one that is not
        yet full. The starting point of the search is advanced by `_selector_step`
        on each successful claim to help distribute threads more evenly under load.

        Returns:
            An available ForkUnit, or None if all are full.
        """
        if self._forks_closed:
            return None

        length = len(self._list_of_forks)
        # Reading the counter is thread-safe, but we lock to update it.
        with self._selector_lock:
            start_index = self._selector_step_counter % length

        # Scan all units starting from the current index.
        for offset in range(length):
            current_index = (start_index + offset) % length
            unit = self._list_of_forks[current_index]

            # Check the gate under the unit's lock to avoid a race condition.
            with unit.lock:
                if not unit.gate:
                    # Found an available unit. Update the global counter for the next thread.
                    with self._selector_lock:
                        self._selector_step_counter = (current_index + self._selector_step)
                    return unit

        # If we complete the loop, all units are full.
        self._forks_closed = True
        return None

    def _detect_number_of_routes(self) -> None:
        """Calculates the total number of execution slots across all fork units."""
        self._route_count = sum(unit.usage_cap for unit in self._list_of_forks)