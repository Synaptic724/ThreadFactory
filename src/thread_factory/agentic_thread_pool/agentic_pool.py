from typing import Callable, Optional
import threading
from ulid import ULID
from thread_factory.concurrency import ConcurrentSet, ConcurrentQueue, ConcurrentList
from thread_factory.agentic_thread_pool import AgenticWorker
from thread_factory.primitives.switchlock import SwitchLock
from thread_factory.utils.interfaces.disposable import IDisposable


class _AgenticPoolContainer(IDisposable):
    def __init__(self):
        super().__init__()
        self._lock = threading.RLock()
        self._switch_lock = SwitchLock(0)
        self._active = False

        self._registered_threads = ConcurrentSet[ULID]()      # Threads currently looping
        self._unregistered_threads = ConcurrentSet[ULID]()    # Threads marked for shutdown externally
        self._unregister_thread_check = False

    def dispose(self):
        """
        Cleans up the container by unregistering all threads.
        """
        if self._disposed:
            return
        with self._lock:
            if self._disposed:
                return
            self._disposed = True
            self._unregistered_threads = self._registered_threads
            self._unregister_thread_check = True
            self._switch_lock.notify_all()
            self._switch_lock.dispose()
            self._active = False
            self._registered_threads.dispose()
            self._unregistered_threads.dispose()
            self._unregister_thread_check = False

    def _container(self):
        """
        Thread participation container for managing agentic threads.
        Handles registration, lifecycle tracking, and graceful unregistration.
        """
        if self._disposed:
            raise RuntimeError("Container has been disposed and cannot be used.")
        self._check_thread()
        self._register_thread()

        while self._active:
            with self._switch_lock:
                pass

            # Check if the current thread is marked for unregistration
            if self._unregister_thread_check:
                if self._should_exit():
                    self._finalize_unregistration()
                    return

    def _check_thread(self) -> None:
        """
        Validates that the current thread is an AgenticWorker.
        """
        current_thread = threading.current_thread()
        if not isinstance(current_thread, AgenticWorker):
            raise TypeError("Current thread must be an instance of AgenticWorker")

    def _register_thread(self):
        """
        Adds current thread to the registered thread set.
        """
        thread_id = self._get_thread_id()
        with self._lock:
            if not self._active:
                self._active = True
            if thread_id in self._registered_threads:
                return
            self._registered_threads.add(thread_id)

    def _get_thread_id(self) -> ULID:
        """Returns the current thread's factory ID."""
        return threading.current_thread().factory_id

    def _should_exit(self) -> bool:
        """
        Returns True if current thread is in the externally marked unregistration set.
        """
        thread_id = self._get_thread_id()
        return thread_id in self._unregistered_threads

    def _finalize_unregistration(self):
        """
        Cleanly unregisters the current thread.
        """
        thread_id = self._get_thread_id()
        self._registered_threads.discard(thread_id)

        if len(self._registered_threads) == 0:
            self._active = False
        if len(self._unregistered_threads) == 0:
            self._unregister_thread_check = False

    def _unregister_thread(self, thread_id: ULID):
        """
        Flags a thread to exit its container loop on next SwitchLock cycle.
        """
        self._unregistered_threads.add(thread_id)

        with self._lock:
            self._unregister_thread_check = True

class AgenticPool(IDisposable):
    """
    AgenticPool
    -----------
    A cooperative thread assistance system based on agentic execution principles.

    Unlike traditional thread pools that offload tasks into queues, AgenticPool enables
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
    AgenticPool empowers them to negotiate, respond, and collaborate under load.

    🧩 Integration Note:
    --------------------
    AgenticPool is a foundational component of the larger `MainPool` architecture,
    but it can also be used independently for standalone agentic threading needs.
    """
    def __init__(self, max_workers: int, min_workers: int = 1):
        super().__init__()
        self.max_workers = max_workers
        self.min_workers = min_workers
        self.worker_pool: ConcurrentList['AgenticWorker'] = ConcurrentList()
        self.task_queue = ConcurrentQueue()
        self.lock = threading.Lock()

        # Initially create workers up to min_workers
        self._create_workers(self.min_workers)

    def _create_workers(self, num_workers: int):
        """
        Creates workers and starts them.
        """
        for worker_id in range(len(self.worker_pool), len(self.worker_pool) + num_workers):
            worker = AgenticWorker()
            self.worker_pool.append(worker)
            worker.start()

    def submit_task(self, task: Callable):
        """
        Submits a new task to the pool.
        If there are not enough workers, create more.
        """
        with self.lock:
            if self._should_create_more_workers():
                self._create_workers(1)  # Create one more worker if needed
            self.task_queue.put(task)

    def _should_create_more_workers(self) -> bool:
        """
        Dynamically add more workers if the number of tasks exceeds the current worker pool size.
        """
        return self.task_queue.qsize() > len(self.worker_pool)

    def return_worker(self, worker: 'DynamicWorker'):
        """
        Returns a worker to the pool when done.
        """
        with self.lock:
            if self.task_queue.empty() and len(self.worker_pool) > self.min_workers:
                worker.shutdown()
                self.worker_pool.remove(worker)

    def shutdown(self):
        """
        Gracefully shuts down all workers in the pool.
        """
        with self.lock:
            for worker in self.worker_pool:
                worker.shutdown()

