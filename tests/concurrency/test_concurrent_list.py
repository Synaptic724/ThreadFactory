import threading
import unittest
import time
import random
from thread_factory import ConcurrentList


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

        # Note: __rmul__ is typically handled by Python if __mul__ is implemented
        # and returns a type with appropriate __rmul__ or the result is of a type
        # that handles __rmul__ itself. ConcurrentList returns a new ConcurrentList
        # in __mul__, so rmul should work correctly.
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
        # Using the context manager bypasses cleanup() on exit, the list is *not* cleared automatically here.
        # The cleanup implementation is called by __exit__, which *does* clear the list.
        # The previous version of the test description for context manager was inaccurate.
        # Let's update the test to reflect the ConcurrentDict __exit__ behavior.
        # The __exit__ method calls cleanup, which clears the list.
        self.assertEqual(len(clist), 0)


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


    def test_concurrency_basic(self):
        """
        Basic concurrency test: multiple runtime appending to the list.
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
        Multiple runtime calling batch_update with different manipulations.
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
        Stress test with runtime performing slicing assignments/deletions concurrently.
        """
        clist = ConcurrentList(list(range(100))) # Ensure it's a list initially

        def slicer():
            for _ in range(200):
                 # Perform a batch update to handle modifications safely
                def batch(lst):
                    # Reverse slice
                    if len(lst) > 10:
                        lst[0:10] = list(reversed(lst[0:10])) # Need to make list for slice assignment

                    # Delete random slice
                    if len(lst) > 5:
                         try:
                             start = random.randint(0, len(lst) - 5)
                             end = start + random.randint(1, 5)
                             del lst[start:end]
                         except (IndexError, ValueError):
                             pass # Ignore potential errors during rapid changes

                clist.batch_update(batch)


        threads = [threading.Thread(target=slicer) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertTrue(len(clist) >= 0)  # No crash or negative


    def test_update_with_iterable(self):
        # Create an initial ConcurrentList
        clist = ConcurrentList([1, 2, 3])

        # Another iterable to update from
        other_items = [4, 5, 6]

        # Perform the update
        clist.update(other_items) # Note: ConcurrentList does not have an `update` method like dict.
                                  # The closest is `extend`. Let's add an `update` method if needed,
                                  # or use extend for this test. Based on the code, there is no `update` method.
                                  # This test seems copied from ConcurrentDict. Let's use extend instead.
        clist = ConcurrentList([1, 2, 3]) # Reset for extend
        clist.extend(other_items)


        # Assert the list now contains the old and new items
        expected_result = [1, 2, 3, 4, 5, 6]
        self.assertEqual(clist.to_list(), expected_result)

    def test_update_with_empty_iterable(self):
        clist = ConcurrentList([1, 2, 3])
        other_items = []
        clist.extend(other_items) # Use extend

        expected_result = [1, 2, 3]
        self.assertEqual(clist.to_list(), expected_result)

    def test_update_with_generator(self):
        clist = ConcurrentList([10, 20])
        def gen():
            for i in range(3):
                yield i * 10
        clist.extend(gen()) # Use extend

        expected_result = [10, 20, 0, 10, 20]
        self.assertEqual(clist.to_list(), expected_result)

    # --- Freeze Tests ---

    def test_is_frozen_property(self):
        clist = ConcurrentList[int]()
        self.assertFalse(clist.is_frozen)
        clist.freeze()
        self.assertTrue(clist.is_frozen)
        clist.unfreeze()
        self.assertFalse(clist.is_frozen)

    def test_freeze_prevents_setitem(self):
        clist = ConcurrentList([1, 2, 3])
        clist.freeze()
        with self.assertRaises(TypeError):
            clist[0] = 99 # Modify existing
        with self.assertRaises(TypeError):
            clist[1:3] = [10, 20] # Modify slice

    def test_freeze_prevents_delitem(self):
        clist = ConcurrentList([1, 2, 3])
        clist.freeze()
        with self.assertRaises(TypeError):
            del clist[0]
        with self.assertRaises(TypeError):
            del clist[1:3]
        # Also test deleting non-existent index still raises TypeError first
        with self.assertRaises(TypeError):
             del clist[10]

    def test_freeze_prevents_append(self):
        clist = ConcurrentList([1])
        clist.freeze()
        with self.assertRaises(TypeError):
            clist.append(2)

    def test_freeze_prevents_extend(self):
        clist = ConcurrentList([1])
        clist.freeze()
        with self.assertRaises(TypeError):
            clist.extend([2, 3])

    def test_freeze_prevents_insert(self):
        clist = ConcurrentList([1])
        clist.freeze()
        with self.assertRaises(TypeError):
            clist.insert(0, 0)

    def test_freeze_prevents_remove(self):
        clist = ConcurrentList([1, 2])
        clist.freeze()
        with self.assertRaises(TypeError):
            clist.remove(1)
        # Test removing non-existent item still raises TypeError first
        with self.assertRaises(TypeError):
             clist.remove(99)


    def test_freeze_prevents_pop(self):
        clist = ConcurrentList([1, 2])
        clist.freeze()
        with self.assertRaises(TypeError):
            clist.pop()
        with self.assertRaises(TypeError):
            clist.pop(0)

    def test_freeze_prevents_clear(self):
        clist = ConcurrentList([1, 2])
        clist.freeze()
        with self.assertRaises(TypeError):
            clist.clear()

    def test_freeze_prevents_iadd(self):
        clist = ConcurrentList([1])
        clist.freeze()
        with self.assertRaises(TypeError):
            clist += [2]

    def test_freeze_prevents_imul(self):
        clist = ConcurrentList([1])
        clist.freeze()
        with self.assertRaises(TypeError):
            clist *= 2

    def test_freeze_prevents_batch_update(self):
        clist = ConcurrentList([1])
        clist.freeze()
        def updater(lst):
            lst.append(2)
        with self.assertRaises(TypeError):
            clist.batch_update(updater)


    def test_freeze_allows_getitem(self):
        clist = ConcurrentList([10, 20, 30])
        clist.freeze()
        self.assertEqual(clist[1], 20)
        self.assertEqual(clist[:2], [10, 20])
        with self.assertRaises(IndexError):
            _ = clist[10] # Still raises IndexError if index doesn't exist

    def test_freeze_allows_len(self):
        clist = ConcurrentList([1, 2, 3])
        clist.freeze()
        self.assertEqual(len(clist), 3)

    def test_freeze_allows_bool(self):
        clist_empty = ConcurrentList[int]()
        clist_empty.freeze()
        self.assertFalse(clist_empty)

        clist_full = ConcurrentList([1])
        clist_full.freeze()
        self.assertTrue(clist_full)

    def test_freeze_allows_contains(self):
        clist = ConcurrentList([10, 20])
        clist.freeze()
        self.assertIn(10, clist)
        self.assertNotIn(30, clist)

    def test_freeze_allows_iter(self):
        clist = ConcurrentList([1, 2, 3])
        clist.freeze()
        items = list(clist)
        self.assertEqual(items, [1, 2, 3])

    def test_freeze_allows_reversed(self):
        clist = ConcurrentList([1, 2, 3])
        clist.freeze()
        items = list(reversed(clist))
        self.assertEqual(items, [3, 2, 1])

    def test_freeze_allows_mul(self):
        clist = ConcurrentList([1, 2])
        clist.freeze()
        result = clist * 3
        self.assertIsInstance(result, ConcurrentList)
        self.assertFalse(result.is_frozen) # Resulting list should not be frozen
        self.assertEqual(list(result), [1, 2, 1, 2, 1, 2])

    def test_freeze_allows_copy_deepcopy_tolist(self):
        import copy
        clist = ConcurrentList([{"x": 1}, {"y": 2}])
        clist.freeze()

        shallow_copy = clist.copy()
        self.assertIsInstance(shallow_copy, ConcurrentList)
        self.assertFalse(shallow_copy.is_frozen)
        self.assertEqual(list(shallow_copy), [{"x": 1}, {"y": 2}])

        deep_copy = copy.deepcopy(clist)
        self.assertIsInstance(deep_copy, ConcurrentList)
        self.assertFalse(deep_copy.is_frozen)
        self.assertEqual(list(deep_copy), [{"x": 1}, {"y": 2}])
        # Ensure it's a deep copy
        clist[0]["x"] = 999 # Modify original (if mutable)
        self.assertEqual(deep_copy[0]["x"], 1) # Deep copy should not be affected

        normal_list = clist.to_list()
        self.assertIsInstance(normal_list, list)
        self.assertEqual(normal_list, [{"x": 999}, {"y": 2}]) # to_list gets current state

    def test_freeze_allows_map_filter_reduce(self):
        clist = ConcurrentList([1, 2, 3, 4])
        clist.freeze()

        mapped = clist.map(lambda x: x * 10)
        self.assertIsInstance(mapped, ConcurrentList)
        self.assertFalse(mapped.is_frozen)
        self.assertEqual(list(mapped), [10, 20, 30, 40])

        filtered = clist.filter(lambda x: x % 2 == 0)
        self.assertIsInstance(filtered, ConcurrentList)
        self.assertFalse(filtered.is_frozen)
        self.assertEqual(list(filtered), [2, 4])

        summed = clist.reduce(lambda acc, x: acc + x, 0)
        self.assertEqual(summed, 10)

        # reduce without initial
        self.assertEqual(clist.reduce(lambda acc, x: acc + x), 10)


    def test_freeze_unfreeze_cycle(self):
        clist = ConcurrentList([1, 2])

        # Freeze and try to modify (should fail)
        clist.freeze()
        self.assertTrue(clist.is_frozen)
        with self.assertRaises(TypeError):
            clist.append(3)

        # Unfreeze and modify (should work)
        clist.unfreeze()
        self.assertFalse(clist.is_frozen)
        clist.append(3)
        self.assertIn(3, clist)

        # Freeze again and try to modify (should fail again)
        clist.freeze()
        self.assertTrue(clist.is_frozen)
        with self.assertRaises(TypeError):
            del clist[0]

    def test_freeze_is_idempotent(self):
        clist = ConcurrentList([1])
        clist.freeze()
        self.assertTrue(clist.is_frozen)
        clist.freeze() # Call freeze again
        self.assertTrue(clist.is_frozen)
        # Check that it's still frozen and modifications are prevented
        with self.assertRaises(TypeError):
            clist.append(2)

    def test_unfreeze_is_idempotent(self):
        clist = ConcurrentList([1])
        clist.freeze()
        self.assertTrue(clist.is_frozen)
        clist.unfreeze()
        self.assertFalse(clist.is_frozen)
        clist.unfreeze() # Call unfreeze again
        self.assertFalse(clist.is_frozen)
        # Check that it's still unfrozen and modifications are allowed
        try:
            clist.append(2)
            self.assertIn(2, clist)
        except TypeError:
            self.fail("Unfreezing multiple times should keep it mutable.")

    def test_cleanup(self):
        """
        Ensures that cleanup:
            - Clears all data.
            - Marks the list as cleaned.
            - Is idempotent (can be called multiple times without error).
        """
        clist = ConcurrentList([1, 2])

        # Check initial state
        self.assertIn(1, clist)
        self.assertEqual(len(clist), 2)
        self.assertFalse(clist.cleaned)

        # cleanup it
        clist.cleanup()

        # It should be marked as cleaned
        self.assertTrue(clist.cleaned)

        # It should be cleared
        self.assertEqual(len(clist), 0)
        self.assertNotIn(1, clist)
        self.assertNotIn(2, clist)

        # Calling cleanup again should not fail
        try:
            clist.cleanup()
        except Exception as e:
            self.fail(f"Calling cleanup() a second time raised an exception: {e}")

    def test_cleanup_clears_frozen_list(self):
        """Ensures cleanup still clears the list even if it's frozen."""
        clist = ConcurrentList([1, 2, 3])
        clist.freeze()
        self.assertTrue(clist.is_frozen)
        self.assertEqual(len(clist), 3)

        clist.cleanup()

        self.assertTrue(clist.cleaned)
        self.assertEqual(len(clist), 0)
        self.assertNotIn(1, clist)


class HighPerformanceConcurrentListTest(unittest.TestCase):
    def setUp(self):
        # This runs before every test method
        self.thread_count = 20  # Increase for more pressure
        self.operations_per_thread = 100_000  # Heavy ops per thread
        self.clist = ConcurrentList()

    def test_massive_concurrent_operations(self):
        """
        Stress test with a large number of concurrent operations (append, pop, slicing, etc.)
        """
        # Initialize with some data to make pops/slicing more likely to hit
        initial_size = 1000
        self.clist = ConcurrentList(list(range(initial_size)))

        def worker(thread_id):
            for _ in range(self.operations_per_thread):
                action = random.randint(0, 9)

                if action < 3:  # 30% chance to append
                    self.clist.append(thread_id)
                elif action < 5:  # 20% chance to pop (with protection)
                    try:
                        self.clist.pop()  # Pop correctly handles empty list
                    except IndexError:
                        pass
                elif action < 7:  # 20% chance to delete slice
                    def batch_delete_slice(lst):
                        if len(lst) > 5:  # This len check is safe because it's inside the batch_update lock
                            try:
                                start = random.randint(0, len(lst) - 5)
                                end = start + random.randint(1, 5)
                                del lst[start:end]
                            except (IndexError, ValueError):  # Catching errors during list mutation under lock
                                pass

                    self.clist.batch_update(batch_delete_slice)
                else:  # 30% chance to read (getitem or check len/contains)
                    read_action = random.randint(0, 2)
                    if read_action == 0:  # getitem
                        # Acquire lock to ensure the list doesn't change size
                        # while we check length, calculate index, and access the item
                        with self.clist._lock:
                            if len(self.clist) > 0:
                                # Calculate index safely *within* the lock
                                try:
                                    index = random.randint(0, len(self.clist) - 1)
                                    # Access item safely *within* the lock
                                    _ = self.clist[index]
                                except IndexError:
                                    # This catch isbelt-and-suspenders; shouldn't happen if len > 0 and index is correct
                                    pass
                            # If len is 0, we just skip, no error raised.
                    elif read_action == 1:  # len
                        _ = len(self.clist)  # len() internally uses the lock or is safe if frozen
                    else:  # contains
                        # 'in' internally uses the lock or is safe if frozen
                        _ = random.randint(0, self.thread_count + initial_size) in self.clist


        threads = [threading.Thread(target=worker, args=(tid,)) for tid in range(self.thread_count)]

        start = time.perf_counter()

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        end = time.perf_counter()

        print(f"\nMassive Concurrent Operations test: completed in {end - start:.2f}s")
        print(f"Final list length: {len(self.clist)}")

        # Sanity check: no crash, length should be non-negative
        self.assertGreaterEqual(len(self.clist), 0)


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)