import logging, threading, time
from dataclasses import dataclass
from typing import Callable, Union, Optional
import ulid
from thread_factory.concurrency.sync_types.sync_bool import SyncBool
from thread_factory.concurrency.sync_types.sync_int import SyncInt
from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.concurrency.concurrent_set import ConcurrentSet
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.synchronization import SignalController
from thread_factory.synchronization.primitives.flow_regulator import FlowRegulator
from thread_factory.synchronization.primitives.latch import Gate
from thread_factory.utils.interfaces.disposable import IDisposable
from thread_factory.agent.thread_pool.records.records import Records, WorkStatus


@dataclass(slots=True)
class ClaimedAgentRef:
    """
    Represents a temporarily claimed agent for pre-dispatch coordination.
    """
    agent_id: str
    template_name: str
    claimed: SyncBool
    pool_id: str
    available: bool

    def release(self):
        """
        Releases this claim, making it available again.
        """
        self.claimed.set(False)

    def is_active(self) -> bool:
        """
        Checks if the agent is still claimed.
        """
        return self.claimed.get()


class AgentContainer(IDisposable):
    """
    AgentContainer
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

    def __init__(self, command_group: 'CommandGroup', logger: Union[logging.Logger, None] = None, ignore_tracking: bool = False):
        """
        Initializes the container.

        Args:
            ignore_tracking (bool): If True, no Records will be tracked per-thread.
                                    Instead, threads are tracked using only a ULID set.
        """
        super().__init__()
        # Internal State
        self._lock = threading.RLock()  # Internal lock for safe concurrent modifications
        self._logger = logger or logging.getLogger(__name__)
        self._id = str(ulid.ULID())
        self._flow_regulator = FlowRegulator(0)  # Smart semaphore-like switch used for synchronization
        self._active = False  # Flag to indicate whether the container is active
        self._ignore_tracking = ignore_tracking  # Whether to store tracking Records or not


        # Agent Tracking Details
        # Track threads either as a simple set (if no tracking) or as a dict mapping to Records
        if ignore_tracking:
            self._registered_agents: Union[ConcurrentSet[ulid.ULID], ConcurrentDict[ulid.ULID, Records]] = ConcurrentSet[ulid.ULID]()
        else:
            self._registered_agents: Union[ConcurrentSet[ulid.ULID], ConcurrentDict[ulid.ULID, Records]] = ConcurrentDict[
                ulid.ULID, Records]()

        # Unregistration Tracking
        self._unregistered_agents = ConcurrentSet[ulid.ULID]()  # Tracks which threads have been requested to unregister
        self._unregister_agent_check = False  # Flag to indicate if any threads should unregister

        # Command group information
        self._command_group_id = command_group.id  # The CommandGroup this container is associated with
        self._command_group_worker_count = command_group._worker_count
        self._command_group_max_worker_count = command_group._max_workers

        # Targeted Agent Tracking
        self._claimed_agents: ConcurrentDict[str, ClaimedAgentRef] = ConcurrentDict()

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

            for records in self._registered_agents.values():
                records.dispose()
            self._registered_agents.dispose()  # Dispose of registry
            self._registered_agents = None
            self._unregistered_agents.dispose()  # Dispose of unregistration list
            self._unregistered_agents = None

            self._unregister_agent_check = False
            # Clear references to CommandGroup
            self._command_group_worker_count = None  # Clear reference to CommandGroup
            self._command_group_max_worker_count = None  # Clear reference to CommandGroup
            self._command_group_id = None  # Clear reference to CommandGroup
            self._claimed_agents.dispose()  # Dispose of claimed agents
            self._claimed_agents = None  # Clear reference to claimed agents
            self._logger.info(f"Disposed AgentContainer for CommandGroup: {self._command_group_id}")
            self._logger = None  # Clear logger reference


    def _untargeted_dispatch_loop(self):
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

        try:
            while self._active and not self._disposed:
                if self._flow_regulator is None:
                    break  # Container was disposed mid-loop

                with self._flow_regulator:
                    pass

                if not self._ignore_tracking:
                    self.attach_record()

                if self._unregister_thread_check and self._should_exit():
                    self._finalize_unregistration()
                    return
        except Exception as e:
            self._logger.error(f"Error in agent pool container: {e}")

    def _targeted_dispatch_loop(self):
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

        try:
            while self._active and not self._disposed:
                if self._flow_regulator is None:
                    break  # Container was disposed mid-loop

                with self._flow_regulator:
                    pass

                if not self._ignore_tracking:
                    self.attach_record()

                if self._unregister_thread_check and self._should_exit():
                    self._finalize_unregistration()
                    return
        except Exception as e:
            self._logger.error(f"Error in agent pool container: {e}")


    def _throughput_loop(self):
        """
        Main entrypoint for worker participation in this pool.

        Threads calling this will:
        - Register themselves
        - Wait until a notify is received
        - Exit gracefully if they're marked for unregistration
        """
        if self._disposed:
            self._logger.error("Container has been disposed and cannot be used.")
            raise RuntimeError("Container has been disposed and cannot be used.")
        self._check_agent()  # Validate the thread is an AgenticWorker
        self._register_agent()  # Add thread to the pool registry

        try:
            while self._active and not self._disposed:
                if self._flow_regulator is None:
                    break  # Container was disposed mid-loop

                with self._flow_regulator:
                    pass

                if not self._ignore_tracking:
                    self.attach_record()

                if self._unregister_thread_check and self._should_exit():
                    self._finalize_unregistration()
                    return
        except Exception as e:
            self._logger.error(f"Error in agent pool container: {e}")


    def _throughput_sleep(self):
        while self._active and not self._disposed:
            if self._flow_regulator is None:
                break  # Container was disposed mid-loop

            with self._flow_regulator:
                pass

            if threading.current_thread()._main_pool == True:
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
        if not hasattr(current_thread, "_pool_agent"):
            raise TypeError("Current thread be a subclass of Agent to use this pool container.")

    def _register_agent(self):
        """
        Registers the current thread in the container.

        Depending on `ignore_tracking`, either adds to a set or creates a Records entry.
        """
        if self._disposed:
            raise RuntimeError("Container has been disposed; cannot register new agents.")
        threading.current_thread()._pool_agent = True
        factory_id = self._get_agent_id()
        with self._lock:
            if not self._active:
                self._active = True
            if self._ignore_tracking:
                self._registered_agents.add(factory_id)
            else:
                if factory_id not in self._registered_agents:
                    self._registered_agents[factory_id] = Records()

    def _get_agent_id(self) -> ulid.ULID:
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
        factory_id = self._get_agent_id()
        if not self._ignore_tracking:
            if records := self._registered_agents.get(factory_id):
                records.dispose()
        if self._ignore_tracking:
            self._registered_agents.discard(factory_id)
        else:
            self._registered_agents.pop(factory_id, None)

        # If the registry is now empty, mark inactive
        if len(self._registered_agents) == 0:
            self._active = False
        # If no more threads left to unregister, unset the check flag
        if len(self._unregistered_agents) == 0:
            self._unregister_thread_check = False

    def _unregister_agent(self, factory_id: ulid.ULID):
        """
        Marks a thread for unregistration and notifies it if it's waiting.

        Args:
            factory_id (ULID): The ID of the thread to unregister.
        """
        self._unregistered_agents.add(factory_id)
        with self._lock:
            self._unregister_thread_check = True
            threading.current_thread()._pool_agent = False

        # If thread is currently waiting on switch lock, wake it up
        if factory_id in self._flow_regulator._cond._waiters:
            self._flow_regulator.notify(factory_ids=[factory_id], awaited_caller=False)

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


    def __len__(self):
        """
        Returns the number of currently registered agents in this pool.

        Returns:
            int: The count of active agents in the pool.
        """
        return len(self._registered_agents) if self._ignore_tracking else len(self._registered_agents.keys())

    def __contains__(self, item):
        """
        Checks if a given agent ID is registered in this pool.

        Args:
            item (ULID): The agent ID to check for.

        Returns:
            bool: True if the agent ID is registered, False otherwise.
        """
        return item in self._registered_agents if self._ignore_tracking else item in self._registered_agents.keys()


class ContainerCluster(IDisposable):

    def __init__(self, command_group: 'CommandGroup', logger: Union[logging.Logger, None] = None):
        super().__init__()
        # Internal State
        self._lock = threading.RLock()  # Internal lock for thread-safe operations
        self._id = str(ulid.ULID())
        self._logger = logger or logging.getLogger(__name__)


        # Command Group Information
        self._logger.info("Initialized ContainerCluster for CommandGroup: %s", command_group.id)

    def dispose(self):
        """
        Disposes all containers in this cluster.
        """
        for container in self._containers:
            container.dispose()

        self._containers.dispose()
        self._containers = None
        self._max_size = None
        self._logger.info("Disposed ContainerCluster for CommandGroup: %s", self._container_type)


    def get_available_container(self) -> Optional[AgentContainer]:
        """
        Returns a container that has room for more agents.

        If all containers are full, returns None.
        """
        for container in self._containers:
            if len(container) < self._max_size.value:
                return container
        return None

    def register_container(self, container: AgentContainer):
        """
        Registers a new container into the cluster.

        Args:
            container (AgentContainer): The container to register.
        """
        self._containers.append(container)

    def unregister_container(self, container: AgentContainer):
        """
        Removes a container from the cluster.

        Args:
            container (AgentContainer): The container to remove.
        """
        try:
            self._containers.remove(container)
            container.dispose()
        except ValueError:
            pass


class CommandGroupContainer(IDisposable):
    """
    CommandGroupContainer
    -----------------------
    Manages the containers for a specific CommandGroup.

    Handles both targeted and untargeted containers per template,
    providing a central access point for retrieving or dispatching
    agents according to dispatch strategy.

    This object abstracts container registration, lookup, and disposal
    for all agent templates under a CommandGroup.
    """

    def __init__(self, command_group: 'CommandGroup' , agent_pool: 'AgentPool',  logger: Union[logging.Logger, None] = None):
        """
        Initializes the container manager for a command group.

        Args:
            group_id (str): The unique ID of the associated CommandGroup.
        """
        super().__init__()
        self._lock = threading.RLock()
        self._id = str(ulid.ULID())
        self._logger = logger or logging.getLogger(__name__)
        self._command_group = command_group
        self._group_id = command_group.id
        self._agent_pool = agent_pool

        # Worker Management
        self._throughput_worker_count = 60
        self._dispatch_worker_count = 40
        self._targeted_dispatch_worker_count = 0

        # Container Management
        self._containers: Optional[ConcurrentDict[str, AgentContainer]] = ConcurrentDict[str, AgentContainer]() # UUID and Agent Container
        self._agents_in_container: ConcurrentDict[str, ConcurrentSet] =  ConcurrentDict[str, ConcurrentSet]()  # UUID and Agent Container
        self._max_size: Optional[SyncInt] = SyncInt(command_group._max_workers)# Optional: max agents per container #TODO: IMplement features with this later per work containers

        self._logger.info(f"Initialized CommandGroupContainer for group ID: {self._group_id}")

    def dispose(self):
        """
        Disposes all containers managed by this group.
        """
        if self._disposed: return
        with self._lock:
            self._disposed = True
            self._agent_pool.remove_command_group_container(self._group_id)
            self._agent_pool = None


            for container in self._containers.values():
                container.dispose()

            self._containers.dispose()
            self._logger.warning(f"Disposed CommandGroupContainer for group ID: {self._group_id}")
            self._logger = None
#region Container Management

    def register_container(self, container: AgentContainer, max_size: int, template_name: str = "default"):
        """
        Registers a container under the correct cluster based on targeting strategy.

        Args:
            container (AgentContainer): The pool to register.
            max_size (int): Maximum number of agents this container can hold.
            template_name (str): Template name or dispatch key.
        """
        if targeted:
            cluster = self._targeted_cluster.get(template_name)
            if not cluster:
                cluster = ContainerCluster(container_type=template_name,
                                           containers=ConcurrentList[AgentContainer](),
                                           max_size=SyncInt(max_size))  # default cap
                self._targeted_cluster[template_name] = cluster
            cluster.register_container(container)
        else:
            if not self._untargeted_cluster:
                self._untargeted_cluster = ContainerCluster(container_type="untargeted",
                                                            containers=ConcurrentList[AgentContainer](),
                                                            max_size=SyncInt(max_size))
            self._untargeted_cluster.register_container(container)

    def unregister_container(self, template_name: str, container: AgentContainer):
        """
        Unregisters a container from the cluster.

        Args:
            template_name (str): The template or key under which the container is stored.
            container (_AgentPoolContainer): The container to unregister.
            targeted (bool): Whether it's from the targeted or untargeted set.
        """
        if targeted:
            cluster = self._targeted_cluster.get(template_name)
            if cluster:
                cluster.unregister_container(container)
                if not cluster.containers:  # if empty
                    self._targeted_cluster.pop(template_name, None)
        else:
            if self._untargeted_cluster:
                self._untargeted_cluster.unregister_container(container)
                if not self._untargeted_cluster.containers:
                    self._untargeted_cluster = None

    def get_or_create_container(self, template_name: str) -> AgentContainer:
        """
        Retrieves a usable container or creates one if none available.

        Args:
            template_name (str): Template or dispatch key.
            targeted (bool): Whether the container should be targeted.

        Returns:
            _AgentPoolContainer: A ready-to-use container.
        """
        cluster = self._targeted_cluster.get(template_name) if targeted else self._untargeted_cluster
        if cluster:
            container = cluster.get_available_container()
            if container:
                return container

        # Make a new one
        new_container = AgentContainer(command_group=self, logger=self._logger)
        self.register_container(template_name=template_name, container=new_container, targeted=targeted)
        return new_container

#endregion Container Management
#region Targeted Retrieval System
#endregion Targeted Retrieval System
#region Worker Management
    def set_agent_pool_distribution(self, throughput_agents: int = 60, dispatch_agents: int= 40, targeted_dispatch_agents: int = 0):
        """
        Sets the distribution of agents across different pools.

        Args:
            throughput_agents (int): Number of agents for throughput tasks.
            dispatch_agents (int): Number of agents for dispatch tasks.
            targeted_dispatch_agents (int): Number of agents for targeted dispatch tasks.
        """
        if self._disposed:
            raise RuntimeError("AgentPool has been disposed and cannot set distribution.")

        with self._lock:
            self._throughput_worker_count = throughput_agents
            self._dispatch_worker_count = dispatch_agents
            self._targeted_dispatch_worker_count = targeted_dispatch_agents

    def increase_max_worker_count(self, number: int):
        """
        Notify the pool to increase its maximum worker count.
        This sends a signal to the maintenance agent to scale up
        the number of workers in the pool, allowing it to handle more
        concurrent requests.

        Args:
            number (int): The number of workers to add to the pool.
        """
        if self._disposed:
            raise RuntimeError("AgentPool has been disposed and cannot notify distribution change.")

        # Notify the maintenance agent to increased worker count
        if self._maintenance_agent: #TODO: Decide if we change something or if the system does
            self._maintenance_agent.increase_max_worker_count(number)
        raise NotImplemented("Method increase_max_worker_count is not implemented yet.")

    def decrease_max_worker_count(self, number: int):
        """
        Notify the pool to decrease its maximum worker count.
        This sends a signal to the maintenance agent to scale down
        the number of workers in the pool, reducing resource usage
        when demand is low.

        Args:
            number (int): The number of workers to remove from the pool.
        """
        if self._disposed:
            raise RuntimeError("AgentPool has been disposed and cannot notify distribution change.")

        # Notify the maintenance agent to adjust worker distribution
        if self._maintenance_agent: #TODO: Decide if we change something or if the system does
            self._maintenance_agent.decrease_max_worker_count(number)
        raise NotImplemented("Method decrease_max_worker_count is not implemented yet.")


    def _notify_distribution_change_event(self):
        """
        Notifies the maintenance agent of a change in worker distribution.
        This is used to trigger a re-evaluation of the current worker allocation
        based on the new distribution settings.
        """
        if self._disposed:
            raise RuntimeError("AgentPool has been disposed and cannot notify distribution change.")
        raise NotImplemented("Method _notify_distribution_change_event is not implemented yet.")

        # Notify the maintenance agent to adjust worker distribution
        if self._maintenance_agent: #TODO: Decide if we change something or if the system does
            self._maintenance_agent.notify_distribution_change(self._throughput_worker_count,
                                                               self._dispatch_worker_count,
                                                               self._targeted_dispatch_worker_count)


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

#endregion Worker Management

class DataCenter(IDisposable):
    """
    _DataCenter
    -----------
    A centralized registry for all CommandGroup containers.

    This class manages the lifecycle of CommandGroup containers,
    allowing for efficient retrieval and management of agent pools
    across different CommandGroups.

    It provides a single point of access to all CommandGroup containers,
    ensuring that resources are properly managed and disposed of.

    It also provides a location to drop off records and other
    metadata that is shared across all CommandGroups.
    """
#TODO: NOt built yet not MVP
    def __init__(self, logger: Union[logging.Logger, None] = None):
        super().__init__()
        self._lock = threading.RLock()
        self._id = str(ulid.ULID())
        self._logger = logger or logging.getLogger(__name__)
        #self._containers: ConcurrentDict[str, CommandGroupContainer] = ConcurrentDict()

        #self._data_records: ConcurrentDict[str, ConcurrentDict[str, ConcurrentDict[str, AgentContainer]]] = ConcurrentDict()

    def dispose(self):
        """
        Disposes all CommandGroup containers in the data center.
        """
        if self._disposed: return
        with self._lock:
            self._disposed = True
            #for container in self._containers.values():
           #     container.dispose()
            #self._containers.dispose()
            #self._containers = None
            self._logger = None

    def receive_agent_records(self, group_id: str, records: Records):
        """
        Receives and stores agent records for a specific CommandGroup.

        Args:
            group_id (str): The ID of the CommandGroup.
            records (Records): The records to store.
        """
        if self._disposed:
            raise RuntimeError("DataCenter has been disposed.")
        with self._lock:
            pass


class AgentPool(IDisposable):
    """
    AgentPool
    ---------------------
    A cooperative, auto-scaling auxiliary thread pool for handling
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

    _singleton_instance: Union["AgentPool", None] = None
    _singleton_lock = threading.RLock()

    @classmethod
    def get_instance(cls) -> "AgentPool":
        with cls._singleton_lock:
            if cls._singleton_instance is None:
                raise RuntimeError("AgentPool has not been initialized in singleton mode.")
            return cls._singleton_instance

    @classmethod
    def initialize_singleton(cls, *args, **kwargs) -> "AgentPool":
        with cls._singleton_lock:
            if cls._singleton_instance is not None:
                raise RuntimeError("AgentPool singleton already initialized.")
            cls._singleton_instance = cls(*args, **kwargs)
            return cls._singleton_instance

    @classmethod
    def _reset_singleton(cls):
        with cls._singleton_lock:
            cls._singleton_instance = None

    def __init__(self, command_center: 'CommandCenter', logger: Union[logging.Logger, None] = None, maintenance_agent: bool = True, signal_controller: 'SignalController' = None):
        """
        Initializes the AgentPool singleton.

        This is guarded by a lock to prevent race conditions if multiple threads
        try to initialize it at the same time.

        Args:
            command_center (CommandCenter): The CommandCenter instance to manage agents.
            logger (logging.Logger, optional): Optional logger for logging events.
        Raises:
            RuntimeError: If the AgentPool has already been initialized.
        """
        super().__init__()
        # Internal State Flags
        self._maintenance_agent = maintenance_agent

        # Internal State
        self._lock = threading.RLock()  # Internal lock for thread-safe initialization
        self._id = str(ulid.ULID())
        self._command_center = command_center
        self._logger = logger or logging.getLogger(__name__)
        self._shutdown_gate = Gate(True)
        self._data_center = DataCenter(logger=self._logger)  # Centralized data center for records and metadata

        # Create and deploy the maintenance agent
        if maintenance_agent:
            self._maintenance_agent = self._create_maintenance_worker()
            self._maintenance_agent.deploy()

        self._command_group_containers = ConcurrentDict[str, CommandGroupContainer]()  # All CommandGroup containers
        self._initialized = True
        logger.info(f"Initialized AgentPool singleton.")

        self._signal_controller = signal_controller
        if self._signal_controller:
            try:
                self._signal_controller.register(self)
                self._logger.info(f"CommandCenter '{self._id}' registered with external SignalController.")
            except Exception as e:
                self._logger.warning(f"Failed to register CommandCenter with external SignalController: {e}", exc_info=True)

