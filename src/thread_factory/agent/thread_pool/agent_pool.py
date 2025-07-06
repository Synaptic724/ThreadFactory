import logging, threading, time
from typing import Callable, Union
import ulid
from ulid import ULID
from thread_factory.runtime.orchestrator.monitoring.records.records import WorkStatus, Record
from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.concurrency.concurrent_queue import ConcurrentQueue
from thread_factory.concurrency.concurrent_set import ConcurrentSet
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.synchronization.primitives.flow_regulator import FlowRegulator
from thread_factory.synchronization.primitives.latch import Gate
from thread_factory.utils.interfaces.disposable import IDisposable
from thread_factory.runtime.orchestrator.monitoring.records.records import Records

class _AgentPoolContainer(IDisposable):
    """
    _AgentPoolContainer
    ---------------------
    Internal coordination structure for managing a set of AgenticWorker threads.

    It ensures:
    - Thread registration (with optional record tracking)
    - Thread unregistration upon disposal
    - Smart signaling and wake-up via FlowRegulator
    - Optional callback-based notifications
    - Controlled shutdown with unregister state cleanup

    This pool is intended for internal orchestration of dynamic, agentic threads
    that behave like living actors in a system.
    """

    def __init__(self, command_group: 'CommandGroup', ignore_tracking: bool = False):
        """
        Initializes the container.

        Args:
            ignore_tracking (bool): If True, no Records will be tracked per-thread.
                                    Instead, threads are tracked using only a ULID set.
        """
        super().__init__()
        self._lock = threading.RLock()  # Internal lock for safe concurrent modifications
        self._id = str(ulid.ULID())
        self._flow_regulator = FlowRegulator(0)  # Smart semaphore-like switch used for synchronization
        self._active = False  # Flag to indicate whether the container is active
        self._ignore_tracking = ignore_tracking  # Whether to store tracking Records or not

        # Track threads either as a simple set (if no tracking) or as a dict mapping to Records
        if ignore_tracking:
            self._registered_agents: Union[ConcurrentSet[ULID], ConcurrentDict[ULID, Records]] = ConcurrentSet[ULID]()
        else:
            self._registered_agents: Union[ConcurrentSet[ULID], ConcurrentDict[ULID, Records]] = ConcurrentDict[
                ULID, Records]()

        self._unregistered_agents = ConcurrentSet[ULID]()  # Tracks which threads have been requested to unregister
        self._unregister_agent_check = False  # Flag to indicate if any threads should unregister
        self._command_group_id = command_group.id  # The CommandGroup this container is associated with
        self._command_group_worker_count = command_group._worker_count
        self._command_group_max_worker_count = command_group._max_workers

    def dispose(self):
        """
        Disposes of the container and signals all waiting threads to exit.

        This will:
        - Transfer all current thread IDs to the unregister list
        - Notify all waiting threads to allow them to exit
        - Dispose of all internal state and clear tracking registries
        """
        if self._disposed:
            return
        with self._lock:
            if self._disposed:
                return
            self._disposed = True

            # Prepare unregistration set based on tracking strategy
            if self._ignore_tracking:
                self._unregistered_agents = self._registered_agents
            else:
                self._unregistered_agents = ConcurrentSet(self._registered_agents.keys())

            self._unregister_agent_check = True
            self._flow_regulator.notify_all()  # Wake all threads
            self._flow_regulator.dispose()  # Dispose of the switch lock
            self._flow_regulator = None  # Clear reference to FlowRegulator
            self._active = False  # Mark container inactive
            self._registered_agents.dispose()  # Dispose of registry
            self._registered_agents = None
            self._unregistered_agents.dispose()  # Dispose of unregistration list
            self._unregistered_agents = None
            self._unregister_agent_check = False
            self._command_group_worker_count = None  # Clear reference to CommandGroup
            self._command_group_max_worker_count = None  # Clear reference to CommandGroup

    def _container(self):
        """
        Main entrypoint for worker participation in this pool.

        Threads calling this will:
        - Register themselves
        - Wait until a notify is received
        - Exit gracefully if they're marked for unregistration
        """
        if self._disposed:
            raise RuntimeError("Container has been disposed and cannot be used.")
        self._check_agent()  # Validate the thread is an AgenticWorker
        self._register_agent()  # Add thread to the pool registry

        while self._active:
            with self._flow_regulator:
                pass  # Thread will block here until notified

            if not self._ignore_tracking:
                self.attach_record()

            if self._unregister_thread_check and self._should_exit():
                self._finalize_unregistration()
                return

    def attach_record(self) -> None:
        """
        Attaches the current thread's `ValueWork` (if present) to its associated `Records` entry
        in the agentic pool, assuming tracking is enabled.

        Raises:
            RuntimeError: If the current thread is not registered in the container.
        """
        thread_id = self._get_agent_id()  # Get the unique thread identifier

        # Try to fetch the current ValueWork task from the thread
        if value_work := getattr(threading.current_thread(), "_value_work", None):
            # Ensure this thread is registered before assigning work
            if thread_id not in self._registered_agents:
                raise RuntimeError("Thread is not registered in the AgenticPoolContainer.")

            # Attach the task into the record structure
            records = self._registered_agents.get(thread_id)
            records[value_work.task_id] = value_work

    def _check_agent(self) -> None:
        """
        Ensures the calling thread is a valid AgenticWorker.
        """
        current_thread = threading.current_thread()
        if not isinstance(current_thread, 'Agent'):
            raise TypeError("Current thread must be an instance of AgenticWorker")

    def _register_agent(self):
        """
        Registers the current thread in the container.

        Depending on `ignore_tracking`, either adds to a set or creates a Records entry.
        """
        thread_id = self._get_agent_id()
        with self._lock:
            if not self._active:
                self._active = True
            if self._ignore_tracking:
                self._registered_agents.add(thread_id)
            else:
                if thread_id not in self._registered_agents:
                    self._registered_agents[thread_id] = Records()

    def _get_agent_id(self) -> ULID:
        """
        Returns the current thread's factory_id (ULID), which uniquely identifies it.

        Returns:
            ULID: The factory_id for the calling thread.
        """
        return threading.current_thread().factory_id

    def _should_exit(self) -> bool:
        """
        Determines whether the current thread is marked for unregistration.

        Returns:
            bool: True if the thread should unregister and exit.
        """
        return self._get_agent_id() in self._unregistered_agents

    def _finalize_unregistration(self):
        """
        Final cleanup for a thread that is leaving the container.
        Disposes its tracking record and removes it from the active registry.
        """
        thread_id = self._get_agent_id()
        if not self._ignore_tracking:
            if records := self._registered_agents.get(thread_id):
                records.dispose()
        if self._ignore_tracking:
            self._registered_agents.discard(thread_id)
        else:
            self._registered_agents.pop(thread_id, None)

        # If the registry is now empty, mark inactive
        if len(self._registered_agents) == 0:
            self._active = False
        # If no more threads left to unregister, unset the check flag
        if len(self._unregistered_agents) == 0:
            self._unregister_thread_check = False

    def _unregister_agent(self, thread_id: ULID):
        """
        Marks a thread for unregistration and notifies it if it's waiting.

        Args:
            thread_id (ULID): The ID of the thread to unregister.
        """
        self._unregistered_agents.add(thread_id)
        with self._lock:
            self._unregister_thread_check = True

        # If thread is currently waiting on switch lock, wake it up
        if thread_id in self._flow_regulator._cond._waiters:
            self._flow_regulator.notify(factory_ids=[thread_id], awaited_caller=False)

    def _change_bias(self, bias: int):
        """
        Adjusts the bias threshold of the SwitchLock.

        Args:
            bias (int): New bias threshold value.
        """
        self._flow_regulator.set_bias_threshold(bias)

    def _notify_callable(self, worker_count: int, work_request: Callable):
        """
        Notifies up to `worker_count` threads with a callable to execute.

        The awakened threads will execute the callable themselves.

        Args:
            worker_count (int): Number of threads to wake.
            work_request (Callable): The callable to be passed to each thread.
        """
        self._flow_regulator.notify(n=worker_count, awaited_caller=True, callback=work_request)

    def _notify_priority_callable(self, worker_count: int, work_request: Callable):
        """
        Notifies threads by bypassing the SwitchLock's bias logic.

        This ensures all targeted threads are woken up immediately.

        Args:
            worker_count (int): Number of threads to wake.
            work_request (Callable): The callable to pass to awakened threads.
        """
        self._flow_regulator.bypass_bias_and_notify(n=worker_count, awaited_caller=True, callback=work_request)




