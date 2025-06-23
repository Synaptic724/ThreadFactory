import threading
from queue import Queue
from typing import Callable, Optional
from thread_factory.concurrency import ConcurrentList
from thread_factory.thread_pool import DynamicWorker

# Dynapool class to manage the pool of workers and tasks
class Dynapool:
    def __init__(self, max_workers: int, min_workers: int = 1):
        self.max_workers = max_workers
        self.min_workers = min_workers
        self.worker_pool: ConcurrentList['DynamicWorker'] = ConcurrentList()
        self.task_queue = Queue()
        self.lock = threading.Lock()

        # Initially create workers up to min_workers
        self._create_workers(self.min_workers)

    def _create_workers(self, num_workers: int):
        """
        Creates workers and starts them.
        """
        for worker_id in range(len(self.worker_pool), len(self.worker_pool) + num_workers):
            worker = DynamicWorker()
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


# Example Task for the workers to run
def example_task():
    print(f"Task is being executed by {threading.current_thread().name}")
    time.sleep(1)
    print(f"Task completed by {threading.current_thread().name}")

# Example usage
if __name__ == "__main__":
    dynapool = Dynapool(max_workers=5, min_workers=2)

    # Submit tasks
    for _ in range(20):
        dynapool.submit_task(example_task)

    # Wait for some tasks to finish before shutting down
    time.sleep(5)
    dynapool.shutdown()
