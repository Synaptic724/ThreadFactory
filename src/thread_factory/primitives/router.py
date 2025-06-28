# class Router:
#     def __init__(...):
#         self.groups: list[RoutedGroup]
#         self.total_threads: int
#         self.available_threads: set[Thread] or count
#         self.policy: RouterCollapsePolicy
#         ...
#
#     def run(self):
#         while not all(group.has_run or skipped for group in self.groups):
#             if not enough threads: wait or sleep
#             for group in self.groups:
#                 if not group.has_run and group.threshold <= available:
#                     dock threads → call func → on return, restore threads
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Optional
from thread_factory.primitives.threshold_semaphore import ThresholdSemaphore


class SyncPolicy(Enum):
    STRICT = auto()       # All `count` threads must be routed or skip/throw
    PARTIAL = auto()      # Allow execution with fewer threads if necessary
    MINIMUM = auto()      # Require at least `min_count`, otherwise wait/retry
    SYNCHRONIZED = auto() # All threads in group must enter before starting

@dataclass
class RoutedGroup:
    name: str
    count: int                     # Threads desired
    func: Callable[[int], None]   # Callable (can be adapted for future)
    policy: SyncPolicy = SyncPolicy.STRICT
    min_count: Optional[int] = None   # Used if policy is MINIMUM
    semaphore: Optional[ThresholdSemaphore] = None  # Created internally or injected

class RouterMode(Enum):
    ONE_SHOT = auto()    # Threads exit after task
    LOOP = auto()        # Threads return to router after task
    STRICT = auto()      # Exit if routing conditions not met

class RouterExitMode(Enum):
    NON_BLOCKING = auto()  # Return immediately after dispatch
    BLOCKING = auto()      # Wait until all work is finished before returning