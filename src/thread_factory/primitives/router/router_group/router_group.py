from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Callable
from thread_factory.primitives.router import SyncPolicy

@dataclass
class RoutedGroup:
    name: str
    count: int                     # Threads desired
    func: Callable[[int], None]   # Callable (can be adapted for future)
    policy: SyncPolicy = SyncPolicy.STRICT
    min_count: Optional[int] = None   # Used if policy is MINIMUM
    semaphore: Optional['ThresholdSemaphore'] = None  # Created internally or injected
