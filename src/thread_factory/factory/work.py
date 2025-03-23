from concurrent.futures import Future

class Work(Future):
    """
    Work represents a unit of execution within the ThreadFactory framework.
    Extends concurrent.futures.Future with additional metadata and lifecycle management.
    """

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

        # Optional metadata
        self.task_id = id(self)
        self.worker_id = None  # can be set when assigned to a worker
        self.queue_id = None   # optional, if we're using multiple queues

    def run(self):
        """
        Execute the assigned function and set the result or exception.
        Called by the worker thread.
        """
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.set_result(result)
        except Exception as e:
            self.set_exception(e)

    def __repr__(self):
        return f"<Work id={self.task_id} state={self._state}>"
