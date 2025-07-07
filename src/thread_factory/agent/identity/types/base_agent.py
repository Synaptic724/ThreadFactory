import logging, ulid, ctypes, time, threading
from enum import Enum, auto
from datetime import datetime, timedelta
from typing import Callable, Any, Optional
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict  # Make sure this is imported
from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.concurrency.concurrent_queue import ConcurrentQueue
from thread_factory.utils.interfaces.disposable import IDisposable
from thread_factory.utils.exceptions.empty import Empty
from thread_factory.agent.thread_pool.records import Records, Record, WorkStatus
from thread_factory.agent.thread_pool.work import Work
from thread_factory.synchronization.controllers.signal_controller import SignalController

class AgentState(Enum):
    """
    Enum representing the lifecycle and behavioral states of a BaseAgent thread.
    """
    CREATED = auto()
    STARTING = auto()
    IDLE = auto()
    ACTIVE = auto()
    BLOCKED = auto()
    PAUSED = auto()
    KILLED = auto()
    DEAD = auto()
    DISPOSED = auto()

    #main pool only states
    REBALANCING = auto()
    TERMINATING = auto()
    SWITCHED = auto()

class BaseAgent(threading.Thread, IDisposable):
    """
    Manages the lifecycle, execution, and performance tracking of a dedicated worker thread.

    This class extends `threading.Thread` to provide a robust framework for
    processing `Work` units from a `ConcurrentQueue`. It integrates with a
    `SignalController` for external management and monitoring, and includes
    built-in mechanisms for tracking execution metrics, handling graceful
    shutdowns, and supporting forceful termination.

    Key Features:
    - **Concurrent Task Execution**: Continuously dequeues and executes `Work` units.
    - **State Management**: Tracks the worker's operational state (e.g., IDLE, ACTIVE, BLOCKED).
    - **Performance Metrics**: Records and calculates metrics like units processed per minute,
      total work units, and task records for analytical purposes.
    - **Graceful Shutdown**: Supports controlled termination via a shutdown flag.
    - **Forceful Termination**: Provides a `hard_kill` mechanism for urgent thread termination (use with caution).
    - **SignalController Integration**: Registers itself with an optional `SignalController`
      to expose its state and commands for remote management and event notification.
    - **Resource Disposal**: Implements `IDisposable` for proper cleanup of resources.
    """

    def __init__(self, group: Optional[threading.Thread] = None,
                 target: Optional[Callable[..., Any]] = None,
                 name: Optional[str] = None,
                 args: tuple = (),
                 kwargs: Optional[dict] = None,
                 *,
                 factory: Any = None,
                 work_queue: Optional[ConcurrentQueue['Work']] = None,
                 signal_controller: Optional['SignalController'] = None,
                 logger: Optional[logging.Logger] = None):
        """
        Initializes a new BaseAgent thread instance.

        This constructor sets up the worker's core components, including its unique
        identifier, logging, state management, performance tracking, and optional
        integration with a `SignalController` and `Work` queue.

        Args:
            group (Optional[threading.ThreadGroup]): The thread group to which this
                thread will belong. Defaults to None.
            target (Optional[Callable]): The callable object to be run by the thread's
                `run()` method. Defaults to None, in which case `BaseAgent.run()` is used.
            name (Optional[str]): The thread name. By default, a unique name is constructed.
            args (tuple): A tuple of arguments for the target callable. Defaults to an
                empty tuple.
            kwargs (Optional[dict]): A dictionary of keyword arguments for the target
                callable. Defaults to None.
            factory (Any): An optional reference to the parent factory or manager that
                created this worker, used for sending back aggregate records.
            work_queue (Optional[ConcurrentQueue[Work]]): A concurrent queue from which
                the worker continuously dequeues and executes `Work` units. If None,
                the worker will remain in a blocked/idle state without a work source.
            signal_controller (Optional[SignalController]): An optional instance of
                `SignalController` to which this worker will register itself. This
                enables external monitoring, command invocation, and event notification
                for the worker.
            logger (Optional[logging.Logger]): A custom logger instance for the worker.
                If None, a default logger named after the module (`__name__`) will be used.
        """
        super().__init__(group, target, name, args, kwargs, daemon=True)
        IDisposable.__init__(self)

        self._lock = threading.RLock() # Thread-safe lock for internal state management
        self.factory = factory
        self.factory_id: str = str(ulid.ULID())
        self._logger = logger or logging.getLogger(__name__)
        self._signal_controller: Optional[SignalController] = signal_controller # Optional SignalController for external management

        # State management
        self.state = AgentState.CREATED
        self.shutdown_flag = threading.Event()
        self.death_event = threading.Event()
        self.worker_type = "mainpool" # Categorization for specific worker pools

        # Metrics tracking
        self.records = Records() # Stores historical records of completed work units
        self.last_completed_work: Optional[Record] = None # The most recently completed work record
        self.availability: float = 0.0 # Estimated utilization or availability percentage
        self.units_per_minute: int = 0 # Work units processed in the current minute
        self.units_per_hour: ConcurrentList[int] = ConcurrentList() # History of units processed per hour
        self.work_unit_counter: int = 0 # Total number of work units processed by this worker
        self.start_time: datetime = datetime.now() # Timestamp of when the worker instance was created

        # Work queue for continuous task processing.
        self.work_queue: Optional[ConcurrentQueue[Work]] = work_queue
        self._last_hourly_reset: datetime = datetime.now() # Tracks the start of the current hourly aggregation period

        # Auto-register with controller (best-effort)
        if self._signal_controller:
            try:
                self._signal_controller.register(self)
                self._logger.debug(f"BaseAgent '{self.id}' auto-registered with SignalController.")
            except Exception as e:
                self._logger.warning(
                    f"Failed to auto-register BaseAgent '{self.id}' with SignalController: {e}", exc_info=True)

    def dispose(self):
        """
        Disposes of the BaseAgent's resources, halts the thread, and unregisters itself.

        This method ensures a clean shutdown by signaling the thread to stop,
        releasing owned IDisposable resources, and unregistering from the
        SignalController. It is designed to be thread-safe and idempotent.

        This method does NOT call `super().dispose()` as per design.
        """
        if self._disposed:
            return

        with self._lock:
            if self._disposed: # Re-check inside the lock for race conditions
                return

            self._disposed = True
            self._logger.info(f"Initiating disposal for BaseAgent '{self.id}'.")

            # Signal thread termination
            self.shutdown_flag.set()
            self.death_event.set()
            self.set_worker_state("DISPOSED")

            # Dispose and nullify owned IDisposable objects
            if self.units_per_hour:
                self.units_per_hour.dispose()
            self.units_per_hour = None

            if self.work_queue:
                self.work_queue.dispose()
            self.work_queue = None

            if self.records:
                self.records.dispose()
            self.records = None

            # Unregister from SignalController and nullify its reference
            if self._signal_controller:
                try:
                    # Prevent recursive dispose call
                    self._signal_controller.unregister(self.factory_id, dispose_object=False)
                except Exception as e:
                    # Log error during unregistration
                    if hasattr(self, '_logger') and self._logger:
                        self._logger.warning(
                            f"Error unregistering BaseAgent '{self.id}' from SignalController: {e}",
                            exc_info=True
                        )
                finally:
                    self._signal_controller = None

            # Nullify remaining references
            self.last_completed_work = None
            self.factory = None
            self.shutdown_flag = None
            self.death_event = None
            self._lock = None

            # Log final disposal message, then nullify logger
            if hasattr(self, '_logger') and self._logger: # Check before using/nullifying
                self._logger.info(f"BaseAgent '{self.id}' disposal complete.")
            self._logger = None


