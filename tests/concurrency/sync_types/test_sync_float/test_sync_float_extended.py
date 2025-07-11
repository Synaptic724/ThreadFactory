import math
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import pickle
import copy  # Import copy module for clarity

# ---- import your concrete classes ----------------------------------
from thread_factory.concurrency.sync_types.sync_float import SyncFloat
from thread_factory.concurrency.sync_types.sync_int import SyncInt
from thread_factory.concurrency.sync_types.sync_bool import SyncBool


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


class TestSyncFloatExtended(unittest.TestCase):
    # ────────────────────────────────────────────────────────────────
    # New: Constructor Edge Cases & Type Coercion
    # ────────────────────────────────────────────────────────────────
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
        self.assertEqual(SyncFloat(-0.0).get(), 0.0)  # -0.0 is same as 0.0 in Python floats

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
    # New: Arithmetic with Zero and One
    # ────────────────────────────────────────────────────────────────
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

        # divide-by-zero must raise, exactly like a raw float
        with self.assertRaises(ZeroDivisionError):
            _ = f / SyncFloat(0.0)

        with self.assertRaises(ZeroDivisionError):
            _ = SyncFloat(0.0) / 0.0

        # behaviour with ±inf is still valid:
        self.assertTrue(math.isinf(f * float('inf')))
        self.assertTrue(math.isnan(SyncFloat(0.0) * float('inf')))

    def test_pow_edge_cases(self):
        f = SyncFloat(2.0)
        self.assertEqual(f ** 0, 1.0)
        self.assertEqual(SyncFloat(0.0) ** f, 0.0)
        self.assertEqual(f ** 1, 2.0)
        self.assertEqual(f ** -1, 0.5)
        self.assertEqual(SyncFloat(0.0) ** 0, 1.0)  # Special case in Python

    # ────────────────────────────────────────────────────────────────
    # New: In-place Operations with Mixed Types
    # ────────────────────────────────────────────────────────────────
    def test_inplace_with_sync_int(self):
        f = SyncFloat(10.0)
        i = SyncInt(3)
        f += i
        self.assertEqual(f.get(), 13.0)
        f -= i
        self.assertEqual(f.get(), 10.0)
        f *= i
        self.assertEqual(f.get(), 30.0)
        f /= i
        self.assertEqual(f.get(), 10.0)
        f //= i
        self.assertEqual(f.get(), 3.0)
        f %= i
        self.assertEqual(f.get(), 0.0)
        f.set(2.0)
        f **= i
        self.assertEqual(f.get(), 8.0)

    def test_inplace_with_sync_bool(self):
        f = SyncFloat(5.0)
        b = SyncBool(True)  # 1
        f += b
        self.assertEqual(f.get(), 6.0)
        f.set(5.0)
        b = SyncBool(False)  # 0
        f *= b
        self.assertEqual(f.get(), 0.0)

    # ────────────────────────────────────────────────────────────────
    # New: Comparison Edge Cases
    # ────────────────────────────────────────────────────────────────
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
        self.assertFalse(nan == nan)  # NaN is never equal to anything, even itself
        self.assertFalse(nan < 0)
        self.assertFalse(nan > 0)
        self.assertFalse(nan == 0)

    def test_mixed_type_comparisons(self):
        f = SyncFloat(5.0)
        i = SyncInt(5)
        s = "5.0"
        self.assertTrue(f == i)
        self.assertTrue(f == 5)
        # _unwrap_other converts "5.0" to 5.0, so the comparison will be True
        self.assertTrue(f == s)
        self.assertTrue(f >= 4.9)
        self.assertTrue(f <= 5.1)

    # ────────────────────────────────────────────────────────────────
    # New: Type Conversion and Representation Details
    # ────────────────────────────────────────────────────────────────
    def test_str_repr_consistency(self):
        f = SyncFloat(123.456)
        self.assertEqual(str(f), "123.456")
        self.assertEqual(repr(f), "SyncFloat(123.456)")

    def test_format_specifiers(self):
        f = SyncFloat(123.456789)
        self.assertEqual(f"{f:.2f}", "123.46")
        self.assertEqual(f"{f:e}", "1.234568e+02")
        # Corrected expected output for 010.2f
        self.assertEqual(f"{f:010.2f}", "0000123.46")

    def test_bool_conversion_strict(self):
        self.assertFalse(bool(SyncFloat(0.0)))
        self.assertTrue(bool(SyncFloat(0.000001)))
        self.assertTrue(bool(SyncFloat(-0.000001)))

    def test_hash_for_float_equivalents(self):
        self.assertEqual(hash(SyncFloat(1.0)), hash(1.0))
        self.assertEqual(hash(SyncFloat(1)), hash(1.0))  # int is coerced to float for hashing

    # ────────────────────────────────────────────────────────────────
    # New: math module interactions
    # ────────────────────────────────────────────────────────────────
    def test_math_trunc_ceil_floor_negative(self):
        f_neg = SyncFloat(-3.75)
        self.assertEqual(math.trunc(f_neg), -3)  # truncates towards zero
        self.assertEqual(math.ceil(f_neg), -3)
        self.assertEqual(math.floor(f_neg), -4)

    def test_math_fabs(self):
        f = SyncFloat(-5.0)
        self.assertEqual(math.fabs(f), 5.0)
        self.assertIsInstance(math.fabs(f), float)

    # ────────────────────────────────────────────────────────────────
    # New: Copying and Pickling
    # ────────────────────────────────────────────────────────────────
    def test_shallow_copy(self):
        f1 = SyncFloat(10.0)
        f2 = copy.copy(f1)  # Using copy.copy for clarity
        self.assertIsInstance(f2, SyncFloat)
        self.assertEqual(f1.get(), f2.get())
        f1.set(20.0)
        self.assertEqual(f1.get(), 20.0)
        self.assertEqual(f2.get(), 10.0)  # Should be independent copy

    def test_deep_copy(self):
        f1 = SyncFloat(15.0)
        f2 = copy.deepcopy(f1)  # Using copy.deepcopy for clarity
        self.assertIsInstance(f2, SyncFloat)
        self.assertEqual(f1.get(), f2.get())
        f1.set(25.0)
        self.assertEqual(f1.get(), 25.0)
        self.assertEqual(f2.get(), 15.0)  # Should be independent copy

    def test_pickling_unpickling(self):
        f_original = SyncFloat(3.14159)
        pickled_f = pickle.dumps(f_original)
        f_unpickled = pickle.loads(pickled_f)

        self.assertIsInstance(f_unpickled, SyncFloat)
        self.assertEqual(f_original.get(), f_unpickled.get())
        # Ensure it's a new instance, not the same object (important for locks)
        self.assertIsNot(f_original, f_unpickled)

    def test_pickling_after_modification(self):
        f_original = SyncFloat(1.0)
        f_original.increment(5.0)  # Value is now 6.0
        pickled_f = pickle.dumps(f_original)
        f_unpickled = pickle.loads(pickled_f)
        self.assertEqual(f_unpickled.get(), 6.0)

    # ────────────────────────────────────────────────────────────────
    # New: Concurrent Operations (More Complex Scenarios)
    # ────────────────────────────────────────────────────────────────
    def test_concurrent_set_and_get(self):
        f = SyncFloat(0.0)
        num_threads = 5
        num_sets_per_thread = 100

        def setter_worker(val):
            # This function runs once per iteration of _spawn_threads
            # Each call to setter_worker will run num_sets_per_thread sets
            for _ in range(num_sets_per_thread):
                f.set(val)

        threads_list = []  # Use a list to store threads for join
        for i in range(num_threads):
            t = threading.Thread(target=setter_worker, args=(float(i),))
            threads_list.append(t)
            t.start()

        # Threads will continuously overwrite each other. The final value
        # will be one of the values set by the threads. This tests that
        # `set` doesn't crash or dead-lock, but the final value is non-deterministic.
        for t in threads_list:
            t.join()

        final_value = f.get()
        # The final value must be one of the values explicitly set by a thread.
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
                    _ = counter.get() * 1.1  # Read operation

        _spawn_threads(worker, num_threads=num_threads)
        # Expected value is hard to predict due to reads/multiplications,
        # but the test ensures no crashes or deadlocks.
        # We just assert it's a number and not NaN/Inf
        self.assertTrue(math.isfinite(counter.get()))

    def test_concurrent_inplace_operations(self):
        val = SyncFloat(1.0)
        num_iterations_per_thread = 1000
        num_threads = 4

        def worker():
            nonlocal val
            for _ in range(num_iterations_per_thread):
                val *= 1.001  # Small multiplication

        _spawn_threads(worker, num_threads=num_threads)
        # 1.0 * (1.001 ^ (num_threads * num_iterations_per_thread))
        expected_value = 1.0 * (1.001 ** (num_threads * num_iterations_per_thread))
        self.assertAlmostEqual(val.get(), expected_value, places=6)

    def test_concurrent_binary_operations_different_types(self):
        f = SyncFloat(10.0)
        i = SyncInt(5)
        num_ops_per_thread = 1000
        results = []  # Store results to verify correct computation

        # Helper to safely append to results list
        results_lock = threading.Lock()

        def append_result(res):
            with results_lock:
                results.append(res)

        def worker_f():
            for _ in range(num_ops_per_thread):
                append_result(f + i)

        def worker_i():
            for _ in range(num_ops_per_thread):
                append_result(i + f)  # Reverse operation

        t1 = threading.Thread(target=worker_f)
        t2 = threading.Thread(target=worker_i)
        t1.start();
        t2.start()
        t1.join();
        t2.join()

        self.assertEqual(len(results), 2 * num_ops_per_thread)
        # All results should be 15.0
        self.assertTrue(all(r == 15.0 for r in results))

    # ────────────────────────────────────────────────────────────────
    # New: Error Handling / Specific Exceptions
    # ────────────────────────────────────────────────────────────────
    def test_pow_three_arg_raises_typeerror(self):
        f = SyncFloat(2.0)
        with self.assertRaises(TypeError):
            pow(f, 3, 2)  # third argument (mod) is not supported for float pow

    def test_as_integer_ratio_on_inf_nan_raises(self):
        f_inf = SyncFloat(float('inf'))
        f_nan = SyncFloat(float('nan'))
        with self.assertRaises(OverflowError):
            f_inf.as_integer_ratio()
        with self.assertRaises(ValueError):
            f_nan.as_integer_ratio()

    # ────────────────────────────────────────────────────────────────
    # New: Property Accessors
    # ────────────────────────────────────────────────────────────────
    def test_real_imag_type(self):
        f = SyncFloat(1.23)
        self.assertIsInstance(f.real, float)
        self.assertIsInstance(f.imag, float)

    # ────────────────────────────────────────────────────────────────
    # New: Additional Dunder Methods
    # ────────────────────────────────────────────────────────────────
    def test_getnewargs_for_pickle(self):
        # This test ensures __getnewargs__ works if __reduce__ isn't used
        # or if older pickle protocols are involved. With __reduce__ present,
        # it might not be strictly necessary to test __getnewargs__ specifically,
        # but it shows the expected output if it were called.
        f = SyncFloat(42.0)
        # Explicitly call __getnewargs__ for testing its output format
        args = f.__getnewargs__()
        self.assertEqual(args, (42.0,))
        # Test reconstruction from args (as pickle would do)
        new_f = type(f)(*args)
        self.assertEqual(new_f.get(), 42.0)

    def test_fromhex_with_negative_and_zero(self):
        self.assertEqual(SyncFloat.fromhex('-0x1.0p+0').get(), -1.0)
        self.assertEqual(SyncFloat.fromhex('0x0.0p+0').get(), 0.0)

    def test_is_integer_method(self):
        self.assertTrue(SyncFloat(5.0).is_integer())
        self.assertTrue(SyncFloat(-3.0).is_integer())
        self.assertFalse(SyncFloat(5.1).is_integer())
        self.assertFalse(SyncFloat(0.00001).is_integer())

    def test_getformat(self):
        # This is primarily for CPython compatibility and introspection
        # The exact string depends on system architecture/Python build
        format_str_double = SyncFloat.__getformat__("double")
        self.assertIsInstance(format_str_double, str)
        self.assertIn(format_str_double, ("unknown", "IEEE, big-endian", "IEEE, little-endian"))

        # Changed to ValueError as float.__getformat__ raises ValueError
        with self.assertRaises(ValueError):
            SyncFloat.__getformat__("invalid_type")

    # ────────────────────────────────────────────────────────────────
    # New: Interoperability with standard float
    # ────────────────────────────────────────────────────────────────
    def test_arithmetic_with_raw_float(self):
        f = SyncFloat(5.5)
        self.assertEqual(f + 2.0, 7.5)
        self.assertEqual(2.0 + f, 7.5)
        self.assertEqual(f - 1.0, 4.5)
        self.assertEqual(1.0 - f, -4.5)
        self.assertEqual(f * 2.0, 11.0)
        self.assertEqual(2.0 * f, 11.0)


    # ────────────────────────────────────────────────────────────────
    # New: RLock Re-entrancy
    # ────────────────────────────────────────────────────────────────
    def test_reentrant_lock_within_instance(self):
        f = SyncFloat(5.0)
        with f._lock:  # Acquire outer lock
            # This should not deadlock as RLock is re-entrant
            with f._lock:  # Acquire inner lock
                f._value += 1.0
                self.assertEqual(f.get(), 6.0)  # get() also acquires the lock
        self.assertEqual(f.get(), 6.0)

    def test_reentrant_lock_through_methods(self):
        f = SyncFloat(10.0)
        # abs(f) will call f.get() which acquires the lock. No re-entrancy issue here.
        self.assertEqual(abs(f), 10.0)
        # f.set() acquires lock, then f.get() inside the argument to set() also acquires lock.
        # This chain of operations demonstrates re-entrancy.
        f.set(f.get() + 5.0)
        self.assertEqual(f.get(), 15.0)


if __name__ == "__main__":
    unittest.main(argv=['first-arg-is-ignored'], exit=False)