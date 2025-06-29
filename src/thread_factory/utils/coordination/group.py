from typing import Optional, Callable


class Group:
    """
    Group
    -----
    Represents a subgroup of threads within the SignalBarrier, Router, Conductor.

    Each group tracks:
    - A `threshold` (number of threads needed to mark the group as ready)
    - A `callback` to be triggered when the group becomes ready
    - A live `count` of threads that have entered the group
    - A `ready` flag to indicate the group has satisfied its threshold
    """
    def __init__(self, threshold: int, callback: Optional[Callable] = None):
        if threshold <= 0:
            raise ValueError("Threshold must be a positive integer.")
        self.threshold = threshold
        self.callback = callback
        self.count = 0
        self.ready = False
        self._released_once = False