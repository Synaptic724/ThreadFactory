import unittest
import threading
import time

from thread_factory.concurrency.value_types.sync_int import SyncInt


# Assuming the SyncInt class provided is in a file named sync_int.py
# from sync_int import SyncInt

# For self-contained execution, the class is included here directly.
# PASTE THE ENTIRE CORRECTED SyncInt CLASS DEFINITION HERE
# from the section above.


class TestSyncInt(unittest.TestCase):

    # __init__
    def test_init_default(self):
        s_int = SyncInt()
        self.assertEqual(s_int.get(), 0)

    def test_init_with_value(self):
        s_int = SyncInt(123)
        self.assertEqual(s_int.get(), 123)

    # get
    def test_get_positive(self):
        s_int = SyncInt(42)
        self.assertEqual(s_int.get(), 42)

    def test_get_negative(self):
        s_int = SyncInt(-99)
        self.assertEqual(s_int.get(), -99)

    # set
    def test_set_value(self):
        s_int = SyncInt(10)
        s_int.set(20)
        self.assertEqual(s_int.get(), 20)

    def test_set_from_float(self):
        s_int = SyncInt(10)
        s_int.set(99.9)
        self.assertEqual(s_int.get(), 99)

    # as_integer_ratio
    def test_as_integer_ratio_positive(self):
        s_int = SyncInt(15)
        self.assertEqual(s_int.as_integer_ratio(), (15, 1))

    def test_as_integer_ratio_zero(self):
        s_int = SyncInt(0)
        self.assertEqual(s_int.as_integer_ratio(), (0, 1))

    # bit_count
    def test_bit_count_positive(self):
        s_int = SyncInt(13)  # 1101
        self.assertEqual(s_int.bit_count(), 3)

    def test_bit_count_negative(self):
        s_int = SyncInt(-13)  # should be same as positive
        self.assertEqual(s_int.bit_count(), 3)

    # bit_length
    def test_bit_length_positive(self):
        s_int = SyncInt(37)  # 100101
        self.assertEqual(s_int.bit_length(), 6)

    def test_bit_length_zero(self):
        s_int = SyncInt(0)
        self.assertEqual(s_int.bit_length(), 0)

    # conjugate
    def test_conjugate_positive(self):
        s_int = SyncInt(10)
        self.assertEqual(s_int.conjugate(), 10)

    def test_conjugate_negative(self):
        s_int = SyncInt(-5)
        self.assertEqual(s_int.conjugate(), -5)

    # from_bytes
    def test_from_bytes_big_endian(self):
        s_int = SyncInt.from_bytes(b'\x00\x10', 'big')
        self.assertEqual(s_int, 16)

    def test_from_bytes_little_endian_signed(self):
        s_int = SyncInt.from_bytes(b'\xff\xff', 'little', signed=True)
        self.assertEqual(s_int, -1)

    # to_bytes
    def test_to_bytes_big_endian(self):
        s_int = SyncInt(16)
        self.assertEqual(s_int.to_bytes(2, 'big'), b'\x00\x10')

    def test_to_bytes_little_endian_signed(self):
        s_int = SyncInt(-2)
        self.assertEqual(s_int.to_bytes(2, 'little', signed=True), b'\xfe\xff')

    # __abs__
    def test_abs_negative(self):
        s_int = SyncInt(-10)
        self.assertEqual(abs(s_int), 10)

    def test_abs_positive(self):
        s_int = SyncInt(10)
        self.assertEqual(abs(s_int), 10)

    # __add__
    def test_add_int(self):
        s_int = SyncInt(10)
        self.assertEqual(s_int + 5, 15)

    def test_add_negative(self):
        s_int = SyncInt(-10)
        self.assertEqual(s_int + 5, -5)

    def test_add_syncint(self):
        s_int1 = SyncInt(10)
        s_int2 = SyncInt(5)
        self.assertEqual(s_int1 + s_int2, 15)

    def test_add_mixed_order(self):
        s_int = SyncInt(10)
        self.assertEqual(5 + s_int, 15) # Should call __radd__

    # __and__
    def test_and_basic(self):
        s_int = SyncInt(12)  # 1100
        self.assertEqual(s_int & 10, 8)  # 1010 -> 1000

    def test_and_all_bits(self):
        s_int = SyncInt(7)  # 0111
        self.assertEqual(s_int & 7, 7)

    def test_and_syncint(self):
        s_int1 = SyncInt(12) # 1100
        s_int2 = SyncInt(10) # 1010
        self.assertEqual(s_int1 & s_int2, 8) # 1000

    def test_and_mixed_order(self):
        s_int = SyncInt(12) # 1100
        self.assertEqual(10 & s_int, 8) # 1010 & 1100 -> 1000

    # __bool__
    def test_bool_true(self):
        s_int = SyncInt(1)
        self.assertTrue(bool(s_int))

    def test_bool_false(self):
        s_int = SyncInt(0)
        self.assertFalse(bool(s_int))

    # __ceil__
    def test_ceil_positive(self):
        s_int = SyncInt(10)
        self.assertEqual(s_int.__ceil__(), 10)

    def test_ceil_negative(self):
        s_int = SyncInt(-10)
        self.assertEqual(s_int.__ceil__(), -10)

    # __divmod__
    def test_divmod_basic(self):
        s_int = SyncInt(10)
        self.assertEqual(divmod(s_int, 3), (3, 1))

    def test_divmod_negative(self):
        s_int = SyncInt(-10)
        self.assertEqual(divmod(s_int, 3), (-4, 2))

    def test_divmod_syncint(self):
        s_int1 = SyncInt(10)
        s_int2 = SyncInt(3)
        self.assertEqual(divmod(s_int1, s_int2), (3, 1))

    def test_divmod_mixed_order(self):
        s_int = SyncInt(3)
        self.assertEqual(divmod(10, s_int), (3, 1)) # Should call __rdivmod__


    # __eq__
    def test_eq_true(self):
        s_int1 = SyncInt(10)
        s_int2 = SyncInt(10)
        self.assertTrue(s_int1 == 10)
        self.assertTrue(s_int1 == s_int2)

    def test_eq_false(self):
        s_int = SyncInt(10)
        self.assertFalse(s_int == 11)

    # __float__
    def test_float_conversion(self):
        s_int = SyncInt(5)
        self.assertAlmostEqual(float(s_int), 5.0)

    def test_float_conversion_zero(self):
        s_int = SyncInt(0)
        self.assertAlmostEqual(float(s_int), 0.0)

    # __floordiv__
    def test_floordiv_basic(self):
        s_int = SyncInt(10)
        self.assertEqual(s_int // 3, 3)

    def test_floordiv_negative(self):
        s_int = SyncInt(-10)
        self.assertEqual(s_int // 3, -4)

    def test_floordiv_syncint(self):
        s_int1 = SyncInt(10)
        s_int2 = SyncInt(3)
        self.assertEqual(s_int1 // s_int2, 3)

    def test_floordiv_mixed_order(self):
        s_int = SyncInt(3)
        self.assertEqual(10 // s_int, 3) # Should call __rfloordiv__

    # __floor__
    def test_floor_positive(self):
        s_int = SyncInt(20)
        self.assertEqual(s_int.__floor__(), 20)

    def test_floor_negative(self):
        s_int = SyncInt(-20)
        self.assertEqual(s_int.__floor__(), -20)

    # __format__
    def test_format_hex(self):
        s_int = SyncInt(255)
        self.assertEqual(format(s_int, 'x'), 'ff')

    def test_format_binary(self):
        s_int = SyncInt(10)
        self.assertEqual(format(s_int, 'b'), '1010')

    # __ge__
    def test_ge_true(self):
        s_int = SyncInt(10)
        self.assertTrue(s_int >= 10)
        self.assertTrue(s_int >= 9)

    def test_ge_false(self):
        s_int = SyncInt(10)
        self.assertFalse(s_int >= 11)

    def test_ge_syncint(self):
        s_int1 = SyncInt(10)
        s_int2 = SyncInt(10)
        s_int3 = SyncInt(9)
        self.assertTrue(s_int1 >= s_int2)
        self.assertTrue(s_int1 >= s_int3)
        self.assertFalse(s_int3 >= s_int1)

    # __gt__
    def test_gt_true(self):
        s_int = SyncInt(10)
        self.assertTrue(s_int > 9)

    def test_gt_false(self):
        s_int = SyncInt(10)
        self.assertFalse(s_int > 10)

    def test_gt_syncint(self):
        s_int1 = SyncInt(10)
        s_int2 = SyncInt(9)
        self.assertTrue(s_int1 > s_int2)
        self.assertFalse(s_int2 > s_int1)


    # __hash__
    def test_hash_value(self):
        s_int = SyncInt(42)
        self.assertEqual(hash(s_int), hash(42))

    def test_hash_consistency(self):
        s_int1 = SyncInt(-1)
        s_int2 = SyncInt(-1)
        self.assertEqual(hash(s_int1), hash(s_int2))

    # __index__
    def test_index_as_slice(self):
        s_int = SyncInt(2)
        data = [10, 20, 30, 40]
        self.assertEqual(data[s_int], 30)

    def test_index_negative(self):
        s_int = SyncInt(-1)
        data = [10, 20, 30, 40]
        self.assertEqual(data[s_int], 40)

    # __invert__
    def test_invert_basic(self):
        s_int = SyncInt(10)  # ...01010
        self.assertEqual(~s_int, -11)  # ...10101

    def test_invert_all_bits_set(self):
        s_int = SyncInt(-1)
        self.assertEqual(~s_int, 0)

    # __le__
    def test_le_true(self):
        s_int = SyncInt(10)
        self.assertTrue(s_int <= 10)
        self.assertTrue(s_int <= 11)

    def test_le_false(self):
        s_int = SyncInt(10)
        self.assertFalse(s_int <= 9)

    def test_le_syncint(self):
        s_int1 = SyncInt(10)
        s_int2 = SyncInt(10)
        s_int3 = SyncInt(11)
        self.assertTrue(s_int1 <= s_int2)
        self.assertTrue(s_int1 <= s_int3)
        self.assertFalse(s_int3 <= s_int1)

    # __lshift__
    def test_lshift_basic(self):
        s_int = SyncInt(5)  # 101
        self.assertEqual(s_int << 2, 20)  # 10100

    def test_lshift_by_zero(self):
        s_int = SyncInt(10)
        self.assertEqual(s_int << 0, 10)

    def test_lshift_syncint(self):
        s_int1 = SyncInt(5)
        s_int2 = SyncInt(2)
        self.assertEqual(s_int1 << s_int2, 20)

    def test_lshift_mixed_order(self):
        s_int = SyncInt(2)
        self.assertEqual(5 << s_int, 20) # Should call __rlshift__


    # __lt__
    def test_lt_true(self):
        s_int = SyncInt(10)
        self.assertTrue(s_int < 11)

    def test_lt_false(self):
        s_int = SyncInt(10)
        self.assertFalse(s_int < 10)

    def test_lt_syncint(self):
        s_int1 = SyncInt(10)
        s_int2 = SyncInt(11)
        self.assertTrue(s_int1 < s_int2)
        self.assertFalse(s_int2 < s_int1)


    # __mod__
    def test_mod_basic(self):
        s_int = SyncInt(10)
        self.assertEqual(s_int % 3, 1)

    def test_mod_negative(self):
        s_int = SyncInt(-10)
        self.assertEqual(s_int % 3, 2)

    def test_mod_syncint(self):
        s_int1 = SyncInt(10)
        s_int2 = SyncInt(3)
        self.assertEqual(s_int1 % s_int2, 1)

    def test_mod_mixed_order(self):
        s_int = SyncInt(3)
        self.assertEqual(10 % s_int, 1) # Should call __rmod__

    # __mul__
    def test_mul_positive(self):
        s_int = SyncInt(10)
        self.assertEqual(s_int * 5, 50)

    def test_mul_by_zero(self):
        s_int = SyncInt(10)
        self.assertEqual(s_int * 0, 0)

    def test_mul_syncint(self):
        s_int1 = SyncInt(4)
        s_int2 = SyncInt(3)
        self.assertEqual(s_int1 * s_int2, 12)

    def test_mul_mixed_order(self):
        s_int = SyncInt(4)
        self.assertEqual(3 * s_int, 12) # Should call __rmul__


    # __neg__
    def test_neg_positive(self):
        s_int = SyncInt(10)
        self.assertEqual(-s_int, -10)

    def test_neg_negative(self):
        s_int = SyncInt(-10)
        self.assertEqual(-s_int, 10)

    # __pos__
    def test_pos_positive(self):
        s_int = SyncInt(5)
        self.assertEqual(+s_int, 5)

    def test_pos_negative(self):
        s_int = SyncInt(-5)
        self.assertEqual(+s_int, -5)

    # ====================================================================
    # IMPORTANT: REVISED POW TESTS TO ALIGN WITH DISPATCH RULES AND safe_pow
    # ====================================================================

    # __pow__ (SyncInt as base)
    def test_pow_syncint_int(self):
        # SyncInt base, int exponent, no modulo. Python dispatches to SyncInt.__pow__.
        s_int_base = SyncInt(2)
        self.assertEqual(s_int_base ** 3, 8)
        self.assertEqual(pow(s_int_base, 3), 8) # Equivalent to s_int_base.__pow__(3)

    def test_pow_syncint_syncint(self):
        # SyncInt base, SyncInt exponent, no modulo. Python dispatches to SyncInt.__pow__.
        s_int_base = SyncInt(2)
        s_int_exp = SyncInt(3)
        self.assertEqual(s_int_base ** s_int_exp, 8)
        self.assertEqual(pow(s_int_base, s_int_exp), 8) # Equivalent to s_int_base.__pow__(s_int_exp)

    def test_pow_syncint_int_mod_int(self):
        # SyncInt base, int exponent, int modulo. Python dispatches to SyncInt.__pow__.
        s_int_base = SyncInt(3)
        self.assertEqual(pow(s_int_base, 3, 4), 3) # 3**3 % 4 = 27 % 4 = 3

    def test_pow_syncint_syncint_mod_int(self):
        # SyncInt base, SyncInt exponent, int modulo. Python dispatches to SyncInt.__pow__.
        s_int_base = SyncInt(3)
        s_int_exp = SyncInt(3)
        self.assertEqual(pow(s_int_base, s_int_exp, 4), 3)

    def test_pow_syncint_int_mod_syncint(self):
        # SyncInt base, int exponent, SyncInt modulo. Python dispatches to SyncInt.__pow__.
        s_int_base = SyncInt(3)
        s_int_mod = SyncInt(4)
        self.assertEqual(pow(s_int_base, 3, s_int_mod), 3)

    def test_pow_syncint_syncint_mod_syncint(self):
        # All SyncInts. Python dispatches to SyncInt.__pow__.
        s_int_base = SyncInt(3)
        s_int_exp = SyncInt(3)
        s_int_mod = SyncInt(4)
        self.assertEqual(pow(s_int_base, s_int_exp, s_int_mod), 3)

    # __rpow__ (SyncInt as exponent)
    def test_rpow_int_syncint(self):
        # int base, SyncInt exponent, no modulo. Python dispatches to int.__pow__ first,
        # which returns NotImplemented, then SyncInt.__rpow__ is called.
        s_int_exp = SyncInt(3)
        self.assertEqual(2 ** s_int_exp, 8)
        self.assertEqual(pow(2, s_int_exp), 8) # This *should* work via __rpow__ as well.


    # Ternary pow involving native int as base and SyncInts as other operands
    # These cases will FAIL with direct `pow()` call due to dispatch rules.
    # They MUST use `SyncInt.safe_pow()`.
    def test_safe_pow_int_syncint_mod_int(self):
        # int base, SyncInt exp, int mod. Direct `pow()` fails. Use `safe_pow`.
        s_int_exp = SyncInt(3)
        self.assertEqual(SyncInt.safe_pow(3, s_int_exp, 4), 3) # 3**3 % 4 = 27 % 4 = 3

    def test_safe_pow_int_int_mod_syncint(self):
        # int base, int exp, SyncInt mod. Direct `pow()` fails. Use `safe_pow`.
        s_int_mod = SyncInt(4)
        self.assertEqual(SyncInt.safe_pow(3, 3, s_int_mod), 3) # 3**3 % 4 = 27 % 4 = 3

    def test_safe_pow_int_syncint_mod_syncint(self):
        # int base, SyncInt exp, SyncInt mod. Direct `pow()` fails. Use `safe_pow`.
        s_int_exp = SyncInt(3)
        s_int_mod = SyncInt(4)
        self.assertEqual(SyncInt.safe_pow(3, s_int_exp, s_int_mod), 3)

    # Other edge cases for power
    def test_pow_negative_base(self):
        s_int_base = SyncInt(-2)
        s_int_exp = SyncInt(3)
        self.assertEqual(s_int_base ** s_int_exp, -8)

    def test_pow_zero_exponent(self):
        s_int_base = SyncInt(10)
        s_int_exp = SyncInt(0)
        self.assertEqual(s_int_base ** s_int_exp, 1)
        self.assertEqual(pow(s_int_base, 0), 1)

    def test_pow_zero_base(self):
        s_int_base = SyncInt(0)
        s_int_exp = SyncInt(5)
        self.assertEqual(s_int_base ** s_int_exp, 0)
        self.assertEqual(pow(s_int_base, 5), 0)

    # Concurrency test for power operations (now always using safe_pow)
    def _pow_worker(self, base, exp, mod, results):
        try:
            val = SyncInt.safe_pow(base, exp, mod) # Use safe_pow here!
            results.append(val)
        except Exception as e:
            results.append(f"Error: {e}")

    def test_pow_thread_safety(self):
        s_int_base = SyncInt(2)
        s_int_exp = SyncInt(10)
        s_int_mod = SyncInt(100)

        results = []
        threads = []

        pow_calls = [
            (s_int_base, s_int_exp, None),
            (2, s_int_exp, None), # Requires safe_pow if int is first operand
            (s_int_base, 10, None),
            (s_int_base, s_int_exp, s_int_mod),
            (2, s_int_exp, 100), # Requires safe_pow if int is first operand
            (s_int_base, 10, s_int_mod),
            (2, 10, s_int_mod), # Requires safe_pow if int is first operand
            (s_int_base, 10, 100),
            (SyncInt(5), SyncInt(2), SyncInt(7)), # all SyncInts
            (5, SyncInt(2), 7),                  # mixed types (int base, SyncInt exp, int mod)
            (SyncInt(5), 2, 7),                  # mixed types (SyncInt base, int exp, int mod)
            (5, 2, SyncInt(7)),                  # mixed types (int base, int exp, SyncInt mod)
        ]

        num_iterations = 5 # Run each combination multiple times
        for _ in range(num_iterations):
            for i, (base, exp, mod) in enumerate(pow_calls):
                t = threading.Thread(target=self._pow_worker, args=(base, exp, mod, results))
                threads.append(t)
                t.start()
                # Optional: small delay to encourage thread interleaving, though not strictly needed for RLock
                # time.sleep(0.0001)

        for t in threads:
            t.join()

        # Define expected values for each call type
        expected_values_template = [
            pow(2, 10),                     # (s_int_base, s_int_exp, None)
            pow(2, 10),                     # (2, s_int_exp, None) - Handled by safe_pow
            pow(2, 10),                     # (s_int_base, 10, None)
            pow(2, 10, 100),                # (s_int_base, s_int_exp, s_int_mod)
            pow(2, 10, 100),                # (2, s_int_exp, 100) - Handled by safe_pow
            pow(2, 10, 100),                # (s_int_base, 10, s_int_mod)
            pow(2, 10, 100),                # (2, 10, s_int_mod) - Handled by safe_pow
            pow(2, 10, 100),                # (s_int_base, 10, 100)
            pow(5, 2, 7),                   # (SyncInt(5), SyncInt(2), SyncInt(7))
            pow(5, 2, 7),                   # (5, SyncInt(2), 7) - Handled by safe_pow
            pow(5, 2, 7),                   # (SyncInt(5), 2, 7)
            pow(5, 2, 7),                   # (5, 2, SyncInt(7)) - Handled by safe_pow
        ]

        expected_total_results = expected_values_template * num_iterations

        self.assertFalse(any("Error" in str(r) for r in results), f"Errors found in results: {results}")

        # Sort results and expected_total_results for reliable comparison
        results.sort()
        expected_total_results.sort()

        self.assertEqual(results, expected_total_results, "Mismatch in expected and actual results.")

    # __rrshift__
    def test_rrshift_basic(self):
        s_int = SyncInt(2)
        self.assertEqual(20 >> s_int, 5)

    def test_rrshift_by_one(self):
        s_int = SyncInt(1)
        self.assertEqual(10 >> s_int, 5)

    # __rshift__
    def test_rshift_basic(self):
        s_int = SyncInt(20)  # 10100
        self.assertEqual(s_int >> 2, 5)  # 101

    def test_rshift_by_zero(self):
        s_int = SyncInt(15)
        self.assertEqual(s_int >> 0, 15)

    # __rsub__
    def test_rsub_int(self):
        s_int = SyncInt(10)
        self.assertEqual(15 - s_int, 5)

    def test_rsub_negative_result(self):
        s_int = SyncInt(10)
        self.assertEqual(5 - s_int, -5)

    # __rtruediv__
    def test_rtruediv_basic(self):
        s_int = SyncInt(4)
        self.assertAlmostEqual(10 / s_int, 2.5)

    def test_rtruediv_result_less_than_one(self):
        s_int = SyncInt(5)
        self.assertAlmostEqual(2 / s_int, 0.4)

    # __rxor__
    def test_rxor_basic(self):
        s_int = SyncInt(12)  # 1100
        self.assertEqual(10 ^ s_int, 6)  # 1010 ^ 1100 -> 0110

    def test_rxor_identity(self):
        s_int = SyncInt(42)
        self.assertEqual(0 ^ s_int, 42)

    # __sizeof__
    def test_sizeof_value(self):
        val = 100
        s_int = SyncInt(val)
        self.assertEqual(s_int.__sizeof__(), val.__sizeof__())

    def test_sizeof_large_value(self):
        val = 123456789123456789
        s_int = SyncInt(val)
        self.assertEqual(s_int.__sizeof__(), val.__sizeof__())

    # __sub__
    def test_sub_int(self):
        s_int = SyncInt(10)
        self.assertEqual(s_int - 5, 5)

    def test_sub_negative(self):
        s_int = SyncInt(10)
        self.assertEqual(s_int - 15, -5)

    # __truediv__
    def test_truediv_basic(self):
        s_int = SyncInt(10)
        self.assertAlmostEqual(s_int / 4, 2.5)

    def test_truediv_result_less_than_one(self):
        s_int = SyncInt(2)
        self.assertAlmostEqual(s_int / 5, 0.4)

    # __trunc__
    def test_trunc_positive(self):
        s_int = SyncInt(15)
        self.assertEqual(s_int.__trunc__(), 15)

    def test_trunc_negative(self):
        s_int = SyncInt(-15)
        self.assertEqual(s_int.__trunc__(), -15)

    # __xor__
    def test_xor_basic(self):
        s_int = SyncInt(12)  # 1100
        self.assertEqual(s_int ^ 10, 6)  # 1100 ^ 1010 -> 0110

    def test_xor_identity(self):
        s_int = SyncInt(42)
        self.assertEqual(s_int ^ 0, 42)

    # numerator
    def test_numerator_positive(self):
        s_int = SyncInt(5)
        self.assertEqual(s_int.numerator, 5)

    def test_numerator_negative(self):
        s_int = SyncInt(-5)
        self.assertEqual(s_int.numerator, -5)

    # denominator
    def test_denominator_positive(self):
        s_int = SyncInt(10)
        self.assertEqual(s_int.denominator, 1)

    def test_denominator_negative(self):
        s_int = SyncInt(-10)
        self.assertEqual(s_int.denominator, 1)

    # real
    def test_real_positive(self):
        s_int = SyncInt(7)
        self.assertEqual(s_int.real, 7)

    def test_real_negative(self):
        s_int = SyncInt(-7)
        self.assertEqual(s_int.real, -7)

    # imag
    def test_imag_positive(self):
        s_int = SyncInt(8)
        self.assertEqual(s_int.imag, 0)

    def test_imag_negative(self):
        s_int = SyncInt(-8)
        self.assertEqual(s_int.imag, 0)

    # is_integer
    def test_is_integer_positive(self):
        s_int = SyncInt(1)
        self.assertTrue(s_int.is_integer())

    def test_is_integer_zero(self):
        s_int = SyncInt(0)
        self.assertTrue(s_int.is_integer())

    # __getattribute__
    def test_getattribute_internal(self):
        s_int = SyncInt(10)
        # Note: Direct access is not typical, but tests the method
        self.assertEqual(object.__getattribute__(s_int, '_value'), 10)

    def test_getattribute_method(self):
        s_int = SyncInt(10)
        self.assertTrue(callable(object.__getattribute__(s_int, 'get')))

    # __getnewargs__
    def test_getnewargs_positive(self):
        s_int = SyncInt(123)
        self.assertEqual(s_int.__getnewargs__(), (123,))

    def test_getnewargs_negative(self):
        s_int = SyncInt(-45)
        self.assertEqual(s_int.__getnewargs__(), (-45,))

    # __int__
    def test_int_conversion(self):
        s_int = SyncInt(42)
        self.assertEqual(int(s_int), 42)

    def test_int_conversion_negative(self):
        s_int = SyncInt(-100)
        self.assertEqual(int(s_int), -100)

    # __new__
    def test_new_instance(self):
        s_int = SyncInt.__new__(SyncInt)
        self.assertIsInstance(s_int, SyncInt)

    def test_new_with_args(self):
        s_int = SyncInt.__new__(SyncInt, 10)
        self.assertIsInstance(s_int, SyncInt)

    # __ne__
    def test_ne_true(self):
        s_int1 = SyncInt(10)
        s_int2 = SyncInt(11)
        self.assertTrue(s_int1 != 11)
        self.assertTrue(s_int1 != s_int2)

    def test_ne_false(self):
        s_int = SyncInt(10)
        self.assertFalse(s_int != 10)


    # __repr__
    def test_repr_positive(self):
        s_int = SyncInt(50)
        self.assertEqual(repr(s_int), '50')

    def test_repr_negative(self):
        s_int = SyncInt(-120)
        self.assertEqual(repr(s_int), '-120')

    # === Concurrency Tests ===
    def _increment_worker(self, s_int, count):
        for _ in range(count):
            s_int.increment()

    def test_increment_default(self):
        s_int = SyncInt(10)
        s_int.increment()
        self.assertEqual(s_int.get(), 11)

    def test_decrement_with_value(self):
        s_int = SyncInt(10)
        s_int.decrement(5)
        self.assertEqual(s_int.get(), 5)

    def test_increment_with_syncint(self):
        s_int1 = SyncInt(100)
        s_int2 = SyncInt(50)
        s_int1.increment(s_int2)
        self.assertEqual(s_int1.get(), 150)

    def test_decrement_return_value(self):
        s_int = SyncInt(20)
        result = s_int.decrement(3)
        self.assertEqual(result, 17)
        self.assertEqual(s_int.get(), 17)

    def test_iadd_with_int(self):
        s_int = SyncInt(5)
        s_int += 10
        self.assertEqual(s_int.get(), 15)

    def test_iadd_with_syncint(self):
        s_int1 = SyncInt(20)
        s_int2 = SyncInt(22)
        s_int1 += s_int2
        self.assertEqual(s_int1.get(), 42)

    def test_isub_with_int(self):
        s_int = SyncInt(10)
        s_int -= 3
        self.assertEqual(s_int.get(), 7)

    def test_isub_with_syncint_negative(self):
        s_int1 = SyncInt(-10)
        s_int2 = SyncInt(5)
        s_int1 -= s_int2
        self.assertEqual(s_int1.get(), -15)

    def test_imul_with_int(self):
        s_int = SyncInt(7)
        s_int *= 3
        self.assertEqual(s_int.get(), 21)

    def test_imul_with_syncint(self):
        s_int1 = SyncInt(8)
        s_int2 = SyncInt(4)
        s_int1 *= s_int2
        self.assertEqual(s_int1.get(), 32)

    def test_ifloordiv_with_syncint(self):
        s_int1 = SyncInt(20)
        s_int2 = SyncInt(3)
        s_int1 //= s_int2
        self.assertEqual(s_int1.get(), 6)

    def test_imod_with_int(self):
        s_int = SyncInt(17)
        s_int %= 5
        self.assertEqual(s_int.get(), 2)

    def test_ipow_with_int(self):
        s_int = SyncInt(3)
        s_int **= 4
        self.assertEqual(s_int.get(), 81)

    def test_ilshift_with_syncint(self):
        s_int1 = SyncInt(5)  # 101
        s_int2 = SyncInt(2)
        s_int1 <<= s_int2
        self.assertEqual(s_int1.get(), 20)  # 10100

    def test_irshift_with_int(self):
        s_int = SyncInt(40)  # 101000
        s_int >>= 3
        self.assertEqual(s_int.get(), 5)  # 101

    def test_iand_with_syncint(self):
        s_int1 = SyncInt(12)  # 1100
        s_int2 = SyncInt(10)  # 1010
        s_int1 &= s_int2
        self.assertEqual(s_int1.get(), 8)  # 1000

    def test_ior_with_int(self):
        s_int = SyncInt(9)  # 1001
        s_int |= 5  # 0101
        self.assertEqual(s_int.get(), 13)  # 1101

    def test_ixor_with_syncint(self):
        s_int1 = SyncInt(15)  # 1111
        s_int2 = SyncInt(7)  # 0111
        s_int1 ^= s_int2
        self.assertEqual(s_int1.get(), 8)  # 1000

    def test_concurrent_iadd_and_isub(self):
        s1 = SyncInt(100)
        s2 = SyncInt(100)
        s3 = SyncInt(1)

        def worker1():
            nonlocal s1, s2, s3
            for _ in range(1000):
                s1 += s3
                s2 -= s3

        def worker2():
            nonlocal s1, s2, s3
            for _ in range(1000):
                s2 += s3
                s1 -= s3

        t1 = threading.Thread(target=worker1)
        t2 = threading.Thread(target=worker2)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # The operations should cancel each other out
        self.assertEqual(s1.get(), 100)
        self.assertEqual(s2.get(), 100)

    def test_ifloordiv_by_zero(self):
        s_int = SyncInt(10)
        with self.assertRaises(ZeroDivisionError):
            s_int //= 0
    def test_thread_safety_increment(self):
        """Test that incrementing from multiple threads is safe."""
        s_int = SyncInt(0)
        num_threads = 10
        increments_per_thread = 10000
        expected_total = num_threads * increments_per_thread

        threads = []
        for _ in range(num_threads):
            t = threading.Thread(target=self._increment_worker, args=(s_int, increments_per_thread))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(s_int.get(), expected_total)

    def _set_and_get_worker(self, s_int, values, results):
        for v in values:
            s_int.set(v)
            time.sleep(0.0001)  # Introduce small delay to increase chance of race conditions
            results.append(s_int.get())

    def test_thread_safety_set_get(self):
        """Test that setting and getting from different threads doesn't corrupt data."""
        s_int = SyncInt(0)
        thread1_values = [1, 3, 5, 7, 9]
        thread2_values = [2, 4, 6, 8, 10]

        results1 = []
        results2 = []

        thread1 = threading.Thread(target=self._set_and_get_worker, args=(s_int, thread1_values, results1))
        thread2 = threading.Thread(target=self._set_and_get_worker, args=(s_int, thread2_values, results2))

        thread1.start()
        thread2.start()

        thread1.join()
        thread2.join()

        all_possible_values = set(thread1_values + thread2_values)
        for r in results1:
            self.assertIn(r, all_possible_values)
        for r in results2:
            self.assertIn(r, all_possible_values)


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)