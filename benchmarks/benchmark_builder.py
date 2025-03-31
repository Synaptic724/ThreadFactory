import sys
import time
import threading
import multiprocessing
from abc import ABC, abstractmethod
from typing import Dict, Any, Callable
from collections import deque

# Replace these with your actual concurrency classes:
from thread_factory import ConcurrentBuffer, ConcurrentCollection, ConcurrentQueue, Empty


def check_gil_enabled() -> bool:
    """
    Helper to check if GIL is enabled (Python 3.13+),
    else assume True if the attribute is not found.
    """
    try:
        return sys._is_gil_enabled()
    except AttributeError:
        return True


###############################################################################
# Base Class for all concurrency benchmarks
###############################################################################
class BaseBenchmark(ABC):
    """
    Each derived class implements a concurrency test with run_benchmark(...).
    """

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def run_benchmark(
        self
    ) -> None:
        """
        Execute the concurrency test and call 'callback' with a dictionary
        containing measurement data, e.g.:
            {
                "duration": ...,
                "remaining": ...,
                "gil_enabled": ...
            }
        """
        pass


###############################################################################
# Concrete Benchmark: ConcurrentBuffer + Threads
###############################################################################
class ConcurrentBufferThreadsBenchmark(BaseBenchmark):
    def __init__(self, **kwargs: Dict[str, Any]):
        super().__init__("concurrent_buffer")
        self.callback: Any = kwargs["callback"]
        self.producers: Any = kwargs["producers"]
        self.consumers: Any = kwargs["consumers"]
        self.items_per_producer: Any = kwargs["items_per_producer"]

    def run_benchmark(self):
        print(f"\n[{self.name}] GIL Enabled: {check_gil_enabled()}")
        total_items = self.producers * self.items_per_producer
        buffer = ConcurrentBuffer(10)

        def producer(thread_id):
            for i in range(self.items_per_producer):
                buffer.enqueue((thread_id, i))

        # Distribute total_items among consumers
        base_target = total_items // self.consumers
        targets = [base_target] * self.consumers
        for i in range(total_items % self.consumers):
            targets[i] += 1

        def consumer(target):
            consumed = 0
            while consumed < target:
                try:
                    _ = buffer.dequeue()
                    consumed += 1
                except Empty:
                    pass

        threads = []
        for pid in range(self.producers):
            threads.append(threading.Thread(target=producer, args=(pid,)))
        for i in range(self.consumers):
            threads.append(threading.Thread(target=consumer, args=(targets[i],)))

        print(f"[{self.name}] Starting {self.producers} producers / {self.consumers} consumers...")
        start = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        end = time.perf_counter()

        duration = end - start
        remaining = len(buffer)

        print(f"[{self.name}] {total_items:,} ops completed in {duration:.2f} seconds.")
        print(f"[{self.name}] Final buffer length: {remaining}\n")

        self.callback({
            "duration": duration,
            "remaining": remaining,
            "gil_enabled": check_gil_enabled()
        })


###############################################################################
# ConcurrentCollection + Threads
###############################################################################
class ConcurrentCollectionThreadsBenchmark(BaseBenchmark):
    def __init__(self, **kwargs: Dict[str, Any]):
        super().__init__("concurrent_collection")
        self.callback: Any = kwargs["callback"]
        self.producers: Any = kwargs["producers"]
        self.consumers: Any = kwargs["consumers"]
        self.items_per_producer: Any = kwargs["items_per_producer"]

    def run_benchmark(self):
        print(f"\n[{self.name}] GIL Enabled: {check_gil_enabled()}")
        total_items = self.producers * self.items_per_producer
        buf = ConcurrentCollection((self.producers + self.consumers) * 2)

        def producer(thread_id):
            for i in range(self.items_per_producer):
                buf.add((thread_id, i))

        base_target = total_items // self.consumers
        targets = [base_target] * self.consumers
        for i in range(total_items % self.consumers):
            targets[i] += 1

        def consumer(target):
            consumed = 0
            while consumed < target:
                try:
                    _ = buf.pop()
                    consumed += 1
                except Empty:
                    pass

        threads = []
        for pid in range(self.producers):
            threads.append(threading.Thread(target=producer, args=(pid,)))
        for i in range(self.consumers):
            threads.append(threading.Thread(target=consumer, args=(targets[i],)))

        print(f"[{self.name}] Starting {self.producers} producers / {self.consumers} consumers...")
        start = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        end = time.perf_counter()

        duration = end - start
        remaining = len(buf)

        print(f"[{self.name}] {total_items:,} ops completed in {duration:.2f} seconds.")
        print(f"[{self.name}] Final buffer length: {remaining}\n")

        self.callback({
            "duration": duration,
            "remaining": remaining,
            "gil_enabled": check_gil_enabled()
        })


