import threading
import time
from typing import Optional, Callable, List
from thread_factory.utils import IDisposable, Group


class SynchronizedSignalBarrier(IDisposable):
    """
    SynchronizedSignalBarrier
    -------------
    A coordinated multi-group barrier that blocks threads until each group meets
    its own threshold. Once all groups are "ready", the barrier releases all waiting
    threads. Reusability and manual release modes are also supported.
    """

    def __init__(
            self,
            groups: Optional[List[Group]] = None,
            reusable: bool = False,
            manual_release: bool = False,
            timeout: Optional[float] = None
    ):
        super().__init__()
        self.groups = groups if groups is not None else []
        self._enabled = False
        self.reusable = reusable
        self.manual_release = manual_release
        self.timeout = timeout
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._released = False
        self._start_time = None
        self._broken = False
        self._waiting_threads = 0

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        with self._condition:
            self._broken = True
            self._released = True
            self._condition.notify_all()

    def get_group_index(self, match: Callable[[Group], bool]) -> int:
        for i, g in enumerate(self.groups):
            if match(g):
                return i
        raise ValueError("No group matched the provided condition.")

    def add_group(self, threshold: int, callback: Optional[Callable] = None):
        if self._enabled:
            raise RuntimeError("Cannot add groups after enable()")
        self.groups.append(Group(threshold, callback))

    def enable(self):
        if self._enabled:
            return
        if not self.groups:
            raise ValueError("No groups to enable.")
        self._enabled = True

    def release(self):
        with self._condition:
            if self._disposed:
                return
            if self.manual_release and not self._released and all(g.ready for g in self.groups):
                self._released = True
                self._condition.notify_all()

    def wait(self, group_index: int) -> bool:
        if not self._enabled:
            raise RuntimeError("SynchronizedSignalBarrier not enabled. Call enable() or provide groups.")

        group = self.groups[group_index]
        with self._condition:
            if self._disposed or self._broken:
                return False

            if self._start_time is None:
                self._start_time = time.monotonic()

            self._waiting_threads += 1
            group.count += 1

            if group.count >= group.threshold and not group._released_once:
                group.ready = True
                group._released_once = True
                if group.callback:
                    try:
                        group.callback()
                    except Exception:
                        pass

            if all(g.ready for g in self.groups) and not self.manual_release:
                self._released = True
                self._condition.notify_all()

            remaining = self.timeout
            if self.timeout is not None:
                elapsed = time.monotonic() - self._start_time
                if elapsed >= self.timeout:
                    self._broken = True
                else:
                    remaining = self.timeout - elapsed

            if self._broken:
                self._released = True
                self._condition.notify_all()

            released = self._condition.wait_for(
                lambda: self._released or self._disposed,
                timeout=remaining
            )

            self._waiting_threads -= 1

            if not released and not self._disposed:
                self._broken = True
                self._released = True
                self._condition.notify_all()

            if self._broken:
                return False

            # FIX: The reusability logic is now cleaner.
            # The last thread of a wave to leave the barrier is responsible for
            # triggering the reset for the next wave.
            if self.reusable and self._waiting_threads == 0:
                self.reset()

            return released and not self._disposed

    def notify_all_override(self):
        with self._condition:
            if self._disposed:
                return
            self._released = True
            for g in self.groups:
                g.ready = True
            self._condition.notify_all()

    def is_spent(self) -> bool:
        return self._released and not self.reusable

    def reset(self):
        """
        Resets the barrier state. This is the single source of truth for resetting.
        """
        # This method is only ever called from wait() or externally,
        # so it's assumed to be entered with the lock already held if needed.
        self._released = False
        self._broken = False
        self._start_time = None
        for group in self.groups:
            group.ready = False
            group.count = 0
            group._released_once = False