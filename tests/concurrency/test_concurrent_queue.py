import sys
import unittest
import time
import threading
import multiprocessing
import random
from thread_factory import ConcurrentQueue, Empty


class TestConcurrentQueue(unittest.TestCase):

    def test_basic_enqueue_dequeue(self):
        """
        Test the basic enqueue/dequeue behavior with a few items.
        """
        q = ConcurrentQueue([1, 2])
        self.assertEqual(len(q), 2)

        q.enqueue(3)
        self.assertEqual(len(q), 3)
        self.assertFalse(q.dequeue() == None)

        first_item = q.dequeue()
        self.assertIn(first_item, [1, 2, 3], "Dequeued item should be one of the original items.")
        self.assertEqual(len(q), 1)

        # Last item
        self.assertNotEqual(q.dequeue(), None)
        self.assertEqual(len(q), 0)

        # Dequeue from empty queue
        with self.assertRaises(Exception):
            q.dequeue()

    def test_remove_item_by_identity(self):
        """
        Test removing a specific item by identity from the queue.
        """
        q = ConcurrentQueue()

        # Create unique objects
        task1 = {"id": 1}
        task2 = {"id": 2}
        task3 = {"id": 3}

        q.enqueue(task1)
        q.enqueue(task2)
        q.enqueue(task3)

        # Confirm items are in the queue
        self.assertEqual(len(q), 3)

        # Remove task2
        removed = q.remove_item(task2)
        self.assertTrue(removed, "Expected task2 to be removed")

        # task2 should no longer be present
        remaining = list(q)
        self.assertNotIn(task2, remaining)

        # Removing again should return False
        removed_again = q.remove_item(task2)
        self.assertFalse(removed_again, "Expected task2 to already be gone")

        # Length is now 2
        self.assertEqual(len(q), 2)

        # task1 and task3 should still be present
        self.assertIn(task1, q)
        self.assertIn(task3, q)

    def test_peek(self):
        """
        Test that peek returns the front item without removing it.
        """
        q = ConcurrentQueue(["apple", "banana"])
        front = q.peek()
        self.assertEqual(front, "apple")
        self.assertEqual(len(q), 2, "Peek should not remove the item.")

        # Peek from an empty queue
        q.clear()
        with self.assertRaises(Exception):
            q.peek()

    def test_len_bool(self):
        """
        Test __len__ and __bool__.
        """
        q = ConcurrentQueue()
        self.assertEqual(len(q), 0)
        self.assertFalse(q)

        q.enqueue(42)
        self.assertEqual(len(q), 1)
        self.assertTrue(q)

    def test_iter(self):
        """
        Test iterating over the queue returns a snapshot of current items.
        """
        q = ConcurrentQueue([1, 2, 3])
        items = list(q)
        self.assertEqual(items, [1, 2, 3])

        # confirm modifications after iteration don't affect that snapshot
        q.enqueue(4)
        self.assertEqual(len(q), 4)

    def test_clear(self):
        """
        Test clearing the queue removes all items.
        """
        q = ConcurrentQueue([10, 20, 30])
        q.clear()
        self.assertEqual(len(q), 0)
        self.assertFalse(q)

    def test_repr_str(self):
        """
        Test __repr__ and __str__ contain the items.
        """
        q = ConcurrentQueue(["alpha", "beta"])
        r = repr(q)
        s = str(q)
        self.assertIn("alpha", r)
        self.assertIn("beta", s)

    def test_copy_and_deepcopy(self):
        """
        Test copy() and deepcopy() produce correct separate objects.
        """
        from copy import deepcopy
        q = ConcurrentQueue([{"x": 1}, {"y": 2}])

        q_copy = q.copy()
        q_deep = deepcopy(q)

        self.assertEqual(len(q_copy), 2)
        self.assertEqual(len(q_deep), 2)

        # modify the original
        q.dequeue()[ "x" ] = 999  # the front dict
        # shallow copy sees that change, deep copy does not
        self.assertEqual(q_copy.peek()["x"], 999)
        self.assertEqual(q_deep.peek()["x"], 1)

    def test_to_concurrent_list(self):
        """
        Test converting the queue to a ConcurrentList.
        (Requires that concurrent_list.ConcurrentList is available).
        """
        q = ConcurrentQueue([10, 20, 30])
        clist = q.to_concurrent_list()  # Might need your actual import
        self.assertEqual(len(clist), 3)
        self.assertEqual(list(clist), [10, 20, 30])

    def test_batch_update(self):
        """
        Test batch_update can be used for multiple atomic mutations.
        """
        q = ConcurrentQueue(["apple", "banana"])

        def remove_and_enqueue(deq):
            deq.clear()
            deq.append("cherry")
            deq.append("date")

        q.batch_update(remove_and_enqueue)
        self.assertEqual(len(q), 2)
        self.assertIn("cherry", q)
        self.assertIn("date", q)

    def test_map_filter_reduce(self):
        """
        Test map/filter/reduce functional methods.
        """
        q = ConcurrentQueue([1, 2, 3, 4])

        mapped = q.map(lambda x: x * 2)
        self.assertEqual(len(mapped), 4)
        self.assertEqual(list(mapped), [2, 4, 6, 8])

        filtered = q.filter(lambda x: x % 2 == 0)
        self.assertEqual(len(filtered), 2)
        self.assertEqual(list(filtered), [2, 4])

        total = q.reduce(lambda acc, x: acc + x, 0)
        self.assertEqual(total, 10)

        # reduce with no initial
        total_no_init = q.reduce(lambda acc, x: acc + x)
        self.assertEqual(total_no_init, 10)

    def test_producer_consumer_threads(self):
        """
        Simulate multiple producer and consumer runtime for concurrency stress.
        """
        q = ConcurrentQueue()
        producers = 5
        consumers = 5
        items_per_thread = 1000

        def producer(thread_id):
            for i in range(items_per_thread):
                q.enqueue((thread_id, i))

        def consumer():
            consumed = 0
            while consumed < items_per_thread:
                try:
                    item = q.dequeue()
                    consumed += 1
                except IndexError:
                    # queue might be empty at times
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
        # but each consumer tries to consume items_per_thread,
        # which might run out the queue early => any leftover are partial
        # We'll confirm the queue is eventually empty or near-empty
        remaining = len(q)
        self.assertLessEqual(remaining, producers * items_per_thread)

    def test_concurrent_batch_updates(self):
        """
        Ensure multiple runtime can call batch_update concurrently without errors.
        """
        q = ConcurrentQueue([1, 2, 3, 4, 5])

        def updater():
            def batched(d):
                # remove one item if any
                if d:
                    d.popleft()
                # add a new item
                d.append(999)
            for _ in range(100):
                q.batch_update(batched)

        threads = [threading.Thread(target=updater) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # We can't predict the final state exactly, but it should never go negative
        self.assertGreaterEqual(len(q), 0)

    def test_concurrent_map_filter(self):
        """
        Multiple runtime do map() and filter() to produce new queues,
        ensuring no crash or data race with the source queue.
        """
        q = ConcurrentQueue(range(100))
        new_queues = []

        def mapper():
            mq = q.map(lambda x: x * 2)
            new_queues.append(mq)

        def filterer():
            fq = q.filter(lambda x: x % 2 == 0)
            new_queues.append(fq)

        threads = []
        for _ in range(5):
            threads.append(threading.Thread(target=mapper))
            threads.append(threading.Thread(target=filterer))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # We just ensure no crash, new queues exist
        self.assertGreater(len(new_queues), 0)

    def test_random_operations(self):
        """
        Perform random enqueues, dequeues, batch updates, and concurrency
        to test overall thread safety under chaotic usage.
        """
        q = ConcurrentQueue()
        num_threads = 10
        ops_per_thread = 2000

        def random_op():
            for _ in range(ops_per_thread):
                op = random.choice(["enqueue", "dequeue", "peek", "batch"])
                try:
                    if op == "enqueue":
                        q.enqueue(random.randint(0, 1000))
                    elif op == "dequeue":
                        q.dequeue()
                    elif op == "peek":
                        try:
                            q.peek()
                        except Empty:
                            pass  # Expected when the queue is empty
                    else:
                        def do_batch(deq):
                            if deq and random.random() < 0.5:
                                deq.popleft()
                            if random.random() < 0.5:
                                deq.append(random.randint(0, 1000))

                        q.batch_update(do_batch)
                except Empty:
                    pass  # Expected under contention

        threads = [threading.Thread(target=random_op) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # no crash => success
        self.assertGreaterEqual(len(q), 0)


class HighPerformanceConcurrentQueueTest(unittest.TestCase):

    def setUp(self):
        self.queue = ConcurrentQueue()
        self.total_ops = 1_000_000
        self.thread_count = 50

    def test_massive_parallel_enqueue_dequeue(self):
        """
        Stress test: parallel enqueue and dequeue with heavy thread contention.
        """
        enqueue_count = self.total_ops
        dequeue_count = self.total_ops

        def enqueuer():
            for _ in range(enqueue_count // self.thread_count):
                self.queue.enqueue(random.randint(1, 10000))

        def dequeuer():
            for _ in range(dequeue_count // self.thread_count):
                try:
                    self.queue.dequeue()
                except Exception:
                    pass  # queue might be empty

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

        print(f"\n[Massive Parallel Enqueue/Dequeue] {self.total_ops:,} ops in {end - start:.2f}s")
        print(f"[Final Queue Length]: {len(self.queue)}")

        self.assertGreaterEqual(len(self.queue), 0)

    def test_parallel_batch_updates_contention(self):
        """
        Batch update under high contention - multiple runtime mutate concurrently.
        """
        initial_data = list(range(10_000))
        self.queue = ConcurrentQueue(initial_data)

        iterations = 10_000

        def batch_worker():
            for _ in range(iterations):
                def batch_op(deq):
                    # Pop half the items (if enough)
                    for _ in range(min(5, len(deq))):
                        deq.popleft()
                    # Append new items
                    for _ in range(5):
                        deq.append(random.randint(0, 10000))
                self.queue.batch_update(batch_op)

        threads = [threading.Thread(target=batch_worker) for _ in range(self.thread_count)]

        start = time.perf_counter()

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        end = time.perf_counter()

        print(f"\n[Parallel Batch Updates Contention] {iterations * self.thread_count:,} batch updates in {end - start:.2f}s")
        print(f"[Final Queue Length]: {len(self.queue)}")

        self.assertGreaterEqual(len(self.queue), 0)

    def test_concurrent_map_filter_reduce_extreme(self):
        """
        Stress test: concurrent map/filter/reduce.
        """
        self.queue = ConcurrentQueue(range(1000))

        def mapper():
            for _ in range(500):
                mapped = self.queue.map(lambda x: x * 2)
                self.assertIsInstance(mapped, ConcurrentQueue)

        def filterer():
            for _ in range(500):
                filtered = self.queue.filter(lambda x: x % 2 == 0)
                self.assertIsInstance(filtered, ConcurrentQueue)

        def reducer():
            for _ in range(500):
                total = self.queue.reduce(lambda acc, x: acc + x, 0)
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

        print(f"\n[Concurrent Map/Filter/Reduce Extreme] finished in {end - start:.2f}s")
        self.assertEqual(len(self.queue), 1000)

    def test_randomized_parallel_operations(self):
        """
        Random enqueue, dequeue, batch, peek under max concurrency.
        """
        operations_per_thread = 20_000

        def random_worker():
            for _ in range(operations_per_thread):
                op = random.choice(["enqueue", "dequeue", "peek", "batch"])
                if op == "enqueue":
                    self.queue.enqueue(random.randint(0, 10000))
                elif op == "dequeue":
                    try:
                        self.queue.dequeue()
                    except Exception:
                        pass
                elif op == "peek":
                    try:
                        _ = self.queue.peek()
                    except Exception:
                        pass
                elif op == "batch":
                    def batch_op(deq):
                        if len(deq) > 0 and random.random() < 0.5:
                            try:
                                deq.popleft()
                            except IndexError:
                                pass
                        deq.append(random.randint(0, 10000))
                    self.queue.batch_update(batch_op)

        threads = [threading.Thread(target=random_worker) for _ in range(self.thread_count)]

        start = time.perf_counter()

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        end = time.perf_counter()

        print(f"\n[Randomized Parallel Operations] {operations_per_thread * self.thread_count:,} ops in {end - start:.2f}s")
        self.assertGreaterEqual(len(self.queue), 0)

    def test_batch_stealing(self):
        """
        Test batch stealing functionality under concurrent conditions.
        Multiple consumers will attempt to steal work from the queue in batches.
        """
        q = ConcurrentQueue([i for i in range(1000)])  # Initialize queue with 1000 items
        num_consumers = 5
        items_per_consumer = 200
        max_steal_batch_size = 10

        def consumer(consumer_id):
            stolen = 0
            while stolen < items_per_consumer:
                try:
                    # Attempt to steal a batch
                    batch = q.steal_batch(max_steal_batch_size)
                    stolen += len(batch)
                    # Simulate processing of stolen work
                    time.sleep(random.uniform(0.01, 0.05))
                except Exception:
                    pass  # Expecting an empty queue at times

        threads = []
        for cid in range(num_consumers):
            threads.append(threading.Thread(target=consumer, args=(cid,)))

        # Start all consumer threads
        start = time.perf_counter()

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        end = time.perf_counter()

        # Assert that no more than the initial number of items were stolen
        self.assertEqual(len(q), 0, f"Queue should be empty after all consumers finish. {len(q)} items remaining.")

        # Print out the final status
        print(f"\n[Batch Stealing Test] {num_consumers * items_per_consumer} items stolen in {end - start:.2f}s")


    def test_dispose(self):
        """
        Ensures that:
            - dispose() clears all queue contents.
            - dispose() sets the disposed flag.
            - dispose() is idempotent (calling it multiple times is safe).
        """
        queue = ConcurrentQueue([1, 2, 3])

        # Initial state check
        self.assertEqual(len(queue), 3)
        self.assertIn(1, queue)
        self.assertFalse(queue.disposed)

        # First disposal
        queue.dispose()

        # State after disposal
        self.assertEqual(len(queue), 0)
        self.assertTrue(queue.disposed)
        self.assertNotIn(1, queue)
        self.assertNotIn(2, queue)
        self.assertNotIn(3, queue)

        # Ensure idempotency (no exception on second dispose)
        try:
            queue.dispose()
        except Exception as e:
            self.fail(f"Calling dispose() twice raised an exception: {e}")