###############################################################################
# ConcurrentQueue + Threads
###############################################################################
class ConcurrentQueueThreadsBenchmark(BaseBenchmark):
    def __init__(self, **kwargs: Dict[str, Any]):
        super().__init__("concurrent_queue")
        self.callback: Any = kwargs["callback"]
        self.producers: Any = kwargs["producers"]
        self.consumers: Any = kwargs["consumers"]
        self.items_per_producer: Any = kwargs["items_per_producer"]

    def run_benchmark(self):
        print(f"\n[{self.name}] GIL Enabled: {check_gil_enabled()}")
        total_items = self.producers * self.items_per_producer
        q = ConcurrentQueue()

        def producer(thread_id):
            for i in range(self.items_per_producer):
                q.enqueue((thread_id, i))

        base_target = total_items // self.consumers
        targets = [base_target] * self.consumers
        for i in range(total_items % self.consumers):
            targets[i] += 1

        def consumer(target):
            consumed = 0
            while consumed < target:
                try:
                    _ = q.dequeue()
                    consumed += 1
                except Empty:
                    pass

        threads = []
        for pid in range(self.producers):
            threads.append(threading.Thread(target=producer, args=(pid,)))
        for i in range(self.consumers):
            threads.append(threading.Thread(target=consumer, args=(targets[i],)))

        print(f"[{self.name}] Starting {self.producers} producers / {self.consumers} consumers...")
        start = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        end = time.perf_counter()

        duration = end - start
        remaining = len(q)

        print(f"[{self.name}] {total_items:,} ops completed in {duration:.2f} seconds.")
        print(f"[{self.name}] Final queue length: {remaining}\n")

        self.callback({
            "duration": duration,
            "remaining": remaining,
            "gil_enabled": check_gil_enabled()
        })


###############################################################################
# collections.deque + Threads
###############################################################################
class CollectionsDequeThreadsBenchmark(BaseBenchmark):
    def __init__(self, **kwargs: Dict[str, Any]):
        super().__init__("collections_deque")
        self.callback: Any = kwargs["callback"]
        self.producers: Any = kwargs["producers"]
        self.consumers: Any = kwargs["consumers"]
        self.items_per_producer: Any = kwargs["items_per_producer"]

    def run_benchmark(self):
        print(f"\n[{self.name}] GIL Enabled: {check_gil_enabled()}")
        total_items = self.producers * self.items_per_producer
        dq = deque()

        def producer(thread_id):
            for i in range(self.items_per_producer):
                dq.append((thread_id, i))

        base_target = total_items // self.consumers
        targets = [base_target] * self.consumers
        for i in range(total_items % self.consumers):
            targets[i] += 1

        def consumer(target):
            consumed = 0
            while consumed < target:
                if dq:
                    _ = dq.popleft()
                    consumed += 1

        threads = []
        for pid in range(self.producers):
            threads.append(threading.Thread(target=producer, args=(pid,)))
        for i in range(self.consumers):
            threads.append(threading.Thread(target=consumer, args=(targets[i],)))

        print(f"[{self.name}] Starting {self.producers} producers / {self.consumers} consumers...")
        start = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        end = time.perf_counter()

        duration = end - start
        remaining = len(dq)

        print(f"[{self.name}] {total_items:,} ops completed in {duration:.2f} seconds.")
        print(f"[{self.name}] Final deque length: {remaining}\n")

        self.callback({
            "duration": duration,
            "remaining": remaining,
            "gil_enabled": check_gil_enabled()
        })


def producer_process(q, item_count, pid):
    for i in range(item_count):
        q.put((pid, i))

def consumer_process(q, item_count):
    consumed = 0
    while consumed < item_count:
        try:
            _ = q.get()
            consumed += 1
        except:
            pass

###############################################################################
# multiprocessing.Queue + Processes
###############################################################################
class MultiprocessingQueueBenchmark(BaseBenchmark):
    def __init__(self, **kwargs: Dict[str, Any]):
        super().__init__("multiprocessing_queue")
        self.callback: Any = kwargs["callback"]
        self.producers: Any = kwargs["producers"]
        self.consumers: Any = kwargs["consumers"]
        self.items_per_producer: Any = kwargs["items_per_producer"]

    def run_benchmark(self):
        print(f"\n[{self.name}] GIL Enabled: {check_gil_enabled()}")
        total_items = self.producers * self.items_per_producer
        queue = multiprocessing.Queue()

        base_target = total_items // self.consumers
        targets = [base_target] * self.consumers
        for i in range(total_items % self.consumers):
            targets[i] += 1

        processes = []

        # Spawn producers
        for pid in range(self.producers):
            p = multiprocessing.Process(target=producer_process, args=(queue, self.items_per_producer, pid))
            processes.append(p)

        # Spawn consumers
        for i in range(self.consumers):
            p = multiprocessing.Process(target=consumer_process, args=(queue, targets[i]))
            processes.append(p)

        print(f"[{self.name}] Starting {self.producers} producers / {self.consumers} consumers...")
        start = time.perf_counter()
        for p in processes:
            p.start()
        for p in processes:
            p.join()
        end = time.perf_counter()

        duration = end - start
        try:
            remaining = queue.qsize()
        except NotImplementedError:
            remaining = "Unknown (platform-dependent)"

        print(f"[{self.name}] {total_items:,} ops completed in {duration:.2f} seconds.")
        print(f"[{self.name}] Final queue length: {remaining}\n")

        self.callback({
            "duration": duration,
            "remaining": remaining,
            "gil_enabled": check_gil_enabled()
        })


###############################################################################
# BenchmarkFactory – Return concurrency test classes by name
###############################################################################
class BenchmarkFactory:
    _registered = {
        "concurrent_buffer": ConcurrentBufferThreadsBenchmark,
        "concurrent_collection": ConcurrentCollectionThreadsBenchmark,
        "concurrent_queue": ConcurrentQueueThreadsBenchmark,
        "collections_deque": CollectionsDequeThreadsBenchmark,
        "multiprocessing_queue": MultiprocessingQueueBenchmark
    }

    @classmethod
    def get_benchmark(cls, name: str, **kwargs) -> BaseBenchmark:
        if name not in cls._registered:
            raise ValueError(f"No concurrency test for '{name}'")
        return cls._registered[name](**kwargs)