#region Signal Controller Integration
    def set_external_controller(self, controller: SignalController):
        """
        Sets an external SignalController to manage or observe this BaseAgent.

        This allows the BaseAgent to register with a controller even after construction,
        enabling remote monitoring, status updates, or lifecycle awareness.

        Args:
            controller (SignalController): The controller to attach.

        Raises:
            TypeError: If the provided object is not a SignalController.
        """
        if not isinstance(controller, SignalController):
            raise TypeError("Expected a SignalController instance.")

        self._signal_controller = controller
        try:
            self._signal_controller.register(self)
        except Exception:
            pass  # Safe fail; controller may choose not to accept

    @property
    def id(self) -> str:
        """
        The unique identifier for this BaseAgent instance, conforming to SignalController's contract.
        """
        return self.factory_id

    def _get_object_details(self) -> ConcurrentDict[str, Any]:
        """
        Returns this worker's essential metadata and a list of callable commands,
        conforming to the SignalController contract.
        """
        # Define commands that you want the SignalController to be able to invoke on this BaseAgent.
        # For example, commands to stop, hard_kill, or get its status.
        return ConcurrentDict({
            "name": self.__class__.__name__,  # Or a more descriptive name like "BaseAgentThread"
            "commands": ConcurrentDict({
                "stop": self.stop,
                "hard_kill": self.hard_kill,
                "get_worker_state": self.get_state,  # Need to add this getter
                "get_units_per_minute": self.get_units_per_minute,  # Need to add this getter
                "get_total_processed": self.get_work_unit_counter,  # Need to add this getter
                # You might want to expose other metrics or control methods here
            })
        })

    # Revised set_status (renamed to set_worker_state for clarity)
    def set_worker_state(self, state_str: str):
        """
        Sets the current state of the worker from a string.

        Args:
            state_str: The string representation of the desired AgentState.

        Raises:
            ValueError: If the provided string does not match any AgentState enum member.
        """
        with self._lock:
            try:
                new_state = AgentState[state_str.upper()]
                if self.state != new_state:
                    self._logger.info(
                        f"BaseAgent '{self.id}' state changed from {self.state.name} to {new_state.name}.")
                    self.state = new_state
                    self._notify("WORKER_STATE_CHANGED", {"state": self.state.name})
                else:
                    self._logger.debug(f"BaseAgent '{self.id}' state is already {new_state.name}.")
            except KeyError:
                # self._logger might not be initialized if an exception occurs during init and then set_status is called
                # It's good practice to ensure self._logger exists before using it
                logger_to_use = getattr(self, '_logger', logging.getLogger(__name__))
                logger_to_use.error(
                    f"Invalid worker state string: '{state_str}'. Must be one of {[s.name for s in AgentState]}.")
                raise ValueError(
                    f"Invalid worker state string: '{state_str}'. Must be one of {[s.name for s in AgentState]}.")

    def _notify(self, event_type: str, data: Optional[dict] = None):
        """
        Notify the connected SignalController (if any) of an event.

        This is a lightweight way for the BaseAgent to report state or activity
        to external systems like the Command Center without being tightly coupled.

        Args:
            event_type (str): A short string describing the event type.
            data (Optional[dict]): Additional contextual data for the event.
        """
        if self._signal_controller is not None:
            self._signal_controller.notify(
                object_id=self.factory_id,
                event_type=event_type,
                data=data or {}
            )


