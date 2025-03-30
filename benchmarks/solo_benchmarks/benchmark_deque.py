import threading
import time
from collections import deque

def benchmark(label, lock_type, num_threads=20, iterations=100_000):
    queue = deque()
    stop_event = threading.Event()
    counter = [0]

    # Choose lock type
    if lock_type == "lock":
        lock = threading.Lock()
    elif lock_type == "rlock":
        lock = threading.RLock()
    else:
        lock = None  # No lock

    def worker():
        local_count = 0
        while not stop_event.is_set() and local_count < iterations:
            if lock:
                with lock:
                    queue.append(1)
                with lock:
                    queue.popleft()
            else:
                queue.append(1)
                queue.popleft()
            local_count += 1
        counter[0] += local_count

    threads = [threading.Thread(target=worker) for _ in range(num_threads)]

    # Start benchmark
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    end = time.perf_counter()

    total_time = end - start
    print(f"=== [{label}] ===")
    print(f"Threads: {num_threads}")
    print(f"Total Operations: {counter[0]}")
    print(f"Total Time: {total_time:.6f} sec")
    print(f"Throughput: {counter[0] / total_time:.2f} ops/sec\n")

# Run all variants
benchmark("deque + Lock", "lock")
benchmark("deque + RLock", "rlock")
benchmark("deque (No Lock)", "none")
