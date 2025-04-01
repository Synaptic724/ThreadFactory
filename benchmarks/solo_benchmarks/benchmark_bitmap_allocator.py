import threading
import time
from array import array
from typing import Type

class InstrumentedBitmapAllocator:
    """
    Bitmap-based ID allocator with built-in detailed instrumentation.
    Records:
      - search_time: time spent picking a start index
      - lock_acquire_time: time waiting to acquire the lock in acquire()
      - acquire_inside_time: work inside the lock during acquire()
      - lock_release_time: time releasing the lock in acquire()
      - release_method_time: total time spent in release() method
      - release_lock_release_time: time spent releasing the lock inside release()
      - ops_count: how many acquire-release cycles completed
    """

    TYPE_CODES = {
        8:  ('B', 0xFF),
        16: ('H', 0xFFFF),
        32: ('I', 0xFFFFFFFF),
        64: ('Q', 0xFFFFFFFFFFFFFFFF),
    }

    def __init__(self, capacity: int, word_size: int = 32,
                 lock_cls: Type[threading.Lock] = threading.Lock):
        if word_size not in self.TYPE_CODES:
            raise ValueError("word_size must be one of: 8, 16, 32, 64")

        self._word_size = word_size
        self._typecode, self._full_mask = self.TYPE_CODES[word_size]
        self._num_words = (capacity + self._word_size - 1) // self._word_size

        self._words = array(self._typecode, [0] * self._num_words)
        self._locks = [lock_cls() for _ in range(self._num_words)]
        self._capacity = capacity

        # Instrumentation accumulators
        self._agg_lock = threading.Lock()
        self._search_time = 0.0
        self._lock_acquire_time = 0.0
        self._acquire_inside_time = 0.0
        self._lock_release_time = 0.0

        self._release_method_time = 0.0
        self._release_lock_release_time = 0.0
        self._ops_count = 0

    def _select_start_word_index(self) -> int:
        """
        Simple pseudo-random index using monotonic_ns bit mixing.
        Also partially measured in the final stats as 'search_time'.
        """
        ns = time.monotonic_ns()
        return ((ns >> 3) ^ ns) % self._num_words

    def acquire(self) -> int:
        """
        Acquire an available ID with detailed timing.
        - search_time: picking a start index
        - lock_acquire_time: waiting for the lock
        - acquire_inside_time: scanning bits + setting bit
        - lock_release_time: releasing the lock
        """
        # measure search for the first word
        t0 = time.perf_counter()
        start_idx = self._select_start_word_index()
        t1 = time.perf_counter()

        for i in range(self._num_words):
            word_idx = (start_idx + i) % self._num_words
            lock = self._locks[word_idx]

            wait_start = time.perf_counter()
            lock.acquire()
            lock_acquired = time.perf_counter()

            word = self._words[word_idx]
            if word != self._full_mask:
                free_bit = (~word) & (word + 1)
                if free_bit != 0:
                    bit_idx = (free_bit - 1).bit_length()
                    self._words[word_idx] |= (1 << bit_idx)

                    inside_end = time.perf_counter()
                    lock.release()
                    lock_release_end = time.perf_counter()

                    # record stats
                    with self._agg_lock:
                        self._search_time += (t1 - t0)
                        self._lock_acquire_time += (lock_acquired - wait_start)
                        self._acquire_inside_time += (inside_end - lock_acquired)
                        self._lock_release_time += (lock_release_end - inside_end)
                        self._ops_count += 1
                    return word_idx * self._word_size + bit_idx

            lock.release()

        # if we exhaust all words => none free
        raise RuntimeError("No IDs available (all slots full).")

    def release(self, id_: int):
        """
        Release an ID with detailed timing.
        - release_method_time: entire time in release()
        - release_lock_release_time: time specifically releasing the lock
        """
        if not (0 <= id_ < self._capacity):
            raise ValueError(f"ID {id_} out of range (0..{self._capacity - 1})")

        method_start = time.perf_counter()

        word_idx = id_ // self._word_size
        bit_idx = id_ % self._word_size

        lock = self._locks[word_idx]
        lock.acquire()

        word = self._words[word_idx]
        if not (word & (1 << bit_idx)):
            lock.release()
            raise RuntimeError(f"Double-free detected for ID {id_}")

        self._words[word_idx] &= ~(1 << bit_idx)

        inside_end = time.perf_counter()
        lock.release()
        lock_release_end = time.perf_counter()

        with self._agg_lock:
            self._release_method_time += (lock_release_end - method_start)
            self._release_lock_release_time += (lock_release_end - inside_end)

    def get_stats(self):
        """
        Return a dict with all instrumentation fields and the operation count.
        """
        with self._agg_lock:
            return {
                "search_time": self._search_time,
                "lock_acquire_time": self._lock_acquire_time,
                "acquire_inside_time": self._acquire_inside_time,
                "lock_release_time": self._lock_release_time,

                "release_method_time": self._release_method_time,
                "release_lock_release_time": self._release_lock_release_time,

                "ops_count": self._ops_count
            }


