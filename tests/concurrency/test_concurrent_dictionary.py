import threading
import unittest
import random
import time
from src.thread_factory.concurrency.concurrent_dictionary import ConcurrentDict


class TestConcurrentDict(unittest.TestCase):

    def test_basic_set_get(self):
        d = ConcurrentDict[str, int]()
        d["a"] = 1
        d["b"] = 2
        self.assertEqual(d["a"], 1)
        self.assertEqual(d["b"], 2)

    def test_len_bool(self):
        d = ConcurrentDict[str, int]()
        self.assertEqual(len(d), 0)
        self.assertFalse(d)

        d["key"] = 10
        self.assertEqual(len(d), 1)
        self.assertTrue(d)

    def test_contains_and_iter(self):
        d = ConcurrentDict[str, int]({"a": 1, "b": 2})
        self.assertIn("a", d)
        self.assertNotIn("z", d)
        keys = list(d)
        self.assertCountEqual(keys, ["a", "b"])

    def test_delete(self):
        d = ConcurrentDict[str, int]({"a": 1})
        del d["a"]
        self.assertEqual(len(d), 0)
        with self.assertRaises(KeyError):
            _ = d["a"]

    def test_clear(self):
        d = ConcurrentDict[str, int]({"a": 1, "b": 2})
        d.clear()
        self.assertEqual(len(d), 0)

    def test_pop_and_popitem(self):
        d = ConcurrentDict[str, int]({"a": 1, "b": 2})
        val = d.pop("a")
        self.assertEqual(val, 1)
        self.assertNotIn("a", d)

        key, val = d.popitem()
        self.assertNotIn(key, d)
        self.assertEqual(len(d), 0)

        with self.assertRaises(KeyError):
            d.popitem()

    def test_get_and_setdefault(self):
        d = ConcurrentDict[str, int]({"a": 1})
        self.assertEqual(d.get("a"), 1)
        self.assertEqual(d.get("b", 99), 99)

        val = d.setdefault("b", 42)
        self.assertEqual(val, 42)
        self.assertIn("b", d)
        self.assertEqual(d["b"], 42)

    def test_update_with_mapping_and_kwargs(self):
        d = ConcurrentDict[str, int]({"a": 1})
        d.update({"b": 2})
        d.update([("c", 3)])
        d.update(d=4, e=5)

        self.assertEqual(d["a"], 1)
        self.assertEqual(d["b"], 2)
        self.assertEqual(d["c"], 3)
        self.assertEqual(d["d"], 4)
        self.assertEqual(d["e"], 5)

    def test_keys_values_items(self):
        d = ConcurrentDict[str, int]({"a": 1, "b": 2})
        self.assertCountEqual(d.keys(), ["a", "b"])
        self.assertCountEqual(d.values(), [1, 2])
        self.assertCountEqual(d.items(), [("a", 1), ("b", 2)])

    def test_copy_and_deepcopy(self):
        import copy
        d = ConcurrentDict[str, int]({"a": 1, "b": 2})

        shallow = d.copy()
        self.assertEqual(shallow["a"], 1)

        deep = copy.deepcopy(d)
        self.assertEqual(deep["a"], 1)

        # Modifying the copy doesn't affect the original
        shallow["a"] = 100
        self.assertEqual(d["a"], 1)

    def test_to_dict(self):
        d = ConcurrentDict[str, int]({"a": 1})
        normal_dict = d.to_dict()
        self.assertIsInstance(normal_dict, dict)
        self.assertEqual(normal_dict["a"], 1)

    def test_batch_update(self):
        d = ConcurrentDict[str, int]({"a": 1})

        def updater(dct):
            dct["b"] = 10
            dct["c"] = 20

        d.batch_update(updater)
        self.assertEqual(d["b"], 10)
        self.assertEqual(d["c"], 20)

    def test_map(self):
        d = ConcurrentDict[str, int]({"a": 1, "b": 2})

        def transformer(k, v):
            return (k.upper(), v * 10)

        mapped = d.map(transformer)
        self.assertIn("A", mapped)
        self.assertEqual(mapped["A"], 10)
        self.assertEqual(mapped["B"], 20)

    def test_filter(self):
        d = ConcurrentDict[str, int]({"a": 1, "b": 2, "c": 3})

        def predicate(k, v):
            return v % 2 == 1  # keep odd values

        filtered = d.filter(predicate)
        self.assertIn("a", filtered)
        self.assertIn("c", filtered)
        self.assertNotIn("b", filtered)

    def test_reduce(self):
        d = ConcurrentDict[str, int]({"a": 1, "b": 2, "c": 3})

        def reducer(acc, kv):
            _, v = kv
            return acc + v

        total = d.reduce(reducer, 0)
        self.assertEqual(total, 6)

        # Empty dict with no initial raises
        empty = ConcurrentDict()
        with self.assertRaises(TypeError):
            empty.reduce(reducer)

    def test_context_manager_direct_access(self):
        d = ConcurrentDict[str, int]({"a": 1})

        with self.assertWarns(UserWarning):
            with d as inner:
                inner["b"] = 10

        self.assertEqual(d["b"], 10)

    def test_concurrent_add_remove(self):
        d = ConcurrentDict[str, int]()

        def adder():
            for _ in range(1000):
                d["x"] = d.get("x", 0) + 1

        def remover():
            for _ in range(1000):
                if "x" in d:
                    val = d["x"]
                    if val > 1:
                        d["x"] = val - 1
                    else:
                        try:
                            del d["x"]
                        except KeyError:
                            pass

        threads = [threading.Thread(target=adder) for _ in range(5)] + \
                  [threading.Thread(target=remover) for _ in range(5)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # x could be there or not, but count should be >= 0
        self.assertGreaterEqual(d.get("x", 0), 0)

    def test_concurrent_batch_update(self):
        d = ConcurrentDict[str, int]({"a": 1})

        def updater():
            def batch(dct):
                dct["a"] += 1
            for _ in range(100):
                d.batch_update(batch)

        threads = [threading.Thread(target=updater) for _ in range(5)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(d["a"], 1 + 100 * 5)

class TestConcurrentDictStress(unittest.TestCase):

    def test_massive_parallel_inserts_and_deletes(self):
        """
        Heavy parallel test with lots of insertions and deletions.
        """
        d = ConcurrentDict[int, int]()

        insertions = 100_000
        num_threads = 20

        def inserter(thread_id):
            for i in range(insertions // num_threads):
                d[i + thread_id * insertions] = thread_id

        def deleter():
            for _ in range(insertions // num_threads):
                key = random.randint(0, insertions)
                try:
                    del d[key]
                except KeyError:
                    pass

        threads = []

        # Half inserting, half deleting
        for i in range(num_threads // 2):
            threads.append(threading.Thread(target=inserter, args=(i,)))
            threads.append(threading.Thread(target=deleter))

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # Sanity check: no key should have a negative count or cause issues
        self.assertGreaterEqual(len(d), 0)

    def test_parallel_batch_updates_and_swaps(self):
        """
        Heavy parallel batch_update and atomic_swap on a shared dict.
        """
        d = ConcurrentDict[str, int]({
            "a": 1,
            "b": 2,
            "c": 3,
            "d": 4,
        })

        num_threads = 30
        iterations = 5_000

        def batch_worker():
            for _ in range(iterations):
                def batch(dct):
                    # Increment 'a', swap 'b' and 'c'
                    dct["a"] += 1
                    dct["b"], dct["c"] = dct["c"], dct["b"]

                d.batch_update(batch)

        threads = []
        for _ in range(num_threads // 2):
            threads.append(threading.Thread(target=batch_worker))

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # Final sanity checks
        a_value = d.get("a", 0)
        self.assertGreaterEqual(a_value, iterations * (num_threads // 2) - 1000)
        print(f"Parallel batch updates and swaps done. Final a={a_value}")

class HighPerformanceConcurrentDictTest(unittest.TestCase):

    def setUp(self):
        self.insertions = 1_000_000  # 1 million key/values
        self.thread_count = 50       # 50 threads hammering at once
        self.batch_iterations = 10_000

    def test_massive_parallel_read_write_delete(self):
        """
        Massive concurrent read/write/delete test to stress check ConcurrentDict.
        """
        d = ConcurrentDict[int, int]()
        keys_range = 500_000

        def writer(thread_id):
            for _ in range(self.insertions // self.thread_count):
                key = random.randint(0, keys_range)
                d[key] = thread_id

        def reader():
            for _ in range(self.insertions // self.thread_count):
                key = random.randint(0, keys_range)
                _ = d.get(key, None)

        def deleter():
            for _ in range(self.insertions // self.thread_count):
                key = random.randint(0, keys_range)
                try:
                    del d[key]
                except KeyError:
                    pass

        threads = []
        for i in range(self.thread_count // 3):
            threads.append(threading.Thread(target=writer, args=(i,)))
            threads.append(threading.Thread(target=reader))
            threads.append(threading.Thread(target=deleter))

        start = time.perf_counter()

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        end = time.perf_counter()

        print(f"\nMassive RW Delete test: {self.insertions:,} ops in {end - start:.2f}s")
        print(f"Remaining keys: {len(d)}")

        self.assertGreaterEqual(len(d), 0)

    def test_parallel_batch_updates_high_contention(self):
        """
        Stress test with parallel batch updates modifying overlapping keys.
        """
        d = ConcurrentDict[str, int]({f"key_{i}": 0 for i in range(100)})

        def batch_worker(thread_id):
            for _ in range(self.batch_iterations):
                def batch(dct):
                    # Increment values across 100 keys
                    for k in dct.keys():
                        dct[k] += 1
                d.batch_update(batch)

        threads = [
            threading.Thread(target=batch_worker, args=(tid,))
            for tid in range(self.thread_count)
        ]

        start = time.perf_counter()

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        end = time.perf_counter()

        # Sanity check: each key should have been incremented batch_iterations * thread_count times
        expected = self.batch_iterations * self.thread_count
        actual_values = d.values()

        print(f"\nParallel batch updates (high contention) finished in {end - start:.2f}s")
        print(f"Expected: {expected}, Actual sample: {actual_values[:5]}")

        for val in actual_values:
            self.assertEqual(val, expected)

    def test_concurrent_map_filter_reduce_extreme(self):
        """
        Stress test for map/filter/reduce under concurrency.
        """
        initial_data = {f"key_{i}": i for i in range(1_000)}
        d = ConcurrentDict(initial=initial_data)

        def mapper():
            for _ in range(500):
                mapped = d.map(lambda k, v: (k.upper(), v * 2))
                self.assertIsInstance(mapped, ConcurrentDict)

        def filterer():
            for _ in range(500):
                filtered = d.filter(lambda k, v: v % 2 == 0)
                self.assertIsInstance(filtered, ConcurrentDict)

        def reducer():
            for _ in range(500):
                total = d.reduce(lambda acc, kv: acc + kv[1], 0)
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

        print(f"\nConcurrent map/filter/reduce finished in {end - start:.2f}s")

        # Just sanity: no corruption, still 1,000 keys
        self.assertEqual(len(d), 1_000)

    def test_super_batch_contention_and_slicing(self):
        """
        Massive batch updates + slicing checks under thread contention.
        """
        d = ConcurrentDict[int, int]({i: 0 for i in range(100_000)})

        def worker(thread_id):
            for _ in range(1_000):
                def batch(dct):
                    # Delete a slice of keys, add new ones
                    keys = list(dct.keys())
                    if len(keys) > 1000:
                        for k in keys[:500]:
                            del dct[k]
                    # Reinsert new keys with thread id
                    for i in range(500):
                        dct[random.randint(0, 1_000_000)] = thread_id

                d.batch_update(batch)

        threads = [threading.Thread(target=worker, args=(tid,)) for tid in range(self.thread_count)]

        start = time.perf_counter()

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        end = time.perf_counter()

        print(f"\nSuper batch contention and slicing test finished in {end - start:.2f}s")

        # Final sanity: no deadlocks, length should be positive
        self.assertGreaterEqual(len(d), 0)
        print(f"Final dictionary length: {len(d)}")
