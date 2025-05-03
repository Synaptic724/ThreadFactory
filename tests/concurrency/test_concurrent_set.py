# tests/test_concurrent_set.py
import threading
import unittest
import random
import time
import copy
from thread_factory.concurrency.concurrent_set import ConcurrentSet
from thread_factory.concurrency.concurrent_list import ConcurrentList


class TestConcurrentSet(unittest.TestCase):

    def test_init_and_add(self):
        cset = ConcurrentSet([1, 2, 3])
        self.assertEqual(len(cset), 3)
        cset.add(4)
        self.assertIn(4, cset)
        self.assertEqual(len(cset), 4)

    def test_remove_and_discard(self):
        cset = ConcurrentSet([1, 2, 3])
        cset.remove(2)
        self.assertNotIn(2, cset)
        # discard should *not* raise
        cset.discard(99)
        with self.assertRaises(KeyError):
            cset.remove(42)

    def test_clear(self):
        cset = ConcurrentSet([1, 2, 3])
        cset.clear()
        self.assertEqual(len(cset), 0)


    def test_union_intersection_difference_symdiff(self):
        a = ConcurrentSet([1, 2, 3])
        b = [3, 4, 5]
        self.assertEqual(a.union(b).to_set(), {1, 2, 3, 4, 5})
        self.assertEqual(a.intersection(b).to_set(), {3})
        self.assertEqual(a.difference(b).to_set(), {1, 2})
        self.assertEqual(a.symmetric_difference(b).to_set(), {1, 2, 4, 5})


    def test_inplace_operators(self):
        cset = ConcurrentSet([1, 2, 3])
        cset |= [3, 4]
        self.assertEqual(cset.to_set(), {1, 2, 3, 4})
        cset &= [2, 4]
        self.assertEqual(cset.to_set(), {2, 4})
        cset -= [4]
        self.assertEqual(cset.to_set(), {2})
        cset ^= [2, 99]
        self.assertEqual(cset.to_set(), {99})


    def test_map_filter_reduce(self):
        cset = ConcurrentSet(range(1, 5))            # {1,2,3,4}
        self.assertEqual(cset.map(lambda x: x * 10).to_set(), {10, 20, 30, 40})
        self.assertEqual(cset.filter(lambda x: x % 2 == 0).to_set(), {2, 4})
        self.assertEqual(cset.reduce(lambda acc, x: acc + x), 10)
        self.assertEqual(cset.reduce(lambda a, x: a + x, 100), 110)


    def test_eq_and_ne(self):
        a = ConcurrentSet([1, 2, 3])
        b = ConcurrentSet([3, 2, 1])
        self.assertTrue(a == b)
        self.assertFalse(a != b)
        self.assertTrue(a == {1, 2, 3})
        self.assertFalse(a == {1, 2})


    def test_freeze_blocks_mutation(self):
        cset = ConcurrentSet([1])
        cset.freeze()
        self.assertTrue(cset.is_frozen)
        with self.assertRaises(TypeError):
            cset.add(2)
        with self.assertRaises(TypeError):
            cset.remove(1)
        with self.assertRaises(TypeError):
            cset |= {3}

    def test_freeze_allows_reads(self):
        cset = ConcurrentSet([10, 20])
        cset.freeze()
        self.assertEqual(len(cset), 2)
        self.assertIn(10, cset)
        items = list(cset)
        self.assertCountEqual(items, [10, 20])

    def test_freeze_unfreeze_cycle(self):
        cset = ConcurrentSet([1])
        cset.freeze()
        with self.assertRaises(TypeError):
            cset.add(99)
        cset.unfreeze()
        cset.add(99)
        self.assertIn(99, cset)


    def test_batch_update(self):
        cset = ConcurrentSet([1, 2, 3])
        def op(s):
            s.discard(1)
            s.update({99, 100})
        cset.batch_update(op)
        self.assertEqual(cset.to_set(), {2, 3, 99, 100})


    def test_to_set_and_to_concurrent_list(self):
        cset = ConcurrentSet({7, 8, 9})
        snapshot = cset.to_set()
        self.assertEqual(snapshot, {7, 8, 9})
        clist = cset.to_concurrent_list()
        self.assertIsInstance(clist, ConcurrentList)
        self.assertCountEqual(clist.to_list(), [7, 8, 9])


    def test_copy_and_deepcopy(self):
        cs = ConcurrentSet([("x", 1), ("y", 2)])  # tuples are hashable
        shallow = copy.copy(cs)
        deep = copy.deepcopy(cs)

        # mutate original by replacing an element
        cs.discard(("x", 1))
        cs.add(("x", 99))

        # shallow shares references → should differ now
        self.assertNotEqual(cs.to_set(), deep.to_set())
        self.assertNotEqual(cs.to_set(), shallow.to_set())  # tuple values changed


    def test_repr_and_bool(self):
        cs = ConcurrentSet()
        self.assertFalse(cs)
        cs.add(1)
        self.assertTrue(cs)
        self.assertIn("ConcurrentSet", repr(cs))


    def test_context_manager_and_dispose(self):
        cs = ConcurrentSet([1, 2])
        with self.assertWarns(UserWarning):
            with cs as raw:
                raw.add(3)
        self.assertTrue(cs.disposed)
        self.assertEqual(len(cs), 0)

    def test_multithreaded_add(self):
        cs = ConcurrentSet()
        threads = [threading.Thread(target=lambda: [cs.add(i) for i in range(1000)])
                   for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        # Each thread added 0..999; final set size ≤ 1000
        self.assertEqual(len(cs), 1000)


    def test_multithreaded_batch_update(self):
        cs = ConcurrentSet(range(1000))
        def worker():
            def batch(s):
                for _ in range(50):
                    s.discard(random.randint(0, 999))
                    s.add(random.randint(1000, 1100))
            for _ in range(20):
                cs.batch_update(batch)
        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertGreaterEqual(len(cs), 0)  # Sanity: no crash


    def test_massive_concurrent_operations(self):
        cs = ConcurrentSet(range(1000))
        ops = 50_000
        t_count = 20

        def actor():
            for _ in range(ops):
                action = random.randint(0, 3)
                if action == 0:
                    cs.add(random.randint(0, 2000))
                elif action == 1:
                    cs.discard(random.randint(0, 2000))
                elif action == 2:
                    _ = random.randint(0, 2000) in cs
                else:
                    _ = len(cs)

        threads = [threading.Thread(target=actor) for _ in range(t_count)]
        start = time.perf_counter()
        for t in threads: t.start()
        for t in threads: t.join()
        duration = time.perf_counter() - start
        print(f"\nConcurrentSet stress test finished in {duration:.2f}s with size {len(cs)}")
        self.assertGreaterEqual(len(cs), 0)  # just ensure no crash/negative


if __name__ == "__main__":
    unittest.main(argv=["first-arg-is-ignored"], exit=False)
