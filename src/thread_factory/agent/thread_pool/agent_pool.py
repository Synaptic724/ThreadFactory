import logging, threading, time
from typing import Callable, Union
from ulid import ULID
from thread_factory.runtime.orchestrator.monitoring.records.records import WorkStatus, Record
from thread_factory.agent.identity.types.agent import Agent
from thread_factory.agent.command_center import CommandCenter
from thread_factory.agent.thread_pool import HelpRequest
from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.concurrency.concurrent_queue import ConcurrentQueue
from thread_factory.concurrency.concurrent_set import ConcurrentSet
from thread_factory.concurrency.concurrent_dictionary import ConcurrentDict
from thread_factory.synchronization.primitives.flow_regulator import FlowRegulator
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

    def __init__(self, ignore_tracking: bool = False):
        """
        Initializes the container.

        Args:
            ignore_tracking (bool): If True, no Records will be tracked per-thread.
                                    Instead, threads are tracked using only a ULID set.
        """
        super().__init__()
        self._lock = threading.RLock()  # Internal lock for safe concurrent modifications
        self._flow_regulator = FlowRegulator(0)  # Smart semaphore-like switch used for synchronization
        self._active = False  # Flag to indicate whether the container is active
        self._ignore_tracking = ignore_tracking  # Whether to store tracking Records or not

        # Track threads either as a simple set (if no tracking) or as a dict mapping to Records
        if ignore_tracking:
            self._registered_threads: Union[ConcurrentSet[ULID], ConcurrentDict[ULID, Records]] = ConcurrentSet[ULID]()
        else:
            self._registered_threads: Union[ConcurrentSet[ULID], ConcurrentDict[ULID, Records]] = ConcurrentDict[
                ULID, Records]()

        self._unregistered_threads = ConcurrentSet[ULID]()  # Tracks which threads have been requested to unregister
        self._unregister_thread_check = False  # Flag to indicate if any threads should unregister

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
                self._unregistered_threads = self._registered_threads
            else:
                self._unregistered_threads = ConcurrentSet(self._registered_threads.keys())

            self._unregister_thread_check = True
            self._flow_regulator.notify_all()  # Wake all threads
            self._flow_regulator.dispose()  # Dispose of the switch lock
            self._active = False  # Mark container inactive
            self._registered_threads.dispose()  # Dispose of registry
            self._unregistered_threads.dispose()  # Dispose of unregistration list
            self._unregister_thread_check = False

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
        self._check_thread()  # Validate the thread is an AgenticWorker
        self._register_thread()  # Add thread to the pool registry

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
        thread_id = self._get_thread_id()  # Get the unique thread identifier

        # Try to fetch the current ValueWork task from the thread
        if value_work := getattr(threading.current_thread(), "_value_work", None):
            # Ensure this thread is registered before assigning work
            if thread_id not in self._registered_threads:
                raise RuntimeError("Thread is not registered in the AgenticPoolContainer.")

            # Attach the task into the record structure
            records = self._registered_threads.get(thread_id)
            records[value_work.task_id] = value_work

    def _check_thread(self) -> None:
        """
        Ensures the calling thread is a valid AgenticWorker.
        """
        current_thread = threading.current_thread()
        if not isinstance(current_thread, 'Agent'):
            raise TypeError("Current thread must be an instance of AgenticWorker")

    def _register_thread(self):
        """
        Registers the current thread in the container.

        Depending on `ignore_tracking`, either adds to a set or creates a Records entry.
        """
        thread_id = self._get_thread_id()
        with self._lock:
            if not self._active:
                self._active = True
            if self._ignore_tracking:
                self._registered_threads.add(thread_id)
            else:
                if thread_id not in self._registered_threads:
                    self._registered_threads[thread_id] = Records()

    def _get_thread_id(self) -> ULID:
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
        return self._get_thread_id() in self._unregistered_threads

    def _finalize_unregistration(self):
        """
        Final cleanup for a thread that is leaving the container.
        Disposes its tracking record and removes it from the active registry.
        """
        thread_id = self._get_thread_id()
        if not self._ignore_tracking:
            if records := self._registered_threads.get(thread_id):
                records.dispose()
        if self._ignore_tracking:
            self._registered_threads.discard(thread_id)
        else:
            self._registered_threads.pop(thread_id, None)

        # If the registry is now empty, mark inactive
        if len(self._registered_threads) == 0:
            self._active = False
        # If no more threads left to unregister, unset the check flag
        if len(self._unregistered_threads) == 0:
            self._unregister_thread_check = False

    def _unregister_thread(self, thread_id: ULID):
        """
        Marks a thread for unregistration and notifies it if it's waiting.

        Args:
            thread_id (ULID): The ID of the thread to unregister.
        """
        self._unregistered_threads.add(thread_id)
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
    AgentPool
    -----------
    A cooperative thread assistance system based on agentic execution principles.

    Unlike traditional thread pools that offload tasks into queues, AgentPool enables
    the calling thread to immediately begin executing work while optionally requesting
    help from agentic workers via `HelpRequest` contracts.

    ⚙️ Core Idea:
    -------------
    • The caller does not delegate — it initiates the work.
    • Agentic workers may choose to assist — or not.
    • If help never arrives, the caller is still responsible.
    • The workload is shared, not offloaded.

    🎯 Features:
    ------------
    • **Backpressure-aware** — Help is only requested if workers are available.
    • **Mutual-completion** — Either the caller or a worker may finalize the work.
    • **Lifecycle-transparent** — Each `HelpRequest` tracks its execution journey.
    • **Autonomous coordination** — Workers act voluntarily and return home when done.

    🧠 Use Cases:
    -------------
    - High-throughput cooperative systems (e.g., shared queues, concurrent stacks).
    - Situations where every available thread, including the caller, should contribute.
    - Agent-like thread orchestration where execution follows intention, not enforcement.
    - Systems requiring dynamic, graceful thread participation under pressure.
    - Existing thread pools that need extra throughput for dealing with spikes in demand.

    🧵 Philosophy:
    --------------
    Threads are not subordinates—they are peers in a dynamic execution model.
    AgentPool empowers them to negotiate, respond, and collaborate under load.

    🧩 Integration Note:
    --------------------
    AgentPool is a foundational component of the larger `MainPool` architecture,
    but it can also be used independently for standalone agentic threading needs.
    """

    class AgentPool(IDisposable):
        """
        A cooperative, auto-scaling auxiliary thread pool for handling bursty,
        parallelizable workloads.
        """

        def __init__(self, command_center: CommandCenter, group_name: str, min_workers: int = 0, max_workers: int = 10):
            super().__init__()
            if not command_center or not isinstance(command_center, CommandCenter):
                raise TypeError("A valid CommandCenter instance is required.")

            self._lock = threading.RLock()
            self._command_center = command_center
            self._group_name = group_name
            self.min_workers = min_workers
            self.max_workers = max_workers

            self._pool_container = _AgentPoolContainer()
            self._all_workers = ConcurrentSet()
            self._shutdown = threading.Event()

            # The Maintenance Worker
            self._maintenance_agent = self._create_maintenance_worker()
            self._maintenance_agent.deploy()

        def dispose(self):
            if self._disposed: return
            with self._lock:
                self._disposed = True
                self._shutdown.set()
                # Politely ask all workers to shut down
                for worker_id in list(self._all_workers):
                    self._retire_worker_by_id(worker_id)

                # Ensure maintenance agent is stopped
                if self._maintenance_agent:
                    self._maintenance_agent.shutdown_flag.set()
                    self._maintenance_agent = None

                self._pool_container.dispose()
                self._all_workers.dispose()

        def submit(self, help_request: HelpRequest, num_workers: int):
            """
            Submits a parallel job to the pool, requesting a specific number of agents.
            """
            if self._disposed:
                raise RuntimeError("AgentPool has been disposed.")
            if num_workers <= 0:
                raise ValueError("Number of workers must be positive.")
            if num_workers > self.max_workers:
                logging.warning(f"Request for {num_workers} workers exceeds pool max of {self.max_workers}. Capping.")
                num_workers = self.max_workers

            help_request.record.status = WorkStatus.IN_PROGRESS
            self._pool_container.dispatch_work(help_request, num_workers)

        def _create_maintenance_worker(self) -> Agent:
            """Creates the dedicated agent responsible for pool scaling."""
            # The maintenance agent does not count towards the user-facing worker pool limits.
            # It's created in the 'default' group to keep it separate.
            agent = self._command_center.create_agent(
                template_name="default",
                target=self._maintenance_loop,
                command_group_name="default"  # Or a dedicated internal group
            )
            return agent

        def _maintenance_loop(self):
            """The main logic for the maintenance agent."""
            while not self._shutdown.is_set():
                try:
                    with self._lock:
                        # --- Scale Up ---
                        if len(self._all_workers) < self.min_workers:
                            self._add_worker()

                        # --- Scale Down (Example Logic) ---
                        # A more sophisticated logic could check for sustained idle time.
                        if self._pool_container.get_idle_worker_count() > self.min_workers:
                            if len(self._all_workers) > self.min_workers:
                                worker_to_retire = self._pool_container.get_idle_workers(1)
                                if worker_to_retire:
                                    self._retire_worker_by_id(worker_to_retire[0].factory_id)

                except Exception as e:
                    logging.error(f"Error in AgentPool maintenance loop: {e}")

                time.sleep(2)  # Maintenance check interval

        def _add_worker(self):
            """Requests a new worker from the CommandCenter and adds it to the pool."""
            if len(self._all_workers) >= self.max_workers:
                return  # Cannot exceed max workers

            agent = self._command_center.create_agent(
                template_name="general_agent",  # Use the customizable General agent
                define_home=self._pool_container.agent_home_loop,
                command_group_name=self._group_name
            )
            if agent:
                self._all_workers.add(agent.factory_id)
                agent.deploy()
                logging.info(f"AgentPool added worker {agent.factory_id}. Total workers: {len(self._all_workers)}")

        def _retire_worker_by_id(self, agent_id: str):
            """Retires a specific worker from the pool."""
            if agent_id in self._all_workers:
                agent = self._command_center.find_agent_by_id(agent_id)
                if agent:
                    agent.shutdown_flag.set()  # Signal the agent's home loop to exit
                    self._pool_container._flow_regulator.release(n=1)  # Wake it up to process the shutdown
                    self._all_workers.remove(agent_id)
                    logging.info(f"AgentPool retired worker {agent_id}. Total workers: {len(self._all_workers)}")
