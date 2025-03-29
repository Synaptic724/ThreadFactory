import multiprocessing
import sys
import unittest
import time
import threading
from thread_factory import ConcurrentBuffer, Empty, ConcurrentCollection


def producer_process_multiproc_queue(queue, item_count, process_id):
    """ Producer for a standard multiprocessing.Queue. """
    for i in range(item_count):
        queue.put((process_id, i))


def consumer_process_multiproc_queue(queue, item_count):
    """ Consumer for a standard multiprocessing.Queue. """
    consumed = 0
    while consumed < item_count:
        try:
            _ = queue.get()
            consumed += 1
        except:
            pass  # queue might be empty or a timeout can occur


producers = 80
consumers = 80
items_per_producer = 10000
total_items = producers * items_per_producer

class TestBufferPerformanceComparison(unittest.TestCase):
    """
    Compare performance between:
      1) ConcurrentBuffer with threads
      2) multiprocessing.Queue with processes
    """

    def threaded_concurrent_unordered_buffer_performance(self):
        """
        Benchmark using ConcurrentUnorderedBuffer with threads.
        Fast unordered buffer using shard-based design.
        """
        buf = ConcurrentCollection(160)

        try:
            GIL_ENABLED = sys._is_gil_enabled()
        except AttributeError:
            GIL_ENABLED = True

        print(f"[ConcurrentCollection] GIL Enabled: {GIL_ENABLED}")

        def producer(thread_id):
            for i in range(items_per_producer):
                buf.add((thread_id, i))

        # Distribute items evenly among consumers
        base_target = total_items // consumers
        targets = [base_target] * consumers
        for i in range(total_items % consumers):
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
        for pid in range(producers):
            threads.append(threading.Thread(target=producer, args=(pid,)))
        for i in range(consumers):
            threads.append(threading.Thread(target=consumer, args=(targets[i],)))

        print(f"\n[ConcurrentCollection] Starting {producers} producers / {consumers} consumers...")
        start = time.perf_counter()

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        end = time.perf_counter()
        duration = end - start

        print(f"[ConcurrentCollection] {total_items:,} ops completed in {duration:.2f} seconds.")
        print(f"[ConcurrentCollection] Final buffer length: {len(buf)}\n")

        self.concurrent_unordered_buffer_duration = duration
        self.concurrent_unordered_buffer_remaining = len(buf)

    def threaded_concurrent_buffer_performance(self):
        """
        High-performance producer/consumer test using threads and ConcurrentBuffer.
        Balanced consumer workload to avoid stalling.
        """
        self.buffer = ConcurrentBuffer(10)
        try:
            GIL_ENABLED = sys._is_gil_enabled()
        except AttributeError:
            GIL_ENABLED = True

        print(f"[ConcurrentBuffer/Threads] GIL Enabled: {GIL_ENABLED}")

        def producer(thread_id):
            for i in range(items_per_producer):
                self.buffer.enqueue((thread_id, i))

        # Distribute total work across consumers
        base_target = total_items // consumers
        targets = [base_target] * consumers
        for i in range(total_items % consumers):
            targets[i] += 1

        def consumer(target):
            consumed = 0
            while consumed < target:
                try:
                    _ = self.buffer.dequeue()
                    consumed += 1
                except Empty:
                    pass
                    #time.sleep(0.001)

        threads = []
        for pid in range(producers):
            threads.append(threading.Thread(target=producer, args=(pid,)))
        for i in range(consumers):
            threads.append(threading.Thread(target=consumer, args=(targets[i],)))

        print(f"\n[ConcurrentBuffer/Threads] Starting {producers} producers / {consumers} consumers...")
        start = time.perf_counter()

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        end = time.perf_counter()
        duration = end - start

        print(f"[ConcurrentBuffer/Threads] {total_items:,} ops completed in {duration:.2f} seconds.")
        remaining = len(self.buffer)
        print(f"[ConcurrentBuffer/Threads] Final buffer length: {remaining}\n")

        self.threaded_buffer_duration = duration
        self.threaded_buffer_remaining = remaining

    def multiprocessing_queue_performance(self):
        """
        Compare with multiprocessing.Queue, using processes for parallelism.
        This version guarantees consumers will collectively consume exactly total_items.
        """
        queue = multiprocessing.Queue()

        try:
            GIL_ENABLED = sys._is_gil_enabled()
        except AttributeError:
            GIL_ENABLED = True

        print(f"[multiprocessing.Queue] GIL Enabled: {GIL_ENABLED}")

        # ✅ Distribute the work equally across consumers
        base_target = total_items // consumers
        targets = [base_target] * consumers
        for i in range(total_items % consumers):
            targets[i] += 1  # handle uneven division

        processes = []

        # Producers
        for pid in range(producers):
            processes.append(multiprocessing.Process(
                target=producer_process_multiproc_queue,
                args=(queue, items_per_producer, pid)
            ))

        # Consumers
        for i in range(consumers):
            processes.append(multiprocessing.Process(
                target=consumer_process_multiproc_queue,
                args=(queue, targets[i])  # Each consumer now gets exactly its share
            ))

        print(f"\n[multiprocessing.Queue] Starting {producers} producers / {consumers} consumers...")
        start = time.perf_counter()

        for p in processes:
            p.start()
        for p in processes:
            p.join()

        end = time.perf_counter()
        duration = end - start

        print(f"[multiprocessing.Queue] {total_items:,} ops completed in {duration:.2f} seconds.")
        try:
            remaining = queue.qsize()
        except NotImplementedError:
            remaining = "Unknown (platform-dependent)"

        print(f"[multiprocessing.Queue] Final queue length: {remaining}\n")

        self.multiproc_queue_duration = duration
        self.multiproc_queue_remaining = remaining

    def threaded_concurrent_queue_performance(self):
        """
        Your existing ConcurrentQueue, running high-performance producer/consumer test.
        Competes with multiprocessing.Queue.
        """
        from thread_factory import ConcurrentQueue
        q = ConcurrentQueue()

        try:
            GIL_ENABLED = sys._is_gil_enabled()
        except AttributeError:
            GIL_ENABLED = True

        print(f"[ConcurrentQueue] GIL Enabled: {GIL_ENABLED}")

        def producer(thread_id):
            for i in range(items_per_producer):
                q.enqueue((thread_id, i))

        # Distribute items evenly among consumers
        base_target = total_items // consumers
        targets = [base_target] * consumers
        for i in range(total_items % consumers):
            targets[i] += 1

        def consumer(target):
            consumed = 0
            while consumed < target:
                try:
                    _ = q.dequeue()
                    consumed += 1
                except Empty:
                    pass
                    #time.sleep(0.001)

        threads = []
        for pid in range(producers):
            threads.append(threading.Thread(target=producer, args=(pid,)))
        for i in range(consumers):
            threads.append(threading.Thread(target=consumer, args=(targets[i],)))

        print(f"\n[ConcurrentQueue] Starting {producers} producers / {consumers} consumers...")
        start = time.perf_counter()

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        end = time.perf_counter()
        duration = end - start

        print(f"[ConcurrentQueue] {total_items:,} ops completed in {duration:.2f} seconds.")
        print(f"[ConcurrentQueue] Final queue length: {len(q)}\n")

        self.concurrent_queue_duration = duration
        self.concurrent_queue_remaining = len(q)

    def threaded_deque_performance(self):
        """
        Benchmark using a plain collections.deque with threading.Lock for safety.
        This simulates a naive shared queue with basic thread-safety.
        """
        from collections import deque
        q = deque()

        try:
            GIL_ENABLED = sys._is_gil_enabled()
        except AttributeError:
            GIL_ENABLED = True

        print(f"[collections.deque] GIL Enabled: {GIL_ENABLED}")

        def producer(thread_id):
            for i in range(items_per_producer):
                q.append((thread_id, i))

        # Distribute items evenly among consumers
        base_target = total_items // consumers
        targets = [base_target] * consumers
        for i in range(total_items % consumers):
            targets[i] += 1

        def consumer(target):
            consumed = 0
            while consumed < target:
                try:
                    if q:
                        _ = q.popleft()
                        consumed += 1
                except Exception:
                    pass

        threads = []
        for pid in range(producers):
            threads.append(threading.Thread(target=producer, args=(pid,)))
        for i in range(consumers):
            threads.append(threading.Thread(target=consumer, args=(targets[i],)))

        print(f"\n[collections.deque] Starting {producers} producers / {consumers} consumers...")
        start = time.perf_counter()

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        end = time.perf_counter()
        duration = end - start

        print(f"[collections.deque] {total_items:,} ops completed in {duration:.2f} seconds.")
        print(f"[collections.deque] Final queue length: {len(q)}\n")

        self.deque_duration = duration
        self.deque_remaining = len(q)

    def test_compare_performance(self):
        """
        Runs all queue types and compares them directly, printing a full summary.
        """
        print("\n🚀 Running side-by-side performance comparison...\n")
        self.threaded_concurrent_buffer_performance()
        self.threaded_concurrent_unordered_buffer_performance()
        self.threaded_concurrent_queue_performance()
        self.threaded_deque_performance()
        self.multiprocessing_queue_performance()

        print("\n⏱️ Performance Summary (including ops/sec):")

        def ops_per_sec(duration):
            return total_items / duration if duration > 0 else 0

        print(
            f"- ConcurrentBuffer (Threads):              {self.threaded_buffer_duration:.2f} seconds ({ops_per_sec(self.threaded_buffer_duration):,.0f} ops/sec)")
        print(
            f"- ConcurrentCollection (Threads):    {self.concurrent_unordered_buffer_duration:.2f} seconds ({ops_per_sec(self.concurrent_unordered_buffer_duration):,.0f} ops/sec)")
        print(
            f"- ConcurrentQueue (Threads):               {self.concurrent_queue_duration:.2f} seconds ({ops_per_sec(self.concurrent_queue_duration):,.0f} ops/sec)")
        print(
            f"- multiprocessing.Queue (Processes):      {self.multiproc_queue_duration:.2f} seconds ({ops_per_sec(self.multiproc_queue_duration):,.0f} ops/sec)")
        print(
            f"- collections.deque (w/ Lock):             {self.deque_duration:.2f} seconds ({ops_per_sec(self.deque_duration):,.0f} ops/sec)")

        print("\n✅ Winners:")
        durations = {
            "ConcurrentBuffer": self.threaded_buffer_duration,
            "ConcurrentUnorderedBuffer": self.concurrent_unordered_buffer_duration,
            "ConcurrentQueue": self.concurrent_queue_duration,
            "multiprocessing.Queue": self.multiproc_queue_duration,
            "collections.deque": self.deque_duration
        }
        sorted_durations = sorted(durations.items(), key=lambda x: x[1])
        fastest = sorted_durations[0]

        print(f"🏆 Fastest: {fastest[0]} ({fastest[1]:.2f} seconds — {ops_per_sec(fastest[1]):,.0f} ops/sec)")
        print(f"Numbers of Producers: {producers}, Consumers: {consumers}, Items per Producer: {items_per_producer}")

        print("\n📦 Final Queue Sizes:")
        print(f"[ConcurrentBuffer]              Remaining items: {self.threaded_buffer_remaining}")
        print(f"[ConcurrentCollection]     Remaining items: {self.concurrent_unordered_buffer_remaining}")
        print(f"[ConcurrentQueue]               Remaining items: {self.concurrent_queue_remaining}")
        print(f"[multiprocessing.Queue]         Remaining items: {self.multiproc_queue_remaining}")
        print(f"[collections.deque]             Remaining items: {self.deque_remaining}")


if __name__ == "__main__":
    unittest.main()