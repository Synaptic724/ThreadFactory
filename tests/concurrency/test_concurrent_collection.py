import unittest
import time
import threading
import random

# Assuming your ConcurrentCollection is in 'thread_factory' similarly to ConcurrentQueue
# Adjust imports as necessary:
from thread_factory import ConcurrentCollection, Empty


def remove_item_by_identity(collection: ConcurrentCollection, item):
    """
    Remove the first occurrence of `item` (by identity) from the ConcurrentCollection
    using a gather-then-rebuild approach.

    Returns:
        bool: True if the item was found and removed, False otherwise.
    """
    all_items = list(collection)  # snapshot
    new_items = []
    removed = False
    for x in all_items:
        if not removed and x is item:
            removed = True
        else:
            new_items.append(x)

    if removed:
        collection.clear()
        for x in new_items:
            collection.add(x)

    return removed


class TestConcurrentCollection(unittest.TestCase):

    def test_basic_add_pop(self):
        """
        Test basic add/pop behavior with a few items.
        """
        cc = ConcurrentCollection(1, initial=[1, 2])
        self.assertEqual(len(cc), 2)

        cc.add(3)
        self.assertEqual(len(cc), 3)

        first_item = cc.pop()
        self.assertIn(first_item, [1, 2, 3], "Popped item should be one of the original items.")
        self.assertEqual(len(cc), 2)

        # Pop until empty
        cc.pop()
        cc.pop()
        self.assertEqual(len(cc), 0)

        # Pop from empty collection
        with self.assertRaises(Empty):
            cc.pop()

    def test_remove_item_by_identity(self):
        """
        Test removing a specific item by identity from the ConcurrentCollection.
        We replicate the 'remove_item' logic with a custom helper function.
        """
        cc = ConcurrentCollection(1)
        # Create unique objects
        task1 = {"id": 1}
        task2 = {"id": 2}
        task3 = {"id": 3}

        cc.add(task1)
        cc.add(task2)
        cc.add(task3)
        self.assertEqual(len(cc), 3)

        # Remove task2
        removed = remove_item_by_identity(cc, task2)
        self.assertTrue(removed, "Expected task2 to be removed")

        # task2 should no longer be present
        remaining = list(cc)
        self.assertNotIn(task2, remaining)

        # Removing again should return False
        removed_again = remove_item_by_identity(cc, task2)
        self.assertFalse(removed_again, "Expected task2 to already be gone")

        # Length is now 2
        self.assertEqual(len(cc), 2)
        self.assertIn(task1, cc)
        self.assertIn(task3, cc)

    def test_peek(self):
        """
        Test that peek returns an item without removing it.

        Notes:
            - Order is not strictly FIFO.
            - Single-thread usage will behave close to FIFO anyway.
        """
        cc = ConcurrentCollection(1, initial=["apple", "banana"])

        # Peek from shard 0 directly
        front = cc.peek(0)
        self.assertIn(front, ["apple", "banana"], "Peek should return a valid item from shard 0.")
        self.assertEqual(len(cc), 2, "Peek should not remove the item.")

        # Test implicit peek (no shard provided)
        front_any = cc.peek()
        self.assertIn(front_any, ["apple", "banana"], "Peek() without index should return a valid item.")

        # Peek from an empty collection
        cc.clear()
        with self.assertRaises(Empty):
            cc.peek(0)

        with self.assertRaises(Empty):
            cc.peek()  # Should also raise

    def test_len_bool(self):
        """
        Test __len__ and __bool__.
        """
        cc = ConcurrentCollection(1)
        self.assertEqual(len(cc), 0)
        self.assertFalse(cc)

        cc.add(42)
        self.assertEqual(len(cc), 1)
        self.assertTrue(cc)

    def test_iter(self):
        """
        Test iterating over the collection returns a snapshot of current items.
        """
        cc = ConcurrentCollection(1, initial=[1, 2, 3])
        items = list(cc)
        self.assertCountEqual(items, [1, 2, 3])

        cc.add(4)
        self.assertEqual(len(cc), 4)

    def test_clear(self):
        """
        Test clearing the collection removes all items.
        """
        cc = ConcurrentCollection(1, initial=[10, 20, 30])
        cc.clear()
        self.assertEqual(len(cc), 0)
        self.assertFalse(cc)

    def test_repr_str(self):
        """
        Test __repr__ and __str__ contain useful info.
        """
        cc = ConcurrentCollection(1, initial=["alpha", "beta"])
        r = repr(cc)
        s = str(cc)
        # The exact formatting might differ, but check for keywords
        self.assertIn("ConcurrentCollection", r)
        self.assertIn("alpha", s)
        self.assertIn("beta", s)

    def test_copy_and_deepcopy(self):
        """
        Test copy() and deepcopy() produce correct separate objects.
        """
        from copy import deepcopy
        cc = ConcurrentCollection(1, initial=[{"x": 1}, {"y": 2}])

        cc_copy = cc.copy()
        cc_deep = deepcopy(cc)

        self.assertEqual(len(cc_copy), 2)
        self.assertEqual(len(cc_deep), 2)

        # modify the original (by reference)
        front_item = cc.pop()
        if "x" in front_item:
            front_item["x"] = 999
        else:
            front_item["y"] = 999

        # validate shallow copy saw the mutation
        matched_copy = next((item for item in cc_copy if "x" in item), None)
        self.assertIsNotNone(matched_copy)
        self.assertEqual(matched_copy["x"], 999)

        # validate deep copy did not
        matched_deep = next((item for item in cc_deep if "x" in item), None)
        self.assertIsNotNone(matched_deep)
        self.assertEqual(matched_deep["x"], 1)

    def test_batch_update(self):
        """
        Test batch_update can be used for multiple atomic mutations.
        """
        cc = ConcurrentCollection(1, initial=["apple", "banana"])

        def remove_and_enqueue(lst):
            lst.clear()
            lst.append("cherry")
            lst.append("date")

        cc.batch_update(remove_and_enqueue)
        self.assertEqual(len(cc), 2)
        snapshot = list(cc)
        self.assertCountEqual(snapshot, ["cherry", "date"])

    def test_map_filter_reduce(self):
        """
        Test map/filter/reduce functional methods.
        """
        cc = ConcurrentCollection(1, initial=[1, 2, 3, 4])

        mapped = cc.map(lambda x: x * 2)
        self.assertEqual(len(mapped), 4)
        self.assertCountEqual(list(mapped), [2, 4, 6, 8])

        filtered = cc.filter(lambda x: x % 2 == 0)
        self.assertEqual(len(filtered), 2)
        self.assertCountEqual(list(filtered), [2, 4])

        total = cc.reduce(lambda acc, x: acc + x, 0)
        self.assertEqual(total, 10)

        # reduce with no initial
        total_no_init = cc.reduce(lambda acc, x: acc + x)
        self.assertEqual(total_no_init, 10)

    def test_producer_consumer_threads(self):
        """
        Simulate multiple producer and consumer threads for concurrency stress.
        """
        cc = ConcurrentCollection(10)
        producers = 5
        consumers = 5
        items_per_thread = 1000

        def producer(thread_id):
            for i in range(items_per_thread):
                cc.add((thread_id, i))

        def consumer():
            consumed = 0
            while consumed < items_per_thread:
                try:
                    _ = cc.pop()
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

        remaining = len(cc)
        # We expect total items = producers * items_per_thread minus whatever was consumed
        self.assertLessEqual(remaining, producers * items_per_thread)

    def test_concurrent_batch_updates(self):
        """
        Ensure multiple threads can call batch_update concurrently without errors.
        """
        cc = ConcurrentCollection(1, initial=[1, 2, 3, 4, 5])

        def updater():
            def batched(item_list):
                # remove one item if any
                if item_list:
                    item_list.pop(0)  # front
                # add a new item
                item_list.append(999)

            for _ in range(100):
                cc.batch_update(batched)

        threads = [threading.Thread(target=updater) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertGreaterEqual(len(cc), 0)

    def test_concurrent_map_filter(self):
        """
        Multiple threads do map() and filter() to produce new collections,
        ensuring no crash or data race with the source collection.
        """
        cc = ConcurrentCollection(1, initial=range(100))
        new_collections = []

        def mapper():
            mb = cc.map(lambda x: x * 2)
            new_collections.append(mb)

        def filterer():
            fb = cc.filter(lambda x: x % 2 == 0)
            new_collections.append(fb)

        threads = []
        for _ in range(5):
            threads.append(threading.Thread(target=mapper))
            threads.append(threading.Thread(target=filterer))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # We just ensure no crash, new collections exist
        self.assertGreater(len(new_collections), 0)

    def test_random_operations(self):
        """
        Perform random adds, pops, batch updates, and concurrency
        to test overall thread safety under chaotic usage.
        """
        cc = ConcurrentCollection(10)
        num_threads = 10
        ops_per_thread = 200

        def random_op():
            for _ in range(ops_per_thread):
                op = random.choice(["add", "pop", "peek", "batch"])
                try:
                    if op == "add":
                        cc.add(random.randint(0, 1000))
                    elif op == "pop":
                        cc.pop()
                    elif op == "peek":
                        cc.peek()
                    else:
                        def do_batch(lst):
                            if lst and random.random() < 0.5:
                                lst.pop(0)  # remove front
                            if random.random() < 0.5:
                                lst.append(random.randint(0, 1000))
                        cc.batch_update(do_batch)
                except Empty:
                    pass  # Expected under contention

        threads = [threading.Thread(target=random_op) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # no crash => success
        self.assertGreaterEqual(len(cc), 0)


class HighPerformanceConcurrentCollectionTest(unittest.TestCase):

    def setUp(self):
        self.collection = ConcurrentCollection(16)
        self.total_ops = 1_000_000
        self.thread_count = 10

    def test_massive_parallel_add_pop(self):
        """
        Stress test: parallel adds and pops with heavy thread contention.
        """
        add_count = self.total_ops
        pop_count = self.total_ops

        def adder():
            for _ in range(add_count // self.thread_count):
                self.collection.add(random.randint(1, 10000))

        def popper():
            for _ in range(pop_count // self.thread_count):
                try:
                    self.collection.pop()
                except Empty:
                    pass

        threads = []
        for _ in range(self.thread_count // 2):
            threads.append(threading.Thread(target=adder))
            threads.append(threading.Thread(target=popper))

        start = time.perf_counter()

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        end = time.perf_counter()

        print(f"\n[ConcurrentCollection] {self.total_ops:,} ops in {end - start:.2f}s")
        print(f"[Final Collection Length]: {len(self.collection)}")

        self.assertGreaterEqual(len(self.collection), 0)

    def test_parallel_batch_updates_contention(self):
        """
        Batch update under high contention - multiple threads mutate concurrently.
        """
        initial_data = list(range(10_000))
        self.collection = ConcurrentCollection(26, initial=initial_data)

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

                self.collection.batch_update(batch_op)

        threads = [threading.Thread(target=batch_worker) for _ in range(self.thread_count)]

        start = time.perf_counter()

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        end = time.perf_counter()

        print(f"\n[ConcurrentCollection Batch Updates] {iterations * self.thread_count:,} batch ops in {end - start:.2f}s")
        print(f"[Final Collection Length]: {len(self.collection)}")

        self.assertGreaterEqual(len(self.collection), 0)

    def test_concurrent_map_filter_reduce_extreme(self):
        """
        Stress test: concurrent map/filter/reduce.
        """
        self.collection = ConcurrentCollection(6, initial=range(1000))

        def mapper():
            for _ in range(500):
                mb = self.collection.map(lambda x: x * 2)
                self.assertIsInstance(mb, ConcurrentCollection)

        def filterer():
            for _ in range(500):
                fb = self.collection.filter(lambda x: x % 2 == 0)
                self.assertIsInstance(fb, ConcurrentCollection)

        def reducer():
            for _ in range(500):
                total = self.collection.reduce(lambda acc, x: acc + x, 0)
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

        print(f"\n[ConcurrentCollection Map/Filter/Reduce] finished in {end - start:.2f}s")
        self.assertEqual(len(self.collection), 1000)

    def test_randomized_parallel_operations(self):
        """
        Random add/pop/batch/peek operations under max concurrency.
        """
        operations_per_thread = 200

        def random_worker():
            for _ in range(operations_per_thread):
                op = random.choice(["add", "pop", "peek", "batch"])
                if op == "add":
                    self.collection.add(random.randint(0, 10000))
                elif op == "pop":
                    try:
                        self.collection.pop()
                    except Empty:
                        pass
                elif op == "peek":
                    try:
                        _ = self.collection.peek()
                    except Empty:
                        pass
                else:
                    def batch_op(lst):
                        if len(lst) > 0 and random.random() < 0.5:
                            lst.pop(0)
                        lst.append(random.randint(0, 10000))

                    self.collection.batch_update(batch_op)

        threads = [threading.Thread(target=random_worker) for _ in range(self.thread_count)]

        start = time.perf_counter()

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        end = time.perf_counter()

        print(f"\n[ConcurrentCollection Random Ops] {operations_per_thread * self.thread_count:,} ops in {end - start:.2f}s")
        self.assertGreaterEqual(len(self.collection), 0)
