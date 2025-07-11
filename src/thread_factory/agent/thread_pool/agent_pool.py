import logging, threading, time, ulid
from dataclasses import dataclass
from typing import Callable, Union, Optional
from thread_factory.agent.thread_pool.utilities.agent_pool_type import AgentPoolType
from thread_factory.agent.thread_pool import HelpRequest
from thread_factory.concurrency.concurrent_queue import ConcurrentQueue
from thread_factory.concurrency.sync_types.sync_bool import SyncBool
from thread_factory.concurrency.sync_types.sync_int import SyncInt
from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.concurrency.concurrent_set import ConcurrentSet
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.synchronization import SignalController
from thread_factory.synchronization.primitives.flow_regulator import FlowRegulator
from thread_factory.synchronization.primitives.latch import Gate
from thread_factory.utilities.interfaces.disposable import IDisposable
from thread_factory.agent.thread_pool.records.records import Records, WorkStatus


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
        self._active = False  # Flag to indicate whether the container is active
        self._ignore_tracking = ignore_tracking  # Whether to store tracking Records or not

        # Command group information
        self._command_group_id = command_group.id  # The CommandGroup this container is associated with
        self._command_group_worker_count = command_group._worker_count
        self._command_group_max_worker_count = command_group._max_workers

        # Agent Tracking Details
        self._all_agents: ConcurrentDict[ulid.ULID, 'Agent'] = ConcurrentDict()
        self._sleep_agents: ConcurrentSet[ulid.ULID] = ConcurrentSet[ulid.ULID]()

        # Track threads either as a simple set (if no tracking) or as a dict mapping to Records
        if ignore_tracking:
            self._throughput_agents: Union[ConcurrentSet[ulid.ULID], ConcurrentDict[ulid.ULID, Records]] = ConcurrentSet[ulid.ULID]()
            self._dispatch_agents: Union[ConcurrentSet[ulid.ULID], ConcurrentDict[ulid.ULID, Records]] = ConcurrentSet[ulid.ULID]()
            self._reserved_dispatch_agents: Union[ConcurrentSet[ulid.ULID], ConcurrentDict[ulid.ULID, Records]] = ConcurrentSet[ulid.ULID]()
        else:
            self._throughput_agents: Union[ConcurrentSet[ulid.ULID], ConcurrentDict[ulid.ULID, Records]] = ConcurrentDict[ulid.ULID, Records]()
            self._dispatch_agents: Union[ConcurrentSet[ulid.ULID], ConcurrentDict[ulid.ULID, Records]] = ConcurrentDict[ulid.ULID, Records]()
            self._reserved_dispatch_agents: Union[ConcurrentSet[ulid.ULID], ConcurrentDict[ulid.ULID, Records]] = ConcurrentDict[ulid.ULID, Records]()

        # Assignments by Category
        self._dismiss_sleep_agents = False  # Flag to indicate if throughput sleep agents should unregister
        self._reintegrate_agents = False #Agents will be internally switched to the appropriate required type

        # Assignments to Sleep for Dispatch
        self._sleep_dispatch_agents = ConcurrentSet[ulid.ULID]()
        self._check_sleep_dispatch_agents = False

        # Assignments to Sleep for Throughput
        self._sleep_throughput_agents = ConcurrentSet[ulid.ULID]()
        self._check_sleep_throughput_agents = False

        # Throughput Mode Queues
        self._throughput_queue: ConcurrentQueue[HelpRequest] = ConcurrentQueue[HelpRequest]()

        # FlowRegulator for managing thread signaling
        self._reserved_dispatch_flow_regulator = FlowRegulator(0)  # Untargeted flow regulator for non-targeted dispatch

        # General Purpose Flow Regulators
        self._dispatch_flow_regulator = FlowRegulator(0)  # Targeted flow regulator for targeted dispatch
        self._throughput_flow_regulator = FlowRegulator(0)  # Smart semaphore-like switch used for synchronization

        # Sleep Flow Regulator
        self._sleep_flow_regulator = FlowRegulator(0)  # Flow regulator for throughput sleep
        self._sleep_count = SyncInt(0)  # Count of agents currently in sleep mode

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

            self._throughput_flow_regulator.dispose()
            self._throughput_flow_regulator = None
            self._reserved_dispatch_flow_regulator.dispose()
            self._reserved_dispatch_flow_regulator = None
            self._dispatch_flow_regulator.dispose()
            self._dispatch_flow_regulator = None
            self._sleep_flow_regulator.dispose()
            self._sleep_flow_regulator = None
            self._active = False  # Mark container inactive

            # Manage Queue disposal
            if self._throughput_queue:
                self._throughput_queue.dispose()
                self._throughput_queue = None

            for records in self._registered_agents.values():
                records.dispose()

            # Clear references to CommandGroup
            self._command_group_worker_count = None  # Clear reference to CommandGroup
            self._command_group_max_worker_count = None  # Clear reference to CommandGroup
            self._command_group_id = None  # Clear reference to CommandGroup
            self._logger.info(f"Disposed AgentContainer for CommandGroup: {self._command_group_id}")
            self._logger = None  # Clear logger reference


    def _reserved_dispatch_loop(self):
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
                if self._reserved_dispatch_flow_regulator is None:
                    break  # Container was disposed mid-loop

                with self._reserved_dispatch_flow_regulator:
                    pass

                if not self._ignore_tracking:
                    self.attach_record()

                if self._check_dismissed:
                    if self._ignore_tracking:
                        self._reserved_dispatch_agents.discard(self._get_agent_id())
                    else:
                        self._reserved_dispatch_agents.pop(self._get_agent_id(), None)
                    threading.current_thread()._dismiss_agent = True
                    #TODO: We need to totally dismiss this agent from the command_group, and agent_container, and
                    #TODO: all required assets
                    return

        except Exception as e:
            self._logger.error(f"Error in agent pool container: {e}")

    def _dismiss_reserved_dispatch_agents(self, targets: Union[str, list[str]]):
        """
        Dismisses reserved dispatch agents by notifying them to unregister.

        Args:
            targets (Union[str, list[str]]): The agent IDs to dismiss.
        """
        raise NotImplementedError("This method is not ready yet.")
        if self._disposed:
            raise RuntimeError("Container has been disposed and cannot dismiss agents.")
        if isinstance(targets, str):
            targets = [targets]

        for target in targets:
            factory_id = ulid.ULID.from_str(target)
            if factory_id in self._reserved_dispatch_agents:
                self._unregister_agent(factory_id)
                self._logger.info(f"Dismissed reserved dispatch agent {factory_id}.")

    def _check_dismissed(self):
        """
        Determines whether the current thread is marked for unregistration.

        Returns:
            bool: True if the thread should unregister and exit.
        """
        if threading.current_thread()._pool_type == AgentPoolType.DISMISS:
             return True
        return False

    def _dispatch_loop(self):
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
                if self._dispatch_flow_regulator is None:
                    break  # Container was disposed mid-loop

                with self._dispatch_flow_regulator:
                    pass

                if not self._ignore_tracking:
                    self.attach_record()

                if self._check_sleep_dispatch_agents and self._should_sleep():
                    if self._ignore_tracking:
                        self._dispatch_agents.discard(self._get_agent_id())
                    else:
                        self._dispatch_agents.pop(self._get_agent_id(), None)
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
                if self._throughput_flow_regulator is None or self._throughput_queue is None:
                    break  # Container was disposed mid-loop


                while not self._throughput_queue.is_empty():
                    try:
                        help_request = self._throughput_queue.dequeue()
                        help_request.acquire_work()
                    finally:
                        if not self._ignore_tracking:
                            self.attach_record()

                with self._throughput_flow_regulator:
                    pass

                if self._check_sleep_throughput_agents and self._should_sleep():
                    if self._ignore_tracking:
                        self._throughput_agents.discard(self._get_agent_id())
                    else:
                        self._throughput_agents.pop(self._get_agent_id(), None)
                    return

        except Exception as e:
            self._logger.error(f"Error in agent pool container: {e}")


    def _sleep(self):
        """
        Agents in this space will eventually be decommissioned if there is no
        activity in their queue and they will be despawned, if activity increases
        the load balancing will kick in and reintroduce them.
        """
        factory_id = self._get_agent_id()  # Get the unique thread identifier
        if not factory_id in self._sleep_agents:
            self._sleep_agents.add(factory_id)

        while self._active and not self._disposed:
            if self._sleep_flow_regulator is None:
                break  # Container was disposed mid-loop

            with self._sleep_flow_regulator:
                pass

            if self._reintegrate_agents:
                pass

            if self._dismiss_sleep_agents and self._sleep_count > 0:
                self._sleep_count.decrement(1)
                self._finalize_dismissal()
                return

    def _request_dismiss_agents(self, number_of_agents: int):
        """
        This method will use the flow regulator in sleep to dismiss a number of agents
        """
        if self._disposed:
            raise RuntimeError("Container has been disposed and cannot request agent dismissal.")
        if number_of_agents > len(self._sleep_agents):
            raise ValueError("Number of agents to dismiss exceeds available sleep agents.")
        if number_of_agents <= 0:
            raise ValueError("Number of agents to dismiss must be greater than zero.")
        with self._lock:
            self._dismiss_sleep_agents = True  # Set flag to dismiss agents
            self._sleep_flow_regulator.notify(number_of_agents)
            self._sleep_count.increment(number_of_agents)

    def attach_record(self) -> None:
        """
        Attaches the current thread's `HelpRequest` (if present) to its associated `Records` entry
        in the agentic pool, assuming tracking is enabled.

        Raises:
            RuntimeError: If the current thread is not registered in the container.
        """
        thread_id = self._get_agent_id()  # Get the unique thread identifier

        # Try to fetch the current ValueWork task from the thread
        if value_work := getattr(threading.current_thread(), "_help_request", None):
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

            if self._check_if_agent_is_registered(factory_id):
                self._logger.warning(f"Thread {factory_id} is already registered in this container.")
                return
            pool_type = threading.current_thread()._pool_type
            if pool_type == AgentPoolType.DISPATCHER:
                if self._ignore_tracking:
                    self._dispatch_agents.add(factory_id)
                else:
                    self._dispatch_agents[factory_id] = Records()
                self._logger.info(f"Agent {factory_id} has been registered to dispatch.")
            elif pool_type == AgentPoolType.THROUGHPUT:
                if self._ignore_tracking:
                    self._throughput_agents.add(factory_id)
                else:
                    self._throughput_agents[factory_id] = Records()
                self._logger.info(f"Agent {factory_id} has been registered to throughput.")
            elif pool_type == AgentPoolType.RESERVED_DISPATCHER:
                if self._ignore_tracking:
                    self._reserved_dispatch_agents.add(factory_id)
                else:
                    self._reserved_dispatch_agents[factory_id] = Records()
                self._logger.info(f"Agent {factory_id} has been registered to reserved dispatch.")
            else:
                threading.current_thread()._pool_type = AgentPoolType.SLEEP
                self._logger.warning(f"Agent {factory_id} is not a valid pool type, defaulting to SLEEP.")
                self._sleep_agents.add(factory_id)

    def _check_if_agent_is_registered(self, factory_id: Union[str, ulid.ULID]) -> bool:
        """
        Checks if the given factory_id is registered in this container.

        Args:
            factory_id (str): The
        """
        if self._ignore_tracking:
            if factory_id in self._throughput_agents | self._sleep_agents | self._dispatch_agents | self._reserved_dispatch_agents:
                return True
        else:
            if factory_id in self._sleep_agents | set(self._throughput_agents.keys() + self._dispatch_agents.keys() + self._reserved_dispatch_agents.keys()):
                return True
        return False

    def _get_agent_id(self) -> ulid.ULID:
        """
        Returns the current thread's factory_id (ULID), which uniquely identifies it.

        Returns:
            ULID: The factory_id for the calling thread.
        """
        return threading.current_thread().factory_id

    def _should_sleep(self) -> bool:
        """
        Determines whether the current thread is marked for unregistration.

        Returns:
            bool: True if the thread should unregister and exit.
        """
        if threading.current_thread()._pool_type == AgentPoolType.SLEEP:
             return True
        return False

    def _finalize_dismissal(self):
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
        self._logger: logging.Logger = logger or logging.getLogger(__name__)
        self._command_group: 'CommandGroup' = command_group
        self._group_id: str = command_group.id
        self._agent_pool: AgentPool = agent_pool

        # Worker Management
        self._throughput_worker_count: SyncInt = SyncInt(60)
        self._dispatch_worker_count: SyncInt = SyncInt(40)
        self._targeted_dispatch_worker_count: SyncInt = SyncInt(0)

        # Container Management
        self._containers: Optional[ConcurrentDict[str, AgentContainer]] = ConcurrentDict[str, AgentContainer]() # UUID and Agent Container
        self._agents_in_container: ConcurrentDict[str, ConcurrentSet] =  ConcurrentDict[str, ConcurrentSet]()  # UUID and Agent Container
        self._max_size: Optional[SyncInt] = command_group._max_workers# Optional: max agents per container
        self._agents_per_container: SyncInt = command_group.agents_per_container

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
            self._command_group = None  # Clear reference to CommandGroup

            #Clear SyncInt Refs
            self._throughput_worker_count = None
            self._dispatch_worker_count = None
            self._targeted_dispatch_worker_count = None
            self._agents_per_container = None
            self._max_size = None

            # Dispose all containers in this group
            for container in self._containers.values():
                container.dispose()
            self._containers.dispose()
            self._containers = None  # Clear reference to containers
            self._agents_in_container.dispose()
            self._agents_in_container = None  # Clear reference to agent sets

            self._logger.warning(f"Disposed CommandGroupContainer for group ID: {self._group_id}")
            self._logger = None

