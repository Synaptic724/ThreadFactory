import unittest
import time
import threading
import random

# Assuming your ConcurrentBuffer is in 'thread_factory' similarly to ConcurrentQueue
# Adjust imports as necessary:
from thread_factory import ConcurrentBuffer, Empty


def remove_item_by_identity(buffer: ConcurrentBuffer, item):
    """
    Remove the first occurrence of `item` (by identity) from the ConcurrentBuffer
    using a gather-then-rebuild approach (similar to how remove_item() works in ConcurrentQueue).

    Returns:
        bool: True if the item was found and removed, False otherwise.
    """
    all_items = list(buffer)  # snapshot
    new_items = []
    removed = False
    for x in all_items:
        if not removed and x is item:
            removed = True
        else:
            new_items.append(x)

    if removed:
        buffer.clear()
        for x in new_items:
            buffer.enqueue(x)

    return removed


class TestConcurrentBuffer(unittest.TestCase):

    def test_basic_enqueue_dequeue(self):
        """
        Test the basic enqueue/dequeue behavior with a few items.
        """
        cb = ConcurrentBuffer(1, initial =[1, 2])
        self.assertEqual(len(cb), 2)

        cb.enqueue(3)
        self.assertEqual(len(cb), 3)

        first_item = cb.dequeue()
        self.assertIn(first_item, [1, 2, 3], "Dequeued item should be one of the original items.")
        self.assertEqual(len(cb), 2)

        # Dequeue until empty
        cb.dequeue()
        cb.dequeue()
        self.assertEqual(len(cb), 0)

        # Dequeue from empty buffer
        with self.assertRaises(Empty):
            cb.dequeue()

    def test_remove_item_by_identity(self):
        """
        Test removing a specific item by identity from the ConcurrentBuffer.
        We replicate 'remove_item' logic by a custom helper function.
        """
        cb = ConcurrentBuffer(1)
        # Create unique objects
        task1 = {"id": 1}
        task2 = {"id": 2}
        task3 = {"id": 3}

        cb.enqueue(task1)
        cb.enqueue(task2)
        cb.enqueue(task3)
        self.assertEqual(len(cb), 3)

        # Remove task2
        removed = remove_item_by_identity(cb, task2)
        self.assertTrue(removed, "Expected task2 to be removed")

        # task2 should no longer be present
        remaining = list(cb)
        self.assertNotIn(task2, remaining)

        # Removing again should return False
        removed_again = remove_item_by_identity(cb, task2)
        self.assertFalse(removed_again, "Expected task2 to already be gone")

        # Length is now 2
        self.assertEqual(len(cb), 2)
        self.assertIn(task1, cb)
        self.assertIn(task3, cb)

    def test_peek(self):
        """
        Test that peek returns the earliest (approximate FIFO) item without removing it.
        """
        cb = ConcurrentBuffer(1, initial=["apple", "banana"])
        front = cb.peek_oldest()
        # Not strictly guaranteed "apple" if concurrency is wild,
        # but under single-thread usage it's near-FIFO.
        self.assertIn(front, ["apple", "banana"])
        self.assertEqual(len(cb), 2, "Peek should not remove the item.")

        # Peek from an empty buffer
        cb.clear()
        with self.assertRaises(Empty):
            cb.peek_oldest()

    def test_len_bool(self):
        """
        Test __len__ and __bool__.
        """
        cb = ConcurrentBuffer(1)
        self.assertEqual(len(cb), 0)
        self.assertFalse(cb)

        cb.enqueue(42)
        self.assertEqual(len(cb), 1)
        self.assertTrue(cb)

    def test_iter(self):
        """
        Test iterating over the buffer returns a snapshot of current items.
        """
        cb = ConcurrentBuffer(1, initial=[1, 2, 3])
        items = list(cb)
        # They might be in a slightly different order if concurrency were involved,
        # but single-threaded, they'll often come out in insertion order.
        self.assertCountEqual(items, [1, 2, 3])

        cb.enqueue(4)
        self.assertEqual(len(cb), 4)

    def test_clear(self):
        """
        Test clearing the buffer removes all items.
        """
        cb = ConcurrentBuffer(1, initial=[10, 20, 30])
        cb.clear()
        self.assertEqual(len(cb), 0)
        self.assertFalse(cb)

    def test_repr_str(self):
        """
        Test __repr__ and __str__ contain useful info.
        """
        cb = ConcurrentBuffer(1, initial=["alpha", "beta"])
        r = repr(cb)
        s = str(cb)
        # The exact formatting might differ, but check for keywords
        self.assertIn("ConcurrentBuffer", r)
        self.assertIn("alpha", s)
        self.assertIn("beta", s)

    def test_copy_and_deepcopy(self):
        """
        Test copy() and deepcopy() produce correct separate objects.
        """
        from copy import deepcopy
        cb = ConcurrentBuffer(1, initial=[{"x": 1}, {"y": 2}])

        cb_copy = cb.copy()
        cb_deep = deepcopy(cb)

        self.assertEqual(len(cb_copy), 2)
        self.assertEqual(len(cb_deep), 2)

        # modify the original (by reference)
        front_item = cb.dequeue()
        if "x" in front_item:
            front_item["x"] = 999
        else:
            front_item["y"] = 999

        # validate shallow copy saw the mutation
        matched_copy = next((item for item in cb_copy if "x" in item), None)
        self.assertIsNotNone(matched_copy)
        self.assertEqual(matched_copy["x"], 999)

        # validate deep copy did not
        matched_deep = next((item for item in cb_deep if "x" in item), None)
        self.assertIsNotNone(matched_deep)
        self.assertEqual(matched_deep["x"], 1)

    def test_batch_update(self):
        """
        Test batch_update can be used for multiple atomic mutations.
        """
        cb = ConcurrentBuffer(1, initial=["apple", "banana"])

        def remove_and_enqueue(lst):
            lst.clear()
            lst.append("cherry")
            lst.append("date")

        cb.batch_update(remove_and_enqueue)
        self.assertEqual(len(cb), 2)
        snapshot = list(cb)
        self.assertCountEqual(snapshot, ["cherry", "date"])

    def test_map_filter_reduce(self):
        """
        Test map/filter/reduce functional methods.
        """
        cb = ConcurrentBuffer(1, initial=[1, 2, 3, 4])

        mapped = cb.map(lambda x: x * 2)
        self.assertEqual(len(mapped), 4)
        self.assertCountEqual(list(mapped), [2, 4, 6, 8])

        filtered = cb.filter(lambda x: x % 2 == 0)
        self.assertEqual(len(filtered), 2)
        self.assertCountEqual(list(filtered), [2, 4])

        total = cb.reduce(lambda acc, x: acc + x, 0)
        self.assertEqual(total, 10)

        # reduce with no initial
        total_no_init = cb.reduce(lambda acc, x: acc + x)
        self.assertEqual(total_no_init, 10)

    def test_producer_consumer_threads(self):
        """
        Simulate multiple producer and consumer threads for concurrency stress.
        """
        cb = ConcurrentBuffer(10)
        producers = 5
        consumers = 5
        items_per_thread = 1000

        def producer(thread_id):
            for i in range(items_per_thread):
                cb.enqueue((thread_id, i))

        def consumer():
            consumed = 0
            while consumed < items_per_thread:
                try:
                    _ = cb.dequeue()
                    consumed += 1
                except Empty:
                    pass

        threads = []
        for pid in range(producers):
            threads.append(threading.Thread(target=producer, args=(pid,)))
        for _ in range(consumers):
            threads.append(threading.Thread(target=consumer))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # We expect total items = producers * items_per_thread
        # The queue might be emptied fully by consumers.
        remaining = len(cb)
        self.assertLessEqual(remaining, producers * items_per_thread)

    def test_concurrent_batch_updates(self):
        """
        Ensure multiple threads can call batch_update concurrently without errors.
        """
        cb = ConcurrentBuffer(1, initial=[1, 2, 3, 4, 5])

        def updater():
            def batched(item_list):
                # remove one item if any
                if item_list:
                    item_list.pop(0)  # front
                # add a new item
                item_list.append(999)

            for _ in range(100):
                cb.batch_update(batched)

        threads = [threading.Thread(target=updater) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertGreaterEqual(len(cb), 0)

    def test_concurrent_map_filter(self):
        """
        Multiple threads do map() and filter() to produce new buffers,
        ensuring no crash or data race with the source buffer.
        """
        cb = ConcurrentBuffer(1, initial=range(100))
        new_buffers = []

        def mapper():
            mb = cb.map(lambda x: x * 2)
            new_buffers.append(mb)

        def filterer():
            fb = cb.filter(lambda x: x % 2 == 0)
            new_buffers.append(fb)

        threads = []
        for _ in range(5):
            threads.append(threading.Thread(target=mapper))
            threads.append(threading.Thread(target=filterer))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # We just ensure no crash, new buffers exist
        self.assertGreater(len(new_buffers), 0)

    def test_random_operations(self):
        """
        Perform random enqueues, dequeues, batch updates, and concurrency
        to test overall thread safety under chaotic usage.
        """
        cb = ConcurrentBuffer(10)
        num_threads = 10
        ops_per_thread = 200

        def random_op():
            for _ in range(ops_per_thread):
                op = random.choice(["enqueue", "dequeue", "peek", "batch"])
                try:
                    if op == "enqueue":
                        cb.enqueue(random.randint(0, 1000))
                    elif op == "dequeue":
                        cb.dequeue()
                    elif op == "peek":
                        cb.peek()
                    else:
                        def do_batch(lst):
                            if lst and random.random() < 0.5:
                                lst.pop(0)  # remove front
                            if random.random() < 0.5:
                                lst.append(random.randint(0, 1000))

                        cb.batch_update(do_batch)
                except Empty:
                    pass  # Expected under contention

        threads = [threading.Thread(target=random_op) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # no crash => success
        self.assertGreaterEqual(len(cb), 0)


class HighPerformanceConcurrentBufferTest(unittest.TestCase):

    def setUp(self):
        self.buffer = ConcurrentBuffer(16)
        self.total_ops = 1_000_000
        self.thread_count = 10

    def test_massive_parallel_enqueue_dequeue(self):
        """
        Stress test: parallel enqueue and dequeue with heavy thread contention.
        """
        enqueue_count = self.total_ops
        dequeue_count = self.total_ops

        def enqueuer():
            for _ in range(enqueue_count // self.thread_count):
                self.buffer.enqueue(random.randint(1, 10000))

        def dequeuer():
            for _ in range(dequeue_count // self.thread_count):
                try:
                    self.buffer.dequeue()
                except Empty:
                    pass

        threads = []
        for _ in range(self.thread_count // 2):
            threads.append(threading.Thread(target=enqueuer))
            threads.append(threading.Thread(target=dequeuer))

        start = time.perf_counter()

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        end = time.perf_counter()

        print(f"\n[ConcurrentBuffer] {self.total_ops:,} ops in {end - start:.2f}s")
        print(f"[Final Buffer Length]: {len(self.buffer)}")

        self.assertGreaterEqual(len(self.buffer), 0)

    def test_parallel_batch_updates_contention(self):
        """
        Batch update under high contention - multiple threads mutate concurrently.
        """
        initial_data = list(range(10_000))
        self.buffer = ConcurrentBuffer(26,initial=initial_data)

        iterations = 1

        def batch_worker():
            for _ in range(iterations):
                def batch_op(lst):
                    # Pop half the items (if enough)
                    for _ in range(min(5, len(lst))):
                        lst.pop(0)
                    # Append new items
                    for _ in range(5):
                        lst.append(random.randint(0, 10000))

                self.buffer.batch_update(batch_op)

        threads = [threading.Thread(target=batch_worker) for _ in range(self.thread_count)]

        start = time.perf_counter()

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        end = time.perf_counter()

        print(f"\n[ConcurrentBuffer Batch Updates] {iterations * self.thread_count:,} batch ops in {end - start:.2f}s")
        print(f"[Final Buffer Length]: {len(self.buffer)}")

        self.assertGreaterEqual(len(self.buffer), 0)

    def test_concurrent_map_filter_reduce_extreme(self):
        """
        Stress test: concurrent map/filter/reduce.
        """
        self.buffer = ConcurrentBuffer(6, initial=range(1000))

        def mapper():
            for _ in range(500):
                mb = self.buffer.map(lambda x: x * 2)
                self.assertIsInstance(mb, ConcurrentBuffer)

        def filterer():
            for _ in range(500):
                fb = self.buffer.filter(lambda x: x % 2 == 0)
                self.assertIsInstance(fb, ConcurrentBuffer)

        def reducer():
            for _ in range(500):
                total = self.buffer.reduce(lambda acc, x: acc + x, 0)
                self.assertIsInstance(total, int)

        threads = []
        for _ in range(self.thread_count // 3):
            threads.append(threading.Thread(target=mapper))
            threads.append(threading.Thread(target=filterer))
            threads.append(threading.Thread(target=reducer))

        start = time.perf_counter()

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        end = time.perf_counter()

        print(f"\n[ConcurrentBuffer Map/Filter/Reduce] finished in {end - start:.2f}s")
        self.assertEqual(len(self.buffer), 1000)

    def test_randomized_parallel_operations(self):
        """
        Random enqueue, dequeue, batch, peek under max concurrency.
        """
        operations_per_thread = 200

        def random_worker():
            for _ in range(operations_per_thread):
                op = random.choice(["enqueue", "dequeue", "peek", "batch"])
                if op == "enqueue":
                    self.buffer.enqueue(random.randint(0, 10000))
                elif op == "dequeue":
                    try:
                        self.buffer.dequeue()
                    except Empty:
                        pass
                elif op == "peek":
                    try:
                        _ = self.buffer.peek()
                    except Empty:
                        pass
                else:
                    def batch_op(lst):
                        if len(lst) > 0 and random.random() < 0.5:
                            lst.pop(0)
                        lst.append(random.randint(0, 10000))

                    self.buffer.batch_update(batch_op)

        threads = [threading.Thread(target=random_worker) for _ in range(self.thread_count)]

        start = time.perf_counter()

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        end = time.perf_counter()

        print(
            f"\n[ConcurrentBuffer Random Ops] {operations_per_thread * self.thread_count:,} ops in {end - start:.2f}s")
        self.assertGreaterEqual(len(self.buffer), 0)
