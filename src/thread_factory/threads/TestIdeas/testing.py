from collections import Counter
import time
import random
import threading

import time
import random

import random
import time
from collections import Counter

def select_shard(num_shards: int) -> int:
    ns = time.monotonic_ns()
    mixed = ((ns >> 3) ^ ns) % num_shards
    return mixed

def select_shard_rr(num_shards: int) -> int:
    select_shard_rr.counter = getattr(select_shard_rr, 'counter', -1) + 1
    return select_shard_rr.counter % num_shards

def test_select_shard_distribution(num_shards: int = 10, iterations: int = 1_000_000):
    counts = Counter()
    for _ in range(iterations):
        idx = select_shard(num_shards)
        counts[idx] += 1

    total = sum(counts.values())
    print(f"--- select_shard() Distribution over {num_shards} shards ---")
    for k in range(num_shards):
        pct = (counts[k] / total) * 100
        print(f"  Shard {k}: {counts[k]} hits ({pct:.2f}%)")

def test_select_vs_random_ns(num_shards: int = 16, iterations: int = 10_000_000):
    print(f"\nRunning {iterations:,} iterations with {num_shards} shards...\n")

    # Time select_shard()
    start = time.perf_counter()
    for _ in range(iterations):
        _ = select_shard(num_shards)
    duration_select = time.perf_counter() - start

    # Time select_shard_rr()
    start = time.perf_counter()
    for _ in range(iterations):
        _ = select_shard_rr(num_shards)
    duration_select_rr = time.perf_counter() - start

    # Time random.randint()
    start = time.perf_counter()
    for _ in range(iterations):
        _ = random.randint(0, num_shards - 1)
    duration_randint = time.perf_counter() - start

    # Time random.randrange()
    start = time.perf_counter()
    for _ in range(iterations):
        _ = random.randrange(num_shards)
    duration_randrange = time.perf_counter() - start

    # Convert to nanoseconds per operation
    ns_per_op = lambda duration: (duration / iterations) * 1e9

    print(f"select_shard():      {duration_select:.4f} sec | {ns_per_op(duration_select):.2f} ns/op")
    print(f"select_shard_rr():   {duration_select_rr:.4f} sec | {ns_per_op(duration_select_rr):.2f} ns/op")
    print(f"random.randint():    {duration_randint:.4f} sec | {ns_per_op(duration_randint):.2f} ns/op")
    print(f"random.randrange():  {duration_randrange:.4f} sec | {ns_per_op(duration_randrange):.2f} ns/op")


# ✅ Distribution test
test_select_shard_distribution(num_shards=50)

# ✅ Performance test
test_select_vs_random_ns(50, iterations=1_000_000)





import time
import threading
from array import array

def test_speed_list_vs_array(iterations=1_000_000):
    results = {}

    # Test: plain list indexing (lockless)
    lst = [0] * 16
    start = time.perf_counter()
    for i in range(iterations):
        lst[i % 16] = i
    results['list_lockless'] = time.perf_counter() - start

    # Test: plain array indexing (lockless)
    arr = array('Q', [0] * 16)
    start = time.perf_counter()
    for i in range(iterations):
        arr[i % 16] = i
    results['array_lockless'] = time.perf_counter() - start

    # Prepare locks
    locks = [threading.Lock() for _ in range(16)]

    # Test: list indexing with lock
    lst = [0] * 16
    start = time.perf_counter()
    for i in range(iterations):
        idx = i % 16
        with locks[idx]:
            lst[idx] = i
    results['list_locked'] = time.perf_counter() - start

    # Test: array indexing with lock
    arr = array('Q', [0] * 16)
    start = time.perf_counter()
    for i in range(iterations):
        idx = i % 16
        with locks[idx]:
            arr[idx] = i
    results['array_locked'] = time.perf_counter() - start

    return results

results = test_speed_list_vs_array()
print(results)

import threading
import time

N = 1_000_000
test_list = [0] * 10
lock = threading.Lock()
rlock = threading.RLock()

def lock_access():
    for _ in range(N):
        with lock:
            test_list[0] += 1

def rlock_access():
    for _ in range(N):
        with rlock:
            test_list[0] += 1

# Lock
start = time.perf_counter()
lock_access()
lock_total = time.perf_counter() - start

# RLock
start = time.perf_counter()
rlock_access()
rlock_total = time.perf_counter() - start

# Convert to nanoseconds per op
lock_ns = (lock_total / N) * 1e9
rlock_ns = (rlock_total / N) * 1e9

print(f"Lock total time: {lock_total:.4f} sec | Per op: {lock_ns:.2f} ns")
print(f"RLock total time: {rlock_total:.4f} sec | Per op: {rlock_ns:.2f} ns")



import time
from array import array
from collections import deque
from typing import Deque, Optional, Tuple

