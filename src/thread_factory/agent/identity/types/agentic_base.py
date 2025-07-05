import threading
import ulid
from typing import Optional, Callable, Union, Any
from thread_factory.runtime.worker.worker.worker import Worker, WorkerState
from thread_factory.agent.thread_pool.help_request import HelpRequest
from thread_factory.runtime.orchestrator.monitoring.records.records import WorkStatus, Record
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.utils.coordination.package import Pack
from thread_factory.utils.interfaces.disposable import IDisposable


class AgenticBase(Worker):
    """
    Agentic Base Profile
    ---------
    An advanced, agentic thread object that serves as the base for all profiles.
    It combines identity, state, and execution logic, designed for sophisticated,
    long-lived operations within a dynamic execution pool.

    This object may be bound to an AgentActivator instance and can be subclassed
    to create specialized agent types.
    """

    def __init__(self, command_center: 'CommandCenter', target: Union[Callable[..., Any], Pack] = None,  *args, **kwargs):
        """
        Initializes the agentic profile, sets up all agentic state, and
        prepares the thread for execution. It extends the base `Worker`
        initialization with features for dynamic behavior, stateful operations,
        and flexible data management.

        Args:
            *args: Arbitrary positional arguments passed to the base `Worker` constructor.
            **kwargs: Arbitrary keyword arguments passed to the base `Worker` constructor.
        """
        # --- Initialize Base Classes ---
        super().__init__(*args, **kwargs) # For Worker
        IDisposable.__init__(self)        # For IDisposable
        if isinstance(target, Callable) or isinstance(target, Pack):
            self._target = Pack.bundle(target) if target else None
        else:
            raise TypeError("Target must be a Callable or Pack instance.")

        # --- Identity & Framework Integration (from original BaseProfile) ---
        self._factory_id = str(ulid.ULID())
        self._command_center = command_center

        # --- Agentic Configuration (from Agent) ---
        self._worker_type = "agentic"
        self._pool_agent: bool = True  # Indicates this worker is part of a dynamic thread pool
        self._return_home: bool = False # Returns to event loop after work completion
        self._lock = threading.RLock()

        # --- Behavior & Execution (from Agent) ---
        self._event_loop: Optional[Union[Callable[..., None], Pack]] = None
        self._value_work: Optional[HelpRequest] = None
        # --- Memory & State (from Agent) ---
        self._private_inventory = threading.local()
        self._private_inventory.data = ConcurrentDict()
        self._public_inventory: ConcurrentDict[str, Any] = ConcurrentDict()

    def dispose(self):
        """
        Performs a comprehensive cleanup of the agent's state, clears
        all references, and then triggers the disposal process of its base class.
        """
        if self._disposed:
            return

        # Dispose agent-specific resources
        self.dispose_work()
        self._private_inventory.dispose()
        self._private_inventory = None
        self._public_inventory.dispose()
        self._public_inventory = None

        self._event_loop = None
        self._command_center = None

        self._disposed = True
        self.state = WorkerState.DISPOSED


    def set_work_state(self, new_state: WorkStatus) -> None:
        if self._value_work:
            self._value_work.set_state(new_state)

    def get_work_state(self) -> Optional[WorkStatus]:
        if self._value_work:
            return self._value_work.get_state()
        return None

    def get_value_work(self) -> Optional[HelpRequest]:
        return self._value_work

    def set_value_work(self, help_request: HelpRequest) -> None:
        self._value_work = help_request

    def mark_work_in_progress(self) -> None:
        if self._value_work:
            self._value_work.mark_in_progress()

    def mark_work_completed(self) -> None:
        if self._value_work:
            self._value_work.mark_completed()

    def mark_work_failed(self) -> None:
        if self._value_work:
            self._value_work.mark_failed()

    def mark_work_cancelled(self) -> None:
        if self._value_work:
            self._value_work.mark_cancelled()

    def reset_work(self) -> None:
        if self._value_work:
            self._value_work.reset()

    def get_work_record(self) -> Optional[Record]:
        if self._value_work:
            return self._value_work.get_record()
        return None

    def acquire_and_run_work(self):
        if self._value_work:
            self._value_work.acquire_work()

    def cancel_bound_job(self):
        if self._value_work:
            self._value_work.cancel_job()

    def dispose_work(self) -> None:
        if self._value_work:
            self._value_work.dispose()
            self._value_work = None

    # --- Behavior Routing & Execution ---
    def should_return_home(self) -> bool:
        with self._lock:
            if self._disposed:
                raise RuntimeError("Cannot check return home after worker is disposed.")
            return self._return_home

    def set_return_home(self, return_home: bool) -> None:
        with self._lock:
            if self._disposed:
                raise RuntimeError("Cannot set return home after worker is disposed.")
            self._return_home = return_home

    def _resolve_worker_by_id(self, factory_id: str) -> Optional['BaseProfile']:
        if self._command_center:
            return self._command_center.get_agent_by_id(factory_id)
        # Fallback for pool-based resolution
        if self.factory and hasattr(self.factory, "get_worker_by_id"):
            return self.factory.get_worker_by_id(factory_id)
        return None

    def bind_to_inventory_by_id(self, factory_id: str, key: str, value: Any):
        worker = self._resolve_worker_by_id(factory_id)
        if worker and hasattr(worker, 'bind_to_inventory'):
            worker.bind_to_inventory(key, value)

    def get_from_inventory_by_id(self, factory_id: str, key: str, default=None) -> Any:
        worker = self._resolve_worker_by_id(factory_id)
        if worker and hasattr(worker, 'get_from_inventory'):
            return worker.get_from_inventory(key, default)
        return default


    def set_home(self, fn: Union[Callable[..., None], Pack]) -> None:
        self._event_loop = Pack.bundle(fn) if fn else fn

    def run(self):
        """
        Main execution entry point for the agentic thread.

        - If `self._pool_agent` is True, this thread is part of a dynamic thread pool and
          will execute the agentic event loop.
        - Otherwise, fallback to standard `threading.Thread.run()` behavior to support
          standalone thread logic outside the pool.
        """
        if not self._pool_agent:
            if callable(getattr(self, "_target", None)):
                return threading.Thread.run(self)
            else:
                raise RuntimeError("No event loop or target function set for standalone thread.")

        # Default agentic behavior for pool-bound workers
        self._bind_factory_id()
        self.state = WorkerState.STARTING

        if self._event_loop is None:
            raise RuntimeError(f"[Worker {self.factory_id}] No home() set before thread start.")
        self._event_loop()
        self.death_event.set()


    def _validate_caller(self, factory_id: Optional[str] = None) -> None:
        expected = factory_id or self.factory_id
        current_id = getattr(threading.current_thread(), "factory_id", None)
        if current_id != expected:
            raise PermissionError(
                f"[Access Denied] Caller factory_id={current_id} does not match expected={expected}"
            )

    # --- Framework Integration & Identity ---
    @property
    def factory_id(self):
        return self._factory_id

    def get_name(self) -> str:
        return "This is a BaseProfile, and thus is nameless until specialized."

    def get_description(self) -> str:
        return "This is a BaseProfile, its purpose is to provide a base for agent profiles."


    def __repr__(self) -> str:
        return f"<AgenticProfile id={self.factory_id} state={self.state.name}>"

    def __str__(self) -> str:
        return f"AgenticProfile<{self.factory_id}>"