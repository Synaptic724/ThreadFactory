import math
import threading
import unittest
import sys # For float_info
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import pickle
import copy  # Import copy module for clarity

# ---- import your concrete classes ----------------------------------
from thread_factory.concurrency.value_types.sync_float import SyncFloat
from thread_factory.concurrency.value_types.sync_int import SyncInt
from thread_factory.concurrency.value_types.sync_bool import SyncBool


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
        # Each thread runs 'fn' 'iterations_per_thread' times
        list(ex.map(lambda _: [fn() for _ in range(iterations_per_thread)], range(num_threads)))


class TestSyncFloatComprehensive(unittest.TestCase): # Renamed for clarity
    # ────────────────────────────────────────────────────────────────
    # Core Construction & Basic Access (retained from original/previous for completeness)
    # ────────────────────────────────────────────────────────────────
    def test_default_and_custom_init(self):
        self.assertEqual(SyncFloat().get(), 0.0)
        self.assertEqual(SyncFloat(3.14).get(), 3.14)
        self.assertEqual(SyncFloat("2.5").get(), 2.5)

    def test_set_and_get(self):
        f = SyncFloat()
        f.set(9.81)
        self.assertEqual(f.get(), 9.81)

    def test_init_with_different_numeric_types(self):
        with self.subTest(msg="init with int"):
            self.assertEqual(SyncFloat(10).get(), 10.0)
        with self.subTest(msg="init with Decimal"):
            self.assertEqual(SyncFloat(Decimal('5.5')).get(), 5.5)
        with self.subTest(msg="init with bool True"):
            self.assertEqual(SyncFloat(True).get(), 1.0)
        with self.subTest(msg="init with bool False"):
            self.assertEqual(SyncFloat(False).get(), 0.0)

    def test_init_with_negative_values(self):
        self.assertEqual(SyncFloat(-10.5).get(), -10.5)

    def test_init_with_zero(self):
        self.assertEqual(SyncFloat(0.0).get(), 0.0)
        self.assertEqual(SyncFloat(-0.0).get(), 0.0)

    def test_set_with_non_float_types(self):
        f = SyncFloat(1.0)
        f.set(10)
        self.assertEqual(f.get(), 10.0)
        f.set("7.7")
        self.assertEqual(f.get(), 7.7)
        f.set(Decimal("3.14"))
        self.assertEqual(f.get(), 3.14)
        f.set(True)
        self.assertEqual(f.get(), 1.0)

    # ────────────────────────────────────────────────────────────────
    # Arithmetic Operations (Forward, Reverse, In-Place)
    # ────────────────────────────────────────────────────────────────
    def test_basic_arithmetic(self):
        a, b = SyncFloat(3.0), SyncFloat(2.0)
        self.assertEqual(a + b, 5.0)
        self.assertEqual(a - b, 1.0)
        self.assertEqual(a * b, 6.0)
        self.assertEqual(a / b, 1.5)
        self.assertEqual(a // b, 1.0)
        self.assertAlmostEqual(a % b, 1.0)
        self.assertEqual(divmod(a, b), (1.0, 1.0))

    def test_reverse_arithmetic(self):
        a = SyncFloat(2.5)
        self.assertEqual(5 + a, 7.5)
        self.assertEqual(7 - a, 4.5)
        self.assertEqual(2 * a, 5.0)
        self.assertAlmostEqual(5 / a, 2.0)
        self.assertEqual(5 // a, 2.0)
        self.assertAlmostEqual(5 % a, 0.0)

    def test_inplace_ops(self):
        f = SyncFloat(1.0)
        f += 4         # 5
        f *= 2         # 10
        f /= 4         # 2.5
        f //= 2        # 1.0
        f %= 0.6       # 0.4
        f **= 2        # 0.16
        self.assertAlmostEqual(f.get(), 0.16, places=8)

    def test_add_sub_zero(self):
        f = SyncFloat(5.0)
        self.assertEqual(f + 0, 5.0)
        self.assertEqual(f - 0, 5.0)
        self.assertEqual(0 + f, 5.0)
        self.assertEqual(0 - f, -5.0)

    def test_mul_div_one(self):
        f = SyncFloat(5.0)
        self.assertEqual(f * 1, 5.0)
        self.assertEqual(f / 1, 5.0)
        self.assertEqual(1 * f, 5.0)
        self.assertEqual(1 / f, 0.2)

    def test_mul_div_by_zero_and_inf(self):
        f = SyncFloat(5.0)
        with self.assertRaises(ZeroDivisionError):
            _ = f / SyncFloat(0.0) # Should raise, consistent with float / 0.0 literal

        with self.assertRaises(ZeroDivisionError):
            _ = SyncFloat(0.0) / 0.0 # Should raise

        self.assertTrue(math.isinf(f * float('inf')))
        self.assertTrue(math.isnan(SyncFloat(0.0) * float('inf')))

    def test_pow_edge_cases(self):
        f = SyncFloat(2.0)
        self.assertEqual(f ** 0, 1.0)
        self.assertEqual(SyncFloat(0.0) ** f, 0.0)
        self.assertEqual(f ** 1, 2.0)
        self.assertEqual(f ** -1, 0.5)
        self.assertEqual(SyncFloat(0.0) ** 0, 1.0) # Special case in Python

    def test_inplace_each_operator(self):
        cases = [
            ("__iadd__",      lambda x: (x.__iadd__(1),      6.0)),
            ("__isub__",      lambda x: (x.__isub__(1),      4.0)),
            ("__imul__",      lambda x: (x.__imul__(2),     10.0)),
            ("__itruediv__",  lambda x: (x.__itruediv__(4), 1.25)),
            ("__ifloordiv__", lambda x: (x.__ifloordiv__(2), 2.0)),
            ("__imod__",      lambda x: (x.__imod__(0.6),   0.2)),
            ("__ipow__",      lambda x: (x.__ipow__(2),     25.0)),
        ]
        for name, fn in cases:
            with self.subTest(name=name):
                f = SyncFloat(5.0)            # fresh value each time
                val, expected = fn(f)
                self.assertIs(val, f)         # in-place returns self
                self.assertAlmostEqual(f.get(), expected, places=8)

    def test_arithmetic_with_negative_numbers(self):
        a = SyncFloat(5.0)
        b = SyncFloat(-2.0)
        self.assertEqual(a + b, 3.0)
        self.assertEqual(a - b, 7.0)
        self.assertEqual(a * b, -10.0)
        self.assertEqual(a / b, -2.5)
        self.assertEqual(a // b, -3.0)  # Floor division
        self.assertAlmostEqual(a % b, -1.0)

        self.assertEqual(-2.0 + a, 3.0)
        self.assertEqual(-7.0 - a, -12.0)
        self.assertEqual(-3.0 * a, -15.0)
        self.assertEqual(-10.0 / a, -2.0)

    def test_divmod_with_negatives_and_fractions(self):
        f1 = SyncFloat(7.5)
        f2 = SyncFloat(-2.0)
        self.assertEqual(divmod(f1, f2), (-4.0, -0.5))

        f3 = SyncFloat(-7.5)
        f4 = SyncFloat(2.0)
        self.assertEqual(divmod(f3, f4), (-4.0, 0.5))

        f5 = SyncFloat(-7.5)
        f6 = SyncFloat(-2.0)
        self.assertEqual(divmod(f5, f6), (3.0, -1.5))

    # ────────────────────────────────────────────────────────────────
    # Comparison & Bool / Hash
    # ────────────────────────────────────────────────────────────────
    def test_comparisons_and_hash(self):
        a, b = SyncFloat(2.0), SyncFloat(3.0)
        self.assertTrue(a < b)
        self.assertTrue(a <= b)
        self.assertTrue(b > a)
        self.assertTrue(b >= a)
        self.assertFalse(a == b)
        self.assertTrue(a != b)
        self.assertEqual(hash(a), hash(2.0))

    def test_comparisons_bool_hash(self):
        a, b = SyncFloat(1.0), SyncFloat(2.0)
        self.assertTrue(a < b)
        self.assertTrue(a <= b)
        self.assertTrue(b > a)
        self.assertTrue(b >= a)
        self.assertFalse(a == b)
        self.assertTrue(a != b)
        self.assertTrue(bool(b))
        self.assertFalse(bool(SyncFloat(0.0)))
        self.assertEqual(hash(a), hash(1.0))

    def test_comparison_with_zero(self):
        f_pos = SyncFloat(0.0001)
        f_neg = SyncFloat(-0.0001)
        f_zero = SyncFloat(0.0)
        self.assertTrue(f_pos > 0)
        self.assertTrue(f_neg < 0)
        self.assertTrue(f_zero == 0)
        self.assertFalse(f_pos == 0)

    def test_comparison_with_inf_and_nan(self):
        pinf = SyncFloat(float('inf'))
        ninf = SyncFloat(float('-inf'))
        nan = SyncFloat(float('nan'))
        normal = SyncFloat(10.0)

        self.assertTrue(pinf > normal)
        self.assertTrue(ninf < normal)
        self.assertTrue(pinf == float('inf'))
        self.assertTrue(ninf == float('-inf'))
        self.assertFalse(nan == nan)
        self.assertFalse(nan < 0)
        self.assertFalse(nan > 0)
        self.assertFalse(nan == 0)

    def test_mixed_type_comparisons(self):
        f = SyncFloat(5.0)
        i = SyncInt(5)
        s = "5.0"
        self.assertTrue(f == i)
        self.assertTrue(f == 5)
        self.assertTrue(f == s) # As per _unwrap_other converting "5.0" to 5.0
        self.assertTrue(f >= 4.9)
        self.assertTrue(f <= 5.1)

    def test_comparison_sync_float_vs_sync_int(self):
        f = SyncFloat(5.0)
        i_eq = SyncInt(5)
        i_lt = SyncInt(4)
        i_gt = SyncInt(6)

        self.assertTrue(f == i_eq)
        self.assertFalse(f != i_eq)
        self.assertTrue(f > i_lt)
        self.assertTrue(f >= i_lt)
        self.assertTrue(f < i_gt)
        self.assertTrue(f <= i_gt)

        self.assertTrue(i_eq == f)
        self.assertFalse(i_eq != f)
        self.assertTrue(i_lt < f)
        self.assertTrue(i_lt <= f)
        self.assertTrue(i_gt > f)
        self.assertTrue(i_gt >= f)

    def test_comparison_sync_float_vs_sync_bool(self):
        f_one = SyncFloat(1.0)
        f_zero = SyncFloat(0.0)
        b_true = SyncBool(True)
        b_false = SyncBool(False)

        self.assertTrue(f_one == b_true)
        self.assertTrue(f_zero == b_false)
        self.assertTrue(f_one > b_false)
        self.assertTrue(f_zero < b_true)
        self.assertFalse(f_one == b_false)
        self.assertFalse(f_zero == b_true)

    # ────────────────────────────────────────────────────────────────
    # Conversion & Unary Operators / Properties
    # ────────────────────────────────────────────────────────────────
    def test_hex_and_fromhex(self):
        f = SyncFloat(3.14159)
        hx = f.hex()
        self.assertEqual(SyncFloat.fromhex(hx).get(), float.fromhex(hx))

    def test_integer_ratio_and_round(self):
        f = SyncFloat(10.0)
        self.assertEqual(f.as_integer_ratio(), (10, 1))
        self.assertEqual(round(SyncFloat(3.14159), 2), 3.14)

    def test_real_imag_properties(self):
        f = SyncFloat(5.5)
        self.assertEqual(f.real, 5.5)
        self.assertEqual(f.imag, 0.0)

    def test_init_variants(self):
        self.assertEqual(SyncFloat().get(), 0.0)
        self.assertAlmostEqual(SyncFloat(3.14).get(), 3.14)
        self.assertAlmostEqual(SyncFloat("2.5").get(), 2.5)
        self.assertAlmostEqual(SyncFloat(Decimal("1.23")).get(), 1.23)

    def test_abs_neg_pos(self):
        f = SyncFloat(-3.5)
        self.assertIsInstance(abs(f), float)
        self.assertEqual(abs(f), 3.5)
        self.assertEqual(-f, 3.5)
        self.assertEqual(+f, -3.5)

    def test_round_trunc_ceil_floor(self):
        f = SyncFloat(3.75)
        self.assertEqual(round(f), 4)
        self.assertEqual(round(f, 1), 3.8)
        self.assertEqual(math.trunc(f), 3)
        self.assertEqual(math.ceil(f), 4)
        self.assertEqual(math.floor(f), 3)

    def test_integer_ratio_and_conjugate(self):
        f = SyncFloat(6.25)
        self.assertEqual(f.as_integer_ratio(), (25, 4))
        self.assertEqual(f.conjugate(), 6.25)

    def test_float_int_str_format(self):
        f = SyncFloat(8.5)
        self.assertEqual(float(f), 8.5)
        self.assertEqual(int(SyncFloat(8.99)), 8)
        self.assertEqual(str(f), "8.5")
        self.assertEqual(format(f, ".1f"), "8.5")

    def test_hex_fromhex_negative(self):
        neg = SyncFloat(-0.1)
        hx = neg.hex()
        self.assertEqual(SyncFloat.fromhex(hx).get(), float.fromhex(hx))

    def test_divmod_cross_types(self):
        f = SyncFloat(7.5)
        i = SyncInt(2)
        self.assertEqual(divmod(f, i), (3.0, 1.5))
        self.assertEqual(divmod(i, f), (0.0, 2.0))

    def test_str_repr_consistency(self):
        f = SyncFloat(123.456)
        self.assertEqual(str(f), "123.456")
        self.assertEqual(repr(f), "SyncFloat(123.456)")

    def test_format_specifiers(self):
        f = SyncFloat(123.456789)
        self.assertEqual(f"{f:.2f}", "123.46")
        self.assertEqual(f"{f:e}", "1.234568e+02")
        self.assertEqual(f"{f:010.2f}", "0000123.46")

    def test_bool_conversion_strict(self):
        self.assertFalse(bool(SyncFloat(0.0)))
        self.assertTrue(bool(SyncFloat(0.000001)))
        self.assertTrue(bool(SyncFloat(-0.000001)))

    def test_hash_for_float_equivalents(self):
        self.assertEqual(hash(SyncFloat(1.0)), hash(1.0))
        self.assertEqual(hash(SyncFloat(1)), hash(1.0))

    def test_math_trunc_ceil_floor_negative(self):
        f_neg = SyncFloat(-3.75)
        self.assertEqual(math.trunc(f_neg), -3)
        self.assertEqual(math.ceil(f_neg), -3)
        self.assertEqual(math.floor(f_neg), -4)

    def test_math_fabs(self):
        f = SyncFloat(-5.0)
        self.assertEqual(math.fabs(f), 5.0)
        self.assertIsInstance(math.fabs(f), float)

    def test_getnewargs_for_pickle(self):
        f = SyncFloat(42.0)
        args = f.__getnewargs__()
        self.assertEqual(args, (42.0,))
        new_f = type(f)(*args)
        self.assertEqual(new_f.get(), 42.0)

    def test_fromhex_with_negative_and_zero(self):
        self.assertEqual(SyncFloat.fromhex('-0x1.0p+0').get(), -1.0)
        self.assertEqual(SyncFloat.fromhex('0x0.0p+0').get(), 0.0)

    def test_is_integer_method(self):
        self.assertTrue(SyncFloat(5.0).is_integer())
        self.assertTrue(SyncFloat(-3.0).is_integer())
        self.assertTrue(SyncFloat(0.0).is_integer())
        self.assertFalse(SyncFloat(5.1).is_integer())
        self.assertFalse(SyncFloat(0.00001).is_integer())

    def test_getformat(self):
        format_str_double = SyncFloat.__getformat__("double")
        self.assertIsInstance(format_str_double, str)
        self.assertIn(format_str_double, ("unknown", "IEEE, big-endian", "IEEE, little-endian"))
        with self.assertRaises(ValueError):
            SyncFloat.__getformat__("invalid_type")

    def test_arithmetic_with_raw_float(self):
        f = SyncFloat(5.5)
        self.assertEqual(f + 2.0, 7.5)
        self.assertEqual(2.0 + f, 7.5)
        self.assertEqual(f - 1.0, 4.5)
        self.assertEqual(1.0 - f, -4.5)
        self.assertEqual(f * 2.0, 11.0)
        self.assertEqual(2.0 * f, 11.0)

    def test_explicit_float_int_calls(self):
        f = SyncFloat(123.789)
        self.assertIsInstance(f.__float__(), float)
        self.assertEqual(f.__float__(), 123.789)
        self.assertIsInstance(f.__int__(), int)
        self.assertEqual(f.__int__(), 123)
        self.assertIsInstance(f.__bool__(), bool)
        self.assertEqual(f.__bool__(), True)
        self.assertEqual(SyncFloat(0.0).__bool__(), False)

    def test_explicit_abs_neg_pos_return_types(self):
        f = SyncFloat(-5.5)
        self.assertIsInstance(f.__abs__(), float)
        self.assertEqual(f.__abs__(), 5.5)
        self.assertIsInstance(f.__neg__(), float)
        self.assertEqual(f.__neg__(), 5.5)
        self.assertIsInstance(f.__pos__(), float)
        self.assertEqual(f.__pos__(), -5.5)

    def test_identity_with_zero_and_negative_zero(self):
        f_pos_zero = SyncFloat(0.0)
        f_neg_zero = SyncFloat(-0.0)
        self.assertEqual(f_pos_zero.get(), f_neg_zero.get())
        self.assertEqual(f_pos_zero, 0.0)
        self.assertEqual(f_neg_zero, 0.0)

    def test_float_is_integer_method(self):
        self.assertTrue(SyncFloat(10.0).is_integer())
        self.assertTrue(SyncFloat(-5.0).is_integer())
        self.assertTrue(SyncFloat(0.0).is_integer())
        self.assertFalse(SyncFloat(10.1).is_integer())
        self.assertFalse(SyncFloat(-5.9).is_integer())
        self.assertFalse(SyncFloat(math.inf).is_integer())
        self.assertFalse(SyncFloat(math.nan).is_integer())

    def test_coerce_method_functionality(self):
        self.assertEqual(SyncFloat._coerce(10), 10.0)
        self.assertEqual(SyncFloat._coerce("3.14"), 3.14)
        self.assertEqual(SyncFloat._coerce(True), 1.0)
        self.assertEqual(SyncFloat._coerce(Decimal("2.7")), 2.7)
        with self.assertRaises(ValueError):
            SyncFloat._coerce("not a number")

    # ────────────────────────────────────────────────────────────────
    # Copying and Pickling
    # ────────────────────────────────────────────────────────────────
    def test_shallow_copy(self):
        f1 = SyncFloat(10.0)
        f2 = copy.copy(f1)
        self.assertIsInstance(f2, SyncFloat)
        self.assertEqual(f1.get(), f2.get())
        f1.set(20.0)
        self.assertEqual(f1.get(), 20.0)
        self.assertEqual(f2.get(), 10.0)

    def test_deep_copy(self):
        f1 = SyncFloat(15.0)
        f2 = copy.deepcopy(f1)
        self.assertIsInstance(f2, SyncFloat)
        self.assertEqual(f1.get(), f2.get())
        f1.set(25.0)
        self.assertEqual(f1.get(), 25.0)
        self.assertEqual(f2.get(), 15.0)

    def test_pickling_unpickling(self):
        f_original = SyncFloat(3.14159)
        pickled_f = pickle.dumps(f_original)
        f_unpickled = pickle.loads(pickled_f)
        self.assertIsInstance(f_unpickled, SyncFloat)
        self.assertEqual(f_original.get(), f_unpickled.get())
        self.assertIsNot(f_original, f_unpickled)

    def test_pickling_after_modification(self):
        f_original = SyncFloat(1.0)
        f_original.increment(5.0)
        pickled_f = pickle.dumps(f_original)
        f_unpickled = pickle.loads(pickled_f)
        self.assertEqual(f_unpickled.get(), 6.0)

    # ────────────────────────────────────────────────────────────────
    # Concurrent Operations
    # ────────────────────────────────────────────────────────────────
    def test_concurrent_increment(self):
        counter = SyncFloat(0.0)
        def bump():
            for _ in range(1000):
                counter.increment(0.1)
        _spawn_threads(bump, num_threads=8)
        self.assertAlmostEqual(counter.get(), 800.0, places=6)

    def test_no_deadlock_two_floats(self):
        a, b = SyncFloat(1.0), SyncFloat(2.0)
        barrier = threading.Barrier(2)
        errors = []
        def t_left():
            try:
                barrier.wait()
                for _ in range(5000):
                    _ = a + b
            except Exception as e:
                errors.append(e)
        def t_right():
            try:
                barrier.wait()
                for _ in range(5000):
                    _ = b - a
            except Exception as e:
                errors.append(e)
        t1, t2 = threading.Thread(target=t_left), threading.Thread(target=t_right)
        t1.start(); t2.start()
        t1.join(1); t2.join(1)
        self.assertFalse(t1.is_alive() or t2.is_alive())
        self.assertEqual(errors, [])

    def test_concurrent_set_and_get(self):
        f = SyncFloat(0.0)
        num_threads = 5
        num_sets_per_thread = 100
        def setter_worker(val):
            for _ in range(num_sets_per_thread):
                f.set(val)
        threads_list = []
        for i in range(num_threads):
            t = threading.Thread(target=setter_worker, args=(float(i),))
            threads_list.append(t)
            t.start()
        for t in threads_list:
            t.join()
        final_value = f.get()
        self.assertIn(final_value, [float(i) for i in range(num_threads)])

    def test_concurrent_mixed_operations(self):
        counter = SyncFloat(100.0)
        num_ops_per_thread = 500
        num_threads = 4
        def worker():
            for i in range(num_ops_per_thread):
                if i % 3 == 0:
                    counter.increment(0.5)
                elif i % 3 == 1:
                    counter.decrement(0.2)
                else:
                    _ = counter.get() * 1.1
        _spawn_threads(worker, num_threads=num_threads)
        self.assertTrue(math.isfinite(counter.get()))

    def test_concurrent_inplace_operations(self):
        val = SyncFloat(1.0)
        num_iterations_per_thread = 1000
        num_threads = 4
        def worker():
            nonlocal val
            for _ in range(num_iterations_per_thread):
                val *= 1.001
        _spawn_threads(worker, num_threads=num_threads)
        expected_value = 1.0 * (1.001 ** (num_threads * num_iterations_per_thread))
        self.assertAlmostEqual(val.get(), expected_value, places=6)

    def test_concurrent_binary_operations_different_types(self):
        f = SyncFloat(10.0)
        i = SyncInt(5)
        num_ops_per_thread = 1000
        results = []
        results_lock = threading.Lock()
        def append_result(res):
            with results_lock:
                results.append(res)
        def worker_f():
            for _ in range(num_ops_per_thread):
                append_result(f + i)
        def worker_i():
            for _ in range(num_ops_per_thread):
                append_result(i + f)
        t1 = threading.Thread(target=worker_f)
        t2 = threading.Thread(target=worker_i)
        t1.start(); t2.start()
        t1.join(); t2.join()
        self.assertEqual(len(results), 2 * num_ops_per_thread)
        self.assertTrue(all(r == 15.0 for r in results))

    def test_concurrent_init_safe(self):
        num_threads = 10
        num_instances_per_thread = 10
        expected_total_instances = num_threads * num_instances_per_thread
        instances = []
        instances_lock = threading.Lock()
        def create_instance_worker():
            with instances_lock:
                instances.append(SyncFloat(1.0, init_safe=True))
        _spawn_threads(create_instance_worker, num_threads=num_threads, iterations_per_thread=num_instances_per_thread)
        self.assertEqual(len(instances), expected_total_instances)
        for inst in instances:
            self.assertEqual(inst.get(), 1.0)
            self.assertIsInstance(inst, SyncFloat)

    def test_concurrent_init_unsafe(self):
        num_threads = 10
        num_instances_per_thread = 10
        expected_total_instances = num_threads * num_instances_per_thread
        instances = []
        instances_lock = threading.Lock()
        def create_instance_unsafe_worker():
            with instances_lock:
                instances.append(SyncFloat(1.0, init_safe=False))
        _spawn_threads(create_instance_unsafe_worker, num_threads=num_threads, iterations_per_thread=num_instances_per_thread)
        self.assertEqual(len(instances), expected_total_instances)
        for inst in instances:
            self.assertEqual(inst.get(), 1.0)
            self.assertIsInstance(inst, SyncFloat)

    def test_reentrant_lock_within_instance(self):
        f = SyncFloat(5.0)
        with f._lock:
            with f._lock:
                f._value += 1.0
                self.assertEqual(f.get(), 6.0)
        self.assertEqual(f.get(), 6.0)

    def test_reentrant_lock_through_methods(self):
        f = SyncFloat(10.0)
        self.assertEqual(abs(f), 10.0)
        f.set(f.get() + 5.0)
        self.assertEqual(f.get(), 15.0)

    def test_concurrent_increment_decrement_mixed_values(self):
        sf = SyncFloat(100.0)
        num_threads = 5
        ops_per_thread = 1000
        def worker():
            for i in range(ops_per_thread):
                if i % 2 == 0:
                    sf.increment(0.3)
                else:
                    sf.decrement(0.1)
        _spawn_threads(worker, num_threads=num_threads)
        expected_final_value = 100.0 + (ops_per_thread // 2 * 0.3 - ops_per_thread // 2 * 0.1) * num_threads
        self.assertAlmostEqual(sf.get(), expected_final_value, places=6)

    def test_concurrent_increment_with_sync_types(self):
        sf_val = SyncFloat(0.0)
        si_inc = SyncInt(1)
        sb_inc = SyncBool(True)
        num_threads = 10
        num_ops = 100
        def worker():
            for i in range(num_ops):
                if i % 2 == 0:
                    sf_val.increment(si_inc)
                else:
                    sf_val.increment(sb_inc)
        _spawn_threads(worker, num_threads=num_threads)
        expected_final_value = (num_ops // 2 * 1 + num_ops // 2 * 1) * num_threads
        self.assertAlmostEqual(sf_val.get(), expected_final_value, places=6)

    # ────────────────────────────────────────────────────────────────
    # Error Handling / Specific Exceptions
    # ────────────────────────────────────────────────────────────────
    def test_pow_three_arg_raises_typeerror(self):
        f = SyncFloat(2.0)
        with self.assertRaises(TypeError):
            pow(f, 3, 2)

    def test_as_integer_ratio_on_inf_nan_raises(self):
        f_inf = SyncFloat(float('inf'))
        f_nan = SyncFloat(float('nan'))
        with self.assertRaises(OverflowError):
            f_inf.as_integer_ratio()
        with self.assertRaises(ValueError):
            f_nan.as_integer_ratio()

    # ────────────────────────────────────────────────────────────────
    # Expanded Math Module Integrations
    # ────────────────────────────────────────────────────────────────
    def test_math_fmod(self):
        f = SyncFloat(10.5)
        self.assertAlmostEqual(math.fmod(f, 3.0), 1.5)
        self.assertAlmostEqual(math.fmod(f, -3.0), 1.5)
        f_neg = SyncFloat(-10.5)
        self.assertAlmostEqual(math.fmod(f_neg, 3.0), -1.5)
        self.assertAlmostEqual(math.fmod(f_neg, -3.0), -1.5)
        self.assertAlmostEqual(math.fmod(f, SyncInt(3)), 1.5)

    def test_math_copysign(self):
        f = SyncFloat(5.0)
        self.assertEqual(math.copysign(f, -1.0), -5.0)
        self.assertEqual(math.copysign(f, SyncFloat(-0.0)), -5.0)
        self.assertEqual(math.copysign(SyncFloat(-5.0), 1.0), 5.0)
        self.assertEqual(math.copysign(SyncFloat(0.0), -1.0), -0.0)


    def test_math_modf(self):
        f = SyncFloat(3.14159)
        fractional, integral = math.modf(f)
        self.assertAlmostEqual(fractional, 0.14159)
        self.assertEqual(integral, 3.0)
        f_neg = SyncFloat(-3.14159)
        fractional_neg, integral_neg = math.modf(f_neg)
        self.assertAlmostEqual(fractional_neg, -0.14159)
        self.assertEqual(integral_neg, -3.0)

    def test_math_isfinite_isinf_isnan(self):
        self.assertTrue(math.isfinite(SyncFloat(10.0)))
        self.assertFalse(math.isfinite(SyncFloat(float('inf'))))
        self.assertFalse(math.isfinite(SyncFloat(float('nan'))))
        self.assertTrue(math.isinf(SyncFloat(float('inf'))))
        self.assertTrue(math.isinf(SyncFloat(float('-inf'))))
        self.assertFalse(math.isinf(SyncFloat(10.0)))
        self.assertTrue(math.isnan(SyncFloat(float('nan'))))
        self.assertFalse(math.isnan(SyncFloat(10.0)))

    def test_math_sum_with_sync_float(self):
        sf_list = [SyncFloat(1.0), SyncFloat(2.0), SyncFloat(3.0)]
        self.assertEqual(sum(sf_list), 6.0)

    # ────────────────────────────────────────────────────────────────
    # Advanced Inf/NaN Arithmetic
    # ────────────────────────────────────────────────────────────────
    def test_inf_inf_arithmetic(self):
        pinf = SyncFloat(float('inf'))
        ninf = SyncFloat(float('-inf'))
        normal = SyncFloat(5.0)

        self.assertEqual(pinf + normal, float('inf'))
        self.assertEqual(pinf * normal, float('inf'))
        self.assertEqual(pinf / normal, float('inf'))
        self.assertEqual(ninf + normal, float('-inf'))
        self.assertEqual(ninf * normal, float('-inf'))
        self.assertEqual(ninf / normal, float('-inf'))
        self.assertEqual(pinf + pinf, float('inf'))
        self.assertEqual(ninf + ninf, float('-inf'))
        self.assertTrue(math.isnan(pinf - pinf))
        self.assertTrue(math.isnan(pinf / pinf))
        self.assertEqual(pinf * ninf, float('-inf'))
        self.assertTrue(math.isnan(pinf * SyncFloat(0.0)))
        self.assertTrue(math.isnan(ninf * SyncFloat(0.0)))

    def test_nan_arithmetic_always_nan(self):
        nan = SyncFloat(float('nan'))
        x = SyncFloat(10.0)

        self.assertTrue(math.isnan(nan + x))
        self.assertTrue(math.isnan(x + nan))
        self.assertTrue(math.isnan(nan - x))
        self.assertTrue(math.isnan(x - nan))
        self.assertTrue(math.isnan(nan * x))
        self.assertTrue(math.isnan(x * nan))
        self.assertTrue(math.isnan(nan / x))
        self.assertTrue(math.isnan(x / nan))
        self.assertTrue(math.isnan(nan // x))
        self.assertTrue(math.isnan(x // nan))
        self.assertTrue(math.isnan(nan % x))
        self.assertTrue(math.isnan(x % nan))
        self.assertTrue(math.isnan(nan ** x))
        self.assertTrue(math.isnan(x ** nan))

    # ────────────────────────────────────────────────────────────────
    # Chained & Complex Operations
    # ────────────────────────────────────────────────────────────────
    def test_chained_arithmetic_ops(self):
        a, b, c = SyncFloat(10.0), SyncFloat(2.0), SyncFloat(3.0)
        self.assertEqual(a + b * c, 10.0 + 2.0 * 3.0)
        self.assertEqual((a + b) * c, (10.0 + 2.0) * 3.0)
        self.assertAlmostEqual(a / b + c, 10.0 / 2.0 + 3.0)
        self.assertAlmostEqual(a / (b + c), 10.0 / (2.0 + 3.0))
        self.assertAlmostEqual(a ** b / c, 10.0 ** 2.0 / 3.0)

    def test_complex_expression_with_mixed_types(self):
        f = SyncFloat(4.0)
        i = SyncInt(2)
        b = SyncBool(True)

        result = (f + i) * b / f
        expected = (4.0 + 2.0) * 1.0 / 4.0
        self.assertAlmostEqual(result, expected)

        result_2 = (f ** i) - (b * 10)
        expected_2 = (4.0 ** 2.0) - (1.0 * 10)
        self.assertAlmostEqual(result_2, expected_2)

    def test_negative_zero_copysign(self):
        self.assertEqual(math.copysign(1.0, SyncFloat(-0.0)), -1.0)
        self.assertEqual(math.copysign(SyncFloat(1.0), -0.0), -1.0)
        self.assertEqual(math.copysign(SyncFloat(-5.0), SyncFloat(0.0)), 5.0)

    # ────────────────────────────────────────────────────────────────
    # Type Checking and Immutability
    # ────────────────────────────────────────────────────────────────
    def test_return_types_of_arithmetic_operations(self):
        a = SyncFloat(5.0)
        b = SyncFloat(2.0)
        self.assertIsInstance(a + b, float)
        self.assertIsInstance(a - b, float)
        self.assertIsInstance(a * b, float)
        self.assertIsInstance(a / b, float)
        self.assertIsInstance(a // b, float)
        self.assertIsInstance(a % b, float)
        self.assertIsInstance(a ** b, float)
        self.assertIsInstance(divmod(a, b), tuple)
        self.assertIsInstance(divmod(a, b)[0], float)
        self.assertIsInstance(divmod(a, b)[1], float)

    def test_return_types_of_comparison_operations(self):
        a = SyncFloat(5.0)
        b = SyncFloat(2.0)
        self.assertIsInstance(a == b, bool)
        self.assertIsInstance(a != b, bool)
        self.assertIsInstance(a < b, bool)
        self.assertIsInstance(a <= b, bool)
        self.assertIsInstance(a > b, bool)
        self.assertIsInstance(a >= b, bool)

    def test_attribute_access_with_slots(self):
        f = SyncFloat(1.0)
        with self.assertRaises(AttributeError):
            f.new_attr = 10
        self.assertEqual(f.get(), 1.0)

    def test_type_of_instance(self):
        f = SyncFloat(1.0)
        self.assertIsInstance(f, SyncFloat)
        self.assertTrue(issubclass(type(f), SyncFloat))
        self.assertIs(type(f), SyncFloat)

    # ────────────────────────────────────────────────────────────────
    # More Rounding Details
    # ────────────────────────────────────────────────────────────────
    def test_round_with_negative_ndigits(self):
        f = SyncFloat(12345.678)
        self.assertEqual(round(f, -1), 12350.0)
        self.assertEqual(round(f, -2), 12300.0)
        self.assertEqual(round(f, -3), 12000.0)

    def test_round_half_to_even_behavior(self):
        self.assertEqual(round(SyncFloat(2.5)), 2)
        self.assertEqual(round(SyncFloat(3.5)), 4)
        self.assertEqual(round(SyncFloat(0.5)), 0)
        self.assertEqual(round(SyncFloat(-0.5)), 0)

    # ────────────────────────────────────────────────────────────────
    # Bitwise Operations (Negative Tests - Expect TypeError)
    # ────────────────────────────────────────────────────────────────
    def test_bitwise_and_raises_typeerror(self):
        f = SyncFloat(5.0)
        with self.assertRaises(TypeError):
            _ = f & 1
        with self.assertRaises(TypeError):
            _ = 1 & f

    def test_bitwise_or_raises_typeerror(self):
        f = SyncFloat(5.0)
        with self.assertRaises(TypeError):
            _ = f | 1
        with self.assertRaises(TypeError):
            _ = 1 | f

    def test_bitwise_xor_raises_typeerror(self):
        f = SyncFloat(5.0)
        with self.assertRaises(TypeError):
            _ = f ^ 1
        with self.assertRaises(TypeError):
            _ = 1 ^ f

    def test_bitwise_left_shift_raises_typeerror(self):
        f = SyncFloat(5.0)
        with self.assertRaises(TypeError):
            _ = f << 1
        with self.assertRaises(TypeError):
            _ = 1 << f

    def test_bitwise_right_shift_raises_typeerror(self):
        f = SyncFloat(5.0)
        with self.assertRaises(TypeError):
            _ = f >> 1
        with self.assertRaises(TypeError):
            _ = 1 >> f

    # ────────────────────────────────────────────────────────────────
    # More Concurrent Scenarios
    # ────────────────────────────────────────────────────────────────
    def test_concurrent_get_only(self):
        f = SyncFloat(100.0)
        read_values = []
        read_lock = threading.Lock()
        def reader_worker():
            for _ in range(1000):
                with read_lock:
                    read_values.append(f.get())
        _spawn_threads(reader_worker, num_threads=10)
        self.assertTrue(all(val == 100.0 for val in read_values))
        self.assertEqual(len(read_values), 10 * 1000)

    def test_concurrent_increment_mixed_sync_float_and_raw_float(self):
        counter = SyncFloat(0.0)
        increment_amount = SyncFloat(0.01)
        def worker_raw_float():
            for _ in range(500):
                counter.increment(0.02)
        def worker_sync_float():
            for _ in range(500):
                counter.increment(increment_amount)
        t1 = threading.Thread(target=worker_raw_float)
        t2 = threading.Thread(target=worker_sync_float)
        t1.start(); t2.start()
        t1.join(); t2.join()
        self.assertAlmostEqual(counter.get(), 15.0, places=6)

    def test_concurrent_set_from_different_threads(self):
        f = SyncFloat(0.0)
        values_to_set = [float(i) for i in range(10)]
        num_threads = 5
        sets_per_thread = 20
        def setter_worker(thread_id):
            for i in range(sets_per_thread):
                val_idx = (thread_id + i) % len(values_to_set)
                f.set(values_to_set[val_idx])
        threads = []
        for i in range(num_threads):
            t = threading.Thread(target=setter_worker, args=(i,))
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
        final_value = f.get()
        self.assertIn(final_value, values_to_set)
        self.assertTrue(math.isfinite(final_value))


    # ────────────────────────────────────────────────────────────────
    # NEW TESTS START HERE (Focus on more niche/edge cases)
    # ────────────────────────────────────────────────────────────────

    # Niche Numeric Behaviors
    def test_very_small_and_large_numbers_arithmetic(self):
        sf_min = SyncFloat(sys.float_info.min) # Smallest positive normal float
        sf_max = SyncFloat(sys.float_info.max) # Largest finite float

        self.assertAlmostEqual(sf_min * 2, sys.float_info.min * 2)
        self.assertAlmostEqual(sf_max / 2, sys.float_info.max / 2)
        self.assertEqual(sf_max * 2, float('inf')) # Overflow
        self.assertAlmostEqual(sf_min / 2, 0.0) # Underflow to zero (subnormal)

    def test_subnormal_floats(self):
        # Python's float handles subnormals (denormalized numbers)
        subnormal_float = sys.float_info.min / 10 # This will be a subnormal
        sf_sub = SyncFloat(subnormal_float)

        self.assertAlmostEqual(sf_sub.get(), subnormal_float)
        self.assertAlmostEqual(sf_sub * 10, subnormal_float * 10)
        self.assertAlmostEqual(sf_sub / 10, subnormal_float / 10)
        # sub-normal comparison
        self.assertAlmostEqual(
            sf_sub / SyncFloat(sys.float_info.min), 0.1, places=15
        )

    def test_pow_zero_exponent_negative_base(self):
        self.assertEqual(SyncFloat(-5.0) ** 0, 1.0)
        self.assertEqual(SyncFloat(-0.0) ** 0, 1.0) # Consistency with float behavior

    def test_pow_one_exponent(self):
        self.assertEqual(SyncFloat(7.0) ** 1, 7.0)
        self.assertEqual(SyncFloat(-7.0) ** 1, -7.0)

    def test_pow_negative_one_exponent(self):
        self.assertEqual(SyncFloat(2.0) ** -1, 0.5)
        self.assertEqual(SyncFloat(-2.0) ** -1, -0.5)
        self.assertEqual(SyncFloat(4.0) ** SyncInt(-1), 0.25)


    # More comprehensive round tests
    def test_round_precision_edge_cases(self):
        # Rounding 0.5 away from zero in Python is usually toward even.
        self.assertEqual(round(SyncFloat(2.5)), 2)
        self.assertEqual(round(SyncFloat(3.5)), 4)
        self.assertEqual(round(SyncFloat(0.5)), 0)
        self.assertEqual(round(SyncFloat(-0.5)), 0)

        self.assertEqual(round(SyncFloat(1.2345), 3), 1.234)

    # String Representations
    def test_str_repr_for_edge_floats(self):
        self.assertEqual(str(SyncFloat(float('inf'))), 'inf')
        self.assertEqual(str(SyncFloat(float('-inf'))), '-inf')
        self.assertEqual(repr(SyncFloat(float('nan'))), 'SyncFloat(nan)') # repr should contain nan
        self.assertIn('nan', str(SyncFloat(float('nan')))) # str for nan is 'nan'

    def test_format_specifiers_edge_cases(self):
        pinf = SyncFloat(float('inf'))
        ninf = SyncFloat(float('-inf'))
        nan = SyncFloat(float('nan'))

        self.assertEqual(f"{pinf:+f}", "+inf")
        self.assertEqual(f"{ninf:-f}", "-inf")
        self.assertEqual(f"{nan}", "nan")
        self.assertEqual(f"{SyncFloat(1.2345e-10):.2e}", "1.23e-10")

    # Property Access
    def test_real_imag_properties_type_and_value(self):
        sf = SyncFloat(10.5)
        self.assertEqual(sf.real, 10.5)
        self.assertEqual(sf.imag, 0.0)
        self.assertIsInstance(sf.real, float)
        self.assertIsInstance(sf.imag, float)

    # Advanced Mixed Type Operations
    def test_arithmetic_with_sync_int_results_in_float(self):
        a = SyncFloat(5.0)
        b = SyncInt(2)
        self.assertIsInstance(a + b, float)
        self.assertIsInstance(a - b, float)
        self.assertIsInstance(a * b, float)
        self.assertIsInstance(a / b, float)
        self.assertIsInstance(a // b, float) # Floor division of float/int is float
        self.assertIsInstance(a % b, float)

    def test_inplace_with_raw_float_and_int(self):
        f = SyncFloat(10.0)
        f += 2.5
        self.assertEqual(f.get(), 12.5)
        f -= 1
        self.assertEqual(f.get(), 11.5)
        f *= 2.0
        self.assertEqual(f.get(), 23.0)
        f /= 2
        self.assertEqual(f.get(), 11.5)

    def test_cross_type_pow(self):
        f_base = SyncFloat(2.0)
        i_exp = SyncInt(3)
        self.assertEqual(f_base ** i_exp, 8.0)
        self.assertEqual(i_exp ** f_base, 9.0) # 3 ** 2.0

        f_exp = SyncFloat(0.5)
        i_base = SyncInt(9)
        self.assertEqual(i_base ** f_exp, 3.0) # 9 ** 0.5 = 3

    # Concurrency and Threading Specifics
    def test_concurrent_arithmetic_on_different_instances_no_collision(self):
        f1 = SyncFloat(1.0)
        f2 = SyncFloat(100.0)
        num_ops = 500
        threads = []

        def worker1():
            for _ in range(num_ops):
                f1.increment(0.1)
        def worker2():
            for _ in range(num_ops):
                f2.decrement(0.5)

        t1 = threading.Thread(target=worker1)
        t2 = threading.Thread(target=worker2)
        threads.extend([t1, t2])

        for t in threads: t.start()
        for t in threads: t.join()

        self.assertAlmostEqual(f1.get(), 1.0 + num_ops * 0.1, places=6) # 1.0 + 50 = 51.0
        self.assertAlmostEqual(f2.get(), 100.0 - num_ops * 0.5, places=6) # 100.0 - 250 = -150.0

    def test_concurrent_cross_type_inplace_ops(self):
        f = SyncFloat(1000.0)
        i_val = SyncInt(10)
        b_val = SyncBool(True)
        num_ops = 200

        def worker_f():
            nonlocal f
            for _ in range(num_ops):
                f += i_val # f += SyncInt

        def worker_i():
            nonlocal f
            for _ in range(num_ops):
                f -= b_val # f -= SyncBool (1)

        t1 = threading.Thread(target=worker_f)
        t2 = threading.Thread(target=worker_i)
        t1.start(); t2.start()
        t1.join(); t2.join()

        # Expected: 1000 + (200 * 10) - (200 * 1) = 1000 + 2000 - 200 = 2800
        self.assertAlmostEqual(f.get(), 2800.0, places=6)


    # Error Handling / Invalid Operations
    def test_set_with_non_convertible_string(self):
        f = SyncFloat(1.0)
        with self.assertRaises(ValueError):
            f.set("not a number")

    def test_fromhex_invalid_string_raises_valueerror(self):
        with self.assertRaises(ValueError):
            SyncFloat.fromhex("invalid_hex_string")
        with self.assertRaises(ValueError):
            SyncFloat.fromhex("0xG.0p+0") # Invalid hex digit


    # Attribute Test for __slots__
    def test_no_arbitrary_attribute_setting(self):
        f = SyncFloat(1.0)
        with self.assertRaises(AttributeError):
            f.new_attribute = "test"
        # __slots__ prevents __dict__
        self.assertFalse(hasattr(f, '__dict__'))

    def test_dir_contains_expected_members(self):
        f = SyncFloat(1.0)
        d = dir(f)
        self.assertIn('get', d)
        self.assertIn('set', d)
        self.assertIn('__add__', d)
        self.assertIn('__float__', d)
        self.assertIn('real', d)
        self.assertIn('imag', d)
        self.assertNotIn('new_attribute', d) # Should not contain arbitrarily added attributes


    # Final sanity check for return types
    def test_float_type_return_for_binary_ops_consistency(self):
        sfa = SyncFloat(10.0)
        sfb = SyncFloat(2.0)
        raw_float = 3.0
        raw_int = 4

        self.assertIsInstance(sfa + sfb, float)
        self.assertIsInstance(sfa + raw_float, float)
        self.assertIsInstance(sfa + raw_int, float)

        self.assertIsInstance(sfa * sfb, float)
        self.assertIsInstance(sfa * raw_float, float)
        self.assertIsInstance(sfa * raw_int, float)

        # Reverse operations
        self.assertIsInstance(raw_float + sfa, float)
        self.assertIsInstance(raw_int + sfa, float)


if __name__ == "__main__":
    unittest.main(argv=['first-arg-is-ignored'], exit=False)