def benchmark_allocator(num_threads: int, ops_per_thread: int,
                        word_size: int, capacity: int, use_rlock: bool):
    """
    Spin up threads, each does 'ops_per_thread' acquire/release ops.
    Gather aggregator stats, compute microsecond averages, and print results.
    """
    lock_type = threading.RLock if use_rlock else threading.Lock
    allocator = InstrumentedBitmapAllocator(
        capacity=capacity,
        word_size=word_size,
        lock_cls=lock_type
    )

    def worker():
        for _ in range(ops_per_thread):
            tmp_id = allocator.acquire()
            allocator.release(tmp_id)

    # Launch threads
    threads = [threading.Thread(target=worker) for _ in range(num_threads)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    end = time.perf_counter()

    total_time = end - start
    total_ops = num_threads * ops_per_thread

    # Get instrumentation
    stats = allocator.get_stats()
    ops_count = stats["ops_count"]  # how many successful acquisitions

    # If no ops done, do not crash
    if ops_count == 0:
        print("No operations completed.")
        return

    # We'll define 'search' as just stats["search_time"]
    # 'acquire' as (lock_acquire_time + acquire_inside_time + lock_release_time)
    # 'release' as stats["release_method_time"] (full method time)
    # total = search + acquire + release
    search = stats["search_time"]
    acquire = (stats["lock_acquire_time"] +
               stats["acquire_inside_time"] +
               stats["lock_release_time"])
    release = stats["release_method_time"]

    # Convert to microseconds
    avg_search = (search / ops_count) * 1e6
    avg_acquire = (acquire / ops_count) * 1e6
    avg_release = (release / ops_count) * 1e6

    avg_total = ((search + acquire + release) / ops_count) * 1e6

    print(f"Threads: {num_threads} | Capacity: {capacity} | WordSize: {word_size}"
          f" | Ops/Thread: {ops_per_thread} | Lock: {'RLock' if use_rlock else 'Lock'}")
    print(f"Elapsed: {total_time:.4f}s | Throughput: {int(total_ops / total_time):,} ops/sec")
    print(f"Avg Search: {avg_search:.2f} μs "
          f"| Avg Acquire: {avg_acquire:.2f} μs "
          f"| Avg Release: {avg_release:.2f} μs")
    print(f"Avg Total (S+A+R): {avg_total:.2f} μs\n")


if __name__ == "__main__":
    # Example usage
    word_sizes = [8, 16, 32, 64]
    thread_counts = [16, 32, 64, 96]
    capacities = [t*8 for t in thread_counts] + [t*16 for t in thread_counts]
    ops_per_thread = 10_000

    for threads in thread_counts:
        for capacity in capacities:
            for word_size in word_sizes:
                # Test normal Lock
                benchmark_allocator(threads, ops_per_thread, word_size, capacity, use_rlock=False)
                # Test RLock
                benchmark_allocator(threads, ops_per_thread, word_size, capacity, use_rlock=True)
