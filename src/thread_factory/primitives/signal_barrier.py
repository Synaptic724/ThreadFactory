import threading
from typing import Optional, Callable, List
from thread_factory.utils import IDisposable, Group


class SignalBarrier(IDisposable):
    """
    SignalBarrier
    -------------
    A coordinated multi-group barrier that blocks threads until each group meets
    its own threshold. Once all groups are "ready", the barrier releases all waiting
    threads. Reusability and manual release modes are also supported.

    Key Features:
    - Thread groups are independently tracked by threshold.
    - Supports per-group callbacks once a group is ready.
    - Global release occurs only when all groups are ready.
    - Reusable mode resets after all threads exit.
    - Manual release defers release until `release()` is explicitly called.
    - Disposable for safe shutdown.

    Parameters:
        groups (List[Group]): List of group configurations (thresholds + callbacks).
        reusable (bool): If True, resets barrier after release.
        manual_release (bool): If True, requires `release()` call after all groups are ready.
    """

    def __init__(
        self,
        groups: Optional[List[Group]] = None,
        reusable: bool = False,
        manual_release: bool = False
    ):
        super().__init__()
        self.groups = groups if groups is not None else []     # List of Group objects managing thresholds
        self._enabled = bool(groups)                           # Auto-enable if groups are pre-supplied
        self.reusable = reusable                               # Determines if barrier resets after release
        self.manual_release = manual_release                   # If True, requires explicit call to `release()`
        self._lock = threading.Lock()                          # Lock for thread-safe operations
        self._condition = threading.Condition(self._lock)      # Condition variable for thread coordination
        self._released = False                                 # Tracks global barrier release state

    def dispose(self):
        """
        Terminates the barrier and releases all waiting threads immediately.
        Once disposed, the object cannot be reused.
        """
        if self._disposed:
            return
        self._disposed = True
        with self._condition:
            self._released = True
            self._condition.notify_all()

    def get_group_index(self, match: Callable[[Group], bool]) -> int:
        """
        Dynamically retrieves the index of the first group matching a condition.

        Args:
            match (Callable): A predicate that returns True for the matching group.

        Returns:
            int: The index of the matched group.

        Raises:
            ValueError: If no matching group is found.
        """
        for i, g in enumerate(self.groups):
            if match(g):
                return i
        raise ValueError("No group matched the provided condition.")

    def add_group(self, threshold: int, callback: Optional[Callable] = None):
        """
        Adds a group to the barrier before it is enabled.

        Args:
            threshold (int): Number of threads required to mark the group as 'ready'.
            callback (Callable, optional): Called when the group's threshold is reached.

        Raises:
            RuntimeError: If called after the barrier is enabled.
        """
        if self._enabled:
            raise RuntimeError("Cannot add groups after enable()")
        self.groups.append(Group(threshold, callback))

    def enable(self):
        """
        Enables the barrier. Must be called if no groups were passed to constructor.

        Raises:
            ValueError: If no groups were added before enabling.
        """
        if self._enabled:
            return
        if not self.groups:
            raise ValueError("No groups to enable.")
        self._enabled = True

    def release(self):
        """
        Manually releases the barrier after all groups are marked ready.
        Only applicable when `manual_release=True`.
        """
        with self._condition:
            if self._disposed:
                return
            if self.manual_release and not self._released and all(g.ready for g in self.groups):
                self._released = True
                self._condition.notify_all()

    def wait(self, group_index: int, timeout: Optional[float] = None) -> bool:
        """
        Waits until the barrier is released. Threads are grouped via `group_index`.

        - If a group's threshold is met, its `callback` is triggered.
        - Barrier is released when *all groups* are ready.
        - If `manual_release=True`, barrier will only release after `release()` is called.

        Args:
            group_index (int): Index of the group this thread belongs to.
            timeout (float, optional): Timeout in seconds.

        Returns:
            bool: True if released successfully, False if disposed or timed out.

        Raises:
            RuntimeError: If `enable()` hasn't been called.
        """
        if not self._enabled:
            raise RuntimeError("SignalBarrier not enabled. Call enable() or provide groups.")

        group = self.groups[group_index]
        with self._condition:
            if self._disposed:
                return False

            group.count += 1

            if group.count == group.threshold and not group._released_once:
                group.ready = True
                group._released_once = True
                if group.callback:
                    try:
                        group.callback()
                    except Exception:
                        pass  # Do not let callback failures halt barrier logic

            if all(g.ready for g in self.groups) and not self.manual_release:
                self._released = True
                self._condition.notify_all()

            released = self._condition.wait_for(lambda: self._released or self._disposed, timeout=timeout)

            # Reset logic if reusable
            if released and self.reusable:
                group.count -= 1
                if group.count == 0:
                    group.ready = False
                    group._released_once = False
                if all(g.count == 0 for g in self.groups):
                    self._released = False

            return released and not self._disposed

    def notify_all_override(self):
        """
        Immediately overrides group readiness and releases all waiting threads.

        - Marks all groups as ready
        - Sets `_released = True`
        - Notifies all threads

        Useful for shutdown, testing, or admin overrides.
        """
        with self._condition:
            if self._disposed:
                return
            self._released = True
            for g in self.groups:
                g.ready = True
            self._condition.notify_all()

    def is_spent(self) -> bool:
        """
        Checks if the barrier has released and is no longer reusable.

        Returns:
            bool: True if the barrier has completed and won't reset.
        """
        return self._released and not self.reusable