#region Destructor
    def dispose(self):
        """
        Shuts down the entire AgentPool service, retiring all agents.
        """
        if self._disposed: return
        with self._lock:
            self._logger.warning("Disposing down AgentPool")
            self._disposed = True
            self._data_center.dispose()
            self._data_center = None
            self._shutdown_gate.close()  # Signal shutdown to the maintenance agent

            if self._maintenance_agent:
                self._maintenance_agent.shutdown_flag.set()

            self._command_center = None  # Clear reference to CommandCenter
            self._logger.warning("AgentPool disposed, shutting down AgentPool")
            self._logger = None  # Clear logger reference

#endregion Destructor
#region Container Group Management

    def create_command_group_container(self, command_group: 'CommandGroup', logger: Union[logging.Logger, None] = None) -> 'CommandGroupContainer':
        """
        Creates a new CommandGroupContainer for managing agents in a specific CommandGroup.

        Args:
            command_group_id (str): The unique ID of the CommandGroup.
            logger (logging.Logger, optional): Optional logger for logging events.

        Returns:
            CommandGroupContainer: The newly created container for the CommandGroup.
        """
        if self._disposed:
            raise RuntimeError("AgentPool has been disposed and cannot create new containers.")

        with self._lock:
            if command_group.id in self._command_group_containers:
                logger.warning(f"CommandGroupContainer for group '{command_group.id}' already exists.")
                raise ValueError(f"CommandGroupContainer for group '{command_group.id}' already exists.")

            container = CommandGroupContainer(command_group=command_group, logger=logger)
            self._command_group_containers[command_group.id] = container
            self._logger.info(f"Created CommandGroupContainer for group '{command_group.id}' with ID {container._id}.")
            return container


    def remove_command_group_container(self, command_group_id: str) -> bool:
        """
        Removes a CommandGroupContainer from the AgentPool.

        Args:
            command_group_id (str): The unique ID of the CommandGroup to remove.
        """
        if self._disposed:
            raise RuntimeError("AgentPool has been disposed and cannot remove containers.")

        with self._lock:
            if command_group_id not in self._command_group_containers:
                raise ValueError(f"No CommandGroupContainer found for group '{command_group_id}'.")

            container = self._command_group_containers.pop(command_group_id, None)
            if container:
                container.dispose()
                self._logger.info(f"Removed CommandGroupContainer for group '{command_group_id}'.")
                return True
            else:
                self._logger.warning(f"CommandGroupContainer for group '{command_group_id}' not found.")
                raise RuntimeError(f"No CommandGroupContainer for group '{command_group_id}'.")


    def get_command_group_container(self, command_group_id: str) -> 'CommandGroupContainer':
        """
        Retrieves the CommandGroupContainer for a specific CommandGroup.

        Args:
            command_group_id (str): The unique ID of the CommandGroup.

        Returns:
            CommandGroupContainer: The container for the specified CommandGroup.
        """
        if self._disposed:
            raise RuntimeError("AgentPool has been disposed and cannot retrieve containers.")

        with self._lock:
            if command_group_id not in self._command_group_containers:
                raise ValueError(f"No CommandGroupContainer found for group '{command_group_id}'.")

            return self._command_group_containers[command_group_id]


#region Maintenance Agent
    def _manage_worker_count_per_group(self):
        """
        When an increase or decrease in worker count is requested,
        we need to adjust the groups by managing their size elastically,
        an event can be sent here to notify the maintenance agent
        that this happened.
        """
        pass


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

#endregion Maintenance Agent