class AgentPool(IDisposable):
    """
    AgentPool (Singleton)
    ---------------------
    A system-wide, cooperative, auto-scaling auxiliary thread pool for handling
    bursty, parallelizable workloads. It manages multiple, isolated pools of agents,
    one for each CommandGroup, ensuring resources are not shared between them.

    This class is implemented as a singleton to provide a single point of control
    for all auxiliary thread management in the application.

    Core Functionality:
    -------------------
    - **Multi-Pool Management**: Holds a dictionary of `_AgentPoolContainer`s,
      one for each `CommandGroup`, providing resource isolation.
    - **Auto-Scaling**: A single, dedicated maintenance agent monitors all pools,
      scaling them up to meet `min_workers` and scaling them down by retiring
      idle agents based on a timer.
    - **On-Demand Dispatch**: Allows users to `submit` a `HelpRequest` to a specific
      group's pool, requesting a team of agents to work on it concurrently.
    """
    _instance = None
    _lock = threading.RLock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(AgentPool, cls).__new__(cls)
        return cls._instance

    def __init__(self, command_center: 'CommandCenter', logger: Union[logging.Logger, None] = None):
        """
        Initializes the AgentPool singleton.

        This is guarded by a lock to prevent race conditions if multiple threads
        try to initialize it at the same time.
        """
        if getattr(self, '_initialized', False):
            return
        with self._lock:  # 🧠 Use the class-level lock
            if getattr(self, '_initialized', False):
                return

            super().__init__()
            self._id = str(ulid.ULID())
            self._command_center = command_center
            self._logger = logger or logging.getLogger(__name__)
            self._group_container_map = ConcurrentDict[str, str]()
            self._containers: ConcurrentDict[str, _AgentPoolContainer] = ConcurrentDict()
            self._shutdown_gate = Gate(True)

            # Create and deploy the maintenance agent
            self._maintenance_agent = self._create_maintenance_worker()
            self._maintenance_agent.deploy()

            self._initialized = True
            logger.info(f"Initialized AgentPool singleton.")

