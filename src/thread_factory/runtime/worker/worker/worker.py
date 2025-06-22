import datetime
import threading
import time
import ulid
import ctypes
from typing import Callable, Any, Union, Optional
from enum import Enum, auto

from thread_factory.utils import IDisposable
from thread_factory.runtime.orchestrator.monitoring.records.records import Records, Record


class WorkerState(Enum):
    """
    Enum representing the lifecycle and behavioral states of a Worker thread.

    These states allow for introspection, debugging, and external control logic
    to track where in its lifecycle the Worker currently resides.
    """
    CREATED = auto()       # The Worker has been instantiated but not started.
    STARTING = auto()      # The Worker thread is initializing (inside run()).
    IDLE = auto()          # The Worker is alive but not actively running tasks.
    ACTIVE = auto()        # The Worker is currently executing a task.
    BLOCKED = auto()       # The Worker is waiting (e.g., on a queue or resource).
    SWITCHED = auto()      # The Worker was reassigned to a different queue.
    PAUSED = auto()        # The Worker is temporarily paused (manual intervention).
    REBALANCING = auto()   # The Worker is participating in load redistribution.
    TERMINATING = auto()   # The Worker is shutting down gracefully.
    KILLED = auto()        # The Worker has been forcefully terminated (via `hard_kill`).
    DEAD = auto()          # The Worker thread has fully exited (natural or forced).
    DISPOSED = auto()      # The Worker has been disposed and will not restart.