#region Container Management

    def create_container(self) -> AgentContainer:
        """
        Creates and registers a new AgentContainer for this group.

        Returns:
            AgentContainer: The created and registered container.
        """
        if self._disposed:
            raise RuntimeError("CommandGroupContainer has been disposed.")

        container = AgentContainer(
            command_group=self._command_group,
            logger=self._logger,
            ignore_tracking=False
        )

        self.register_container(container)
        return container

    def register_container(self, container: AgentContainer):
        """
        Registers a new AgentContainer into the internal container registry.

        Args:
            container (AgentContainer): The container to register.
        """
        if self._disposed:
            raise RuntimeError("CommandGroupContainer has been disposed.")

        self._containers[container._id] = container
        self._agents_in_container[container._id] = ConcurrentSet()

    def unregister_container(self, container: AgentContainer):
        """
        Unregisters and removes a container from the internal registry.

        Args:
            container (AgentContainer): The container to remove.
        """
        if self._disposed:
            raise RuntimeError("CommandGroupContainer has been disposed.")

        self._containers.pop(container._id, None)
        self._agents_in_container.pop(container._id, None)

    def remove_container(self, container: AgentContainer) -> bool:
        """
        Unregisters and disposes a container from the group.

        Args:
            container (AgentContainer): The container to remove.

        Returns:
            bool: True if successfully removed, False otherwise.
        """
        if self._disposed:
            raise RuntimeError("CommandGroupContainer has been disposed.")

        try:
            self.unregister_container(container)
            container.dispose()
            return True
        except Exception as e:
            self._logger.warning(f"Failed to remove container: {e}")
            return False

    def get_or_create_container(self) -> AgentContainer:
        """
        Retrieves an available container or creates a new one if needed.

        Returns:
            AgentContainer: A container with space for new agents.
        """
        if self._disposed:
            raise RuntimeError("CommandGroupContainer has been disposed.")

        for container_id, container in self._containers.items():
            agent_count = len(self._agents_in_container[container_id])
            if agent_count < self._agents_per_container.value:
                return container

        return self.create_container()

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
            self._throughput_worker_count.set(throughput_agents)
            self._dispatch_worker_count.set(dispatch_agents)
            self._targeted_dispatch_worker_count.set(targeted_dispatch_agents)


#endregion Container Management
#region Targeted Retrieval System

#endregion Targeted Retrieval System
#region Agent Management

#endregion Agent Management

#region Work Management
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

#endregion Work Management

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