# Dummy Empty exception
class Empty(Exception):
    pass

class _Shard:
    def __init__(self, len_array: array, time_array: array, index: int):
        self._Rlock = threading.RLock()
        self._queue: Deque[Tuple[int, int]] = deque()
        self._len_array = len_array
        self._time_array = time_array
        self._index = index

    def enqueue_item(self, item: int) -> None:
        with self._Rlock:
            now = time.monotonic_ns()
            self._time_array[self._index] = now
            self._queue.append((now, item))
            self._len_array[self._index] += 1

    def dequeue_item(self) -> int:
        with self._Rlock:
            if not self._queue:
                raise Empty()
            self._len_array[self._index] -= 1
            item = self._queue.popleft()
            self._time_array[self._index] = self._queue[0][0] if self._queue else 0
            return item[1]

class ConcurrentBuffer:
    def __init__(self, num_shards: int):
        self._num_shards = num_shards
        self._len_array = array("Q", [0] * num_shards)
        self._time_array = array("Q", [0] * num_shards)
        self._shards = [_Shard(self._len_array, self._time_array, i) for i in range(num_shards)]
        self._mid = num_shards // 2
        self._left_range = range(0, self._mid)
        self._right_range = range(self._mid, num_shards)

    def enqueue(self, item: int) -> None:
        if self._num_shards == 1:
            shard_idx = 0
        else:
            flip = time.monotonic_ns() & 1
            scan_range = self._left_range if flip == 0 else self._right_range
            shard_idx = min(scan_range, key=lambda i: self._len_array[i])
        self._shards[shard_idx].enqueue_item(item)

    def dequeue(self) -> int:
        min_ts = None
        min_idx = None
        for i, ts in enumerate(self._time_array):
            if ts > 0 and (min_ts is None or ts < min_ts):
                min_ts = ts
                min_idx = i
        if min_idx is None:
            raise Empty()
        return self._shards[min_idx].dequeue_item()

# Benchmark
def benchmark_buffer(shards: int, iterations: int):
    buf = ConcurrentBuffer(shards)
    start = time.perf_counter()
    for i in range(iterations):
        buf.enqueue(i)
    enqueue_duration = time.perf_counter() - start

    start = time.perf_counter()
    for _ in range(iterations):
        buf.dequeue()
    dequeue_duration = time.perf_counter() - start

    print(f"\n--- {shards} Shards ---")
    print(f"Enqueue avg: {(enqueue_duration / iterations) * 1e9:.2f} ns")
    print(f"Dequeue avg: {(dequeue_duration / iterations) * 1e9:.2f} ns")

# Run for 10 and 20 shards
benchmark_buffer(10, 1_000_000)
benchmark_buffer(20, 1_000_000)
benchmark_buffer(30, 1_000_000)
benchmark_buffer(40, 1_000_000)

import time
from typing import List


class DummyShard:
    def __init__(self):
        self._Rlock = threading.RLock()
        self.data = []

    def add_item(self, item):
        with self._Rlock:
            self.data.append(item)

    def pop_item(self):
        with self._Rlock:
            if not self.data:
                raise Exception("Empty")
            return self.data.pop()


class ConcurrentCollection:
    def __init__(self, num_shards: int):
        self._num_shards = num_shards
        self._shards = [DummyShard() for _ in range(num_shards)]
        self._length_array = [0] * num_shards

    def _select_shard(self) -> int:
        ns = time.monotonic_ns()
        return ((ns >> 3) ^ ns) % self._num_shards

    def add(self, item):
        shard_idx = self._select_shard()
        self._shards[shard_idx].add_item(item)
        self._length_array[shard_idx] += 1

    def pop(self):
        start = self._select_shard()
        for offset in range(self._num_shards):
            idx = (start + offset) % self._num_shards
            if self._length_array[idx] > 0:
                self._length_array[idx] -= 1
                return self._shards[idx].pop_item()
        raise Exception("Empty")


def benchmark_concurrent_collection(shards: int, operations: int):
    collection = ConcurrentCollection(num_shards=shards)

    start_time = time.perf_counter()
    for i in range(operations):
        collection.add(i)
    enqueue_duration = time.perf_counter() - start_time

    start_time = time.perf_counter()
    for _ in range(operations):
        collection.pop()
    dequeue_duration = time.perf_counter() - start_time

    return enqueue_duration, dequeue_duration


# Run benchmark
results = {}
for shards in [10, 20, 30, 40]:
    enqueue_time, dequeue_time = benchmark_concurrent_collection(shards, 1_000_000)
    results[shards] = {
        "enqueue_avg_ns": (enqueue_time / 1_000_000) * 1e9,
        "dequeue_avg_ns": (dequeue_time / 1_000_000) * 1e9,
    }

print(results)