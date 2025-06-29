import threading
import time
from typing import Any, Callable, List, Optional
from thread_factory.utils import Group, IDisposable


class MultiConductor(IDisposable):
    """A coordinated, multi-group conductor that synchronizes threads and runs tasks.

    The MultiConductor manages multiple `Group` objects, each with its own
    thread threshold and list of tasks. As each group's threshold is met,
    its specific tasks are executed and their outcomes are captured.

    Once ALL managed groups are "ready", the MultiConductor performs a global
    release, unblocking all threads that are waiting on it.

    This is ideal for complex, phased startup sequences where different
    sub-systems (groups) need to complete their own setup tasks before the
    main application logic proceeds.

    Usage Example:
        # Group for database connections
        db_group = Group(threshold=2, tasks=[lambda: "db_init_ok"])
        # Group for API connections
        api_group = Group(threshold=3, tasks=[lambda: "api_init_ok"])

        conductor = MultiConductor(groups=[db_group, api_group])

        def db_worker():
            print("DB worker waiting...")
            conductor.wait(0)
            print("DB worker released!")

        def api_worker():
            print("API worker waiting...")
            conductor.wait(1)
            print("API worker released!")

        # Start 2 DB workers and 3 API workers
        threads = [threading.Thread(target=db_worker) for _ in range(2)]
        threads += [threading.Thread(target=api_worker) for _ in range(3)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        print(f"DB Group results: {db_group.results}")
        print(f"API Group results: {api_group.results}")
    """
    __slots__ = IDisposable.__slots__ + [
        "groups", "reusable", "manual_release", "timeout", "raise_on_timeout",
        "_enabled", "_lock", "_condition", "_released", "_start_time",
        "_broken", "_total_waiting_threads"
    ]

    def __init__(
            self,
            groups: Optional[List[Group]] = None,
            reusable: bool = False,
            manual_release: bool = False,
            timeout: Optional[float] = None,
            raise_on_timeout: bool = False
    ):
        """Initializes the MultiConductor.

        Args:
            groups (Optional[List[Group]]): A list of pre-configured Group
                objects to manage.
            reusable (bool): If True, the conductor and all its groups will
                reset after all threads from a cycle have passed.
            manual_release (bool): If True, waits for an explicit `release()`
                call even after all groups are ready.
            timeout (Optional[float]): A global timeout in seconds. If not all
                groups become ready in this time, the conductor breaks.
            raise_on_timeout (bool): If True, raises `TimeoutError` on timeout.
        """
        super().__init__()
        self.groups: List[Group] = groups if groups is not None else []
        self.reusable = reusable
        self.manual_release = manual_release
        self.timeout = timeout
        self.raise_on_timeout = raise_on_timeout

        self._enabled = bool(self.groups)
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._released = False
        self._start_time = None
        self._broken = False
        self._total_waiting_threads = 0

    @property
    def all_outcomes(self) -> List['Outcome']:
        """A convenience property to get a flat list of all outcomes from all groups."""
        if self.disposed: return []
        return [outcome for group in self.groups for outcome in group.outcomes]

    def dispose(self):
        """Disposes of the MultiConductor and cascades disposal to all its Groups."""
        if self.disposed: return
        with self._condition:
            self._disposed = True
            for group in self.groups:
                group.dispose()
            self.groups.clear()
            self._broken = True
            self._released = True
            self._condition.notify_all()

    def add_group(self, group: Group):
        """Adds a new, pre-configured Group to the conductor.

        This must be called before the conductor is enabled via `enable()`.

        Args:
            group (Group): The Group instance to add.

        Raises:
            RuntimeError: If called after the conductor is enabled.
            TypeError: If the provided object is not a Group instance.
        """
        if self._enabled:
            raise RuntimeError("Cannot add groups after MultiConductor is enabled.")
        if not isinstance(group, Group):
            raise TypeError("Only Group objects can be added.")
        self.groups.append(group)

    def enable(self):
        """Enables the MultiConductor, preventing further groups from being added."""
        if self._enabled: return
        if not self.groups:
            raise ValueError("Cannot enable with no groups.")
        self._enabled = True

    def release(self):
        """Manually releases the conductor.

        This is only effective when `manual_release=True` and all groups have
        already met their respective thresholds.
        """
        with self._condition:
            if self.disposed: return
            if self.manual_release and not self._released and all(g.ready for g in self.groups):
                self._released = True
                self._condition.notify_all()

    def wait(self, group_index: int) -> bool:
        """Blocks the calling thread until all groups are ready and releases.

        As soon as this thread's group meets its threshold, its tasks are
        executed. The thread will then continue to block until ALL groups are ready.

        Args:
            group_index (int): The index of the group this thread belongs to.

        Returns:
            bool: `True` for a successful release, `False` otherwise (timeout,
                disposed, or broken by an override).

        Raises:
            RuntimeError: If called before `enable()`.
            IndexError: If `group_index` is out of bounds.
        """
        if not self._enabled:
            raise RuntimeError("MultiConductor not enabled.")

        # This will raise IndexError for invalid indices, which is appropriate.
        group = self.groups[group_index]
        with self._condition:
            # Check for terminal states first.
            if self.disposed or self._broken: return False

            if self._start_time is None: self._start_time = time.monotonic()

            self._total_waiting_threads += 1
            group.count += 1

            # If this thread's arrival makes its group ready, execute the group's tasks.
            # This block runs only once per group, per cycle.
            if group.count >= group.threshold and not group.ready:
                group.ready = True
                # The thread completing the group is responsible for running its tasks.
                for task, outcome in zip(group.tasks, group.outcomes):
                    try:
                        result = task()
                        outcome.set_result(result)
                    except Exception as e:
                        outcome.set_exception(e)

            # Check if ALL groups are now ready, which triggers the global release.
            if all(g.ready for g in self.groups) and not self.manual_release:
                self._released = True
                self._condition.notify_all()

            # Wait until the global release is signaled or a failure occurs.
            remaining_time = None
            if self.timeout is not None:
                elapsed = time.monotonic() - self._start_time
                remaining_time = max(0, self.timeout - elapsed)

            was_released = self._condition.wait_for(
                lambda: self._released or self._disposed or self._broken,
                timeout=remaining_time
            )

            # --- CRITICAL SECTION FOR RACE-CONDITION-SAFE REUSABILITY ---
            # Capture the "broken" state AT THIS MOMENT, before any reset logic runs.
            is_broken_on_exit = self._broken

            # If the wait ended due to a timeout, break the barrier for everyone.
            if not was_released and not self.disposed:
                self._broken = True
                self._released = True
                self._condition.notify_all()
                if self.raise_on_timeout:
                    raise TimeoutError("MultiConductor wait timed out.")

            # This thread is now leaving the wait block.
            self._total_waiting_threads -= 1

            # In reusable mode, reset only when the VERY LAST thread from ALL groups has exited.
            if self.reusable and self._total_waiting_threads == 0 and self._released:
                self.reset()

            # The final return value depends on the captured "broken" state to avoid race conditions.
            return was_released and not self.disposed and not is_broken_on_exit

    def reset(self):
        """Resets the conductor and all its groups for another cycle.

        This method is for internal use by the `reusable` mode logic.
        """
        self._released = False
        self._broken = False
        self._start_time = None
        # Cascade the reset to all contained groups.
        for group in self.groups:
            group.reset()