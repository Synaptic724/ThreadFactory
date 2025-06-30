from typing import Callable, List, Optional
import threading
from thread_factory.synchronization import MultiConductor, Dynaphore, SignalBarrier, Conductor
from thread_factory.utils import IDisposable, RouterGroup, Group


class Router(IDisposable):
    """
    Router
    ------
    A streamlined phase-driven thread coordinator.

    - Threads are routed through a sequence of synchronized phases (groups).
    - Each phase uses a Dynaphore to select a 'leader' and a SignalBarrier to
      synchronize all participating threads.
    - Actions are executed once the group is synchronized.

    Parameters:
        sync (bool): If True, all threads in the group will run the group's actions.
                     If False, only the phase leader executes the actions.
        stop_on_exception (bool): If True, halts execution after the first error.
    """

    def __init__(
            self,
            groups: Optional[List[RouterGroup]] = None,
            *,
            sync: bool = False,
            stop_on_exception: bool = False
    ):
        super().__init__()
        self._lock = threading.RLock()
        self._groups: List[RouterGroup] = groups or []
        self._enabled = bool(groups)
        self.sync = sync
        self.stop_on_exception = stop_on_exception
        self._dynaphore = Dynaphore(1)
        self._exceptions: List[Exception] = []

        # Internal state for phase management
        self._current_group_index = -1  # Start at -1, so the first group is 0
        self._dynaphore: Optional[Dynaphore] = None
        self._barrier: Optional[SignalBarrier] = None
        self._total_threads_in_phase = 0

        # Pre-create all synchronization primitives
        self._phase_dynaphores: List[Dynaphore] = []
        self._phase_barriers: List[SignalBarrier] = []
        self._initializer: bool = False
        if self._groups:
            self._pre_create_primitives()
            self._enabled = True

    def _pre_create_primitives(self):
        """
        Creates all Dynaphore and SignalBarrier instances upfront for each phase.
        """
        for group in self._groups:
            # Create a Dynaphore for each phase, allowing one permit for the leader
            self._phase_dynaphores.append(Dynaphore(group.threshold))

    def add_group(self, group: RouterGroup):
        """
        Adds a group to the router before it is enabled.
        """
        if self._enabled:
            raise RuntimeError("Cannot add group after router is enabled.")
        self._groups.append(group)

    def enable(self):
        """
        Enables the router and prepares all synchronization primitives.
        """
        with self._lock:
            if self._enabled:
                return
            if not self._groups:
                raise ValueError("No groups to enable.")

            self._pre_create_primitives()
            self._enabled = True
            self._current_group_index = 0  # Start at the first group

    def run(self, group_index: int) -> bool:
        """
        Coordinates a thread's entry into a specific phase (group).

        Args:
            group_index (int): The index of the group the thread belongs to for this run.

        Returns:
            bool: True if the thread completed its run in the phase, False otherwise.
        """
        if not self._enabled:
            # This is a critical check; prevent execution if not enabled
            raise RuntimeError("Router is not enabled. Call enable() first.")

        # Check if the thread is meant for the current active phase
        if not self._initializer:
            with self._dynaphore:
                if not self._initializer:
                    current_phase_index = self._current_group_index
                    if group_index != current_phase_index:
                        # If the thread is not for the current phase, it waits
                        # until the router progresses to its phase.
                        # A more advanced design would use a condition variable here to wait.
                        # For this implementation, we simply return False.
                        # A thread from a future phase should not be able to "jump the queue."
                        return False

                    if current_phase_index >= len(self._groups):
                        # All phases are complete
                        return False

                    # Get the correct primitives for this phase
                    group = self._groups[current_phase_index]
                    dynaphore = self._phase_dynaphores[current_phase_index]
                    barrier = self._phase_barriers[current_phase_index]
                    self._initializer = True
                    dynaphore.increase_permits(self._groups[current_phase_index].threshold)

        # PHASE 1: Acquire permit from Dynaphore (Phase Leader)
        # This will block all threads except the first one to enter this phase.
        is_leader = dynaphore.wait_for_permit()

        # PHASE 2: Wait on the SignalBarrier for all threads to synchronize
        # Note: The barrier will internally handle the group threshold and ready state.
        if not barrier.wait(group_index=0):  # SignalBarrier has only one group
            # Barrier was disposed or timed out
            return False

        # PHASE 3: Execute actions
        should_run_actions = self.sync or is_leader

        if should_run_actions:
            try:
                for action in group.actions:
                    action()
            except Exception as e:
                with self._lock:
                    self._exceptions.append(e)
                if self.stop_on_exception:
                    # On exception, dispose the router to unblock other threads
                    self.dispose()
                    return False

        # After execution, the phase leader releases its permit so the next phase can start.
        # This is a crucial step that was missing.
        if is_leader:
            dynaphore.release_permit()

        # PHASE 4: Transition to the next phase
        # This state change must be protected by a lock to avoid race conditions.
        # We need to know when all threads have finished the current phase before moving on.
        with self._lock:
            self._total_threads_in_phase += 1
            if self._total_threads_in_phase >= group.threshold:
                # This check ensures that the router moves to the next phase
                # only after all threads for the current phase have completed.
                self._current_group_index += 1
                self._total_threads_in_phase = 0

        return True

    def join(self):
        """
        Collects and raises any exceptions that occurred during execution.
        """
        if self._exceptions:
            raise RuntimeError(f"Router encountered exceptions: {self._exceptions}")

    def dispose(self):
        """
        Disposes of the router and all its internal synchronization primitives.
        """
        if self._disposed:
            return
        self._disposed = True

        # Dispose all pre-created primitives
        for dyn in self._phase_dynaphores:
            if dyn:
                dyn.dispose()
        for barrier in self._phase_barriers:
            if barrier:
                barrier.dispose()

        with self._lock:
            self._exceptions.clear()
            self._groups.clear()
            self._phase_dynaphores.clear()
            self._phase_barriers.clear()
            self._current_group_index = -1
            self._enabled = False
            self._total_threads_in_phase = 0