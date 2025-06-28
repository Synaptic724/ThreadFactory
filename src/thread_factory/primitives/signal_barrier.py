import threading
from typing import Optional, Callable, List
from thread_factory.utils import IDisposable


class Group:
    """
    Group
    -----
    Represents a subgroup of threads within the SignalBarrier.

    Each group tracks:
    - A `threshold` (number of threads needed to mark the group as ready)
    - A `callback` to be triggered when the group becomes ready
    - A live `count` of threads that have entered the group
    - A `ready` flag to indicate the group has satisfied its threshold
    """

    def __init__(self, threshold: int, callback: Optional[Callable[[], None]] = None):
        self.threshold = threshold
        self.callback = callback
        self.count = 0
        self.ready = False


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
        groups: List[Group],
        reusable: bool = False,
        manual_release: bool = False
    ):
        super().__init__()
        self.groups = groups
        self.reusable = reusable
        self.manual_release = manual_release
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._released = False

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

        Parameters:
            group_index (int): Index of the group this thread belongs to.
            timeout (float, optional): Timeout in seconds.

        Returns:
            bool: True if successfully released, False if disposed or timed out.
        """
        group = self.groups[group_index]
        with self._condition:
            if self._disposed:
                return False

            # Count the thread in its group
            group.count += 1

            # If group threshold met, mark ready and trigger callback
            if group.count == group.threshold:
                group.ready = True
                if group.callback:
                    try:
                        group.callback()
                    except Exception:
                        pass  # Callback failures are non-fatal

            # If all groups are ready and not using manual release, release all
            if all(g.ready for g in self.groups) and not self.manual_release:
                self._released = True
                self._condition.notify_all()

            # Wait for either a release or a dispose event
            released = self._condition.wait_for(lambda: self._released or self._disposed, timeout=timeout)

            # Reset if reusable and this thread was released
            if released and self.reusable:
                group.count -= 1
                if group.count == 0:
                    group.ready = False
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
        Returns:
            bool: True if the barrier has released and is not reusable.
        """
        return self._released and not self.reusable
