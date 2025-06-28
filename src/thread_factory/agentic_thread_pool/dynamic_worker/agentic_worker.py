import threading
from typing import Callable, Any, Union, Optional
from thread_factory.runtime import Worker, WorkerState
from thread_factory.agentic_thread_pool.help_request.help_request import HelpRequest
from thread_factory.runtime.orchestrator.monitoring.records.records import WorkStatus, Record


class AgenticWorker(Worker):
    """
    AgenticWorker class enhances the base Worker class by supporting agentic execution
    with dynamic behaviors and external task handling. This worker is suited for use
    in systems that require long-lived threads that respond to signals and change
    behavior dynamically.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Initialize the dynamic worker specific attributes
        self._wake_event = threading.Event()
        self.save_points: dict[str, Callable[[], None]] = {}
        self.locations: dict[str, Callable[[], None]] = {}
        self._event_loop: Optional[Callable[[], None]] = None
        self._value_work: HelpRequest | None = None  # Work Associated with this worker
        self._worker_type = "agentic"  # Type of worker, can be used for identification

    # State-mutation wrappers
    def set_work_state(self, new_state: WorkStatus):
        """
        Safely updates the state of the associated ValueWork.
        """
        if self._value_work:
            self._value_work.set_state(new_state)

    def get_work_state(self) -> Optional[WorkStatus]:
        """
        Retrieves the current state of the associated ValueWork.
        """
        if self._value_work:
            return self._value_work.get_state()
        return None

    def mark_work_in_progress(self) -> None:
        """
        Marks the associated ValueWork as 'in progress'.
        """
        if self._value_work:
            self._value_work.mark_in_progress()

    def mark_work_completed(self) -> None:
        """
        Marks the associated ValueWork as 'completed'.
        """
        if self._value_work:
            self._value_work.mark_completed()

    def mark_work_failed(self) -> None:
        """
        Marks the associated ValueWork as 'failed'.
        """
        if self._value_work:
            self._value_work.mark_failed()

    def mark_work_cancelled(self) -> None:
        """
        Marks the associated ValueWork as 'cancelled'.
        """
        if self._value_work:
            self._value_work.mark_cancelled()

    def reset_work(self) -> None:
        """
        Resets the associated ValueWork to 'pending'.
        """
        if self._value_work:
            self._value_work.reset()

    def get_work_record(self) -> Optional[Record]:
        """
        Retrieves the record of the associated ValueWork.
        """
        if self._value_work:
            return self._value_work.get_record()
        return None

    def acquire_and_run_work(self):
        """
        Acquires and runs the associated ValueWork.
        """
        if self._value_work:
            self._value_work.acquire_work()

    def cancel_bound_job(self):
        """
        Cancels the bound ValueWork job.
        """
        if self._value_work:
            self._value_work.cancel_job()

    # Disposal
    def dispose_work(self) -> None:
        """Dispose the bound ValueWork and detach it."""
        if self._value_work:
            self._value_work.dispose()
            self._value_work = None  # <-- This line is crucial

    def register_save_point(self, name: str, fn: Callable[[], None]) -> None:
        """
        Register a save point that can be recalled to resume execution later.
        """
        self.save_points[name] = fn

    def register_location(self, name: str, fn: Callable[[], None]) -> None:
        """
        Register a callable location that the worker can transition to.
        """
        self.locations[name] = fn

    def set_home(self, fn: Callable[[], None]) -> None:
        """
        Set the home function (main loop or resting state) for the worker.
        """
        self._event_loop = fn

    def run(self):
        """
        Main worker execution loop.

        This function repeatedly calls `home()` unless stopped. It will call external
        `locations` and `save_points` when directed.
        """
        self._bind_factory_id()  # Ensures the factory_id is set for the worker's thread context.
        self.state = WorkerState.STARTING
        if self._event_loop is None:
            raise RuntimeError(f"[Worker {self.factory_id}] No home() set before thread start.")
        self._event_loop()  # The worker will always call the home method
        self.death_event.set()  # Notify that the thread has completed

    def stop(self):
        """
        Gracefully stop the worker.
        """
        self.shutdown_flag.set()
        self._wake_event.set()

    def dispose(self):
        """
        Ensure proper disposal of dynamic worker resources, including cleaning
        up save points, locations, the event loop, and the bound ValueWork.
        """
        # A guard to prevent multiple disposals
        if self.disposed:
            return

        # Explicitly dispose of the bound ValueWork to free its resources.
        self.dispose_work()

        # Clear and dereference callable locations and save points
        if self.save_points is not None:
            self.save_points.clear()
        self.save_points = None

        if self.locations is not None:
            self.locations.clear()
        self.locations = None

        # Dereference the event loop (home function)
        self._event_loop = None

        # Call the parent class's dispose method for standard cleanup
        super().dispose()

    def __repr__(self):
        """
        String representation for debugging/logging, reflecting agentic behavior.
        """
        return f"<AgenticWorker id={self.factory_id} state={self.state.name}>"