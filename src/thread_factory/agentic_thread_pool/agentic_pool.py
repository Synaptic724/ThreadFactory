import threading
from queue import Queue
from typing import Callable, Optional
from ulid import ULID
from thread_factory.concurrency import ConcurrentList
from thread_factory.agentic_thread_pool import AgenticWorker
from thread_factory.primitives.switchlock import SwitchLock
from thread_factory.utils.interfaces.disposable import IDisposable

class _AgenticPoolContainer(IDisposable):
    def __init__(self):
        super().__init__()
        self._switch_lock = SwitchLock(0)
        self._active = False
        self._registered_threads = ConcurrentList[ULID]()
        self._unregistered_threads = ConcurrentList[ULID]() # We need to incorporate unregistered threads into the system. #TODO: Implement unregistered threads handling
        self._unregister_thread_check = False
        self._unregister_lock = threading.RLock()

    def _container(self):
        """
        A container for managing dynamic threads.
        """
        self._check_thread()
        self._register_thread()

        while self._active:
            with self._switch_lock:
                pass

            if self._unregister_thread_check:
                if self._return_if_unregistered:
                    return

    def _check_thread(self) -> None:
        """
        Checks if a thread is registered in the container.
        """
        current_thread = threading.current_thread()
        if not isinstance(current_thread, AgenticWorker):
            raise TypeError("Current thread must be an instance of DynamicWorker")

    def _register_thread(self):
        """
        Adds a thread to the container and increments the thread count.
        """
        with self._switch_lock:
            if not self._active:
                self._active = True
            id = threading.current_thread().factory_id
            # Check if the thread is already registered
            if id in self._registered_threads:
                return
            self._registered_threads.append(id)

    def _return_if_unregistered(self):
        """
        Checks if the current thread is unregistered and sets the flag to unregister.
        """
        with self._unregister_lock:
            if threading.current_thread().factory_id not in self._registered_threads:
                self._unregister_thread_check = True
                return True
        return False

    def _unregister_thread(self, thread_id: ULID):
        """
        Removes a thread from the container and decrements the thread count.
        """
        with self._switch_lock:
            if not self._active:
                return
            # Check if the thread is registered
            if thread_id not in self._registered_threads:
                return
            self._registered_threads.remove(thread_id)
            if len(self._registered_threads) == 0:
                self._active = False

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
        self.task_queue = Queue()
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