#region Destructor
    def dispose(self):
        """
        Shuts down the entire AgentPool service, retiring all agents.
        """
        if self._disposed: return
        with self._lock:
            self._logger.warning("Disposing down AgentPool")
            self._disposed = True
            self._shutdown_gate.close()  # Signal shutdown to the maintenance agent

            if self._maintenance_agent:
                self._maintenance_agent.shutdown_flag.set()

            for container in self._containers.values():
                container.dispose()
            self._containers.dispose()
            self._command_center = None  # Clear reference to CommandCenter
            self._logger.warning("AgentPool disposed, shutting down AgentPool")

#endregion Destructor
#region Command Group Pool Management
    def create_new_group_container(self, command_group : 'CommandGroup', tracking_records: bool = False) -> _AgentPoolContainer:
        """
        Creates a new pool container for a specific CommandGroup.

        Args:
            command_group (CommandGroup): The CommandGroup for which to create a pool.
            tracking_records (bool): If True, enables tracking of Records per thread.

        Returns:
            _AgentPoolContainer: The newly created pool container.
        """
        if self._disposed: raise RuntimeError("AgentPool has been disposed.")
        if command_group.id in self._containers:
            self._logger.info(f"New pool container {command_group.id} already exists.")
            raise ValueError(f"Pool already exists for group CommandGroup: Name: {command_group.name} ID: '{command_group.id}'.")

        container = _AgentPoolContainer(command_group=command_group, ignore_tracking=tracking_records)
        self._group_container_map[command_group.id] = container._id
        self._containers[container._id] = container
        return container

#endregion Command Group Pool Management
    def submit(self, help_request: 'HelpRequest', group_name: str, num_workers: int):
        """
        Submits a parallel job to a specific group's pool.

        Args:
            help_request (HelpRequest): The parallel work contract to be executed.
            group_name (str): The name of the CommandGroup whose pool should handle the request.
            num_workers (int): The number of agents requested for the job.
        """
        if self._disposed: raise RuntimeError("AgentPool has been disposed.")
        if group_name not in self._containers:
            raise ValueError(f"No pool configured for group '{group_name}'. Use configure_pool_for_group() first.")

        config = self._group_configs[group_name]
        if num_workers > config['max']:
            logging.warning(
                f"Request for {num_workers} workers exceeds group '{group_name}' max of {config['max']}. Capping.")
            num_workers = config['max']

        help_request.record.status = WorkStatus.IN_PROGRESS
        self._containers[group_name].dispatch_work(help_request, num_workers)

    def _create_maintenance_worker(self) -> 'Agent':
        """Creates the dedicated agent responsible for all pool scaling."""
        agent = self._command_center.create_agent(
            template_name="default",  # A simple, internal agent
            target=self._maintenance_loop,
            command_group_name="default"
        )
        return agent

    def _maintenance_loop(self):
        """The main logic for the maintenance agent, managing all pools."""
        while self._shutdown_gate.is_open():
            time.sleep(5)  # Maintenance check interval
            try:
                with self._lock:
                    for group_name, container in self._containers.items():
                        config = self._group_configs[group_name]
                        group = self._command_center.get_command_group(group_name)

                        # --- Scale Up ---
                        if group._worker_count < config['min']:
                            self._add_worker(group_name)

                        # --- Scale Down (Simple Timer-Based) ---
                        if container.get_idle_worker_count() > config['min']:
                            if group._worker_count > config['min']:
                                worker_to_retire = container.get_idle_workers(1)
                                if worker_to_retire:
                                    self._retire_worker(worker_to_retire[0])

            except Exception as e:
                logging.error(f"Error in AgentPool maintenance loop: {e}")

    def _add_worker(self, group_name: str):
        """Requests a new worker from the CommandCenter for a specific group's pool."""
        container = self._containers[group_name]

        if group._worker_count >= config['max']:
            return

        agent = self._command_center.create_agent(
            template_name="general_agent",
            define_home=container.agent_home_loop,
            command_group_name=group_name
        )
        if agent:
            agent.deploy()
            logging.info(
                f"AgentPool added worker to group '{group_name}'. Total workers in group: {group._worker_count.value}")

    def _retire_worker(self, agent: 'Agent'):
        """Retires a specific worker from the pool."""
        if agent and not agent.shutdown_flag.is_set():
            agent.shutdown_flag.set()
            # Wake the agent up so it can process its shutdown signal
            container = self._containers[agent._group_name]
            container._flow_regulator.release(n=1, factory_ids=[agent.factory_id])
            logging.info(f"AgentPool retired worker {agent.factory_id} from group '{agent._group_name}'.")

