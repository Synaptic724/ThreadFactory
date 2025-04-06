import datetime
import threading
import time
import ulid
import ctypes
import inspect
from typing import Callable, Any, Optional, Union
from thread_factory.utils import Disposable
from enum import Enum, auto


class Records:
    """
    Tracks ULID records of completed work.

    This object is intended to store history of executed tasks for audit/logging.
    """
    def __init__(self):
        self.records: list[ulid.ULID] = []

    def add(self, record: ulid.ULID):
        """Appends a ULID for a completed task."""
        self.records.append(record)

    def __repr__(self):
        return f"<Records count={len(self.records)}>"

    def __len__(self):
        return len(self.records)


class WorkStatus(Enum):
    """
    Enum describing the type or lifecycle state of a Work item.

    This combines both 'what the task is' and 'what stage it's in',
    similar to `concurrent.futures.Future._state`.
    """
    # Lifecycle states (for execution tracking)
    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    CANCELLED = auto()
    FAILED = auto()

class WorkerState(Enum):
    """
    Represents the current lifecycle and behavior of a Worker thread.
    """
    CREATED = auto()            # Thread object created, not started yet
    STARTING = auto()           # Thread is initializing
    IDLE = auto()               # No task, waiting for work
    ACTIVE = auto()             # Executing a task
    BLOCKED = auto()            # Waiting on lock, I/O, or dependency
    SWITCHED = auto()           # Assigned a new queue or execution context
    PAUSED = auto()             # Temporarily suspended (manually or automatically)
    REBALANCING = auto()        # In the middle of a factory-controlled reassignment
    TERMINATING = auto()        # Graceful shutdown in progress
    KILLED = auto()             # Terminated via `hard_kill()`
    DEAD = auto()               # Fully stopped, no longer participating
    DISPOSED = auto()           # Disposed, no longer usable

class Worker(threading.Thread, Disposable):
    """
    Worker Thread
    -------------
    Executes tasks from a work queue and tracks lifecycle and execution metadata.

    Features:
    - Unique ULID-based worker ID
    - Graceful stop via `stop()`
    - Hard-kill via `hard_kill()` (unsafe, uses `ctypes`)
    - Tracks completed work count
    - Death signaling via `death_event` for external observers
    - Supports dynamic queue switching
    """

    def __init__(self, factory: Any, work_queue: Any):
        """
        Initializes a new worker instance.

        Args:
            factory (Any): Reference to the managing factory.
            work_queue (Any): Queue-like object to pull Work items from.
        """
        super().__init__()
        self.factory = factory
        self.work_queue = work_queue
        self.worker_id = str(ulid.ULID())  # Unique identifier
        self.state = 'IDLE'                # One of: IDLE, ACTIVE, SWITCHED, TERMINATING
        self.daemon = True                 # Die with main thread
        self.records = Records()           # Track task completions
        self.shutdown_flag = threading.Event()
        self.completed_work = 0
        self.death_event = threading.Event()
        self.disposed = False

    def run(self):
        """Main worker loop: pulls from queue and executes work."""
        print(f"[Worker {self.worker_id}] Starting.")
        try:
            self.state = 'STARTING'
            while not self.shutdown_flag.is_set():
                try:
                    task = self.work_queue.dequeue()
                    self.state = 'ACTIVE'
                    self._execute_task(task)
                except Exception:
                    self.state = 'IDLE'
                    time.sleep(0.01)
        finally:
            self.state = 'TERMINATING'
            print(f"[Worker {self.worker_id}] Exiting.")
            self.death_event.set()

    def _execute_task(self, task: Union[Callable, 'Work']):
        """
        Executes a single task. Supports both raw functions and `Work` objects.

        Args:
            task (Callable or Work): A function or Work object to run.
        """
        try:
            if hasattr(task, 'run') and callable(task.run):
                task.run()
            elif callable(task):
                task()
            else:
                raise TypeError(f"Invalid task type: {type(task)}")

            self.completed_work += 1

            if hasattr(task, "task_id"):
                self.records.add(ulid.ULID.from_bytes(task.task_id.to_bytes(16, "big")))

        except Exception as e:
            print(f"[Worker {self.worker_id}] Task failed: {e}")

    def stop(self):
        """Signals the worker to gracefully shut down."""
        self.shutdown_flag.set()

    def hard_kill(self):
        """
        Forcefully terminates the thread (unsafe).
        Uses `ctypes` to raise `SystemExit` inside the thread.

        Should only be used when graceful shutdown fails.
        """
        if not self.is_alive():
            print(f"[Worker {self.worker_id}] Already dead.")
            return

        res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_long(self.ident),
            ctypes.py_object(SystemExit)
        )
        if res == 0:
            raise ValueError("Invalid thread ID.")
        elif res > 1:
            ctypes.pythonapi.PyThreadState_SetAsyncExc(self.ident, None)
            raise SystemError("Failed to kill thread cleanly.")

        print(f"[Worker {self.worker_id}] Scheduled for hard kill.")

    def thread_switch(self, new_queue: Any):
        """
        Reassigns this worker to a different queue. Used during rebalancing.

        Args:
            new_queue: The new queue to pull from.
        """
        self.work_queue = new_queue
        self.state = 'SWITCHED'

    def get_creation_datetime(self) -> datetime.datetime:
        """Returns the ULID-based datetime of thread creation."""
        return ulid.ULID.from_str(self.worker_id).datetime

    def get_creation_timestamp(self) -> float:
        """Returns the ULID-based UNIX timestamp of thread creation."""
        return ulid.ULID.from_str(self.worker_id).timestamp

    def __del__(self):
        """Signals external observers of cleanup."""
        print(f"[Worker {self.worker_id}] __del__ called.")
        self.death_event.set()

    def dispose(self):
        """
        Clean up resources and signal permanent shutdown.
        This should be called only when the thread is no longer needed.

        Ensures:
        - `death_event` is triggered.
        - Thread is marked as disposed.
        - Any future logic depending on cleanup can hook into this.
        """
        if hasattr(self, "disposed") and self._disposed:
            return

        self.disposed = True
        self.shutdown_flag.set()
        self.death_event.set()
        self.state = WorkerState.DISPOSED
        print(f"[Worker {self.worker_id}] Disposed.")

    def __repr__(self):
        return f"<Worker id={self.worker_id} state={self.state} completed={self.completed_work}>"