class Worker(threading.Thread, IDisposable):
    """
    Worker
    ------
    A specialized, lifecycle-aware thread that can execute queued work or a direct task.

    Key Features:
    - Unique factory ID for tracing and condition targeting.
    - Lifecycle control via shutdown flags and disposal.
    - Supports both continuous queue processing and one-shot execution.
    - Tracks completion statistics and operational state.
    - Emits lifecycle logs and exposes its final death event.
    - Unsafe but available `hard_kill()` for forced termination.

    Usage:
        worker = Worker(target=my_func)
        worker.start()
        worker.stop()  # Graceful
        worker.hard_kill()  # Forced (unsafe)

    Advanced:
        worker.thread_switch(new_queue)  # Dynamically reassign work queues
        worker.records  # Access execution records
    """

    def __init__(self, group=None, target=None, name=None,
                 args=(), kwargs=None, *, factory_id: Optional[str | int] = None,
                 factory: Any = None, work_queue: Optional[Any] = None):
        """
        Initialize a Worker.

        Args:
            group: Reserved for ThreadGroup support (unused).
            target: A callable to run once (used in unit tests or ad-hoc mode).
            name: Optional thread name.
            args: Arguments for the direct target callable.
            kwargs: Keyword arguments for the direct target callable.
            factory_id: Optional external ULID for tracking. Auto-generated if None.
            factory: Optional orchestrator or owner context.
            work_queue: Optional work queue to loop through.
        """
        super().__init__(group, target, name, args, kwargs, daemon=True)
        IDisposable.__init__(self)

        self.factory = factory
        self.factory_id = factory_id if factory_id else str(ulid.ULID())
        self.state = WorkerState.CREATED
        self.records = Records()
        self.shutdown_flag = threading.Event()
        self.completed_work = 0
        self.death_event = threading.Event()
        self.work_queue = work_queue

        self._direct_target = target
        self._direct_args = args
        self._direct_kwargs = kwargs if kwargs is not None else {}

    def _bind_factory_id(self):
        """Assigns this Worker's factory_id to the active thread context."""
        threading.current_thread().factory_id = self.factory_id

    def run(self):
        """
        Main thread entry point (called by `start()`).
        Handles direct target execution or continuous task loop from queue.

        Direct targets are run once and exit. Queued mode runs until shutdown.
        """
        self._bind_factory_id()
        print(f"[Worker {self.factory_id}] Starting.")
        self.state = WorkerState.STARTING

        # If a target function is passed and no work queue exists,
        # run the function once then exit.
        if self._direct_target and self.work_queue is None:
            try:
                self.state = WorkerState.ACTIVE
                self._direct_target(*self._direct_args, **self._direct_kwargs)
                self.completed_work += 1
            except Exception as e:
                print(f"[Worker {self.factory_id}] Direct target execution failed: {e}")
            finally:
                self.shutdown_flag.set()
                self.state = WorkerState.IDLE

        try:
            # Main processing loop
            while not self.shutdown_flag.is_set():
                if self.work_queue is None:
                    # If no queue is assigned, idle until told to exit
                    self.state = WorkerState.BLOCKED
                    time.sleep(0.01)
                    continue

                try:
                    task = self.work_queue.dequeue()
                    self.state = WorkerState.ACTIVE
                    self._execute_task(task)
                except Exception as e:
                    print(f"[Worker {self.factory_id}] Dequeue or task execution error: {e}")
                    self.state = WorkerState.IDLE
                    time.sleep(0.01)
        finally:
            self.state = WorkerState.TERMINATING
            print(f"[Worker {self.factory_id}] Exiting.")
            self.death_event.set()

    def _execute_task(self, task: Union[Callable, 'Work']):
        """
        Executes a unit of work.
        Accepts either a callable or an object with a .run() method.

        Automatically logs completion if a task_id is available.
        """
        try:
            if hasattr(task, 'run') and callable(task.run):
                task.run()
            elif callable(task):
                task()
            else:
                raise TypeError(f"Invalid task type: {type(task)}. Must be callable or have .run().")

            self.completed_work += 1

            if hasattr(task, "task_id"):
                self.records.add(Record(task.task_id, Record.WorkStatus.COMPLETED))
        except Exception as e:
            print(f"[Worker {self.factory_id}] Task failed during execution: {e}")

    def stop(self):
        """
        Request a graceful shutdown. Thread will finish any active work then exit.
        """
        self.shutdown_flag.set()

    def hard_kill(self):
        """
        Forcefully terminate the thread using ctypes injection of SystemExit.

        ⚠️ Use only in emergencies. May cause memory corruption or leave shared
        resources (locks, queues) in an undefined state.
        """
        if not self.is_alive():
            print(f"[Worker {self.factory_id}] Already dead or not started.")
            return

        res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_long(self.ident),
            ctypes.py_object(SystemExit)
        )
        if res == 0:
            raise ValueError(f"Invalid thread ID for hard kill: {self.ident}.")
        elif res > 1:
            ctypes.pythonapi.PyThreadState_SetAsyncExc(self.ident, None)
            raise SystemError(f"Multiple exceptions set for thread {self.ident}.")

        self.state = WorkerState.KILLED
        print(f"[Worker {self.factory_id}] Scheduled for hard kill.")

    def thread_switch(self, new_queue: Any):
        """
        Dynamically assign the worker to a different work queue.
        """
        self.work_queue = new_queue
        self.state = WorkerState.SWITCHED

    def get_creation_datetime(self) -> datetime.datetime:
        """
        Returns the UTC datetime this worker was created based on its ULID.
        """
        return ulid.ULID.from_str(self.factory_id).datetime

    def get_creation_timestamp(self) -> float:
        """
        Returns the Unix timestamp of creation from ULID.
        """
        return ulid.ULID.from_str(self.factory_id).timestamp

    def __del__(self):
        """
        Destructor — ensures the death event is set, even if not gracefully exited.
        """
        if hasattr(self, "factory_id"):
            print(f"[Worker {self.factory_id}] __del__ called.")
        if hasattr(self, "death_event"):
            self.death_event.set()

    def dispose(self):
        """
        Public disposal method. Halts the thread, marks it disposed, sets death flag.
        Safe to call multiple times.
        """
        if self.disposed:
            return
        self._disposed = True
        self.shutdown_flag.set()
        self.death_event.set()
        self.state = WorkerState.DISPOSED
        print(f"[Worker {self.factory_id}] Disposed.")

    def __repr__(self):
        """
        Human-readable representation for debugging/logging.
        """
        return f"<Worker id={self.factory_id} state={self.state.name} completed={self.completed_work}>"
