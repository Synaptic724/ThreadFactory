from enum import Enum, auto


class SyncPolicy(Enum):
    STRICT = auto()       # All `count` threads must be routed or skip/throw
    PARTIAL = auto()      # Allow execution with fewer threads if necessary
    MINIMUM = auto()      # Require at least `min_count`, otherwise wait/retry
    SYNCHRONIZED = auto() # All threads in group must enter before starting
