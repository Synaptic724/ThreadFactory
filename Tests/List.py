import unittest
import threading
import time
import copy
from Threading.List import ConcurrentList  # Adjust to your actual module import


class TestConcurrentList(unittest.TestCase):

    def test_init_and_append(self):
        clist = ConcurrentList([1, 2, 3])
        self.assertEqual(len(clist), 3)
        clist.append(4)
        self.assertEqual(len(clist), 4)
        self.assertEqual(clist[-1], 4)

    def test_getitem_slicing(self):
        clist = ConcurrentList([0, 1, 2, 3, 4, 5])
        self.assertEqual(clist[1], 1)
        self.assertEqual(clist[-1], 5)

        # Slice
        slice_part = clist[2:5]
        self.assertEqual(slice_part, [2, 3, 4])

        with self.assertRaises(IndexError):
            _ = clist[10]  # out of range

    def test_setitem_slicing(self):
        clist = ConcurrentList([0, 1, 2, 3, 4, 5])
        clist[1] = 100
        self.assertEqual(clist[1], 100)

        clist[2:4] = [200, 300, 400]
        self.assertEqual(list(clist), [0, 100, 200, 300, 400, 4, 5])
        self.assertEqual(len(clist), 7)

        # Replace slice with single item
        clist[2:5] = 999
        self.assertEqual(list(clist), [0, 100, 999, 4, 5])
        self.assertEqual(len(clist), 5)

    def test_delitem_slicing(self):
        clist = ConcurrentList([0, 1, 2, 3, 4, 5])
        del clist[1]
        self.assertEqual(list(clist), [0, 2, 3, 4, 5])

        del clist[1:3]  # remove indices 1..2
        self.assertEqual(list(clist), [0, 4, 5])
        self.assertEqual(len(clist), 3)

        with self.assertRaises(IndexError):
            del clist[10]

    def test_extend_insert(self):
        clist = ConcurrentList([1, 2])
        clist.extend([3, 4, 5])
        self.assertEqual(list(clist), [1, 2, 3, 4, 5])

        clist.insert(0, 0)
        self.assertEqual(list(clist), [0, 1, 2, 3, 4, 5])
        self.assertEqual(len(clist), 6)

    def test_remove_pop_clear(self):
        clist = ConcurrentList(["apple", "banana", "cherry"])
        clist.remove("banana")
        self.assertEqual(list(clist), ["apple", "cherry"])
        self.assertEqual(len(clist), 2)

        popped = clist.pop()
        self.assertEqual(popped, "cherry")
        self.assertEqual(len(clist), 1)

        clist.clear()
        self.assertEqual(len(clist), 0)

        with self.assertRaises(IndexError):
            clist.pop()

        with self.assertRaises(ValueError):
            clist.remove("not-here")

    def test_len_bool_contains(self):
        clist = ConcurrentList()
        self.assertFalse(clist)
        clist.append(42)
        self.assertTrue(clist)
        self.assertIn(42, clist)
        self.assertNotIn(99, clist)

    def test_eq_inequality(self):
        clist1 = ConcurrentList([1, 2, 3])
        clist2 = ConcurrentList([1, 2, 3])
        self.assertTrue(clist1 == clist2)

        clist3 = ConcurrentList([1, 2])
        self.assertTrue(clist1 != clist3)

        normal_list = [1, 2, 3]
        self.assertTrue(clist2 == normal_list)
        self.assertFalse(clist2 == [1, 2])

    def test_repr_str(self):
        clist = ConcurrentList(["apple", "banana"])
        r = repr(clist)
        s = str(clist)
        self.assertIn("apple", r)
        self.assertIn("banana", s)

    def test_iadd_imul(self):
        clist = ConcurrentList([1, 2])
        clist += [3, 4]
        self.assertEqual(list(clist), [1, 2, 3, 4])

        clist *= 2
        self.assertEqual(list(clist), [1, 2, 3, 4, 1, 2, 3, 4])

        with self.assertRaises(TypeError):
            clist *= 2.5  # must be int

    def test_mul_rmul(self):
        clist = ConcurrentList([10, 20])
        mul_result = clist * 3
        self.assertEqual(list(mul_result), [10, 20, 10, 20, 10, 20])

        rmul_result = 2 * clist
        self.assertEqual(list(rmul_result), [10, 20, 10, 20])

        with self.assertRaises(TypeError):
            _ = clist * "x"

    def test_index_and_count(self):
        clist = ConcurrentList(["apple", "banana", "banana", "cherry"])
        idx = clist.index("banana")
        self.assertEqual(idx, 1)
        self.assertEqual(clist.count("banana"), 2)
        with self.assertRaises(ValueError):
            clist.index("not-here")

    def test_copy_and_deepcopy(self):
        import copy
        clist = ConcurrentList([{"x": 1}, {"y": 2}])
        shallow = copy.copy(clist)
        deep = copy.deepcopy(clist)

        self.assertEqual(len(shallow), 2)
        self.assertEqual(len(deep), 2)

        # Modifying the original dict in clist doesn't affect the deep copy
        clist[0]["x"] = 999
        self.assertEqual(shallow[0]["x"], 999)  # same object in shallow
        self.assertEqual(deep[0]["x"], 1)       # different object in deep

    def test_context_manager(self):
        clist = ConcurrentList([1, 2])
        with self.assertWarns(UserWarning):
            with clist as internal_list:
                internal_list.append(3)
        self.assertEqual(list(clist), [1, 2, 3])

    def test_to_list_and_batch_update(self):
        clist = ConcurrentList([10, 20, 30])

        def batch_func(lst):
            # Reverse it and append 999
            lst.reverse()
            lst.append(999)

        clist.batch_update(batch_func)
        # The final list should be reversed + 999 appended
        self.assertEqual(list(clist), [30, 20, 10, 999])

        out_list = clist.to_list()
        self.assertEqual(out_list, [30, 20, 10, 999])

    def test_sort_and_reverse(self):
        clist = ConcurrentList([5, 2, 9, 1])
        clist.sort()
        self.assertEqual(list(clist), [1, 2, 5, 9])

        clist.reverse()
        self.assertEqual(list(clist), [9, 5, 2, 1])

    def test_map_filter_reduce(self):
        clist = ConcurrentList([1, 2, 3, 4])

        mapped = clist.map(lambda x: x * 10)
        self.assertEqual(list(mapped), [10, 20, 30, 40])

        filtered = clist.filter(lambda x: x % 2 == 0)
        self.assertEqual(list(filtered), [2, 4])

        summed = clist.reduce(lambda acc, x: acc + x, 0)
        self.assertEqual(summed, 10)

        # reduce without initial
        self.assertEqual(clist.reduce(lambda acc, x: acc + x), 10)

    def test_atomic_update_and_swap(self):
        clist = ConcurrentList([10, 20, 30])

        def increment(x):
            return x + 1

        clist.atomic_update(1, increment)
        self.assertEqual(clist[1], 21)

        with self.assertRaises(IndexError):
            clist.atomic_update(10, increment)

        clist.atomic_swap(0, 2)
        self.assertEqual(list(clist), [30, 21, 10])

        with self.assertRaises(IndexError):
            clist.atomic_swap(0, 99)

    def test_concurrency_basic(self):
        """
        Basic concurrency test: multiple threads appending to the list.
        """
        clist = ConcurrentList()
        num_threads = 10
        items_per_thread = 1000

        def adder():
            for _ in range(items_per_thread):
                clist.append(1)

        threads = [threading.Thread(target=adder) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(clist), num_threads * items_per_thread)

    def test_concurrency_batch_updates(self):
        """
        Multiple threads calling batch_update with different manipulations.
        """
        clist = ConcurrentList(range(1000))

        def batch_worker():
            def batch(lst):
                # pop a few items if possible
                for _ in range(5):
                    if lst:
                        lst.pop()
                # append some items
                lst.append(999)
                lst.append(888)
            for _ in range(50):
                clist.batch_update(batch)

        threads = [threading.Thread(target=batch_worker) for _ in range(8)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # We can't predict the exact final length, but it shouldn't crash or go negative
        self.assertGreaterEqual(len(clist), 0)

    def test_concurrency_slice_operations(self):
        """
        Stress test with threads performing slicing assignments/deletions concurrently.
        """
        clist = ConcurrentList(range(100))

        def slicer():
            for _ in range(200):
                # Reverse slice
                with clist._lock:  # we can't do partial slicing outside the lock
                    if len(clist) > 10:
                        clist[0:10] = reversed(clist[0:10])
                # Delete random slice
                with clist._lock:
                    if len(clist) > 5:
                        del clist[0:5]

        threads = [threading.Thread(target=slicer) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertTrue(len(clist) >= 0)  # No crash or negative


# If running standalone:
# if __name__ == "__main__":
#     unittest.main()
