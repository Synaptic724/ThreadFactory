from typing import Callable, Optional, List
from thread_factory.utilities.interfaces.disposable import IDisposable

# NOT ACTIVE CLASS ATM
class RouterGroup(IDisposable):
    """
    RouterGroup
    ------------
    Represents a logical execution group. Contains a threshold (number of threads
    required to activate) and an ordered list of callables to execute once active.
    """

    def __init__(self, threshold: int, actions: Optional[List[Callable[[], None]]] = None):
        super().__init__()
        self.threshold = threshold
        self.actions = actions or []

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        self.actions.clear()
        self.actions = None

    def add_action(self, fn: Callable[[], None]):
        self.actions.append(fn)