#endregion Signal Controller Integration
    def run(self):
        """
        Main thread entry point (called by `start()`).
        Handles continuous task loop from queue.
        """
        self.set_worker_state("STARTING")

        try:
            while not self.shutdown_flag.is_set():
                if len(self.work_queue) == 0:
                    self.set_worker_state("BLOCKED")
                    time.sleep(0.01) # Small sleep to prevent busy-waiting
                    continue

                try:
                    task = self.work_queue.dequeue()
                    self.set_worker_state("ACTIVE")
                    self._execute_task(task)
                except Empty:
                    self.set_worker_state("IDLE") # If dequeue with timeout was used
                    time.sleep(0.01)
                except Exception as e:
                    # This catches unexpected errors during dequeue or before _execute_task is fully engaged
                    print(f"[BaseAgent {self.factory_id}] Error dequeuing or executing task: {e}")
                    time.sleep(0.1)


        finally:
            self.state = AgentState.TERMINATING
            self.death_event.set()
            self.dispose() # Ensure resources are disposed when thread exits gracefully

    # Add simple getters for metrics that you expose in _get_object_details
    def get_state(self) -> AgentState:
        """
        Retrieves the worker's current operational state.

        Returns:
            AgentState: The current state of the worker.
        """
        with self._lock:
            return self.state

    def get_units_per_minute(self) -> int:
        """
        Retrieves the number of work units processed in the current minute.

        Returns:
            int: The count of units processed within the last minute.
        """
        with self._lock:
            return self.units_per_minute

    def get_work_unit_counter(self) -> int:
        """
        Retrieves the total number of work units processed by this worker.

        Returns:
            int: The cumulative count of all work units processed.
        """
        with self._lock:
            return self.work_unit_counter


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
            print(f"[BaseAgent {self.factory_id}] Critical worker-level error during task execution: {e}")
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
                print(f"[BaseAgent {self.factory_id}] Warning: Task Future did not complete its lifecycle or record not finalized.")
                # Force add if not done but record has a state
                if task_record_reference and task_record_reference.status != WorkStatus.PENDING:
                    self.records.add(task_record_reference)
                    self.last_completed_work = task_record_reference

            self.update_metrics()

    def stop(self) -> None:
        """
        Signals the worker thread to gracefully stop its execution.

        This method sets an internal shutdown flag (`shutdown_flag`) which the
        worker's `run()` loop periodically checks. Upon detecting the flag,
        the `run()` method will complete its current task (if any), exit its loop,
        and proceed to dispose of its resources.

        This is the preferred method for terminating a worker thread as it allows
        for orderly cleanup and prevents data corruption. It does not immediately
        terminate the thread but requests its cooperation in shutting down.
        """
        self.shutdown_flag.set()

    def hard_kill(self) -> None:
        """
        Forcefully terminates the worker thread using low-level ctypes.

        This method is a drastic measure and should be used with extreme caution
        and only when graceful shutdown (`stop()`) is not feasible or effective.
        It injects an exception (SystemExit) into the target thread, which can
        cause unpredictable behavior, resource leaks, or data corruption if
        the thread is in the middle of a critical operation.

        This method should only be called if the worker is currently alive.
        After calling `hard_kill`, the worker's state is immediately set to `AgentState.KILLED`.

        Raises:
            ValueError: If the thread ID is invalid or the target thread cannot be found.
            SystemError: If multiple exceptions are set for the target thread (indicates an issue).
        """
        if not self.is_alive():
            self._logger.debug(f"Attempted hard_kill on non-alive worker '{self.id}'. No action taken.")
            return

        res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_long(self.ident),
            ctypes.py_object(SystemExit)
        )
        if res == 0:
            if hasattr(self, '_logger') and self._logger:
                self._logger.error(f"Failed to hard_kill worker '{self.id}': Invalid thread ID.")
            raise ValueError(f"Invalid thread ID for hard kill: {self.ident}.")
        elif res > 1:
            ctypes.pythonapi.PyThreadState_SetAsyncExc(self.ident, None) # Clear pending exceptions
            if hasattr(self, '_logger') and self._logger:
                self._logger.error(f"Failed to hard_kill worker '{self.id}': Multiple exceptions already set.")
            raise SystemError(f"Multiple exceptions set for thread {self.ident}.")

        self.state = AgentState.KILLED
        self._logger.warning(f"BaseAgent '{self.id}' forcefully terminated (hard_kill).")

    def update_metrics(self) -> None:
        """
        Updates all composite performance metrics for the worker.

        This method serves as a consolidated entry point to recalculate various
        metrics, such as availability. It is typically called internally after
        a unit of work is completed or when new metric data becomes available.
        """
        self.update_availability()

    def update_availability(self) -> None:
        """
        Calculates and updates the worker's estimated availability or utilization.

        Availability is derived from `units_per_minute` (work units processed in the
        current minute) as a percentage relative to a theoretical maximum (60 units/minute).
        The value is capped at 1.0 (100%) to ensure it doesn't exceed full utilization.

        This metric provides an indication of how busy the worker is.
        """
        # Ensure units_per_minute does not exceed 60 to prevent availability > 1.0
        # If units_per_minute represents work in a given minute, max is 60.0 assuming 1 unit/sec.
        # If it represents theoretical max, this calculation might need adjustment based on context.
        # Assuming 60.0 is the baseline for 100% utilization.
        self.availability = min(1.0, self.units_per_minute / 60.0)

    def _check_and_reset_hourly_metrics(self):
        """
        Checks if a new hour has elapsed since the last hourly metric reset.
        Also, removes records older than an hour to keep the data manageable.
        """
        current_time = datetime.now()
        hours_elapsed = (current_time - self._last_hourly_reset).total_seconds() / 3600.0

        self._send_records_to_factory()

        # Clean up records older than 1 hour from self.records.records (now a dict)
        self.records.records = ConcurrentDict({
            k: v for k, v in self.records.records.items()
            if (current_time - v.timestamp_creation_time).total_seconds() < 3600
        })

        while hours_elapsed >= 1.0:
            self.units_per_hour.append(self.units_per_minute)
            self.units_per_minute = 0
            self._last_hourly_reset += timedelta(hours=1)
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
        return f"<BaseAgent id={self.factory_id} state={self.state.name} units_per_minute={self.units_per_minute} total_processed={self.work_unit_counter}>"