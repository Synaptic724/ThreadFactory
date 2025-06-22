import threading
from typing import Callable, Any, Union, Optional
from thread_factory.runtime import Worker, WorkerState

#region DynamicWorker
class DynamicWorker(Worker):
    """
    DynamicWorker
    -------------
    A behavior-driven, long-lived thread designed for agentic execution.

    Key Concepts:
    - Starts in a dormant state and waits for external activation.
    - Executes coordinated behavior through named callables.
    - Always returns to a central 'home' loop (usually the threadpool controller).
    - Does not poll a queue internally—work is dispatched externally.
    - Safe to shut down via external signal (`dispose()` or `_graceful_shutdown()`).

    This model enables thread orchestration that mimics living agents in a system,
    responding to signals, changing behavior, and looping intelligently.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Blocking event that allows this worker to wait for activation.
        self._wake_event = threading.Event()

        # Dictionary of checkpointed behaviors that can be resumed by name.
        self.save_points: dict[str, Callable[[], None]] = {}

        # Dictionary of callable behaviors representing "destinations" this worker can move to.
        self.locations: dict[str, Callable[[], None]] = {}

        # A default callable that represents the thread's main loop or resting state.
        self.home: Optional[Callable[[], None]] = None

#region Behavioural API
    def register_save_point(self, name: str, fn: Callable[[], None]) -> None:
        """
        Register a save point that can later be recalled by name.
        Useful for pausing/resuming long-lived agentic behaviors.
        """
        self.save_points[name] = fn

    def register_location(self, name: str, fn: Callable[[], None]) -> None:
        """
        Register a callable destination by name.
        Enables external systems to direct this thread to a specific behavior.
        """
        self.locations[name] = fn

    def set_home(self, fn: Callable[[], None]) -> None:
        """
        Define the thread's "home" behavior — typically the threadpool's event loop.
        This function is repeatedly invoked unless shutdown is triggered.
        """
        self.home = fn

    def call_save_point(self, name: str) -> None:
        """
        Resume execution from a previously registered save point.
        """
        fn = self.save_points.get(name)
        if not fn:
            print(f"[Worker {self.factory_id}] Save point '{name}' not found.")
            return
        fn()

    def go_home(self) -> None:
        """
        Manually invoke the home function from anywhere.
        This allows external rerouting to base behavior.
        """
        if not self.home:
            print(f"[Worker {self.factory_id}] No home set.")
            return
        self.home()

    def target_work_location(self, name: str) -> None:
        """
        Manually invoke a registered location function.
        Used to direct this worker toward a named behavior.
        """
        fn = self.locations.get(name)
        if not fn:
            print(f"[Worker {self.factory_id}] Work location '{name}' not registered.")
            return
        fn()


    def _graceful_shutdown(self):
        """
        Internal: Initiates graceful shutdown sequence.
        Wakes the thread (if sleeping) so that it can detect shutdown and exit cleanly.
        """
        self.shutdown_flag.set()
        self._wake_event.set()

    def _count_work(self):
        """
        Internal: Increment completed work counter.
        Useful for diagnostics or monitoring.
        """
        self.completed_work += 1
#endregion Behavioural API
#region Core Execution Logic
    def run(self):
        """
        Main thread entry point.

        - On start: binds the factory ID and prints status.
        - Verifies that a home() function is assigned.
        - Enters an infinite loop, repeatedly calling `home()` unless shutdown is signaled.
        - This loop never ends on its own — thread lifetime is externally controlled.
        """
        self._bind_factory_id()
        print(f"[Worker {self.factory_id}] DynamicWorker booted.")
        self.state = WorkerState.STARTING

        try:
            if self.home is None:
                raise RuntimeError(f"[Worker {self.factory_id}] No home() set before thread start.")

            while not self.shutdown_flag.is_set():
                try:
                    self.state = WorkerState.IDLE
                    self.home()
                except Exception as e:
                    print(f"[Worker {self.factory_id}] Home loop crashed: {e}")
        finally:
            # Cleanup phase after shutdown is triggered.
            self.state = WorkerState.TERMINATING
            print(f"[Worker {self.factory_id}] DynamicWorker exiting.")
            self.death_event.set()
#endregion Core Execution Logic
#region Disposal Logic
    def dispose(self):
        """
        Public API for cleanup and shutdown.

        - Ensures the thread exits if it’s in a blocked state.
        - Delegates core disposal logic to parent class.
        """
        if self.disposed:
            return
        self._graceful_shutdown()
        self.save_points.clear()
        self.locations.clear()
        self.home = None
        if self._wake_event:
            self._wake_event.set()
        self._wake_event = None
        super().dispose()
#endregion Disposal Logic
#endregion DynamicWorker