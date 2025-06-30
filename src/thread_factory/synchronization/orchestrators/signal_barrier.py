import threading
from typing import Optional, Callable, List, Union
import ulid
from thread_factory.utils import IDisposable, Group

class SignalBarrier(IDisposable):
    """
    SignalBarrier
    -------------
    A coordinated, multi-group thread barrier that integrates **event-driven callable execution**
    with traditional threshold-based synchronization.

    Each thread belongs to a named `Group`. When enough threads (defined by `threshold`) arrive
    at a group, that group is marked **ready**. Once all groups are ready, the barrier releases
    all waiting threads.

    It's best to use a shared context object to pass data between callables assigned
    to different groups, as the barrier does not manage data flow between them.
    You would generally use this class when you want to coordinate state between
    stages of work.

    🔧 Group-Triggered Callables
    ----------------------------
    Each `Group` can register one or more **callables**. When the group reaches readiness:

    • One thread (the completer) executes all associated callables.
    • The return values or exceptions are stored in outcome holders.
    • These can be used to track logging, state transitions, progress updates, or broadcast signals.
    • This execution is **transit-based**, not polling: it happens once, on group completion.

    🧵 Barrier Thread Behavior
    --------------------------
    • Threads call `wait(group_index)` and block until barrier release.
    • Barrier releases when all groups are ready.
    • If `manual_release=True`, release must be explicitly triggered via `release()`.

    🔁 Reusability
    -------------
    • If `reusable=True`, the barrier resets automatically after all threads exit.
    • Supports repeated coordination cycles (generations).

    ✅ Use Cases
    -----------
    • Multi-phase thread orchestration.
    • Per-group transition logging or checkpointing.
    • Coordinated work loop where signal transit should fire exactly once per group.
    """
    __slots__ = IDisposable.__slots__ + [
        "_id", "groups", "_enabled", "reusable", "manual_release",
        "_lock", "_condition", "_released"
    ]

    def __init__(
            self,
            groups: Optional[List[Group]] = None,
            reusable: bool = False,
            manual_release: bool = False
    ):
        super().__init__()
        self._id = str(ulid.ULID())
        self.groups = groups if groups is not None else []
        self._enabled = bool(groups)
        self.reusable = reusable
        self.manual_release = manual_release
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._released = False

    def dispose(self):
        """
        Disposes of the barrier and all associated groups, releasing waiting threads.
        Once disposed, the object cannot be reused.
        """
        if self._disposed:
            return

        with self._condition:
            self._disposed = True
            if self.groups:
                for group in self.groups:
                    group.dispose()
                self.groups.clear()

            self._released = True
            self._condition.notify_all()

    def add_group(self, threshold: int, tasks: Optional[Union[Callable, List[Callable]]] = None):
        """
        Adds a data-aware group to the barrier before it is enabled.

        Args:
            threshold (int): Number of threads required for the group to be 'ready'.
            tasks (Optional): A function or list of functions to be executed
                              when the group's threshold is reached.
        """
        if self._enabled:
            raise RuntimeError("Cannot add groups after the barrier is enabled.")
        self.groups.append(Group(threshold, tasks))

    def enable(self):
        """
        Enables the barrier. Must be called if no groups were passed to the constructor.
        """
        if self._enabled:
            return
        if not self.groups:
            raise ValueError("Cannot enable the barrier with no groups added.")
        self._enabled = True

    def release(self):
        """
        Manually releases the barrier if all groups are ready.
        Only effective when `manual_release=True`.
        """
        with self._condition:
            if self._disposed: return
            if self.manual_release and not self._released and all(g.ready for g in self.groups):
                self._released = True
                self._condition.notify_all()

    def wait(self, group_index: int, timeout: Optional[float] = None) -> bool:
        """
        A thread calls this to wait until the barrier is released. When its group's
        threshold is met, that group's tasks are executed by the completing thread.

        Args:
            group_index (int): Index of the group this thread belongs to.
            timeout (float, optional): Timeout in seconds.

        Returns:
            bool: True if released successfully, False if disposed or timed out.
        """
        if not self._enabled:
            raise RuntimeError("SignalBarrier not enabled. Call enable() or provide groups.")

        group = self.groups[group_index]
        with self._condition:
            if self._disposed:
                return False

            group.count += 1

            # If this thread completes the group, it becomes responsible for running the tasks.
            if group.count == group.threshold and not group.ready:
                group.ready = True

                # Execute all tasks associated with this group
                for i, task in enumerate(group.tasks):
                    outcome = group.outcomes[i]
                    try:
                        result = task()
                        outcome.set_result(result)
                    except Exception as e:
                        outcome.set_exception(e)

            # Check if all groups are now ready to globally release the barrier
            if all(g.ready for g in self.groups) and not self.manual_release:
                self._released = True
                self._condition.notify_all()

            # Wait for the global release signal (_released = True)
            released = self._condition.wait_for(lambda: self._released or self._disposed, timeout=timeout)

            # If reusable, decrement count and reset states as threads exit
            if released and self.reusable:
                group.count -= 1
                # If this was the last thread to exit the group, reset the group
                if group.count == 0:
                    group.reset()

                # If all threads from all groups have exited, reset the barrier
                if all(g.count == 0 for g in self.groups):
                    self._released = False

            return released and not self._disposed

    # Other helper methods from your original class
    def get_group_index(self, match: Callable[[Group], bool]) -> int:
        for i, g in enumerate(self.groups):
            if match(g):
                return i
        raise ValueError("No group matched the provided condition.")

    def notify_all_override(self):
        with self._condition:
            if self._disposed: return
            self._released = True
            for g in self.groups:
                g.ready = True
            self._condition.notify_all()

    def is_spent(self) -> bool:
        return self._released and not self.reusable