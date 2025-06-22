import threading
import time
from queue import Queue
from typing import Callable, Optional, List
#from src.thread_factory.thread_pool.worker.dynamic_worker import DynamicWorker
from thread_factory.primatives import switchlock, smart_condition
#from thread_factory.runtime.worker.worker.worker import WorkerState
from thread_factory.concurrency import ConcurrentList, ConcurrentQueue, ConcurrentDict


# Dynapool class to manage the pool of workers and tasks
class Dynapool:
    def __init__(self, max_workers: int, min_workers: int = 1):
        self.max_workers = max_workers
        self.min_workers = min_workers
        self.worker_pool: ConcurrentList['DynamicWorker'] = []
        self.task_queue = Queue()
        self.lock = threading.Lock()

        # Initially create workers up to min_workers
        self._create_workers(self.min_workers)

    def _create_workers(self, num_workers: int):
        for _ in range(num_workers):
            #worker = Worker(id=str(len(self.worker_pool) + 1), task_queue=self.task_queue, dynapool=self)
            #self.worker_pool.append(worker)
            #worker.start()
            pass

    def submit_task(self, task: Callable):
        with self.lock:
            if self._should_create_more_workers():
                self._create_workers(1)  # Create one more worker if needed
            self.task_queue.put(task)

    def _should_create_more_workers(self) -> bool:
        # Dynamically add more workers if the number of tasks exceeds capacity
        return self.task_queue.qsize() > len(self.worker_pool)

    def return_worker(self, worker: 'Worker'):
        with self.lock:
            if self.task_queue.empty() and len(self.worker_pool) > self.min_workers:
                worker.shutdown()
                self.worker_pool.remove(worker)

    def shutdown(self):
        with self.lock:
            for worker in self.worker_pool:
                worker.shutdown()

# Example Task for the workers to run
def example_task():
    print(f"Task is being executed by {threading.current_thread().name}")
    time.sleep(1)
    print(f"Task completed by {threading.current_thread().name}")

# Example usage
if __name__ == "__main__":
    dynapool = Dynapool(max_workers=10)

    # Submit tasks
    for _ in range(20):
        dynapool.submit_task(example_task)

    # Wait for some tasks to finish before shutting down
    time.sleep(5)
    dynapool.shutdown()
