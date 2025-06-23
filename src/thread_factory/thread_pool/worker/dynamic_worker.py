import threading
from typing import Callable, Any, Union, Optional
from thread_factory.runtime import Worker, WorkerState

class DynamicWorker(Worker):
    """
    DynamicWorker class enhances the base Worker class by supporting agentic execution
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
        self.home: Optional[Callable[[], None]] = None
        self._value_work = None  # Work Associated with this worker

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
        self.home = fn

    def run(self):
        """
        Main worker execution loop.

        This function repeatedly calls `home()` unless stopped. It will call external
        `locations` and `save_points` when directed.
        """
        self._bind_factory_id()  # Ensures the factory_id is set for the worker's thread context.
        self.state = WorkerState.STARTING

        if self.home is None:
            raise RuntimeError(f"[Worker {self.factory_id}] No home() set before thread start.")

        # Execute the home loop, making sure it's externally controllable and dynamic
        while not self.shutdown_flag.is_set():
            self.state = WorkerState.IDLE
            self.home()  # The worker will always call the home method

        self.death_event.set()  # Notify that the thread has completed

    def stop(self):
        """
        Gracefully stop the worker.
        """
        self.shutdown_flag.set()
        self._wake_event.set()

    def dispose(self):
        """
        Ensure proper disposal of dynamic worker resources.
        """
        if self.disposed:
            return
        self.save_points.clear()  # Clear all dynamic behaviors and save points
        self.save_points = None
        self.locations.clear()  # Clear all dynamic locations
        self.locations = None
        self.home = None  # Clear the home function reference
        super().dispose()  # Call parent class disposal

    def __repr__(self):
        """
        String representation for debugging/logging, reflecting dynamic behavior.
        """
        return f"<DynamicWorker id={self.factory_id} state={self.state.name}>"
