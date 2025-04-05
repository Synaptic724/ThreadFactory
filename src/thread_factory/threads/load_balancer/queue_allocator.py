from thread_factory.concurrency import ConcurrentQueue
from thread_factory.utils import Empty, Disposable


class QueueAllocator(Disposable):
    """
    QueueAllocator is a simple ticket allocator based on a single ConcurrentQueue.

    Responsibilities:
    ------------------
    - Manages a pool of sequentially numbered tickets (0 .. queue_size-1)
    - Allows threads to acquire and release ticket IDs
    - Ensures IDs are recycled and reused
    - Provides safe disposal and optional context manager support

    Notes:
    ------
    - This is designed for usage with a thread pool or task system.
    - Tickets can be treated as thread IDs, worker IDs, or task IDs depending on the system.

    Example:
    --------
    with QueueAllocator(100) as allocator:
        ticket = allocator.acquire()
        # use the ticket
        allocator.release(ticket)
    """

    def __init__(self, queue_size: int = 500):
        """
        Initialize the allocator with `queue_size` tickets.

        Args:
            queue_size (int): Number of available tickets. Defaults to 500.
        """
        self._queue_size = queue_size
        self._queue = ConcurrentQueue[int](initial=list(range(queue_size)))
        self.disposed = False

    def acquire(self) -> int:
        """
        Acquire a ticket ID from the pool.

        Returns:
            int: The acquired ticket ID.

        Raises:
            RuntimeError: If no tickets are available.
        """
        try:
            return self._queue.dequeue()
        except Empty:
            raise RuntimeError("Queue is empty. No IDs available.")

    def release(self, id_: int):
        """
        Release a ticket back into the pool.

        Args:
            id_ (int): The ticket ID to release.

        Raises:
            ValueError: If the ID is outside the valid range.
            RuntimeError: If the allocator is disposed.
        """
        if not (0 <= id_ < self._queue_size):
            raise ValueError(f"ID {id_} out of range (0..{self._queue_size - 1})")
        self._queue.enqueue(id_)

    def dispose(self):
        """
        Dispose of the allocator and release internal resources.
        Safe to call multiple times.
        """
        if not self.disposed:
            self._queue.dispose()
            self.disposed = True
        else:
            # Optional: make this silent instead of raising if you prefer idempotency
            raise RuntimeError("QueueAllocator already disposed.")

    def __enter__(self):
        """
        Enter the context manager.
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Exit the context manager and automatically dispose of the allocator.
        """
        self.dispose()

    def __len__(self) -> int:
        """
        Return the number of currently available tickets.

        Returns:
            int: Number of tickets currently in the queue.
        """
        return len(self._queue)
