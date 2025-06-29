from typing import Optional, Callable, List, Union


class Group:
    """
    Group (Robust Version)
    -----
    Represents a subgroup of threads. This version gracefully handles
    either a single callback or a list of callbacks.
    """

    def __init__(self, threshold: int, callbacks: Optional[Union[Callable, List[Callable]]] = None):
        if threshold <= 0:
            raise ValueError("Threshold must be a positive integer.")

        self.threshold = threshold
        self.callbacks: List[Callable] = []
        self.count = 0
        self.ready = False
        self._released_once = False

        if callbacks is not None:
            # If a single callable is passed, wrap it in a list
            if callable(callbacks):
                self.callbacks = [callbacks]
            # If a list is passed, validate that it contains callables
            elif isinstance(callbacks, list) and all(callable(cb) for cb in callbacks):
                self.callbacks = callbacks
            # Otherwise, the type is incorrect
            else:
                raise TypeError("callbacks must be a callable function or a list of callable functions.")