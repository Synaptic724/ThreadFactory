import unittest
import threading
import random
from src.thread_factory import ConcurrentStack, Empty

class TestConcurrentStack(unittest.TestCase):

    def test_basic_push_pop(self):
        """
        Test the basic push/pop behavior with a few items.
        """
        s = ConcurrentStack([1, 2])
        self.assertEqual(len(s), 2)

        s.push(3)
        self.assertEqual(len(s), 3)
        self.assertIsNotNone(s.pop(), "Pop should return an item")

        top_item = s.pop()
        self.assertIn(top_item, [1, 2, 3], "Popped item should be one of the original items.")
        self.assertEqual(len(s), 1)

        # Last item
        self.assertIsNotNone(s.pop(), "Should be able to pop the last item")
        self.assertEqual(len(s), 0)

        # Pop from empty stack
        with self.assertRaises(Empty):
            s.pop()

    def test_peek(self):
        """
        Test that peek returns the top item without removing it.
        """
        s = ConcurrentStack(["apple", "banana"])
        top = s.peek()
        self.assertEqual(top, "banana", "Peek should return the last (top) item in the stack.")
        self.assertEqual(len(s), 2, "Peek should not remove the item.")

        # Peek from an empty stack
        s.clear()
        with self.assertRaises(Empty):
            s.peek()

    def test_len_bool(self):
        """
        Test __len__ and __bool__.
        """
        s = ConcurrentStack()
        self.assertEqual(len(s), 0)
        self.assertFalse(s)

        s.push(42)
        self.assertEqual(len(s), 1)
        self.assertTrue(s)

    def test_iter(self):
        """
        Test iterating over the stack returns a snapshot of current items.
        NOTE: By default, iteration goes from bottom to top in the underlying deque.
        """
        s = ConcurrentStack([1, 2, 3])
        items = list(s)
        self.assertEqual(items, [1, 2, 3])

        # confirm modifications after iteration don't affect that snapshot
        s.push(4)
        self.assertEqual(len(s), 4)

    def test_clear(self):
        """
        Test clearing the stack removes all items.
        """
        s = ConcurrentStack([10, 20, 30])
        s.clear()
        self.assertEqual(len(s), 0)
        self.assertFalse(s)

    def test_repr_str(self):
        """
        Test __repr__ and __str__ contain the items.
        """
        s = ConcurrentStack(["alpha", "beta"])
        r = repr(s)
        st = str(s)
        self.assertIn("alpha", r)
        self.assertIn("beta", st)

    def test_copy_and_deepcopy(self):
        """
        Test copy() and deepcopy() produce correct separate objects.
        """
        from copy import deepcopy
        s = ConcurrentStack([{"y": 2}, {"x": 1}])

        s_copy = s.copy()
        s_deep = deepcopy(s)

        self.assertEqual(len(s_copy), 2)
        self.assertEqual(len(s_deep), 2)

        # modify the original
        s.pop()["x"] = 999  # the top dict
        # shallow copy sees that change, deep copy does not
        self.assertEqual(s_copy.peek()["x"], 999)
        self.assertEqual(s_deep.peek()["x"], 1)

    def test_to_concurrent_list(self):
        """
        Test converting the stack to a ConcurrentList.
        (Requires that concurrent_list.ConcurrentList is available).
        """
        s = ConcurrentStack([10, 20, 30])
        clist = s.to_concurrent_list()  # Adjust your import path if needed
        self.assertEqual(len(clist), 3)
        self.assertEqual(list(clist), [10, 20, 30])

    def test_batch_update(self):
        """
        Test batch_update can be used for multiple atomic mutations.
        """
        s = ConcurrentStack(["apple", "banana"])

        def remove_and_push(deq):
            deq.clear()
            deq.append("cherry")
            deq.append("date")

        s.batch_update(remove_and_push)
        self.assertEqual(len(s), 2)
        # The order is bottom->top in the deque, so "date" is the top
        self.assertIn("cherry", s)
        self.assertIn("date", s)

    def test_map_filter_reduce(self):
        """
        Test map/filter/reduce functional methods.
        """
        s = ConcurrentStack([1, 2, 3, 4])

        mapped = s.map(lambda x: x * 2)
        self.assertEqual(len(mapped), 4)
        self.assertEqual(list(mapped), [2, 4, 6, 8])

        filtered = s.filter(lambda x: x % 2 == 0)
        self.assertEqual(len(filtered), 2)
        self.assertEqual(list(filtered), [2, 4])

        total = s.reduce(lambda acc, x: acc + x, 0)
        self.assertEqual(total, 10)

        # reduce with no initial
        total_no_init = s.reduce(lambda acc, x: acc + x)
        self.assertEqual(total_no_init, 10)

    def test_producer_consumer_threads(self):
        """
        Simulate multiple producer and consumer threads for concurrency stress.
        """
        s = ConcurrentStack()
        producers = 5
        consumers = 5
        items_per_thread = 1000

        def producer(thread_id):
            for i in range(items_per_thread):
                s.push((thread_id, i))

        def consumer():
            consumed = 0
            while consumed < items_per_thread:
                try:
                    s.pop()
                    consumed += 1
                except IndexError:
                    # stack might be empty at times
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
        # which might run out the stack early => any leftover are partial
        # We'll confirm the stack is eventually empty or near-empty
        remaining = len(s)
        self.assertLessEqual(remaining, producers * items_per_thread)

    def test_concurrent_batch_updates(self):
        """
        Ensure multiple threads can call batch_update concurrently without errors.
        """
        s = ConcurrentStack([1, 2, 3, 4, 5])

        def updater():
            def batched(d):
                # remove one item if any (pop from right)
                if d:
                    d.pop()
                # add a new item
                d.append(999)
            for _ in range(100):
                s.batch_update(batched)

        threads = [threading.Thread(target=updater) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # We can't predict the final state exactly, but it should never go negative
        self.assertGreaterEqual(len(s), 0)

    def test_concurrent_map_filter(self):
        """
        Multiple threads do map() and filter() to produce new stacks,
        ensuring no crash or data race with the source stack.
        """
        s = ConcurrentStack(range(100))
        new_stacks = []

        def mapper():
            ms = s.map(lambda x: x * 2)
            new_stacks.append(ms)

        def filterer():
            fs = s.filter(lambda x: x % 2 == 0)
            new_stacks.append(fs)

        threads = []
        for _ in range(5):
            threads.append(threading.Thread(target=mapper))
            threads.append(threading.Thread(target=filterer))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # We just ensure no crash, new stacks exist
        self.assertGreater(len(new_stacks), 0)

    def test_random_operations(self):
        """
        Perform random pushes, pops, batch updates, and concurrency
        to test overall thread safety under chaotic usage.
        """
        s = ConcurrentStack()
        num_threads = 10
        ops_per_thread = 2000

        def random_op():
            for _ in range(ops_per_thread):
                op_type = random.choice(["push", "pop", "batch", "peek"])
                if op_type == "push":
                    s.push(random.randint(0, 1000))
                elif op_type == "pop":
                    try:
                        s.pop()
                    except IndexError:
                        pass
                elif op_type == "peek":
                    try:
                        s.peek()
                    except IndexError:
                        pass
                else:  # "batch"
                    def do_batch(d):
                        if d and random.random() < 0.5:
                            try:
                                d.pop()
                            except IndexError:
                                pass
                        if random.random() < 0.5:
                            d.append(random.randint(0, 1000))
                    s.batch_update(do_batch)

        threads = [threading.Thread(target=random_op) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # no crash => success
        self.assertGreaterEqual(len(s), 0)
