import threading
import time
from typing import List, Optional, Callable
from thread_factory.primitives.threshold_semaphore import ThresholdSemaphore

class Router:
    """
    RouterNode
    -----------
    A dynamic routing structure that coordinates groups of threads according to a policy-based threshold model.

    Each node executes groups of tasks based on availability and declared thresholds.
    Can be chained or repeated to simulate graph-like execution.
    """

    def __init__(
        self,
        groups: List[RoutedGroup],
        total_threads: int,
        mode: RouterMode = RouterMode.ONE_SHOT,
        exit_mode: RouterExitMode = RouterExitMode.BLOCKING,
        on_complete: Optional[Callable[[], None]] = None
    ):
        self.groups = groups
        self.total_threads = total_threads
        self.available_threads = threading.Semaphore(total_threads)
        self.mode = mode
        self.exit_mode = exit_mode
        self.on_complete = on_complete

        self._lock = threading.Lock()
        self._active_threads = 0

        for group in self.groups:
            if group.semaphore is None:
                group.semaphore = ThresholdSemaphore(group.count)

    def run(self):
        """
        Run the router loop, dispatching threads to each RoutedGroup
        according to SyncPolicy and available thread count.
        """
        while True:
            all_done = all(g.semaphore.is_released() for g in self.groups)
            if all_done:
                break

            for group in self.groups:
                if group.semaphore.is_released():
                    continue

                if self._can_dispatch(group):
                    self._dispatch_group(group)

            time.sleep(0.001)  # small delay to avoid tight loop

        if self.on_complete:
            if self.exit_mode == RouterExitMode.BLOCKING:
                ThresholdSemaphore(self.total_threads).wait()  # Wait for all threads to finish
            self.on_complete()

    def _can_dispatch(self, group: RoutedGroup) -> bool:
        with self._lock:
            if group.policy == SyncPolicy.STRICT:
                return self.available_threads._value >= group.count
            elif group.policy == SyncPolicy.MINIMUM:
                return self.available_threads._value >= (group.min_count or group.count)
            elif group.policy == SyncPolicy.PARTIAL:
                return self.available_threads._value > 0
            elif group.policy == SyncPolicy.SYNCHRONIZED:
                return self._active_threads == 0 and self.available_threads._value >= group.count
            return False

    def _dispatch_group(self, group: RoutedGroup):
        def task_runner():
            index = group.semaphore.acquire()
            try:
                group.func(index)
            finally:
                group.semaphore.release()
                with self._lock:
                    self._active_threads -= 1
                self.available_threads.release()

        for _ in range(group.count):
            self.available_threads.acquire()
            with self._lock:
                self._active_threads += 1
            threading.Thread(target=task_runner, daemon=True).start()
