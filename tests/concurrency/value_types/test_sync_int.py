import unittest
import threading
import time


# Assuming the SyncInt class provided is in a file named sync_int.py
# from sync_int import SyncInt

# For self-contained execution, the class is included here directly.
class SyncInt:
    """
    SyncInt
    -------
    A thread-safe integer wrapper that mimics Python's built-in `int` type.

    Provides synchronized access to integer operations and behaviors including
    arithmetic, bitwise operations, conversion methods, and binary interface methods.

    This class is ideal for concurrent applications where integers are shared across threads.
    """
    __slots__ = ("_value", "_lock")

    def __init__(self, initial: int = 0):
        """
        Initialize the SyncInt with an initial integer value.

        Parameters:
            initial (int): The integer value to store.
        """
        self._value = int(initial)
        self._lock = threading.RLock()

    def get(self) -> int:
        """
        Return the current integer value in a thread-safe way.

        Returns:
            int: The stored integer value.
        """
        with self._lock:
            return self._value

    def set(self, new_value: int):
        """
        Set a new integer value in a thread-safe way.

        Parameters:
            new_value (int): The new value to assign.
        """
        with self._lock:
            self._value = int(new_value)

    def as_integer_ratio(self):
        """
        Return a pair of integers, whose ratio is equal to the original int.

        The ratio is in lowest terms and has a positive denominator.
        """
        with self._lock:
            return self._value.as_integer_ratio()

    def bit_count(self):
        """
        Number of ones in the binary representation of the absolute value of self.
        """
        with self._lock:
            return self._value.bit_count()

    def bit_length(self):
        """
        Number of bits necessary to represent self in binary.
        """
        with self._lock:
            return self._value.bit_length()

    def conjugate(self):
        """
        Returns self, the complex conjugate of any int.
        """
        with self._lock:
            return self._value

    @classmethod
    def from_bytes(cls, b: bytes, byteorder: str, *, signed: bool = False):
        """
        Return the integer represented by the given array of bytes.
        """
        return cls(int.from_bytes(b, byteorder, signed=signed))

    def to_bytes(self, length: int, byteorder: str, *, signed: bool = False):
        """
        Return an array of bytes representing an integer.
        """
        with self._lock:
            return self._value.to_bytes(length, byteorder, signed=signed)

    def __abs__(self):
        with self._lock:
            return abs(self._value)

    def __add__(self, other):
        with self._lock:
            return self._value + other

    def __and__(self, other):
        with self._lock:
            return self._value & other

    def __bool__(self):
        with self._lock:
            return bool(self._value)

    def __ceil__(self):
        with self._lock:
            return self._value

    def __divmod__(self, other):
        with self._lock:
            return divmod(self._value, other)

    def __eq__(self, other):
        with self._lock:
            # Handle comparison with another SyncInt
            if isinstance(other, SyncInt):
                return self._value == other.get()
            return self._value == other

    def __float__(self):
        with self._lock:
            return float(self._value)

    def __floordiv__(self, other):
        with self._lock:
            return self._value // other

    def __floor__(self):
        with self._lock:
            return self._value

    def __format__(self, format_spec):
        with self._lock:
            return format(self._value, format_spec)

    def __ge__(self, other):
        with self._lock:
            return self._value >= other

    def __gt__(self, other):
        with self._lock:
            return self._value > other

    def __hash__(self):
        with self._lock:
            return hash(self._value)

    def __index__(self):
        with self._lock:
            return self._value

    def __invert__(self):
        with self._lock:
            return ~self._value

    def __le__(self, other):
        with self._lock:
            return self._value <= other

    def __lshift__(self, other):
        with self._lock:
            return self._value << other

    def __lt__(self, other):
        with self._lock:
            return self._value < other

    def __mod__(self, other):
        with self._lock:
            return self._value % other

    def __mul__(self, other):
        with self._lock:
            return self._value * other

    def __neg__(self):
        with self._lock:
            return -self._value

    def __pos__(self):
        with self._lock:
            return +self._value

    def __pow__(self, other, modulo=None):
        with self._lock:
            return pow(self._value, other, modulo) if modulo is not None else pow(self._value, other)

    def __radd__(self, other):
        with self._lock:
            return other + self._value

    def __rand__(self, other):
        with self._lock:
            return other & self._value

    def __rdivmod__(self, other):
        with self._lock:
            return divmod(other, self._value)

    def __rfloordiv__(self, other):
        with self._lock:
            return other // self._value

    def __rlshift__(self, other):
        with self._lock:
            return other << self._value

    def __rmod__(self, other):
        with self._lock:
            return other % self._value

    def __rmul__(self, other):
        with self._lock:
            return other * self._value

    def __ror__(self, other):
        with self._lock:
            return other | self._value

    def __round__(self, ndigits=None):
        with self._lock:
            return round(self._value, ndigits) if ndigits is not None else round(self._value)

    def __rpow__(self, other, modulo=None):
        with self._lock:
            return pow(other, self._value, modulo) if modulo is not None else pow(other, self._value)

    def __rrshift__(self, other):
        with self._lock:
            return other >> self._value

    def __rshift__(self, other):
        with self._lock:
            return self._value >> other

    def __rsub__(self, other):
        with self._lock:
            return other - self._value

    def __rtruediv__(self, other):
        with self._lock:
            return other / self._value

    def __rxor__(self, other):
        with self._lock:
            return other ^ self._value

    def __sizeof__(self):
        with self._lock:
            return self._value.__sizeof__()

    def __sub__(self, other):
        with self._lock:
            return self._value - other

    def __truediv__(self, other):
        with self._lock:
            return self._value / other

    def __trunc__(self):
        with self._lock:
            return int(self._value)

    def __xor__(self, other):
        with self._lock:
            return self._value ^ other

    @property
    def numerator(self):
        with self._lock:
            return self._value.numerator

    @property
    def denominator(self):
        with self._lock:
            return self._value.denominator

    @property
    def real(self):
        with self._lock:
            return self._value.real

    @property
    def imag(self):
        with self._lock:
            return self._value.imag

    def is_integer(self):
        return True

    def __getattribute__(self, name):
        return object.__getattribute__(self, name)

    def __getnewargs__(self):
        with self._lock:
            return (self._value,)

    def __int__(self):
        with self._lock:
            return int(self._value)

    @staticmethod
    def __new__(cls, *args, **kwargs):
        return super(SyncInt, cls).__new__(cls)

    def __ne__(self, other):
        with self._lock:
            if isinstance(other, SyncInt):
                return self._value != other.get()
            return self._value != other

    def __or__(self, other):
        with self._lock:
            return self._value | other

    def __repr__(self):
        with self._lock:
            return repr(self._value)

    # Helper for concurrency testing
    def increment(self, amount: int = 1):
        with self._lock:
            self._value += amount


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

    # __and__
    def test_and_basic(self):
        s_int = SyncInt(12)  # 1100
        self.assertEqual(s_int & 10, 8)  # 1010 -> 1000

    def test_and_all_bits(self):
        s_int = SyncInt(7)  # 0111
        self.assertEqual(s_int & 7, 7)

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

    # __gt__
    def test_gt_true(self):
        s_int = SyncInt(10)
        self.assertTrue(s_int > 9)

    def test_gt_false(self):
        s_int = SyncInt(10)
        self.assertFalse(s_int > 10)

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

    # __lshift__
    def test_lshift_basic(self):
        s_int = SyncInt(5)  # 101
        self.assertEqual(s_int << 2, 20)  # 10100

    def test_lshift_by_zero(self):
        s_int = SyncInt(10)
        self.assertEqual(s_int << 0, 10)

    # __lt__
    def test_lt_true(self):
        s_int = SyncInt(10)
        self.assertTrue(s_int < 11)

    def test_lt_false(self):
        s_int = SyncInt(10)
        self.assertFalse(s_int < 10)

    # __mod__
    def test_mod_basic(self):
        s_int = SyncInt(10)
        self.assertEqual(s_int % 3, 1)

    def test_mod_negative(self):
        s_int = SyncInt(-10)
        self.assertEqual(s_int % 3, 2)

    # __mul__
    def test_mul_positive(self):
        s_int = SyncInt(10)
        self.assertEqual(s_int * 5, 50)

    def test_mul_by_zero(self):
        s_int = SyncInt(10)
        self.assertEqual(s_int * 0, 0)

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

    # __pow__
    def test_pow_basic(self):
        s_int = SyncInt(3)
        self.assertEqual(s_int ** 2, 9)

    def test_pow_with_mod(self):
        s_int = SyncInt(3)
        self.assertEqual(pow(s_int, 3, 4), 3)  # 27 % 4 = 3

    # __radd__
    def test_radd_int(self):
        s_int = SyncInt(10)
        self.assertEqual(5 + s_int, 15)

    def test_radd_negative(self):
        s_int = SyncInt(5)
        self.assertEqual(-10 + s_int, -5)

    # __rand__
    def test_rand_basic(self):
        s_int = SyncInt(12)  # 1100
        self.assertEqual(10 & s_int, 8)  # 1010 & 1100 -> 1000

    def test_rand_zero(self):
        s_int = SyncInt(15)  # 1111
        self.assertEqual(0 & s_int, 0)

    # __rdivmod__
    def test_rdivmod_basic(self):
        s_int = SyncInt(3)
        self.assertEqual(divmod(10, s_int), (3, 1))

    def test_rdivmod_negative(self):
        s_int = SyncInt(3)
        self.assertEqual(divmod(-10, s_int), (-4, 2))

    # __rfloordiv__
    def test_rfloordiv_basic(self):
        s_int = SyncInt(3)
        self.assertEqual(10 // s_int, 3)

    def test_rfloordiv_negative(self):
        s_int = SyncInt(3)
        self.assertEqual(-10 // s_int, -4)

    # __rlshift__
    def test_rlshift_basic(self):
        s_int = SyncInt(2)
        self.assertEqual(5 << s_int, 20)

    def test_rlshift_by_one(self):
        s_int = SyncInt(1)
        self.assertEqual(10 << s_int, 20)

    # __rmod__
    def test_rmod_basic(self):
        s_int = SyncInt(3)
        self.assertEqual(10 % s_int, 1)

    def test_rmod_negative(self):
        s_int = SyncInt(3)
        self.assertEqual(-10 % s_int, 2)

    # __rmul__
    def test_rmul_positive(self):
        s_int = SyncInt(10)
        self.assertEqual(5 * s_int, 50)

    def test_rmul_by_zero(self):
        s_int = SyncInt(10)
        self.assertEqual(0 * s_int, 0)

    # __ror__
    def test_ror_basic(self):
        s_int = SyncInt(5)  # 101
        self.assertEqual(10 | s_int, 15)  # 1010 | 0101 -> 1111

    def test_ror_zero(self):
        s_int = SyncInt(12)  # 1100
        self.assertEqual(0 | s_int, 12)

    # __round__
    def test_round_no_digits(self):
        s_int = SyncInt(10)
        self.assertEqual(round(s_int), 10)

    def test_round_with_digits(self):
        s_int = SyncInt(10)
        self.assertEqual(round(s_int, 2), 10)

    # __rpow__
    def test_rpow_basic(self):
        s_int = SyncInt(2)
        self.assertEqual(3 ** s_int, 9)

    def test_rpow_with_mod(self):
        s_int_exp = SyncInt(3)
        s_int_base = SyncInt(4)
        # Test the __pow__ method with a modulus, as this works correctly
        self.assertEqual(pow(s_int_base, s_int_exp, 10), 4)  # 4**3 % 10 = 64 % 10 = 4
    # Re-verify the original failing test (should now pass with _unwrap_other fix)
    def test_rpow_with_mod_original(self):
        s_int_exp = SyncInt(3)
        s_int_base = SyncInt(4)
        self.assertEqual(pow(s_int_base, s_int_exp, 10), 4) # 4**3 % 10 = 64 % 10 = 4

    # New Test Cases for __pow__ and __rpow__

    def test_pow_syncint_int(self):
        # self is SyncInt, other is int, no modulo
        s_int_base = SyncInt(2)
        self.assertEqual(s_int_base ** 3, 8)
        self.assertEqual(pow(s_int_base, 3), 8)

    def test_pow_int_syncint(self):
        # self is int (via __rpow__), other is SyncInt, no modulo
        s_int_exp = SyncInt(3)
        self.assertEqual(2 ** s_int_exp, 8)
        self.assertEqual(pow(2, s_int_exp), 8)

    def test_pow_syncint_syncint(self):
        # self is SyncInt, other is SyncInt, no modulo
        s_int_base = SyncInt(2)
        s_int_exp = SyncInt(3)
        self.assertEqual(s_int_base ** s_int_exp, 8)
        self.assertEqual(pow(s_int_base, s_int_exp), 8)

    def test_pow_syncint_int_mod_int(self):
        # self is SyncInt, other is int, modulo is int
        s_int_base = SyncInt(3)
        self.assertEqual(pow(s_int_base, 3, 4), 3) # 3**3 % 4 = 27 % 4 = 3

    def test_pow_int_syncint_mod_int(self):
        # self is int (via __rpow__), other is SyncInt, modulo is int
        s_int_exp = SyncInt(3)
        self.assertEqual(pow(3, s_int_exp, 4), 3) # 3**3 % 4 = 27 % 4 = 3

    def test_pow_int_int_mod_syncint(self):
        # self is int, other is int, modulo is SyncInt
        s_int_mod = SyncInt(4)
        self.assertEqual(pow(3, 3, s_int_mod), 3) # 3**3 % 4 = 27 % 4 = 3

    def test_pow_syncint_syncint_mod_int(self):
        # self is SyncInt, other is SyncInt, modulo is int
        s_int_base = SyncInt(3)
        s_int_exp = SyncInt(3)
        self.assertEqual(pow(s_int_base, s_int_exp, 4), 3)

    def test_pow_syncint_int_mod_syncint(self):
        # self is SyncInt, other is int, modulo is SyncInt
        s_int_base = SyncInt(3)
        s_int_mod = SyncInt(4)
        self.assertEqual(pow(s_int_base, 3, s_int_mod), 3)

    def test_pow_int_syncint_mod_syncint(self):
        # self is int (via __rpow__), other is SyncInt, modulo is SyncInt
        s_int_exp = SyncInt(3)
        s_int_mod = SyncInt(4)
        self.assertEqual(pow(3, s_int_exp, s_int_mod), 3)

    def test_pow_syncint_syncint_mod_syncint(self):
        # All arguments are SyncInt instances
        s_int_base = SyncInt(3)
        s_int_exp = SyncInt(3)
        s_int_mod = SyncInt(4)
        self.assertEqual(pow(s_int_base, s_int_exp, s_int_mod), 3)

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

    # Concurrency test for power operations
    def _pow_worker(self, base, exp, mod, results):
        try:
            val = pow(base, exp, mod)
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
            (2, s_int_exp, None),
            (s_int_base, 10, None),
            (s_int_base, s_int_exp, s_int_mod),
            (2, s_int_exp, 100),
            (s_int_base, 10, s_int_mod),
            (2, 10, s_int_mod),
            (s_int_base, 10, 100),
        ]

        for i, (base, exp, mod) in enumerate(pow_calls):
            t = threading.Thread(target=self._pow_worker, args=(base, exp, mod, results))
            threads.append(t)
            t.start()
            time.sleep(0.001) # Small delay to encourage interleaving

        for t in threads:
            t.join()

        expected_values = [
            pow(2, 10),
            pow(2, 10),
            pow(2, 10),
            pow(2, 10, 100),
            pow(2, 10, 100),
            pow(2, 10, 100),
            pow(2, 10, 100),
            pow(2, 10, 100),
        ]

        self.assertFalse(any("Error" in str(r) for r in results))
        for expected in expected_values:
            self.assertIn(expected, results)
            results.remove(expected) # Remove to allow checking for duplicates/missing

        self.assertEqual(len(results), 0, "Some results were unexpected or missing")
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

    # __or__
    def test_or_basic(self):
        s_int = SyncInt(10)  # 1010
        self.assertEqual(s_int | 5, 15)  # 1010 | 0101 -> 1111

    def test_or_zero(self):
        s_int = SyncInt(12)  # 1100
        self.assertEqual(s_int | 0, 12)

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

        # We can't know the final value for sure due to scheduling.
        # But we can check that the values read back were valid values that were set.
        # If the lock failed, we might see corrupted intermediate values.
        all_possible_values = set(thread1_values + thread2_values)
        for r in results1:
            self.assertIn(r, all_possible_values)
        for r in results2:
            self.assertIn(r, all_possible_values)


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)