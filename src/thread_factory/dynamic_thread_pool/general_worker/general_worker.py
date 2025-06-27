import threading
import ulid
from typing import Optional, Callable, Any


class GeneralWorker(threading.Thread):
    """
    GeneralWorker
    -------------
    A minimal thread with identity tagging for use in systems that require
    factory_id and worker_type (e.g., SwitchLock, SmartCondition).

    This is ideal for lightweight orchestration or signaling without task queue logic.

    Usage:
        def my_task():
            print("Running task in GeneralWorker")

        worker = GeneralWorker(on_run=my_task)
        worker.start()
    """

    def __init__(self,
                 on_run: Optional[Callable[[], Any]] = None,
                 name: Optional[str] = None,
                 factory_id: Optional[str] = None,
                 worker_type: str = "general"):
        super().__init__(name=name, daemon=True)
        self.factory_id: str = factory_id or str(ulid.ULID())
        self.worker_type: str = worker_type
        self.on_run = on_run or self.default_run
        self.shutdown_flag = threading.Event()
        self.death_event = threading.Event()

    def _bind_identity(self):
        """
        Binds factory_id and worker_type to the thread instance itself,
        so other systems (like SwitchLock) can detect identity.
        """
        current = threading.current_thread()
        setattr(current, "factory_id", self.factory_id)
        setattr(current, "worker_type", self.worker_type)

    def run(self):
        self._bind_identity()

        try:
            self.on_run()
        finally:
            self.death_event.set()

    def stop(self):
        """Sets the shutdown flag for graceful exit (if supported by on_run)."""
        self.shutdown_flag.set()

    def default_run(self):
        """Default idle loop."""
        while not self.shutdown_flag.is_set():
            self.death_event.wait(0.1)  # Just chill

    def __repr__(self):
        return f"<GeneralWorker id={self.factory_id} type={self.worker_type}>"
