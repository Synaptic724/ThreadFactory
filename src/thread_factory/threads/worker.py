import datetime
import threading
import time
import ulid
import ctypes
from typing import Callable, Any, Optional
from thread_factory.utils import Disposable
from enum import Enum, auto
import asyncio

class Records:
    class WorkStatus(Enum):
        """
        This class tracks the work that was done by the thread and its results.
        The outcome of this class is transferred to another area in the ThreadFactory for logging.
        """
        COMPUTE = auto()
        IO = auto()
        NETWORK = auto()



    """Tracks the record of completed work items by ULID."""
    def __init__(self):
        self.records: list[ulid.ULID] = []

    def add(self, record):
        """Adds a ULID record of completed work."""
        self.records.append(record)

    def __repr__(self):
        return f"<Records count={len(self.records)}>"

    def __len__(self):
        return len(self.records)


class Worker(threading.Thread, Disposable):
    """
    Managed Worker Thread
    ---------------------
    - Has a unique ID (ULID)
    - Can gracefully shut down or be forcefully killed
    - Tracks work completion
    - Can participate in tree / shard systems via the factory
    """

    def __init__(self, factory: Any, work_queue: Any):
        """
        Initializes a new Worker thread.

        Args:
            factory (Any): Reference to the parent ThreadFactory (or manager).
            work_queue (Any): Queue-like object from which this thread will fetch work.
        """
        super().__init__()
        self.factory = factory
        self.work_queue = work_queue
        self.worker_id = str(ulid.ULID())  # Assign unique identifier
        self.state = 'IDLE'  # States: IDLE, ACTIVE, SWITCHED, TERMINATING
        self.daemon = True  # Ensure thread dies when main process exits
        self.records = Records()  # Track completed work records
        self.shutdown_flag = threading.Event()  # For graceful shutdown signal
        self.completed_work = 0  # Total successfully executed tasks
        self.death_event = threading.Event()  # Optional event for external death detection

    def run(self):
        """Main execution loop of the worker thread."""
        print(f"[Worker {self.worker_id}] Starting.")
        try:
            self.state = 'STARTING'
            while not self.shutdown_flag.is_set():
                try:
                    # Main work loop: fetch and execute tasks
                    task = self.work_queue.dequeue()  # Must be provided by external queue system
                    self.state = 'ACTIVE'
                    self._execute_task(task)
                except Exception:
                    # No task available or error -> go idle briefly
                    self.state = 'IDLE'
                    time.sleep(0.01)
        finally:
            # Cleanup when thread exits (naturally or forced)
            self.state = 'TERMINATING'
            print(f"[Worker {self.worker_id}] Exiting.")
            self.death_event.set()  # Signal external observers that we are gone

    def _execute_task(self, task: Callable):
        """
        Executes a single task.

        Args:
            task (Callable): The work to execute.
        """
        try:
            task()
            self.completed_work += 1
        except Exception as e:
            print(f"[Worker {self.worker_id}] Task failed: {e}")

    def stop(self):
        """Graceful shutdown signal (soft exit)."""
        self.shutdown_flag.set()

    def hard_kill(self):
        """
        Forces the thread to raise a SystemExit inside itself (unsafe, but useful).

        Notes:
            - Dangerous if resources are mid-allocation.
            - Threads should ideally be stopped via `stop()`.
        """
        if not self.is_alive():
            print(f"[Worker {self.worker_id}] Already dead.")
            return
        res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_long(self.ident),
            ctypes.py_object(SystemExit)
        )
        if res == 0:
            raise ValueError("Thread ID invalid")
        elif res > 1:
            ctypes.pythonapi.PyThreadState_SetAsyncExc(self.ident, None)
            raise SystemError("Failed to kill thread safely")
        print(f"[Worker {self.worker_id}] Scheduled for hard kill.")

    def thread_switch(self, new_queue: Any):
        """
        Re-assigns the worker to a different queue (can be used for rebalancing).
        """
        self.work_queue = new_queue
        self.state = 'SWITCHED'

    def get_creation_datetime(self) -> datetime.datetime:
        """
        Returns:
            datetime: The time this worker was created based on its ULID.
        """
        return ulid.ULID.from_str(self.worker_id).datetime

    def get_creation_timestamp(self) -> float:
        """
        Returns:
            float: Epoch timestamp derived from the ULID.
        """
        return ulid.ULID.from_str(self.worker_id).timestamp

    def __del__(self):
        """Triggered when Python's GC cleans up this object."""
        print(f"[Worker {self.worker_id}] __del__ called.")
        self.death_event.set()

    def __repr__(self):
        return f"<Worker id={self.worker_id} state={self.state} completed={self.completed_work}>"

    def dispose(self):
        pass