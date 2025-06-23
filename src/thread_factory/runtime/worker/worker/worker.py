import threading
from enum import Enum, auto
from datetime import datetime, timedelta
import ulid
import ctypes
import time
from typing import Callable, Any, Union, Optional

from thread_factory import ConcurrentList
from thread_factory.concurrency.concurrent_queue import ConcurrentQueue, Empty
from thread_factory.utils import IDisposable # Assumed to raise NotImplementedError for dispose()
from thread_factory.runtime.orchestrator.monitoring.records.records import Records, Record, WorkStatus
from thread_factory.runtime.factory.operations.work.work import Work # Assumed to be the corrected version

class WorkerState(Enum):
    """
    Enum representing the lifecycle and behavioral states of a Worker thread.
    """
    CREATED = auto()
    STARTING = auto()
    IDLE = auto()
    ACTIVE = auto()
    BLOCKED = auto() # Worker is explicitly waiting for tasks from an empty queue
    SWITCHED = auto()
    PAUSED = auto()
    REBALANCING = auto()
    TERMINATING = auto()
    KILLED = auto()
    DEAD = auto()
    DISPOSED = auto()

class Worker(threading.Thread, IDisposable):
    """
    Worker class that manages lifecycle and performance tracking for threads executing tasks.
    """

    def __init__(self, group=None, target=None, name=None,
                 args=(), kwargs=None, *, factory_id: Optional[str | int] = None,
                 factory: Any = None, work_queue: Optional[ConcurrentQueue[Work]] = None):
        """
        Initializes a Worker thread with tracking capabilities for work performance metrics.
        """
        super().__init__(group, target, name, args, kwargs, daemon=True)
        # IDisposable.__init__(self) # No need to call if IDisposable is just an interface

        self.factory = factory
        self.factory_id = factory_id if factory_id else str(ulid.ULID())

        # State management
        self.state = WorkerState.CREATED
        self.shutdown_flag = threading.Event()
        self.death_event = threading.Event()
        self._disposed: bool = False # Manually managed disposed flag for this class

        # Metrics tracking
        self.records = Records()
        self.last_completed_work: Optional[Record] = None
        self.availability: float = 0.0
        self.units_per_minute: int = 0
        self.units_per_hour: ConcurrentList[int] = ConcurrentList()
        self.work_unit_counter: int = 0
        self.start_time: datetime = datetime.now() # Worker's overall start time

        # Work queue for continuous task processing.
        self.work_queue: Optional[ConcurrentQueue[Work]] = work_queue
        self._last_hourly_reset: datetime = datetime.now() # Tracks when the current hourly bucket started

    def _bind_factory_id(self):
        """Binds the factory ID to the current thread for traceability."""
        if not hasattr(threading.current_thread(), 'factory_id'):
            setattr(threading.current_thread(), 'factory_id', self.factory_id)
        else:
            threading.current_thread().factory_id = self.factory_id


    def run(self):
        """
        Main thread entry point (called by `start()`).
        Handles continuous task loop from queue.
        """
        self._bind_factory_id()
        self.state = WorkerState.STARTING

        try:
            while not self.shutdown_flag.is_set():
                if len(self.work_queue) == 0:
                    self.state = WorkerState.BLOCKED
                    time.sleep(0.01) # Small sleep to prevent busy-waiting
                    continue

                try:
                    task = self.work_queue.dequeue()
                    self.state = WorkerState.ACTIVE
                    self._execute_task(task)
                except Empty:
                    self.state = WorkerState.IDLE # If dequeue with timeout was used
                    time.sleep(0.01)
                except Exception as e:
                    # This catches unexpected errors during dequeue or before _execute_task is fully engaged
                    print(f"[Worker {self.factory_id}] Error dequeuing or executing task: {e}")
                    time.sleep(0.1)


        finally:
            self.state = WorkerState.TERMINATING
            self.death_event.set()
            self.dispose() # Ensure resources are disposed when thread exits gracefully

    def _execute_task(self, task: 'Work'):
        """
        Executes a unit of work. Updates the worker's metrics and collects the task's final record.
        This method is now fully responsible for managing the Work object's disposal.
        """
        # Get a reference to the task's record BEFORE it runs.
        # This reference will persist even if the Work object's internal `record` is later nulled by Work.dispose().
        task_record_reference = task.record

        try:
            task.run() # This executes the work function and updates task.record.status internally.

        except Exception as e:
            # This 'except' block catches *any* exception that propagates out of task.run().
            # This includes the "Future in unexpected state" error.
            print(f"[Worker {self.factory_id}] Critical worker-level error during task execution: {e}")
            # If Work.run() failed in a way that its own internal set_exception/set_result
            # didn't finalize the record, we force it to FAILED here.
            if task_record_reference and not task.done(): # Check if Future itself wasn't marked done
                 task_record_reference.status = WorkStatus.FAILED
                 if not task_record_reference.timestamp_completion_time:
                     task_record_reference.timestamp_completion_time = datetime.now()


        finally:
            self.units_per_minute += 1
            self.work_unit_counter += 1
            self._check_and_reset_hourly_metrics()

            # Add the (now finalized) record to the worker's collection using the stored reference.
            # We check task.done() to ensure the Work object itself finished its Future lifecycle.
            # The record should have the correct status set by Work.set_result/set_exception.
            if task_record_reference and task.done():
                self.records.add(task_record_reference)
                self.last_completed_work = task_record_reference
            else:
                # This indicates a problem where Work.run() did not complete its Future lifecycle properly.
                print(f"[Worker {self.factory_id}] Warning: Task Future did not complete its lifecycle or record not finalized.")
                # Force add if not done but record has a state
                if task_record_reference and task_record_reference.status != WorkStatus.PENDING:
                    self.records.add(task_record_reference)
                    self.last_completed_work = task_record_reference

            self.update_metrics()

    def stop(self):
        """Gracefully stop the worker by setting the shutdown flag."""
        self.shutdown_flag.set()

    def hard_kill(self):
        """Forcefully terminate the thread using ctypes."""
        if not self.is_alive():
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

    def dispose(self):
        """
        Public disposal method. Halts the thread, marks it disposed, and sets death flag.
        This implementation does NOT call super().dispose() as per design.
        """
        if self._disposed:
            return
        self._disposed = True # Manually set disposed flag

        self.shutdown_flag.set() # Ensure thread stops if it's still running
        self.death_event.set() # Signal thread death
        self.state = WorkerState.DISPOSED

        self.work_queue = None
        self.records = None

    def update_metrics(self):
        """Updates all the metrics related to the worker."""
        self.update_availability()

    def update_availability(self):
        """Estimate the availability (or utilization) of the worker."""
        self.availability = min(1.0, self.units_per_minute / 60.0)

    def _check_and_reset_hourly_metrics(self):
        """
        Checks if a new hour has elapsed since the last hourly metric reset.
        Also, removes records older than an hour to keep the data manageable.
        """
        # Get the current time
        current_time = datetime.now()

        # Calculate how many hours have passed since the last reset
        hours_elapsed = (current_time - self._last_hourly_reset).total_seconds() / 3600.0

        self._send_records_to_factory()

        # Clean up records older than 1 hour from self.records.records
        self.records.records = ConcurrentList([record for record in self.records.records if
                                               (current_time - record.timestamp_creation_time).total_seconds() < 3600])

        while hours_elapsed >= 1.0:
            # Append the current units per minute to the hourly record (using ConcurrentList)
            self.units_per_hour.append(self.units_per_minute)

            # Instead of resetting immediately, accumulate the work for the next hour
            self.units_per_minute = 0

            # Update the last reset time
            self._last_hourly_reset += timedelta(hours=1)

            # Recalculate the hours elapsed to account for the new reset
            hours_elapsed -= 1.0


    def _send_records_to_factory(self):
        """
        Sends the worker's records to the factory for aggregation or storage.
        This method is a placeholder and should be implemented in subclasses or by the factory.
        """
        if self.factory and hasattr(self.factory, 'receive_worker_records'):
            self.factory.receive_worker_records(self.records)

    def __repr__(self):
        """Human-readable representation for debugging/logging."""
        return f"<Worker id={self.factory_id} state={self.state.name} units_per_minute={self.units_per_minute} total_processed={self.work_unit_counter}>"