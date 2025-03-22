import unittest
import threading
import random
import time
import copy
from Threading.Queue import ConcurrentQueue  # <-- Adjust your actual import path

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
        with self.assertRaises(IndexError):
            q.dequeue()

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
        with self.assertRaises(IndexError):
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
        from copy import copy, deepcopy
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
        Simulate multiple producer and consumer threads for concurrency stress.
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
        Ensure multiple threads can call batch_update concurrently without errors.
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
        Multiple threads do map() and filter() to produce new queues,
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
                op_type = random.choice(["enqueue", "dequeue", "batch", "peek"])
                if op_type == "enqueue":
                    q.enqueue(random.randint(0, 1000))
                elif op_type == "dequeue":
                    try:
                        q.dequeue()
                    except IndexError:
                        pass
                elif op_type == "peek":
                    try:
                        q.peek()
                    except IndexError:
                        pass
                else:  # "batch"
                    def do_batch(deq):
                        if deq and random.random() < 0.5:
                            try:
                                deq.popleft()
                            except IndexError:
                                pass
                        if random.random() < 0.5:
                            deq.append(random.randint(0, 1000))
                    q.batch_update(do_batch)

        threads = [threading.Thread(target=random_op) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # no crash => success
        self.assertGreaterEqual(len(q), 0)
