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
            timeout: Optional[float] = None,
            raise_on_timeout: bool = False
    ):
        """
        Initializes the SynchronizedSignalBarrier.

        Args:
            groups (Optional[List[Group]]): A list of Group objects, each with a threshold.
            reusable (bool): If True, the barrier resets after all threads are released.
            manual_release (bool): If True, the barrier only releases when the release() method is called.
            timeout (Optional[float]): The maximum time in seconds to wait for all groups to be ready.
        """
        super().__init__()
        # List of groups to coordinate. Each group has its own threshold.
        self.groups = groups if groups is not None else []

        # Internal state flags.
        self._enabled = False  # True after enable() is called.
        self.reusable = reusable  # Controls automatic reset.
        self.manual_release = manual_release  # Controls manual release mode.
        self.timeout = timeout  # Timeout for the barrier to release.
        self.raise_on_timeout = raise_on_timeout  # If True, raises an exception on timeout.
        self._internal_raised = False  # Internal flag to track if an exception was raised.

        # Synchronization primitives.
        self._lock = threading.Lock()  # A lock to protect shared state.
        self._condition = threading.Condition(self._lock)  # The condition variable used to block/unblock threads.

        # Barrier state variables.
        self._released = False  # True when the barrier has been released (e.g., all threads can pass).
        self._start_time = None  # Time when the first thread entered the barrier.
        self._broken = False  # True if the barrier is in a broken state (e.g., due to timeout or dispose).
        self._waiting_threads = 0  # Counter for the number of threads currently waiting in the barrier.

    def dispose(self):
        """
        Disposes of the barrier, releasing all waiting threads and preventing further use.
        """
        if self._disposed:
            return
        self._disposed = True  # Mark the object as disposed.

        with self._condition:
            # Set the broken and released flags to wake up all waiting threads.
            self._broken = True
            self._released = True
            self._condition.notify_all()  # Wake up all threads waiting on the condition.

    def get_group_index(self, match: Callable[[Group], bool]) -> int:
        """
        Finds the index of a group that matches a given condition.

        Args:
            match (Callable[[Group], bool]): A function that returns True if a group matches.

        Returns:
            int: The index of the first matching group.

        Raises:
            ValueError: If no group is found that matches the condition.
        """
        for i, g in enumerate(self.groups):
            if match(g):
                return i
        raise ValueError("No group matched the provided condition.")

    def add_group(self, threshold: int, callback: Optional[Callable] = None):
        """
        Adds a new group to the barrier. Must be called before enable().

        Args:
            threshold (int): The number of threads required for this group to be ready.
            callback (Optional[Callable]): A function to be called when this group's threshold is met.
        """
        if self._enabled:
            raise RuntimeError("Cannot add groups after enable()")
        self.groups.append(Group(threshold, callback))

    def enable(self):
        """
        Enables the barrier for use. Must be called after all groups have been added.
        """
        if self._enabled:
            return
        if not self.groups:
            raise ValueError("No groups to enable.")
        self._enabled = True

    def release(self):
        """
        Manually releases the barrier. Only effective in manual_release mode.
        """
        with self._condition:
            if self._disposed:
                return
            # Check if in manual mode, not already released, and all groups are ready.
            if self.manual_release and not self._released and all(g.ready for g in self.groups):
                self._released = True
                self._condition.notify_all()  # Release all waiting threads.

    def wait(self, group_index: int) -> bool:
        """
        Blocks the calling thread until all groups meet their thresholds or a timeout occurs.

        Args:
            group_index (int): The index of the group this thread belongs to.

        Returns:
            bool: True if the barrier was released successfully, False if it was broken or disposed.

        Raises:
            TimeoutError: If raise_on_timeout is True and a timeout occurs.
            RuntimeError: If the barrier is not enabled.
        """
        # Barrier must be enabled before any thread can wait on it.
        if not self._enabled:
            raise RuntimeError("SynchronizedSignalBarrier not enabled. Call enable() or provide groups.")

        group = self.groups[group_index]
        with self._condition:
            # --- Check 1: Handle threads arriving after the barrier is broken or disposed.
            if self._disposed:
                return False
            if self._broken:
                if self.raise_on_timeout:
                    # Raise for threads arriving late.
                    raise TimeoutError("Barrier is already broken due to a previous timeout.")
                else:
                    return False

            # Set the start time when the very first thread enters the barrier.
            if self._start_time is None:
                self._start_time = time.monotonic()

            # Increment the total waiting threads and the group's count.
            self._waiting_threads += 1
            group.count += 1

            # Check if this group has met its threshold for the first time.
            if group.count >= group.threshold and not group._released_once:
                group.ready = True
                group._released_once = True
                if group.callback:
                    try:
                        group.callback()
                    except Exception:
                        pass

            # Check if ALL groups are ready and we are not in manual release mode.
            if all(g.ready for g in self.groups) and not self.manual_release:
                self._released = True
                self._condition.notify_all()

            # Calculate the remaining timeout duration.
            remaining = self.timeout
            if self.timeout is not None:
                elapsed = time.monotonic() - self._start_time
                if elapsed >= self.timeout:
                    # The barrier has already timed out before this thread even waits.
                    remaining = 0
                else:
                    remaining = self.timeout - elapsed

            # If the barrier is already broken, release everyone.
            if self._broken:
                self._released = True
                self._condition.notify_all()

            # Wait for the barrier to be released or for a timeout to occur.
            released = self._condition.wait_for(
                lambda: self._released or self._disposed,
                timeout=remaining
            )

            # Decrement the waiting thread counter after waking up.
            self._waiting_threads -= 1

            # --- Check 2: This is the code for the thread that actually times out.
            if not released and not self._disposed:
                self._broken = True
                self._released = True
                self._condition.notify_all()
                if self.raise_on_timeout:
                    # This thread is the one that failed the deadline.
                    raise TimeoutError("Barrier wait timed out.")

            # --- Check 3: Final state check for all threads leaving the barrier.
            # If the barrier is broken, the thread should not be considered successfully released.
            if self._broken:
                return False

            # If the barrier is reusable and this is the last thread to leave, reset it for the next wave.
            if self.reusable and self._waiting_threads == 0:
                self.reset()

            # Return True if the thread was released successfully, False otherwise.
            return released and not self._disposed


    def notify_all_override(self):
        """
        Forces the barrier to release all waiting threads, regardless of thresholds.
        This is a hard override.
        """
        with self._condition:
            if self._disposed:
                return
            self._released = True
            # Mark all groups as ready so the `all()` check passes for future threads.
            for g in self.groups:
                g.ready = True
            self._condition.notify_all()  # Wake up all threads.

    def is_spent(self) -> bool:
        """
        Checks if the barrier has been released and is not reusable.
        A spent barrier cannot be used again without a reset.
        """
        return self._released and not self.reusable

    def reset(self):
        """
        Resets the barrier state. This is the single source of truth for resetting.
        This method should be called with the condition lock held if called internally.
        """
        # The lock is acquired by the caller (e.g., from `wait`).
        # This is a critical section.
        self._released = False
        self._broken = False
        self._start_time = None
        for group in self.groups:
            group.ready = False
            group.count = 0
            group._released_once = False