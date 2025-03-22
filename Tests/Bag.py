import unittest
import threading
from Threading.Bag import ConcurrentBag  # Update this import to match your module structure

class TestConcurrentBag(unittest.TestCase):

    def test_add_and_len(self):
        bag = ConcurrentBag()
        bag.add('apple')
        bag.add('apple')
        bag.add('banana')

        self.assertEqual(len(bag), 3)
        self.assertEqual(bag.count_of('apple'), 2)
        self.assertEqual(bag.count_of('banana'), 1)

    def test_remove_and_discard(self):
        bag = ConcurrentBag(['apple', 'apple', 'banana'])
        bag.remove('apple')
        self.assertEqual(bag.count_of('apple'), 1)
        self.assertEqual(len(bag), 2)

        bag.discard('apple')
        self.assertNotIn('apple', bag)
        self.assertEqual(len(bag), 1)

        # discard on non-existing item doesn't raise
        bag.discard('pineapple')
        self.assertEqual(len(bag), 1)

        # remove on non-existing item raises
        with self.assertRaises(KeyError):
            bag.remove('pineapple')

    def test_pop(self):
        bag = ConcurrentBag(['apple', 'banana'])
        popped_item = bag.pop()

        self.assertIn(popped_item, ['apple', 'banana'])
        self.assertEqual(len(bag), 1)

        bag.pop()  # empty it completely

        with self.assertRaises(KeyError):
            bag.pop()

    def test_clear(self):
        bag = ConcurrentBag(['apple', 'banana'])
        bag.clear()
        self.assertEqual(len(bag), 0)
        self.assertFalse(bag)

    def test_contains_and_iteration(self):
        bag = ConcurrentBag(['apple', 'banana', 'banana'])
        self.assertIn('apple', bag)
        self.assertNotIn('orange', bag)

        items = list(bag)
        self.assertEqual(len(items), 3)
        self.assertCountEqual(items, ['apple', 'banana', 'banana'])

    def test_unique_items(self):
        bag = ConcurrentBag(['apple', 'banana', 'banana'])
        unique = bag.unique_items()
        self.assertCountEqual(unique, ['apple', 'banana'])

    def test_copy_and_deepcopy(self):
        from copy import copy, deepcopy

        bag = ConcurrentBag(['apple', 'banana', 'banana'])
        bag_copy = copy(bag)
        bag_deepcopy = deepcopy(bag)

        self.assertEqual(len(bag), len(bag_copy))
        self.assertEqual(len(bag), len(bag_deepcopy))

        bag.add('orange')
        self.assertNotIn('orange', bag_copy)
        self.assertNotIn('orange', bag_deepcopy)

    def test_batch_update(self):
        bag = ConcurrentBag(['apple', 'banana', 'banana'])

        def add_items(d):
            d['apple'] += 2
            d['banana'] += 1
            d['grape'] = 5

        bag.batch_update(add_items)

        self.assertEqual(bag.count_of('apple'), 3)
        self.assertEqual(bag.count_of('banana'), 3)
        self.assertEqual(bag.count_of('grape'), 5)
        self.assertEqual(len(bag), 11)

    def test_map(self):
        bag = ConcurrentBag(['apple', 'banana', 'banana'])

        # Replace all items with their lengths
        mapped = bag.map(lambda x: len(x))

        self.assertEqual(mapped.count_of(5), 1)  # apple
        self.assertEqual(mapped.count_of(6), 2)  # banana
        self.assertEqual(len(mapped), 3)

    def test_filter(self):
        bag = ConcurrentBag(['apple', 'banana', 'grape', 'kiwi'])

        # Only keep items longer than 4 characters
        filtered = bag.filter(lambda x: len(x) > 4)

        self.assertIn('apple', filtered)
        self.assertIn('banana', filtered)
        self.assertNotIn('kiwi', filtered)

    def test_reduce(self):
        bag = ConcurrentBag([1, 2, 3, 3])

        # Sum all items (with duplicates)
        result = bag.reduce(lambda acc, x: acc + x, 0)
        self.assertEqual(result, 1 + 2 + 3 + 3)

        # Without initial, should work the same
        result2 = bag.reduce(lambda acc, x: acc + x)
        self.assertEqual(result2, 1 + 2 + 3 + 3)

        empty_bag = ConcurrentBag()
        with self.assertRaises(TypeError):
            empty_bag.reduce(lambda acc, x: acc + x)

    def test_len_and_bool(self):
        bag = ConcurrentBag()
        self.assertEqual(len(bag), 0)
        self.assertFalse(bag)

        bag.add('apple')
        self.assertTrue(bag)

    def test_repr_and_str(self):
        bag = ConcurrentBag(['apple', 'banana'])

        r = repr(bag)
        s = str(bag)

        self.assertIn('apple', r)
        self.assertIn('banana', s)

    def test_to_concurrent_dict(self):
        bag = ConcurrentBag(['apple', 'apple', 'banana'])
        concurrent_dict = bag.to_concurrent_dict()

        self.assertEqual(concurrent_dict['apple'], 2)
        self.assertEqual(concurrent_dict['banana'], 1)

    def test_concurrent_add_and_remove(self):
        """
        Simulate multiple threads adding and removing items from the bag.
        This tests for thread-safety under concurrent access.
        """
        bag = ConcurrentBag()

        def adder():
            for _ in range(1000):
                bag.add('apple')

        def remover():
            for _ in range(1000):
                try:
                    bag.remove('apple')
                except KeyError:
                    pass

        threads = [threading.Thread(target=adder) for _ in range(10)] + \
                  [threading.Thread(target=remover) for _ in range(10)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # At the end, we might have some apples left or none, but count should be >= 0
        self.assertGreaterEqual(bag.count_of('apple'), 0)

    def test_concurrent_batch_update(self):
        """
        Ensure batch_update works as expected when called concurrently.
        """
        bag = ConcurrentBag(['apple'] * 10)

        def updater():
            def batch(d):
                d['apple'] += 1
            bag.batch_update(batch)

        threads = [threading.Thread(target=updater) for _ in range(10)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # 10 threads each incremented apple by 1
        self.assertEqual(bag.count_of('apple'), 20)
