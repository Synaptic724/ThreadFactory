import concurrent.futures
import os
import threading
from thread_factory.utils import Disposable

class ThreadFactory:
    _shared_pool = None
    _lock = threading.Lock()

    def __init__(self, max_workers=None, dynamic=True, singleton=False):
        self.dynamic = dynamic
        self.shutdown_flag = threading.Event()
        self.max_workers = max_workers or self._detect_cores()

        # Singleton behavior at launch
        if singleton:
            if ThreadFactory._shared_pool:
                raise Exception("Shared pool already exists! Use get_shared_pool() instead.")
            with ThreadFactory._lock:
                ThreadFactory._shared_pool = self

        # Create workers and queues
        self.queues = []
        self.workers = []
        self._create_workers(self.max_workers)

        # Optionally start scaling loop
        self._scaler_thread = None
        if self.dynamic:
            self._start_scaling_loop()

    @classmethod
    def get_shared_pool(cls):
        with cls._lock:
            if cls._shared_pool is None:
                cls._shared_pool = ThreadFactory(singleton=True)
            return cls._shared_pool

    @staticmethod
    def _detect_cores():
        return os.cpu_count() or 4

#concurrent.futures.ThreadPoolExecutor = ThreadPoolManager
