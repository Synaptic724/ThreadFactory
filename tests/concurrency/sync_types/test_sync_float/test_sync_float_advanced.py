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


class TestSyncFloatAdvanced(unittest.TestCase):
    # ────────────────────────────────────────────────────────────────
    # New: Detailed Arithmetic Scenarios
    # ────────────────────────────────────────────────────────────────
    def test_arithmetic_with_negative_numbers(self):
        a = SyncFloat(5.0)
        b = SyncFloat(-2.0)
        self.assertEqual(a + b, 3.0)
        self.assertEqual(a - b, 7.0)
        self.assertEqual(a * b, -10.0)
        self.assertEqual(a / b, -2.5)
        self.assertEqual(a // b, -3.0)  # Floor division
        self.assertAlmostEqual(a % b, -1.0) # 5 % -2 = -2 * (-3) + -1 = 6 - 1 = 5

        # Reverse operations with negatives
        self.assertEqual(-2.0 + a, 3.0)
        self.assertEqual(-7.0 - a, -12.0)
        self.assertEqual(-3.0 * a, -15.0)
        self.assertEqual(-10.0 / a, -2.0)

    def test_divmod_with_negatives_and_fractions(self):
        f1 = SyncFloat(7.5)
        f2 = SyncFloat(-2.0)
        # Python's divmod for floats: q = floor(a/b), r = a - q*b
        # 7.5 / -2.0 = -3.75
        # q = math.floor(-3.75) = -4.0
        # r = 7.5 - (-4.0) * (-2.0) = 7.5 - 8.0 = -0.5
        self.assertEqual(divmod(f1, f2), (-4.0, -0.5))

        f3 = SyncFloat(-7.5)
        f4 = SyncFloat(2.0)
        # -7.5 / 2.0 = -3.75
        # q = math.floor(-3.75) = -4.0
        # r = -7.5 - (-4.0) * 2.0 = -7.5 + 8.0 = 0.5
        self.assertEqual(divmod(f3, f4), (-4.0, 0.5))

        f5 = SyncFloat(-7.5)
        f6 = SyncFloat(-2.0)
        # -7.5 / -2.0 = 3.75
        # q = math.floor(3.75) = 3.0
        # r = -7.5 - (3.0) * (-2.0) = -7.5 + 6.0 = -1.5
        self.assertEqual(divmod(f5, f6), (3.0, -1.5))

    # ────────────────────────────────────────────────────────────────
    # New: Advanced Mixed-Type Comparisons
    # ────────────────────────────────────────────────────────────────
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

        # Reverse comparisons
        self.assertTrue(i_eq == f)
        self.assertFalse(i_eq != f)
        self.assertTrue(i_lt < f)
        self.assertTrue(i_lt <= f)
        self.assertTrue(i_gt > f)
        self.assertTrue(i_gt >= f)

    def test_comparison_sync_float_vs_sync_bool(self):
        f_one = SyncFloat(1.0)
        f_zero = SyncFloat(0.0)
        b_true = SyncBool(True)  # Coerces to 1.0
        b_false = SyncBool(False) # Coerces to 0.0

        self.assertTrue(f_one == b_true)
        self.assertTrue(f_zero == b_false)
        self.assertTrue(f_one > b_false)
        self.assertTrue(f_zero < b_true)
        self.assertFalse(f_one == b_false)
        self.assertFalse(f_zero == b_true)

    # ────────────────────────────────────────────────────────────────
    # New: Explicit Dunder Method Calls (for type consistency)
    # ────────────────────────────────────────────────────────────────
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

    # ────────────────────────────────────────────────────────────────
    # New: Concurrent Increment/Decrement with Specific Values
    # ────────────────────────────────────────────────────────────────
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

        # Each thread performs 500 increments of 0.3 and 500 decrements of 0.1
        # Net change per thread: 500 * 0.3 - 500 * 0.1 = 150 - 50 = 100
        # Total change: 100 * num_threads = 100 * 5 = 500
        expected_final_value = 100.0 + 500.0
        self.assertAlmostEqual(sf.get(), expected_final_value, places=6)

    def test_concurrent_increment_with_sync_types(self):
        sf_val = SyncFloat(0.0)
        si_inc = SyncInt(1)
        sb_inc = SyncBool(True) # 1.0
        num_threads = 10
        num_ops = 100

        def worker():
            for i in range(num_ops):
                if i % 2 == 0:
                    sf_val.increment(si_inc) # add SyncInt
                else:
                    sf_val.increment(sb_inc) # add SyncBool

        _spawn_threads(worker, num_threads=num_threads)
        # Each thread adds (num_ops/2 * 1) + (num_ops/2 * 1) = num_ops * 1 = 100
        # Total: 100 * 10 = 1000
        self.assertAlmostEqual(sf_val.get(), 1000.0, places=6)


    # ────────────────────────────────────────────────────────────────
    # New: Identity and Truthiness
    # ────────────────────────────────────────────────────────────────
    def test_identity_with_zero_and_negative_zero(self):
        # Python floats treat 0.0 and -0.0 as equal, but not identical.
        # SyncFloat should follow this.
        f_pos_zero = SyncFloat(0.0)
        f_neg_zero = SyncFloat(-0.0)
        self.assertEqual(f_pos_zero.get(), f_neg_zero.get())
        # self.assertIs not applicable to values, but to objects.
        # Check behavior when retrieving values.
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

    # ────────────────────────────────────────────────────────────────
    # Test for `_coerce` method if it's public/part of the API
    # ────────────────────────────────────────────────────────────────
    def test_coerce_method_functionality(self):
        # Assuming _coerce is intended for internal use but can be tested
        self.assertEqual(SyncFloat._coerce(10), 10.0)
        self.assertEqual(SyncFloat._coerce("3.14"), 3.14)
        self.assertEqual(SyncFloat._coerce(True), 1.0)
        self.assertEqual(SyncFloat._coerce(Decimal("2.7")), 2.7)
        with self.assertRaises(ValueError):
            SyncFloat._coerce("not a number")

    # ────────────────────────────────────────────────────────────────
    # More comprehensive test for `hex()` and `fromhex()`
    # ────────────────────────────────────────────────────────────────
    def test_hex_fromhex_accuracy_and_edge_cases(self):
        test_values = [
            0.0,
            1.0,
            -1.0,
            0.5,
            -0.5,
            123.456,
            -123.456,
            float('inf'),
            float('-inf'),
            float('nan'),
            2.2250738585072014e-308, # Smallest normal positive float
            1.7976931348623157e+308  # Largest finite float
        ]
        for val in test_values:
            with self.subTest(value=val):
                sf = SyncFloat(val)
                hex_str = sf.hex()
                # Special handling for NaN, as NaN == NaN is False
                if math.isnan(val):
                    self.assertTrue(math.isnan(SyncFloat.fromhex(hex_str).get()))
                else:
                    self.assertEqual(SyncFloat.fromhex(hex_str).get(), val)

    # ────────────────────────────────────────────────────────────────
    # New Section: Expanded Math Module Integrations
    # ────────────────────────────────────────────────────────────────
    def test_math_fmod(self):
        f = SyncFloat(10.5)
        # fmod(a, b) is float remainder x such that a == n*b + x, for some integer n.
        # Sign of x is same as sign of a.
        self.assertAlmostEqual(math.fmod(f, 3.0), 1.5)
        self.assertAlmostEqual(math.fmod(f, -3.0), 1.5)

        f_neg = SyncFloat(-10.5)
        self.assertAlmostEqual(math.fmod(f_neg, 3.0), -1.5)
        self.assertAlmostEqual(math.fmod(f_neg, -3.0), -1.5)

        # Test with SyncInt
        self.assertAlmostEqual(math.fmod(f, SyncInt(3)), 1.5)

    def test_math_copysign(self):
        f = SyncFloat(5.0)
        # copysign(x, y) returns x with the sign of y
        self.assertEqual(math.copysign(f, -1.0), -5.0)
        self.assertEqual(math.copysign(f, SyncFloat(-0.0)), -5.0)
        self.assertEqual(math.copysign(SyncFloat(-5.0), 1.0), 5.0)
        self.assertEqual(math.copysign(SyncFloat(0.0), -1.0), -0.0) # Check negative zero

    def test_math_frexp_ldexp(self):
        f = SyncFloat(12.5)
        mantissa, exponent = math.frexp(f)
        self.assertEqual(mantissa, 0.78125)
        self.assertEqual(exponent, 4)

        # Test ldexp to reconstruct
        self.assertEqual(math.ldexp(mantissa, exponent), 12.5)
        self.assertEqual(math.ldexp(SyncFloat(mantissa), exponent), 12.5)
        self.assertEqual(math.ldexp(mantissa, int(SyncInt(exponent))), 12.5)

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
        # sum() works on iterables, so direct SyncFloat objects can't be summed
        # but a list of SyncFloats should be sum-able.
        sf_list = [SyncFloat(1.0), SyncFloat(2.0), SyncFloat(3.0)]
        self.assertEqual(sum(sf_list), 6.0) # Sum calls __float__ on elements

    # ────────────────────────────────────────────────────────────────
    # New Section: Advanced Inf/NaN Arithmetic
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
        self.assertTrue(math.isnan(pinf - pinf)) # inf - inf is NaN
        self.assertTrue(math.isnan(pinf / pinf)) # inf / inf is NaN
        self.assertEqual(pinf * ninf, float('-inf')) # inf * -inf is -inf, wait... no.
        # This one is tricky: `inf * -inf` should be `-inf`. Let's correct the expectation.
        self.assertEqual(pinf * ninf, float('-inf'))

        self.assertTrue(math.isnan(pinf * SyncFloat(0.0))) # inf * 0 is NaN
        self.assertTrue(math.isnan(ninf * SyncFloat(0.0))) # -inf * 0 is NaN

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

    def test_inf_mod_behavior(self):
        pinf = SyncFloat(float('inf'))
        ninf = SyncFloat(float('-inf'))
        normal = SyncFloat(5.0)
        zero_sf = SyncFloat(0.0)

        self.assertTrue(math.isnan(pinf % normal)) # inf % x is NaN
        self.assertTrue(math.isnan(ninf % normal)) # -inf % x is NaN
        with self.assertRaises(ZeroDivisionError):
                 _ = normal % zero_sf

    # ────────────────────────────────────────────────────────────────
    # New Section: Chained & Complex Operations
    # ────────────────────────────────────────────────────────────────
    def test_chained_arithmetic_ops(self):
        a, b, c = SyncFloat(10.0), SyncFloat(2.0), SyncFloat(3.0)
        self.assertEqual(a + b * c, 10.0 + 2.0 * 3.0) # 16.0
        self.assertEqual((a + b) * c, (10.0 + 2.0) * 3.0) # 36.0
        self.assertAlmostEqual(a / b + c, 10.0 / 2.0 + 3.0) # 8.0
        self.assertAlmostEqual(a / (b + c), 10.0 / (2.0 + 3.0)) # 2.0
        self.assertAlmostEqual(a ** b / c, 10.0 ** 2.0 / 3.0) # 100 / 3 = 33.33...

    def test_complex_expression_with_mixed_types(self):
        f = SyncFloat(4.0)
        i = SyncInt(2)
        b = SyncBool(True) # 1.0

        result = (f + i) * b / f
        expected = (4.0 + 2.0) * 1.0 / 4.0 # (6.0) * 1.0 / 4.0 = 1.5
        self.assertAlmostEqual(result, expected)

        result_2 = (f ** i) - (b * 10)
        expected_2 = (4.0 ** 2.0) - (1.0 * 10) # 16.0 - 10.0 = 6.0
        self.assertAlmostEqual(result_2, expected_2)

    # ────────────────────────────────────────────────────────────────
    # New Section: Negative Zero Behavior
    # ────────────────────────────────────────────────────────────────
    def test_negative_zero_in_division(self):
        with self.assertRaises(ZeroDivisionError):
            _ = SyncFloat(1.0) / SyncFloat(-0.0)
        with self.assertRaises(ZeroDivisionError):
            _ = SyncFloat(1.0) / -0.0

    def test_negative_zero_copysign(self):
        self.assertEqual(math.copysign(1.0, SyncFloat(-0.0)), -1.0)
        self.assertEqual(math.copysign(SyncFloat(1.0), -0.0), -1.0)
        self.assertEqual(math.copysign(SyncFloat(-5.0), SyncFloat(0.0)), 5.0)

    # ────────────────────────────────────────────────────────────────
    # New Section: Type Checking and Immutability
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
        # Should not be able to set new attributes due to __slots__
        with self.assertRaises(AttributeError):
            f.new_attr = 10
        # Existing attributes should be accessible
        self.assertEqual(f.get(), 1.0)

    def test_type_of_instance(self):
        f = SyncFloat(1.0)
        self.assertIsInstance(f, SyncFloat)
        self.assertTrue(issubclass(type(f), SyncFloat))
        self.assertIs(type(f), SyncFloat) # Specific type check

    # ────────────────────────────────────────────────────────────────
    # New Section: More Rounding Details
    # ────────────────────────────────────────────────────────────────
    def test_round_with_negative_ndigits(self):
        f = SyncFloat(12345.678)
        self.assertEqual(round(f, -1), 12350.0)
        self.assertEqual(round(f, -2), 12300.0)
        self.assertEqual(round(f, -3), 12000.0)

    def test_round_half_to_even_behavior(self):
        # Python's round() uses round half to even for .5
        self.assertEqual(round(SyncFloat(2.5)), 2)
        self.assertEqual(round(SyncFloat(3.5)), 4)
        self.assertEqual(round(SyncFloat(2.125), 2), 2.12) # Original behavior
        self.assertEqual(round(SyncFloat(2.135), 2), 2.13)

    # ────────────────────────────────────────────────────────────────
    # New Section: Bitwise Operations (Negative Tests - Expect TypeError)
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
    # New Section: More Concurrent Scenarios
    # ────────────────────────────────────────────────────────────────
    def test_concurrent_get_only(self):
        f = SyncFloat(100.0)
        read_values = []
        read_lock = threading.Lock()

        def reader_worker():
            for _ in range(1000):
                with read_lock: # Protect appending to shared list
                    read_values.append(f.get())

        _spawn_threads(reader_worker, num_threads=10)
        # All values should be the initial 100.0, as no modifications happen
        self.assertTrue(all(val == 100.0 for val in read_values))
        self.assertEqual(len(read_values), 10 * 1000)

    def test_concurrent_increment_mixed_sync_float_and_raw_float(self):
        counter = SyncFloat(0.0)
        increment_amount = SyncFloat(0.01) # Use a SyncFloat for some increments

        def worker_raw_float():
            for _ in range(500):
                counter.increment(0.02) # Raw float increment

        def worker_sync_float():
            for _ in range(500):
                counter.increment(increment_amount) # SyncFloat increment

        t1 = threading.Thread(target=worker_raw_float)
        t2 = threading.Thread(target=worker_sync_float)
        t1.start(); t2.start()
        t1.join(); t2.join()

        # Total increments: (500 * 0.02) + (500 * 0.01) = 10.0 + 5.0 = 15.0
        self.assertAlmostEqual(counter.get(), 15.0, places=6)
    def test_div_zero_raises(self):
        with self.assertRaises(ZeroDivisionError):
            _ = SyncFloat(5.0) / SyncFloat(0.0)
        with self.assertRaises(ZeroDivisionError):
            _ = SyncFloat(5.0) % SyncFloat(0.0)

    # ────────────────────────────────────────────────────────────
    # 2.  inf × -inf  →  -inf   (IEEE-754)
    # ────────────────────────────────────────────────────────────
    def test_inf_times_neg_inf(self):
        pinf = SyncFloat(float('inf'))
        ninf = SyncFloat(float('-inf'))
        self.assertEqual(pinf * ninf, float('-inf'))

    # ────────────────────────────────────────────────────────────
    # 3.  Binary “round half to even” example
    # ────────────────────────────────────────────────────────────
    def test_round_half_to_even(self):
        self.assertEqual(round(SyncFloat(2.135), 2), 2.13)   # 2.135 → 2.13

    # ────────────────────────────────────────────────────────────
    # 4.  math.ldexp requires a *plain* int for argument 2
    # ────────────────────────────────────────────────────────────
    def test_math_ldexp_with_sync_int(self):
        mantissa, exponent = 0.78125, 4          # 12.5 split
        self.assertEqual(
            math.ldexp(mantissa, int(SyncInt(exponent))),
            12.5
        )

    # ────────────────────────────────────────────────────────────
    # 5. float * SyncBool behaves like float * bool  (no error)
    # ────────────────────────────────────────────────────────────
    def test_float_times_syncbool(self):
        self.assertEqual(3.0 * SyncBool(True), 3.0)
        self.assertEqual(3.0 * SyncBool(False), 0.0)

    # ────────────────────────────────────────────────────────────
    # 6.  Pickling must ignore the internal RLock
    # ────────────────────────────────────────────────────────────
    def test_pickling_roundtrip(self):
        original = SyncFloat(42.0)
        pickled  = pickle.dumps(original)     # should not raise
        clone    = pickle.loads(pickled)
        self.assertIsInstance(clone, SyncFloat)
        self.assertEqual(clone.get(), 42.0)
        self.assertIsNot(clone, original)     # new instance


    def test_concurrent_set_from_different_threads(self):
        # This test is intentionally non-deterministic for the final value,
        # but verifies that concurrent sets complete without errors.
        f = SyncFloat(0.0)
        values_to_set = [float(i) for i in range(10)] # Values from 0.0 to 9.0
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
        # The final value should be one of the values that were attempted to be set.
        self.assertIn(final_value, values_to_set)
        # Ensure it's finite (not NaN/Inf)
        self.assertTrue(math.isfinite(final_value))

    # ────────────────────────────────────────────────────────────────
    # Test for `_coerce` method if it's public/part of the API (repeated from previous, good to keep)
    # ────────────────────────────────────────────────────────────────
    # def test_coerce_method_functionality(self):
    #     self.assertEqual(SyncFloat._coerce(10), 10.0)
    #     self.assertEqual(SyncFloat._coerce("3.14"), 3.14)
    #     self.assertEqual(SyncFloat._coerce(True), 1.0)
    #     self.assertEqual(SyncFloat._coerce(Decimal("2.7")), 2.7)
    #     with self.assertRaises(ValueError):
    #         SyncFloat._coerce("not a number")


if __name__ == "__main__":
    unittest.main(argv=['first-arg-is-ignored'], exit=False)