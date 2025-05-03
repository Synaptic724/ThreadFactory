import datetime
import threading
import time
import ulid
import ctypes
from typing import Callable, Any, Union
from thread_factory.runtime.orchestrator.monitoring.records.records import Records, Record
from thread_factory.utils import IDisposable
from enum import Enum, auto


class WorkerState(Enum):
    """
    Represents the current lifecycle and behavior of a Worker thread.
    """
    CREATED = auto()  # Thread object created, not started yet
    STARTING = auto()  # Thread is initializing
    IDLE = auto()  # No task, waiting for work
    ACTIVE = auto()  # Executing a task
    BLOCKED = auto()  # Waiting on lock, I/O, or dependency
    SWITCHED = auto()  # Assigned a new queue or execution context
    PAUSED = auto()  # Temporarily suspended (manually or automatically)
    REBALANCING = auto()  # In the middle of a factory-controlled reassignment
    TERMINATING = auto()  # Graceful shutdown in progress
    KILLED = auto()  # Terminated via `hard_kill()`
    DEAD = auto()  # Fully stopped, no longer participating
    DISPOSED = auto()  # Disposed, no longer usable

class Worker(threading.Thread, IDisposable):
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
    def __init__(self, group=None, target=None, name=None,
                 args=(), kwargs=None, *, daemon=None, factory_id, factory):
        """
        Initializes a new worker instance.

        Args:
            factory (Any): Reference to the managing factory.
            work_queue (Any): Queue-like object to pull Work items from.
        """
        super().__init__(group, target, name, args, kwargs, daemon=daemon)
        self.factory = factory
        self.factory_id = factory_id
        self.unique = str(ulid.ULID())  # Unique identifier
        self.state = 'IDLE'                # One of: IDLE, ACTIVE, SWITCHED, TERMINATING
        self.daemon = True                 # Die with main thread
        self.records = Records()           # Track task completions
        self.shutdown_flag = threading.Event()
        self.completed_work = 0
        self.death_event = threading.Event()

    def run(self):
        """Main worker loop: pulls from queue and executes work."""
        print(f"[Worker {self.unique}] Starting.")
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
            print(f"[Worker {self.unique}] Exiting.")
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
                self.records.add(Record(task.task_id, Record.WorkStatus.COMPLETED))

        except Exception as e:
            print(f"[Worker {self.unique}] Task failed: {e}")

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
            print(f"[Worker {self.unique}] Already dead.")
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

        print(f"[Worker {self.unique}] Scheduled for hard kill.")

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
        return ulid.ULID.from_str(self.unique).datetime

    def get_creation_timestamp(self) -> float:
        """Returns the ULID-based UNIX timestamp of thread creation."""
        return ulid.ULID.from_str(self.unique).timestamp

    def __del__(self):
        """Signals external observers of cleanup."""
        print(f"[Worker {self.unique}] __del__ called.")
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
        if hasattr(self, "disposed") and self.disposed:
            return

        self.disposed = True
        self.shutdown_flag.set()
        self.death_event.set()
        self.state = WorkerState.DISPOSED
        print(f"[Worker {self.unique}] Disposed.")

    def __repr__(self):
        return f"<Worker id={self.unique} state={self.state} completed={self.completed_work}>"
