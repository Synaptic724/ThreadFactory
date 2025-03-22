#!/usr/bin/env python
"""
Benchmark script comparing:
1) A no-GIL, threaded ConcurrentQueue
2) A multiprocessing.Manager().Queue

Windows users:
 - We place multiprocess producer/consumer functions at the module level
   so they can be pickled.
 - Use 'if __name__ == "__main__":' guard to avoid recursive process spawns.
"""

import time
import threading
import multiprocessing
from typing import Callable

###############################################################################
# Multiprocessing Producer/Consumer Functions (Top Level)
###############################################################################

def multiproc_producer_fn(pid: int, items_per_producer: int, q, remaining, remaining_lock):
    """Producer function for multiprocessing."""
    for i in range(items_per_producer):
        q.put((pid, i))

def multiproc_consumer_fn(q, remaining, remaining_lock):
    """Consumer function for multiprocessing."""
    while True:
        with remaining_lock:
            if remaining.value <= 0:
                return
            remaining.value -= 1
        try:
            q.get_nowait()
        except:
            pass

###############################################################################
# Benchmark with THREADS (no-GIL, using your ConcurrentQueue)
###############################################################################

def benchmark_concurrent_queue(
    queue_factory: Callable[[], object],
    producers: int,
    consumers: int,
    items_per_producer: int
) -> float:
    """
    Benchmark a queue-like object by spawning `producers` threads that each enqueue
    `items_per_producer` items, and `consumers` threads that dequeue until all items
    have been consumed.
    """
    q = queue_factory()

    total_items = producers * items_per_producer
    remaining = total_items
    remaining_lock = threading.Lock()

    def producer_fn(pid: int):
        for i in range(items_per_producer):
            q.enqueue((pid, i))

    def consumer_fn():
        nonlocal remaining
        while True:
            with remaining_lock:
                if remaining <= 0:
                    return
                remaining -= 1
            try:
                q.dequeue()
            except IndexError:
                pass  # queue empty momentarily

    threads = []
    for pid in range(producers):
        threads.append(threading.Thread(target=producer_fn, args=(pid,)))
    for _ in range(consumers):
        threads.append(threading.Thread(target=consumer_fn))

    start = time.perf_counter()

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    end = time.perf_counter()
    elapsed = end - start
    return elapsed

###############################################################################
# Benchmark with MULTIPROCESSING
###############################################################################

def benchmark_multiprocessing_queue(
    producers: int,
    consumers: int,
    items_per_producer: int
) -> float:
    """
    Similar benchmark, but uses a multiprocessing Queue and processes
    instead of threads.
    """
    manager = multiprocessing.Manager()
    q = manager.Queue()

    total_items = producers * items_per_producer
    remaining = manager.Value('i', total_items)
    remaining_lock = manager.Lock()

    processes = []
    # Producer processes
    for pid in range(producers):
        p = multiprocessing.Process(
            target=multiproc_producer_fn,
            args=(pid, items_per_producer, q, remaining, remaining_lock)
        )
        processes.append(p)
    # Consumer processes
    for _ in range(consumers):
        p = multiprocessing.Process(
            target=multiproc_consumer_fn,
            args=(q, remaining, remaining_lock)
        )
        processes.append(p)

    start = time.perf_counter()
    for p in processes:
        p.start()
    for p in processes:
        p.join()
    end = time.perf_counter()

    return end - start

###############################################################################
# Main Benchmark Runner
###############################################################################

def run_benchmark():
    """
    Example usage comparing your no-GIL ConcurrentQueue vs. a multiprocessing queue.
    Adjust producers/consumers/items_per_producer as needed for your tests.
    """
    producers = 15
    consumers = 15
    items_per_producer = 100_000

    # 1) Test your no-GIL ConcurrentQueue
    from Threading.Queue import ConcurrentQueue  # or your actual path
    def create_concurrent_queue():
        return ConcurrentQueue()

    elapsed_concurrent_queue = benchmark_concurrent_queue(
        create_concurrent_queue,
        producers=producers,
        consumers=consumers,
        items_per_producer=items_per_producer
    )
    print(f"ConcurrentQueue (threads, no-GIL) => {elapsed_concurrent_queue:.3f} seconds")

    # 2) Test multiprocessing
    elapsed_multiproc = benchmark_multiprocessing_queue(
        producers=producers,
        consumers=consumers,
        items_per_producer=items_per_producer
    )
    print(f"Multiprocessing Queue => {elapsed_multiproc:.3f} seconds")

###############################################################################
# Script Entry Point
###############################################################################

if __name__ == "__main__":
    run_benchmark()
