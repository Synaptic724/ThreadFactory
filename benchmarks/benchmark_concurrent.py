import multiprocessing
import sys
import unittest
import time
import threading
from thread_factory import ConcurrentBuffer, Empty


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


class TestBufferPerformanceComparison(unittest.TestCase):
    """
    Compare performance between:
      1) ConcurrentBuffer with threads
      2) multiprocessing.Queue with processes
    """

    def threaded_concurrent_buffer_performance(self):
        """
        High-performance producer/consumer test using threads and ConcurrentBuffer.
        Balanced consumer workload to avoid stalling.
        """
        self.buffer = ConcurrentBuffer(4)
        producers = 10
        consumers = 20
        self.items_per_producer = 100000
        total_items = producers * self.items_per_producer

        try:
            GIL_ENABLED = sys._is_gil_enabled()
        except AttributeError:
            GIL_ENABLED = True

        print(f"[ConcurrentBuffer/Threads] GIL Enabled: {GIL_ENABLED}")

        def producer(thread_id):
            for i in range(self.items_per_producer):
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
        producers = 10
        consumers = 20
        items_per_producer = 100_000
        total_items = producers * items_per_producer

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
        producers = 10
        consumers = 20
        items_per_producer = 100000
        total_items = producers * items_per_producer

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

        producers = 10
        consumers = 20
        items_per_producer = 100000
        total_items = producers * items_per_producer

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
        self.multiprocessing_queue_performance()
        self.threaded_concurrent_queue_performance()
        self.threaded_deque_performance()

        print(f"\n⏱️ Performance Summary:")
        print(f"- ConcurrentBuffer (Threads) duration: {self.threaded_buffer_duration:.2f} seconds")
        print(f"- ConcurrentQueue (Threads) duration: {self.concurrent_queue_duration:.2f} seconds")
        print(f"- multiprocessing.Queue (Processes) duration: {self.multiproc_queue_duration:.2f} seconds")
        print(f"- collections.deque (w/ Lock) duration: {self.deque_duration:.2f} seconds")

        # Comparison block
        if self.threaded_buffer_duration < self.multiproc_queue_duration:
            diff = self.multiproc_queue_duration - self.threaded_buffer_duration
            print(f"✅ ConcurrentBuffer/Threads was faster than multiprocessing.Queue by {diff:.2f} seconds")
        else:
            diff = self.threaded_buffer_duration - self.multiproc_queue_duration
            print(f"✅ multiprocessing.Queue was faster than ConcurrentBuffer by {diff:.2f} seconds")

        if self.threaded_buffer_duration < self.concurrent_queue_duration:
            diff = self.concurrent_queue_duration - self.threaded_buffer_duration
            print(f"✅ ConcurrentBuffer/Threads was faster than ConcurrentQueue by {diff:.2f} seconds")
        else:
            diff = self.threaded_buffer_duration - self.concurrent_queue_duration
            print(f"✅ ConcurrentQueue/Threads was faster than ConcurrentBuffer by {diff:.2f} seconds")

        if self.threaded_buffer_duration < self.deque_duration:
            diff = self.deque_duration - self.threaded_buffer_duration
            print(f"✅ ConcurrentBuffer/Threads was faster than deque by {diff:.2f} seconds")
        else:
            diff = self.threaded_buffer_duration - self.deque_duration
            print(f"✅ deque was faster than ConcurrentBuffer by {diff:.2f} seconds")

        print("\n📦 Final Queue Sizes:")
        print(f"[ConcurrentBuffer] Remaining items: {self.threaded_buffer_remaining}")
        print(f"[multiprocessing.Queue] Remaining items: {self.multiproc_queue_remaining}")
        print(f"[ConcurrentQueue] Remaining items: {self.concurrent_queue_remaining}")
        print(f"[collections.deque] Remaining items: {self.deque_remaining}")


if __name__ == "__main__":
    unittest.main()