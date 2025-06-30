from typing import Callable, Optional, Any
from thread_factory.runtime import Worker, WorkerState
from thread_factory.agent_thread_pool.help_request import HelpRequest
from thread_factory.runtime.orchestrator.monitoring.records.records import WorkStatus, Record
from thread_factory.utils.general_helpers.coroutine_helpers import CoroutineHelpers
import threading


class Agent(Worker):
    """
    The cornerstone of the Agentic Programming Model.

    This class transforms a standard thread into an intelligent, stateful agent.
    Unlike traditional workers that merely execute tasks, an Agent acts as an
    autonomous entity with its own identity, private memory, and a repertoire
    of defined behaviors.

    Core Principles:
    - **Thread Affinity by Design**: An Agent "owns" its state. Data and tasks
      are bound directly to the agent, eliminating the need for complex locks
      around shared data. This is managed via a thread-local `inventory`.
    - **Behavioral Routing**: Agents are not commanded; they are directed.
      Instead of a rigid script, an agent's execution flow is determined by
      directing it to different "locations," which are named, pre-defined
      behaviors.
    - **Coordination Over Orchestration**: Agents are designed to be part of an
      ecosystem. They can be coordinated via high-level signals and events,
      allowing for emergent, adaptive group behavior.

    An `agentic_toolkit` will provide a simplified API for developers to
    bind work to agents and direct their actions, abstracting the underlying
    mechanisms.
    """

    def __init__(self, *args, **kwargs):
        """
        Initializes the agent's core components.

        Sets up the agent's identity, its private memory (`inventory`),
        and its registries for behaviors (`locations` and `save_points`).
        """
        super().__init__(*args, **kwargs)

        self._save_points: dict[str, Callable[[], None]] = {}
        self._locations: dict[str, Callable[[], None]] = {}
        self._event_loop: Optional[Callable[[], None]] = None
        self._value_work: HelpRequest | None = None
        self._worker_type = "agentic"  # Reflects the new model

        # The agent's private, thread-local memory store.
        self._inventory = threading.local()
        self._inventory.data = {}

        # A globally-accessible data store for inter-agent coordination.
        self._shared_inventory: dict[str, Any] = {}
        # A registry for named data processing functions.
        self._data_transfer: dict[str, Callable[..., Any]] = {}

    # --- Mission & Work Management ---

    def set_value_work(self, help_request: HelpRequest) -> None:
        """
        Assigns a mission or work request to this agent.

        This method "binds" a task to the agent, making it responsible
        for the lifecycle of that work. The assignment is designed to be
        idempotent from the perspective of an external toolkit.
        """
        self._value_work = help_request

    def get_value_work(self) -> Optional[HelpRequest]:
        """Retrieves the agent's currently assigned mission."""
        return self._value_work

    def acquire_and_run_work(self):
        """Commands the agent to begin executing its bound mission."""
        if self._value_work:
            self._value_work.acquire_work()

    def get_work_state(self) -> Optional[WorkStatus]:
        """Queries the status of the agent's current mission."""
        if self._value_work:
            return self._value_work.get_state()
        return None

    def dispose_work(self) -> None:
        """Completes and disposes of the agent's current mission."""
        if self._value_work:
            self._value_work.dispose()
            self._value_work = None

    # --- Behavior & Capability Routing ---

    def set_home(self, fn: Callable[[], None]) -> None:
        """
        Defines the agent's default behavior or primary event loop.

        This "home" function dictates what the agent does when idle or
        awaiting direction.
        """
        if CoroutineHelpers.is_coroutine(fn):
            raise TypeError("Cannot set a coroutine as home; Agent model is synchronous.")
        self._event_loop = fn

    def register_location(self, name: str, fn: Callable[[], None]) -> None:
        """
        Equips the agent with a named capability or behavior.

        These "locations" are the building blocks of the agent's skills.
        The agent can be directed to execute the logic at any registered location.
        """
        if CoroutineHelpers.is_coroutine(fn):
            raise TypeError(f"Cannot register coroutine '{name}'; capabilities must be synchronous.")
        self._locations[name] = fn

    def get_locations_dict(self) -> dict[str, Callable[[], None]]:
        """Returns a dictionary of the agent's learned capabilities."""
        return self._locations.copy()

    def run(self):
        """The entry point for the agent's life, executing its event loop."""
        self._bind_factory_id()
        self.state = WorkerState.STARTING
        if self._event_loop is None:
            raise RuntimeError(f"[Agent {self.factory_id}] No home() behavior set before start.")
        self._event_loop()
        self.death_event.set()

    # --- State & Memory (Inventory) Management ---

    def bind_to_inventory(self, key: str, value: Any):
        """
        Stores data in the agent's private, thread-local memory.

        This is the primary mechanism for achieving "thread affinity," where
        state is bound directly to the agent that owns it.
        """
        self._inventory.data[key] = value

    def get_from_inventory(self, key: str, default=None) -> Any:
        """Retrieves data from the agent's private memory."""
        return self._inventory.data.get(key, default)

    def set_shared_inventory_item(self, key: str, value: Any) -> None:
        """
        Places data in the shared inventory for inter-agent coordination.

        Warning: Access to this shared state must be externally synchronized
        if concurrent writes are expected.
        """
        self._shared_inventory[key] = value

    def get_shared_inventory_item(self, key: str, default: Any = None) -> Any:
        """Retrieves data from the shared inventory."""
        return self._shared_inventory.get(key, default)

    # --- Inter-Agent Communication & Control ---

    def _resolve_worker_by_id(self, factory_id: str) -> Optional['Agent']:
        """
        Resolves another agent by its unique ID via the factory.

        This acts as a discovery service, allowing agents to find and
        interact with their peers.
        """
        if self.factory and hasattr(self.factory, "get_worker_by_id"):
            return self.factory.get_worker_by_id(factory_id)
        return None

    def bind_to_inventory_by_id(self, factory_id: str, key: str, value: Any) -> None:
        """
        Directly places data into another agent's private inventory.

        This enables powerful, direct state manipulation between agents,
        forming a core pattern for agent-to-agent communication.
        """
        worker = self._resolve_worker_by_id(factory_id)
        if worker:
            worker.bind_to_inventory(key, value)

    def get_from_inventory_by_id(self, factory_id: str, key: str, default=None) -> Any:
        """Directly retrieves data from another agent's private inventory."""
        worker = self._resolve_worker_by_id(factory_id)
        if worker:
            return worker.get_from_inventory(key, default)
        return default

    # --- Disposal ---

    def dispose(self):
        """
        Terminates the agent and cleans up all its resources.

        This includes disposing of its current mission, clearing its memory,
        and unregistering its behaviors.
        """
        if self.disposed:
            return
        self.dispose_work()
        if self._save_points is not None:
            self._save_points.clear()
        self._save_points = None
        if self._locations is not None:
            self._locations.clear()
        self._locations = None
        self._event_loop = None
        self._disposed = True
        self.state = WorkerState.DISPOSED

    def __repr__(self):
        """Provides a string representation of the agent's identity and state."""
        return f"<Agent id={self.factory_id} state={self.state.name}>"

    # NOTE: Other methods like register_save_point, get_work_record, etc.,
    # would be documented similarly, focusing on their intent within this model.