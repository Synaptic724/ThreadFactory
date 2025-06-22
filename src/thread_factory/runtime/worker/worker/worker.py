import threading
from enum import Enum, auto
from datetime import datetime
import ulid
import ctypes
import time
from typing import Callable, Any, Union, Optional
from thread_factory.utils import IDisposable
from thread_factory.runtime.orchestrator.monitoring.records.records import Records, Record, WorkStatus


class WorkerState(Enum):
    """
    Enum representing the lifecycle and behavioral states of a Worker thread.

    These states allow for introspection, debugging, and external control logic
    to track where in its lifecycle the Worker currently resides.
    """
    CREATED = auto()  # The Worker has been instantiated but not started.
    STARTING = auto()  # The Worker thread is initializing (inside run()).
    IDLE = auto()  # The Worker is alive but not actively running tasks.
    ACTIVE = auto()  # The Worker is currently executing a task.
    BLOCKED = auto()  # The Worker is waiting (e.g., on a queue or resource).
    SWITCHED = auto()  # The Worker was reassigned to a different queue.
    PAUSED = auto()  # The Worker is temporarily paused (manual intervention).
    REBALANCING = auto()  # The Worker is participating in load redistribution.
    TERMINATING = auto()  # The Worker is shutting down gracefully.
    KILLED = auto()  # The Worker has been forcefully terminated (via `hard_kill`).
    DEAD = auto()  # The Worker thread has fully exited (natural or forced).
    DISPOSED = auto()  # The Worker has been disposed and will not restart.


class Worker(threading.Thread, IDisposable):
    """
    Worker class that manages lifecycle and performance tracking for threads executing tasks.

    Key Features:
    - Tracks the state and lifecycle of the thread.
    - Monitors work units completed per minute, per hour, and overall availability.
    - Supports lifecycle management with graceful shutdown and forced kill.
    - Records task completion details for auditing and monitoring purposes.

    Metrics Tracked:
    - **Units per minute**: Tracks the number of tasks completed per minute.
    - **Units per hour**: Tracks the number of tasks completed per hour (in a rolling window).
    - **Availability**: Indicates the worker's current load as a percentage of capacity (0.0 to 1.0).
    """

    def __init__(self, group=None, target=None, name=None,
                 args=(), kwargs=None, *, factory_id: Optional[str | int] = None,
                 factory: Any = None, work_queue: Optional[Any] = None):
        """
        Initializes a Worker thread with tracking capabilities for work performance metrics.

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

        # State management
        self.state = WorkerState.CREATED
        self.shutdown_flag = threading.Event()
        self.death_event = threading.Event()

        # Metrics tracking
        self.records = Records()  # Collection of task records
        self.last_completed_work: Optional[Record] = None  # Last completed task record
        self.availability: float = 0.0  # Worker availability: 0.0 (idle) to 1.0 (fully utilized)
        self.units_per_minute: int = 0  # Tasks completed in the last minute
        self.units_per_hour: list[int] = []  # Rolling history of tasks completed per hour
        self.work_unit_counter: int = 0  # Internal counter for tasks in the current minute
        self.start_time: datetime = datetime.now()  # Track the start time for hour-based tracking

        # Work queue for continuous task processing.
        self.work_queue = work_queue

        # Direct target execution parameters
        self._direct_target = target
        self._direct_args = args
        self._direct_kwargs = kwargs if kwargs is not None else {}

    def _bind_factory_id(self):
        """
        Assigns this Worker's factory_id to the active thread context.
        """
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

        if self._direct_target and self.work_queue is None:
            # Direct task execution if no work queue exists
            try:
                self.state = WorkerState.ACTIVE
                self._direct_target(*self._direct_args, **self._direct_kwargs)
                self.units_per_minute += 1
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

                task = self.work_queue.dequeue()
                self.state = WorkerState.ACTIVE
                self._execute_task(task)

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

            self.units_per_minute += 1  # Increment unit count for this minute
            self._update_hourly_metrics()  # Update units per hour

            if hasattr(task, "task_id"):
                self.records.add(Record(task.task_id, WorkStatus.COMPLETED))

        except Exception as e:
            print(f"[Worker {self.factory_id}] Task failed during execution: {e}")
            self.units_per_minute += 1  # Even failed tasks are counted for work per minute

    def update_metrics(self):
        """
        This method updates all the metrics related to the worker, including:
        - Availability (how busy the worker is)
        - Units completed per minute
        - Units completed per hour (rolling history)
        """
        # Update availability based on the units per minute (work done in the last minute)
        self.update_availability()

        # Update hourly metrics
        self._update_hourly_metrics()

    def update_availability(self):
        """
        Estimate the availability of the worker.
        Availability is based on the units completed per minute as a percentage of capacity.
        """
        self.availability = min(1.0, self.units_per_minute / 60.0)  # Availability is a ratio of work completed in a minute

    def _update_hourly_metrics(self):
        """
        Update the hourly work metrics.
        Tracks the number of units completed per hour and resets units_per_minute every hour.
        """
        current_time = datetime.now()
        if (current_time - self.start_time).seconds >= 3600:  # Check if an hour has passed
            self.units_per_hour.append(self.units_per_minute)  # Add current minute count to hourly history
            self.units_per_minute = 0  # Reset the units for the new hour
            self.start_time = current_time  # Reset start time for the next hour

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
        return f"<Worker id={self.factory_id} state={self.state.name} completed={self.units_per_minute} units_per_hour={self.units_per_hour}>"
