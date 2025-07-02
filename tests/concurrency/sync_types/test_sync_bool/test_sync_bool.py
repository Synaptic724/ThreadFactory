import math
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import pickle
import copy
import sys

# ---- import your concrete classes ----------------------------------
from thread_factory.concurrency.sync_types.sync_bool import SyncBool
from thread_factory.concurrency.sync_types.sync_int import SyncInt
from thread_factory.concurrency.sync_types.sync_float import SyncFloat
from thread_factory.utils.interfaces.isync import ISync # Import ISync to test _unwrap_other


# --------------------------------------------------------------------
# Helper used in several tests
# --------------------------------------------------------------------
def _spawn_threads(fn, num_threads=8, iterations_per_thread=1):
    """
    Spawns multiple threads to execute a given function.
    Args:
        fn (callable): The function to execute in each thread.
        num_threads (int): The number of threads to spawn.
        iterations_per_thread (int): How many times 'fn' should be called by each thread.
    """
    with ThreadPoolExecutor(max_workers=num_threads) as ex:
        list(ex.map(lambda _: [fn() for _ in range(iterations_per_thread)], range(num_threads)))


class TestSyncBool(unittest.TestCase):

    # ────────────────────────────────────────────────────────────────
    # Core Functionality (retained from original/previous for completeness)
    # ────────────────────────────────────────────────────────────────
    def test_initial_true(self):
        b = SyncBool(True)
        self.assertTrue(b.get())

    def test_initial_false(self):
        b = SyncBool(False)
        self.assertFalse(b.get())

    def test_set_true(self):
        b = SyncBool()
        b.set(True)
        self.assertTrue(b.get())

    def test_set_false(self):
        b = SyncBool(True)
        b.set(False)
        self.assertFalse(b.get())

    def test_toggle_functionality(self):
        b = SyncBool(False)
        b.toggle()
        self.assertTrue(b.get())
        b.toggle()
        self.assertFalse(b.get())

    def test_int_conversion(self):
        b = SyncBool(True)
        self.assertEqual(int(b), 1)
        b.set(False)
        self.assertEqual(int(b), 0)

    def test_float_conversion(self):
        b = SyncBool(True)
        self.assertEqual(float(b), 1.0)
        b.set(False)
        self.assertEqual(float(b), 0.0)

    def test_index(self):
        b = SyncBool(True)
        self.assertEqual(b.__index__(), 1)
        b.set(False)
        self.assertEqual(b.__index__(), 0)

    def test_truthiness(self):
        b = SyncBool(True)
        self.assertTrue(bool(b))
        b.set(False)
        self.assertFalse(bool(b))

    def test_str_repr(self):
        b = SyncBool(True)
        self.assertEqual(str(b), "True")
        self.assertEqual(repr(b), "True")
        b.set(False)
        self.assertEqual(str(b), "False")
        self.assertEqual(repr(b), "False")

    def test_hash(self):
        b = SyncBool(True)
        self.assertEqual(hash(b), hash(True))
        b.set(False)
        self.assertEqual(hash(b), hash(False))

    def test_format(self):
        b = SyncBool(True)
        self.assertEqual(format(b, ""), "True")
        self.assertEqual(format(b, "d"), "1")
        b.set(False)
        self.assertEqual(format(b, ""), "False")
        self.assertEqual(format(b, "d"), "0")

    def test_comparisons(self):
        b = SyncBool(True)
        self.assertTrue(b == True)
        self.assertFalse(b != True)
        self.assertTrue(b != False)
        self.assertTrue(b == 1)
        self.assertFalse(b == 0)
        self.assertTrue(b == 1.0)
        self.assertFalse(b == 0.0)

    def test_and_operation(self):
        b = SyncBool(True)
        self.assertTrue(b & True)
        self.assertFalse(b & False)
        self.assertTrue(b & 1)
        self.assertFalse(b & 0)
        self.assertTrue(b & SyncBool(True))
        self.assertFalse(b & SyncBool(False))

    def test_or_operation(self):
        b = SyncBool(False)
        self.assertTrue(b | True)
        self.assertFalse(b | False)
        self.assertTrue(b | 1)
        self.assertFalse(b | 0)
        self.assertTrue(b | SyncBool(True))
        self.assertFalse(b | SyncBool(False))

    def test_xor_operation(self):
        b = SyncBool(True)
        self.assertFalse(b ^ True)
        self.assertTrue(b ^ False)
        self.assertFalse(b ^ 1)
        self.assertTrue(b ^ 0)
        self.assertFalse(b ^ SyncBool(True))
        self.assertTrue(b ^ SyncBool(False))

    def test_invert_behavior(self):
        b = SyncBool(True)
        self.assertEqual(~b, -2)
        b.set(False)
        self.assertEqual(~b, -1)

    def test_reverse_and(self):
        b = SyncBool(True)
        self.assertTrue(True & b)
        self.assertFalse(False & b)
        self.assertTrue(1 & b)
        self.assertFalse(0 & b)
        self.assertTrue(SyncBool(True) & b)
        self.assertFalse(SyncBool(False) & b)

    def test_reverse_or(self):
        b = SyncBool(False)
        self.assertTrue(True | b)
        self.assertFalse(False | b)
        self.assertTrue(1 | b)
        self.assertFalse(0 | b)
        self.assertTrue(SyncBool(True) | b)
        self.assertFalse(SyncBool(False) | b)

    def test_reverse_xor(self):
        b = SyncBool(True)
        self.assertFalse(True ^ b)
        self.assertTrue(False ^ b)
        self.assertFalse(1 ^ b)
        self.assertTrue(0 ^ b)
        self.assertFalse(SyncBool(True) ^ b)
        self.assertTrue(SyncBool(False) ^ b)

    def test_syncbool_to_syncbool_comparison(self):
        b1 = SyncBool(True)
        b2 = SyncBool(True)
        b3 = SyncBool(False)
        self.assertTrue(b1 == b2)
        self.assertFalse(b1 == b3)
        self.assertTrue(b1 != b3)

    def test_syncbool_to_syncbool_bitwise_ops(self):
        b_true = SyncBool(True)
        b_false = SyncBool(False)
        self.assertFalse(b_false & b_true)
        self.assertTrue(b_false | b_true)
        self.assertTrue(b_true ^ b_false)

    def test_deadlock_prevention_on_binary_op(self):
        b1 = SyncBool(True)
        b2 = SyncBool(False)
        barrier = threading.Barrier(2)
        exceptions = []
        def thread1_task():
            try:
                barrier.wait()
                for _ in range(10000):
                    _ = b1 & b2
            except Exception as e:
                exceptions.append(e)
        def thread2_task():
            try:
                barrier.wait()
                for _ in range(10000):
                    _ = b2 | b1
            except Exception as e:
                exceptions.append(e)
        t1 = threading.Thread(target=thread1_task)
        t2 = threading.Thread(target=thread2_task)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)
        self.assertFalse(t1.is_alive(), "Thread 1 deadlocked or timed out")
        self.assertFalse(t2.is_alive(), "Thread 2 deadlocked or timed out")
        self.assertEqual(exceptions, [], "Threads raised exceptions")

    def test_indexing_behavior(self):
        lst = ["zero", "one"]
        b = SyncBool(True)
        self.assertEqual(lst[b.__index__()], "one")
        b.set(False)
        self.assertEqual(lst[b.__index__()], "zero")

    def test_thread_safety_set_get(self):
        b = SyncBool()
        def set_true():
            for _ in range(1000):
                b.set(True)
        def set_false():
            for _ in range(1000):
                b.set(False)

        t1 = threading.Thread(target=set_true)
        t2 = threading.Thread(target=set_false)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        self.assertIn(b.get(), [True, False])

    def test_thread_safe_toggle(self):
        b = SyncBool(False)
        def toggler():
            for _ in range(1000): b.toggle()
        threads = [threading.Thread(target=toggler) for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertFalse(b.get())

    # ────────────────────────────────────────────────────────────────
    # NEW TESTS START HERE
    # ────────────────────────────────────────────────────────────────

    # 1. Initialization and Coercion
    def test_init_with_non_bool_truthy_falsy(self):
        self.assertTrue(SyncBool(1).get())
        self.assertFalse(SyncBool(0).get())
        self.assertTrue(SyncBool("hello").get())
        self.assertFalse(SyncBool("").get())
        self.assertTrue(SyncBool([1]).get())
        self.assertFalse(SyncBool([]).get())
        self.assertTrue(SyncBool(3.14).get())
        self.assertFalse(SyncBool(0.0).get())
        self.assertTrue(SyncBool(Decimal('1')).get())
        self.assertFalse(SyncBool(Decimal('0')).get())

    def test_set_with_non_bool_truthy_falsy(self):
        b = SyncBool(False)
        b.set(1)
        self.assertTrue(b.get())
        b.set(0)
        self.assertFalse(b.get())
        b.set("test")
        self.assertTrue(b.get())
        b.set("")
        self.assertFalse(b.get())

    def test_init_safe_concurrency(self):
        num_threads = 20
        num_instances_per_thread = 5
        instances = []
        lock = threading.Lock() # For protecting list append

        def create_syncbool():
            sb = SyncBool(initial=True, init_safe=True)
            with lock:
                instances.append(sb)

        _spawn_threads(create_syncbool, num_threads=num_threads, iterations_per_thread=num_instances_per_thread)
        self.assertEqual(len(instances), num_threads * num_instances_per_thread)
        for sb in instances:
            self.assertTrue(sb.get())
            self.assertIsInstance(sb, SyncBool)

    def test_init_unsafe_concurrency(self):
        num_threads = 20
        num_instances_per_thread = 5
        instances = []
        lock = threading.Lock()

        def create_syncbool_unsafe():
            sb = SyncBool(initial=False, init_safe=False)
            with lock:
                instances.append(sb)

        _spawn_threads(create_syncbool_unsafe, num_threads=num_threads, iterations_per_thread=num_instances_per_thread)
        self.assertEqual(len(instances), num_threads * num_instances_per_thread)
        for sb in instances:
            self.assertFalse(sb.get())
            self.assertIsInstance(sb, SyncBool)

    # 2. Arithmetic Operations (as numeric)
    def test_add_with_various_types(self):
        b_true = SyncBool(True)
        b_false = SyncBool(False)

        self.assertEqual(b_true + 5, 6)
        self.assertEqual(b_false + 5, 5)
        self.assertEqual(b_true + 5.5, 6.5)
        self.assertEqual(b_false + 5.5, 5.5)
        self.assertEqual(b_true + SyncInt(10), 11)
        self.assertEqual(b_false + SyncInt(10), 10)
        self.assertEqual(b_true + SyncFloat(0.5), 1.5)
        self.assertEqual(b_false + SyncFloat(0.5), 0.5)

    def test_sub_with_various_types(self):
        b_true = SyncBool(True)
        b_false = SyncBool(False)

        self.assertEqual(b_true - 5, -4)
        self.assertEqual(b_false - 5, -5)
        self.assertEqual(b_true - 0.5, 0.5)
        self.assertEqual(b_false - 0.5, -0.5)
        self.assertEqual(b_true - SyncInt(1), 0)
        self.assertEqual(b_false - SyncInt(1), -1)

    def test_mul_with_various_types(self):
        b_true = SyncBool(True)
        b_false = SyncBool(False)

        self.assertEqual(b_true * 5, 5)
        self.assertEqual(b_false * 5, 0)
        self.assertEqual(b_true * 5.5, 5.5)
        self.assertEqual(b_false * 5.5, 0.0)
        self.assertEqual(b_true * SyncInt(10), 10)
        self.assertEqual(b_false * SyncInt(10), 0)

    def test_truediv_with_various_types(self):
        b_true = SyncBool(True)
        b_false = SyncBool(False)

        self.assertEqual(b_true / 2, 0.5)
        self.assertEqual(b_true / 0.5, 2.0)
        self.assertEqual(b_true / SyncInt(4), 0.25)
        self.assertEqual(b_true / SyncFloat(0.25), 4.0)

        with self.assertRaises(ZeroDivisionError):
            _ = b_true / 0
        with self.assertRaises(ZeroDivisionError):
            _ = b_false / 0
        with self.assertRaises(ZeroDivisionError):
            _ = b_true / SyncInt(0)
        with self.assertRaises(ZeroDivisionError):
            _ = b_false / SyncFloat(0.0)

    def test_floordiv_with_various_types(self):
        b_true = SyncBool(True)
        b_false = SyncBool(False)

        self.assertEqual(b_true // 2, 0)
        self.assertEqual(b_true // 0.5, 2.0)
        self.assertEqual(b_true // SyncInt(4), 0)
        self.assertEqual(b_true // SyncFloat(0.25), 4.0)

        with self.assertRaises(ZeroDivisionError):
            _ = b_true // 0

    def test_mod_with_various_types(self):
        b_true = SyncBool(True)
        b_false = SyncBool(False)

        self.assertEqual(b_true % 2, 1)
        self.assertEqual(b_true % 0.5, 0.0)
        self.assertEqual(b_true % SyncInt(4), 1)
        self.assertEqual(b_true % SyncFloat(0.25), 0.0)

        with self.assertRaises(ZeroDivisionError):
            _ = b_true % 0

    def test_pow_with_various_types(self):
        b_true = SyncBool(True)
        b_false = SyncBool(False)

        self.assertEqual(b_true ** 5, 1)
        self.assertEqual(b_false ** 5, 0)
        self.assertEqual(b_true ** 0.5, 1.0)
        self.assertEqual(b_false ** 0.5, 0.0)
        self.assertEqual(b_true ** SyncInt(10), 1)
        self.assertEqual(b_false ** SyncInt(10), 0)

        self.assertEqual(b_false ** 0, 1)
        self.assertEqual(b_true ** 0, 1)

        with self.assertRaises(TypeError):
            pow(b_true, 2, 3)

    # 3. Reverse Arithmetic Operations
    def test_radd_with_various_types(self):
        b_true = SyncBool(True)
        b_false = SyncBool(False)

        self.assertEqual(5 + b_true, 6)
        self.assertEqual(5 + b_false, 5)
        self.assertEqual(5.5 + b_true, 6.5)
        self.assertEqual(5.5 + b_false, 5.5)
        self.assertEqual(SyncInt(10) + b_true, 11)
        self.assertEqual(SyncInt(10) + b_false, 10)
        self.assertEqual(SyncFloat(0.5) + b_true, 1.5)
        self.assertEqual(SyncFloat(0.5) + b_false, 0.5)

    def test_rsub_with_various_types(self):
        b_true = SyncBool(True)
        b_false = SyncBool(False)

        self.assertEqual(5 - b_true, 4)
        self.assertEqual(5 - b_false, 5)
        self.assertEqual(0.5 - b_true, -0.5)
        self.assertEqual(0.5 - b_false, 0.5)
        self.assertEqual(SyncInt(10) - b_true, 9)
        self.assertEqual(SyncInt(10) - b_false, 10)

    def test_rmul_with_various_types(self):
        b_true = SyncBool(True)
        b_false = SyncBool(False)

        self.assertEqual(5 * b_true, 5)
        self.assertEqual(5 * b_false, 0)
        self.assertEqual(5.5 * b_true, 5.5)
        self.assertEqual(5.5 * b_false, 0.0)
        self.assertEqual(SyncInt(10) * b_true, 10)
        self.assertEqual(SyncInt(10) * b_false, 0)

    def test_rtruediv_with_various_types(self):
        b_true = SyncBool(True)
        b_false = SyncBool(False)

        self.assertEqual(2 / b_true, 2.0)
        self.assertEqual(0.5 / b_true, 0.5)
        self.assertEqual(SyncInt(4) / b_true, 4.0)
        self.assertEqual(SyncFloat(0.25) / b_true, 0.25)

        with self.assertRaises(ZeroDivisionError):
            _ = 5 / b_false
        with self.assertRaises(ZeroDivisionError):
            _ = 0.0 / b_false
        with self.assertRaises(ZeroDivisionError):
            _ = SyncInt(10) / b_false

    def test_rfloordiv_with_various_types(self):
        b_true = SyncBool(True)
        b_false = SyncBool(False)

        self.assertEqual(2 // b_true, 2)
        self.assertEqual(0.5 // b_true, 0.0)
        self.assertEqual(SyncInt(4) // b_true, 4)
        self.assertEqual(SyncFloat(0.25) // b_true, 0.0)

        with self.assertRaises(ZeroDivisionError):
            _ = 5 // b_false

    def test_rmod_with_various_types(self):
        b_true = SyncBool(True)
        b_false = SyncBool(False)

        self.assertEqual(2 % b_true, 0)
        self.assertEqual(0.5 % b_true, 0.5) # Correct
        self.assertEqual(SyncInt(4) % b_true, 0)
        self.assertEqual(SyncFloat(0.25) % b_true, 0.25) # Correct

        with self.assertRaises(ZeroDivisionError):
            _ = 5 % b_false

    def test_rpow_with_various_types(self):
        b_true = SyncBool(True)
        b_false = SyncBool(False)

        self.assertEqual(5 ** b_true, 5)
        self.assertEqual(5 ** b_false, 1)
        self.assertEqual(0.5 ** b_true, 0.5)
        self.assertEqual(0.5 ** b_false, 1.0)
        self.assertEqual(SyncInt(10) ** b_true, 10)
        self.assertEqual(SyncInt(10) ** b_false, 1)

        self.assertEqual(0 ** b_false, 1)
        self.assertEqual(0 ** b_true, 0)

        with self.assertRaises(TypeError):
            pow(2, b_true, 3)

    # 4. Comparison Operations (>, >=, <, <=)
    def test_less_than_greater_than(self):
        b_true = SyncBool(True)
        b_false = SyncBool(False)

        self.assertTrue(b_false < b_true)
        self.assertTrue(b_false <= b_true)
        self.assertTrue(b_true > b_false)
        self.assertTrue(b_true >= b_false)

        self.assertFalse(b_true < b_false)
        self.assertFalse(b_true <= b_false)
        self.assertFalse(b_false > b_true)
        self.assertFalse(b_false >= b_true)

        self.assertFalse(b_true < b_true)
        self.assertTrue(b_true <= b_true)

    def test_comparisons_with_int_float(self):
        b_true = SyncBool(True)
        b_false = SyncBool(False)

        self.assertTrue(b_true > 0)
        self.assertTrue(b_true >= 1)
        self.assertFalse(b_true < 1)
        self.assertFalse(b_true <= 0)

        self.assertTrue(b_false < 1)
        self.assertTrue(b_false <= 0)
        self.assertFalse(b_false > 0)
        self.assertFalse(b_false >= 1)

        self.assertTrue(b_true > 0.5) # Corrected logic check in previous turn
        self.assertTrue(b_false < 0.5)

    def test_comparisons_with_sync_types(self):
        b_true = SyncBool(True)
        b_false = SyncBool(False)
        si_zero = SyncInt(0)
        si_one = SyncInt(1)
        sf_zero = SyncFloat(0.0)
        sf_one = SyncFloat(1.0)

        self.assertTrue(b_true == si_one)
        self.assertTrue(b_false == si_zero)
        self.assertTrue(b_true == sf_one)
        self.assertTrue(b_false == sf_zero)

        self.assertTrue(b_true > si_zero)
        self.assertTrue(b_false < si_one)
        self.assertTrue(b_true >= sf_one)
        self.assertTrue(b_false <= sf_zero)

    # 5. Bitwise Operations with SyncInt
    def test_bitwise_and_sync_int(self):
        b_true = SyncBool(True)
        b_false = SyncBool(False)
        si_val = SyncInt(5) # Binary 101

        self.assertEqual(b_true & si_val, 1) # Correct, result is int
        self.assertEqual(b_false & si_val, 0)
        self.assertEqual(si_val & b_true, 1)
        self.assertEqual(si_val & b_false, 0)

    def test_bitwise_or_sync_int(self):
        b_true = SyncBool(True)
        b_false = SyncBool(False)
        si_val = SyncInt(5) # Binary 101

        self.assertEqual(b_true | si_val, 5) # Correct, result is int
        self.assertEqual(b_false | si_val, 5)
        self.assertEqual(si_val | b_true, 5)
        self.assertEqual(si_val | b_false, 5)

    def test_bitwise_xor_sync_int(self):
        b_true = SyncBool(True)
        b_false = SyncBool(False)
        si_val = SyncInt(5) # Binary 101

        self.assertEqual(b_true ^ si_val, 4) # Correct, result is int
        self.assertEqual(b_false ^ si_val, 5)
        self.assertEqual(si_val ^ b_true, 4)
        self.assertEqual(si_val ^ b_false, 5)

    # 6. Copying and Pickling
    def test_shallow_copy_independence(self):
        b1 = SyncBool(True)
        b2 = copy.copy(b1)
        self.assertIsInstance(b2, SyncBool)
        self.assertEqual(b1.get(), b2.get())
        self.assertIsNot(b1, b2)
        b1.set(False)
        self.assertTrue(b2.get())

    def test_deep_copy_independence(self):
        b1 = SyncBool(False)
        b2 = copy.deepcopy(b1)
        self.assertIsInstance(b2, SyncBool)
        self.assertEqual(b1.get(), b2.get())
        self.assertIsNot(b1, b2)
        b1.set(True)
        self.assertFalse(b2.get())

    def test_pickling_after_toggle(self):
        b_original = SyncBool(True)
        b_original.toggle()
        pickled_b = pickle.dumps(b_original)
        b_unpickled = pickle.loads(pickled_b)
        self.assertIsInstance(b_unpickled, SyncBool)
        self.assertFalse(b_unpickled.get())

    # 7. Concurrency Scenarios
    def test_concurrent_mixed_ops_on_single_instance(self):
        b = SyncBool(False)
        num_threads = 5
        ops_per_thread = 1000

        def worker():
            for i in range(ops_per_thread):
                if i % 3 == 0:
                    b.toggle()
                elif i % 3 == 1:
                    b.set(True)
                else:
                    b.set(False)
                _ = b.get()

        _spawn_threads(worker, num_threads=num_threads)
        self.assertIn(b.get(), [True, False])

    def test_concurrent_bitwise_ops_with_raw_int(self):
        b = SyncBool(True)
        num_threads = 10
        ops_per_thread = 500

        def worker_and():
            for _ in range(ops_per_thread):
                _ = b & 0

        def worker_or():
            for _ in range(ops_per_thread):
                _ = b | 1

        threads = [threading.Thread(target=worker_and) for _ in range(num_threads // 2)]
        threads.extend([threading.Thread(target=worker_or) for _ in range(num_threads // 2)])

        for t in threads: t.start()
        for t in threads: t.join()

        self.assertTrue(b.get())

    def test_concurrent_comparison_ops(self):
        b1 = SyncBool(True)
        b2 = SyncBool(False)
        results = []
        results_lock = threading.Lock()

        def worker_compare():
            for _ in range(1000):
                with results_lock:
                    results.append(b1 == b2)
                    results.append(b1 > b2)

        _spawn_threads(worker_compare, num_threads=5)
        self.assertEqual(len(results), 5 * 1000 * 2)
        self.assertTrue(all(not r for r in results[::2]))
        self.assertTrue(all(r for r in results[1::2]))

    # 8. __slots__ and Attribute Access
    def test_no_dict_attribute(self):
        b = SyncBool(True)
        self.assertFalse(hasattr(b, '__dict__'))
        with self.assertRaises(AttributeError):
            b.__dict__ = {}

    def test_dir_output_contains_expected_methods(self):
        b = SyncBool(True)
        d = dir(b)
        expected_methods = ['get', 'set', 'toggle', '__int__', '__float__', '__bool__',
                            '__str__', '__repr__', '__hash__', '__eq__', '__ne__',
                            '__and__', '__or__', '__xor__', '__invert__', '__rand__',
                            '__ror__', '__rxor__', '__copy__', '__deepcopy__', '__format__',
                            '__reduce__', '__lt__', '__le__', '__gt__', '__ge__',
                            '__radd__', '__rsub__', '__rmul__', '__rtruediv__',
                            '__rfloordiv__', '__rmod__', '__rpow__', '__pow__']
        for method in expected_methods:
            self.assertIn(method, d)
        self.assertNotIn('some_new_attr', d)

    # 9. Type Coercion and Return Types
    def test_coerce_method_returns_bool(self):
        self.assertIsInstance(SyncBool._coerce(1), bool)
        self.assertIsInstance(SyncBool._coerce("hello"), bool)
        self.assertIsInstance(SyncBool._coerce(0.0), bool)
        self.assertEqual(SyncBool._coerce(1), True)
        self.assertEqual(SyncBool._coerce(0), False)

    def test_arithmetic_return_types(self):
        b_true = SyncBool(True)
        b_false = SyncBool(False)

        self.assertIsInstance(b_true + 1, int)
        self.assertIsInstance(b_true + 1.0, float)
        self.assertIsInstance(b_true * SyncInt(5), int)
        self.assertIsInstance(b_true / 2, float)
        self.assertIsInstance(b_true // 2, int)
        self.assertIsInstance(b_true // 2.0, float)
        self.assertIsInstance(b_true % 2, int)
        self.assertIsInstance(b_true ** 2, int)
        self.assertIsInstance(b_true ** 2.0, float)

        self.assertIsInstance(1 + b_true, int)
        self.assertIsInstance(1.0 + b_true, float)
        self.assertIsInstance(SyncInt(5) * b_true, int)
        self.assertIsInstance(2 / b_true, float)
        self.assertIsInstance(2 // b_true, int)
        self.assertIsInstance(2.0 // b_true, float)
        self.assertIsInstance(2 % b_true, int)
        self.assertIsInstance(2 ** b_true, int)
        self.assertIsInstance(2.0 ** b_true, float)

    def test_bitwise_return_types(self):
        b_true = SyncBool(True)
        b_false = SyncBool(False)

        self.assertIsInstance(b_true & True, bool)
        self.assertIsInstance(b_true & 1, int)
        self.assertIsInstance(b_true | False, bool)
        self.assertIsInstance(b_true | 0, int)
        self.assertIsInstance(b_true ^ True, bool)
        self.assertIsInstance(b_true ^ 1, int)
        self.assertIsInstance(~b_true, int)

        self.assertIsInstance(True & b_true, bool)
        self.assertIsInstance(1 & b_true, int)
        self.assertIsInstance(False | b_true, bool)
        self.assertIsInstance(0 | b_true, int)
        self.assertIsInstance(True ^ b_true, bool)
        self.assertIsInstance(1 ^ b_true, int)

    # 10. Edge Cases and Other Specific Scenarios
    def test_zero_division_error_message(self):
        b_false = SyncBool(False)
        with self.assertRaisesRegex(ZeroDivisionError, "division by zero"):
            _ = 5 / b_false
        self.assertEqual(b_false / 5, 0.0)
        with self.assertRaisesRegex(ZeroDivisionError, "division by zero"):
            _ = b_false / 0

    def test_power_with_negative_exponent_and_zero_base(self):
        b_false = SyncBool(False)
        with self.assertRaises(ZeroDivisionError):
            _ = b_false ** -1
        with self.assertRaises(ZeroDivisionError):
            _ = b_false ** -0.5

    def test_power_with_negative_base_and_fractional_exponent(self):
        b_true = SyncBool(True)
        b_false = SyncBool(False)
        self.assertEqual((-2) ** b_true, -2)
        self.assertEqual((-2) ** b_false, 1)

    def test_comparison_with_non_numeric_types_returns_false(self):
        b = SyncBool(True)
        # These should not be equal under strict comparison logic
        self.assertFalse(b == "True")
        self.assertFalse(b == [1])
        self.assertFalse(b == None)
        self.assertFalse(b == (1,))

    def test_id_of_locks_are_different_for_different_instances(self):
        b1 = SyncBool(True)
        b2 = SyncBool(False)
        self.assertIsNot(b1._lock, b2._lock)
        b3 = SyncBool(True)
        self.assertIsNot(b1._lock, b3._lock)

    # ────────────────────────────────────────────────────────────────
    # NEW EXTENDED TESTS
    # ────────────────────────────────────────────────────────────────

    # I. _unwrap_other specific tests (assuming it's public/testable, or mockable)
    def test_unwrap_other_with_raw_bools(self):
        b = SyncBool(True)
        self.assertIs(b._unwrap_other(True), True)
        self.assertIs(b._unwrap_other(False), False)

    def test_unwrap_other_with_raw_ints(self):
        b = SyncBool(True)
        self.assertEqual(b._unwrap_other(1), 1)
        self.assertEqual(b._unwrap_other(0), 0)
        self.assertEqual(b._unwrap_other(-5), -5)

    def test_unwrap_other_with_raw_floats(self):
        b = SyncBool(True)
        self.assertEqual(b._unwrap_other(1.0), 1.0)
        self.assertEqual(b._unwrap_other(0.0), 0.0)
        self.assertEqual(b._unwrap_other(3.14), 3.14)

    def test_unwrap_other_with_decimal(self):
        b = SyncBool(True)
        self.assertEqual(b._unwrap_other(Decimal('10.5')), Decimal('10.5'))

    def test_unwrap_other_with_sync_types(self):
        b = SyncBool(True)
        self.assertEqual(b._unwrap_other(SyncInt(5)), 5)
        self.assertEqual(b._unwrap_other(SyncFloat(2.5)), 2.5)
        self.assertEqual(b._unwrap_other(SyncBool(False)), False)

    def test_unwrap_other_with_convertible_strings(self):
        b = SyncBool(True)
        # Note: _unwrap_other should return actual float/int for "numeric" strings
        # or the string itself if it strictly passes to bool conversion later.
        # Based on ISync's _unwrap_other, it tries float() then int()
        self.assertEqual(b._unwrap_other("1"), 1.0) # float conversion
        self.assertEqual(b._unwrap_other("0"), 0.0) # float conversion
        self.assertEqual(b._unwrap_other("-5.5"), -5.5) # float conversion

        # Test cases where conversion might be ambiguous or undesirable for direct numeric use.
        # Assuming _unwrap_other converts to float/int where possible.
        self.assertIsInstance(b._unwrap_other("1"), float)
        self.assertIsInstance(b._unwrap_other("100"), float)
        self.assertIsInstance(b._unwrap_other("False"), str) # Should not convert "False" to bool here

    def test_unwrap_other_with_non_convertible_types(self):
        b = SyncBool(True)
        obj = object()
        self.assertIs(b._unwrap_other(obj), obj)
        self.assertIs(b._unwrap_other(None), None)
        self.assertEqual(b._unwrap_other([1,2]), [1,2])
        self.assertEqual(b._unwrap_other("hello"), "hello") # Should not convert non-numeric string


    # II. Comprehensive Cross-Type Arithmetic & Return Types
    def test_mixed_type_add_return_types(self):
        sb_true = SyncBool(True)
        sb_false = SyncBool(False)
        si = SyncInt(10)
        sf = SyncFloat(5.5)

        self.assertIsInstance(sb_true + si, int)
        self.assertIsInstance(sb_true + sf, float)
        self.assertIsInstance(si + sb_true, int)
        self.assertIsInstance(sf + sb_true, float)
        self.assertIsInstance(sb_false + si, int)
        self.assertIsInstance(sb_false + sf, float)

    def test_mixed_type_sub_return_types(self):
        sb_true = SyncBool(True)
        sb_false = SyncBool(False)
        si = SyncInt(10)
        sf = SyncFloat(5.5)

        self.assertIsInstance(sb_true - si, int)
        self.assertIsInstance(sb_true - sf, float)
        self.assertIsInstance(si - sb_true, int)
        self.assertIsInstance(sf - sb_true, float)

    def test_mixed_type_mul_return_types(self):
        sb_true = SyncBool(True)
        sb_false = SyncBool(False)
        si = SyncInt(10)
        sf = SyncFloat(5.5)

        self.assertIsInstance(sb_true * si, int)
        self.assertIsInstance(sb_true * sf, float)
        self.assertIsInstance(si * sb_true, int)
        self.assertIsInstance(sf * sb_true, float)

    def test_mixed_type_div_return_types(self):
        sb_true = SyncBool(True)
        sb_false = SyncBool(False)
        si = SyncInt(2)
        sf = SyncFloat(2.0)

        self.assertIsInstance(sb_true / si, float)
        self.assertIsInstance(sb_true / sf, float)
        self.assertIsInstance(si / sb_true, float)
        self.assertIsInstance(sf / sb_true, float)

        self.assertIsInstance(sb_true // si, int) # int // int is int
        self.assertIsInstance(sb_true // sf, float) # int // float is float
        self.assertIsInstance(si // sb_true, int)
        self.assertIsInstance(sf // sb_true, float)

    def test_mixed_type_mod_return_types(self):
        sb_true = SyncBool(True)
        sb_false = SyncBool(False)
        si = SyncInt(2)
        sf = SyncFloat(2.0)

        self.assertIsInstance(sb_true % si, int)
        self.assertIsInstance(sb_true % sf, float)
        self.assertIsInstance(si % sb_true, int)
        self.assertIsInstance(sf % sb_true, float)

    def test_mixed_type_pow_return_types(self):
        sb_true = SyncBool(True)
        sb_false = SyncBool(False)
        si = SyncInt(2)
        sf = SyncFloat(2.0)

        self.assertIsInstance(sb_true ** si, int)
        self.assertIsInstance(sb_true ** sf, float)
        self.assertIsInstance(si ** sb_true, int)
        self.assertIsInstance(sf ** sb_true, float)

    # III. __index__ in real-world contexts
    def test_index_in_list_access(self):
        my_list = ["apple", "banana"]
        b_true = SyncBool(True)
        b_false = SyncBool(False)

        self.assertEqual(my_list[b_true], "banana")
        self.assertEqual(my_list[b_false], "apple")

    def test_index_in_range_and_sum(self):
        b_true = SyncBool(True)
        b_false = SyncBool(False)

        self.assertEqual(list(range(b_true)), [0])
        self.assertEqual(list(range(b_false)), [])

        # Sum implicitly calls int()
        self.assertEqual(sum([b_true, b_true, b_false]), 2)
        self.assertEqual(sum([b_true, 5, b_false]), 6) # b_true becomes 1, b_false becomes 0

    # IV. More Edge Cases for Conversions
    def test_implicit_conversion_in_if_statement(self):
        b_true = SyncBool(True)
        b_false = SyncBool(False)

        if b_true:
            result_true = True
        else:
            result_true = False
        self.assertTrue(result_true)

        if b_false:
            result_false = True
        else:
            result_false = False
        self.assertFalse(result_false)

    def test_chained_conversions(self):
        b = SyncBool(True)
        self.assertEqual(float(int(b)), 1.0)
        self.assertEqual(int(float(b)), 1)
        self.assertIsInstance(float(int(b)), float)
        self.assertIsInstance(int(float(b)), int)

    # V. Advanced Concurrency
    def test_concurrent_mixed_instance_bitwise_ops(self):
        b1 = SyncBool(True)
        b2 = SyncBool(False)
        results = []
        results_lock = threading.Lock()

        def worker_op():
            for _ in range(100):
                with results_lock:
                    results.append(b1 & b2) # Should be False (1&0=0)
                    results.append(b1 | b2) # Should be True (1|0=1)
                    results.append(b1 ^ b2) # Should be True (1^0=1)

        _spawn_threads(worker_op, num_threads=10)
        self.assertEqual(len(results), 10 * 100 * 3)
        self.assertTrue(all(not r for r in results[::3])) # AND results (False)
        self.assertTrue(all(r for r in results[1::3]))    # OR results (True)
        self.assertTrue(all(r for r in results[2::3]))    # XOR results (True)


    def test_concurrent_set_and_read_mixed_types(self):
        b = SyncBool(True)
        si = SyncInt(10)
        sf = SyncFloat(5.5)

        read_values = []
        read_lock = threading.Lock()

        def set_worker(new_val):
            for _ in range(50):
                b.set(new_val)

        def read_worker():
            for _ in range(50):
                with read_lock:
                    read_values.append(b.get())
                    read_values.append(b + si) # int result
                    read_values.append(b * sf) # float result

        set_t_true = threading.Thread(target=set_worker, args=(True,))
        set_t_false = threading.Thread(target=set_worker, args=(False,))
        read_t1 = threading.Thread(target=read_worker)
        read_t2 = threading.Thread(target=read_worker)

        set_t_true.start(); set_t_false.start(); read_t1.start(); read_t2.start()
        set_t_true.join(); set_t_false.join(); read_t1.join(); read_t2.join()

        # The actual values read will be non-deterministic (True or False, 11 or 10, 5.5 or 0.0)
        # But we assert that they are valid values based on the operations.
        self.assertEqual(len(read_values), 2 * 50 * 3) # 2 readers * 50 ops * 3 appends
        for val in read_values[::3]: # bool values
            self.assertIn(val, [True, False])
        for val in read_values[1::3]: # int results from b + si
            self.assertIn(val, [11, 10]) # (True+10) or (False+10)
        for val in read_values[2::3]: # float results from b * sf
            self.assertIn(val, [5.5, 0.0]) # (True*5.5) or (False*5.5)

    def test_concurrent_toggle_with_reads(self):
        b = SyncBool(False)
        num_toggles = 100
        read_counts = {True: 0, False: 0}
        read_lock = threading.Lock()
        barrier = threading.Barrier(2)

        # This toggle worker will flip the value every time
        def toggle_worker():
            barrier.wait()  # start with reader
            for _ in range(num_toggles):
                b.toggle()
                time.sleep(0.001)  # give readers time to observe

        # This reader will continuously check and log observed values
        def read_worker():
            barrier.wait()
            for _ in range(num_toggles * 2):  # read twice as much
                val = b.get()
                with read_lock:
                    read_counts[val] += 1
                time.sleep(0.0005)

        t_toggle = threading.Thread(target=toggle_worker)
        t_read = threading.Thread(target=read_worker)

        t_toggle.start()
        t_read.start()
        t_toggle.join()
        t_read.join()

        # Should have seen both states at least once
        self.assertGreater(read_counts[True], 0, "Never observed True during toggles")
        self.assertGreater(read_counts[False], 0, "Never observed False during toggles")
        self.assertFalse(b.get(), "Final value should be False after even number of toggles")


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)