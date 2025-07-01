import threading

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

        >>> SyncInt(10).as_integer_ratio()
        (10, 1)
        >>> SyncInt(-10).as_integer_ratio()
        (-10, 1)
        >>> SyncInt(0).as_integer_ratio()
        (0, 1)
        """
        with self._lock:
            return self._value.as_integer_ratio()

    def bit_count(self):
        """
        Number of ones in the binary representation of the absolute value of self.

        Also known as the population count.

        >>> bin(13)
        '0b1101'
        >>> SyncInt(13).bit_count()
        3
        """
        with self._lock:
            return self._value.bit_count()

    def bit_length(self):
        """
        Number of bits necessary to represent self in binary.

        >>> bin(37)
        '0b100101'
        >>> SyncInt(37).bit_length()
        6
        """
        with self._lock:
            return self._value.bit_length()

    def conjugate(self):
        """
        Returns self, the complex conjugate of any int.

        For all integers, this is just self.
        """
        with self._lock:
            return self._value

    @classmethod
    def from_bytes(cls, b: bytes, byteorder: str, *, signed: bool = False):
        """
        Return the integer represented by the given array of bytes.

        Parameters:
            b (bytes): The byte array to convert.
            byteorder (str): 'big' or 'little'.
            signed (bool): Whether the integer is signed.

        Returns:
            SyncInt: A new SyncInt representing the decoded value.
        """
        return cls(int.from_bytes(b, byteorder, signed=signed))

    def to_bytes(self, length: int, byteorder: str, *, signed: bool = False):
        """
        Return an array of bytes representing an integer.

        Parameters:
            length (int): Desired byte length of the output.
            byteorder (str): 'big' or 'little'.
            signed (bool): Whether to use two's complement.

        Returns:
            bytes: The byte representation of the stored integer.
        """
        with self._lock:
            return self._value.to_bytes(length, byteorder, signed=signed)

    def __abs__(self):
        """
        Return the absolute value of the integer.

        Returns:
            int: |self|
        """
        with self._lock:
            return abs(self._value)

    def __add__(self, other):
        """
        Return self + other.

        Parameters:
            other (Any): The value to add.

        Returns:
            int: Sum of self and other.
        """
        with self._lock:
            return self._value + other

    def __and__(self, other):
        """
        Return self & other.

        Parameters:
            other (Any): The value to bitwise-AND with.

        Returns:
            int: Result of AND operation.
        """
        with self._lock:
            return self._value & other

    def __bool__(self):
        """
        Return True if self is nonzero, False otherwise.

        Returns:
            bool: Truthiness of the integer.
        """
        with self._lock:
            return bool(self._value)

    def __ceil__(self):
        """
        Ceiling of an Integral returns itself.

        Returns:
            int: Same integer.
        """
        with self._lock:
            return self._value

    def __divmod__(self, other):
        """
        Return divmod(self, other).

        Parameters:
            other (Any): Divisor.

        Returns:
            tuple: (self // other, self % other)
        """
        with self._lock:
            return divmod(self._value, other)

    def __eq__(self, other):
        """
        Return self == other.

        Parameters:
            other (Any): Value to compare.

        Returns:
            bool: True if equal.
        """
        with self._lock:
            return self._value == other

    def __float__(self):
        """
        Return float(self).

        Returns:
            float: Float value.
        """
        with self._lock:
            return float(self._value)

    def __floordiv__(self, other):
        """
        Return self // other.

        Parameters:
            other (Any): Divisor.

        Returns:
            int: Floor division result.
        """
        with self._lock:
            return self._value // other

    def __floor__(self):
        """
        Flooring an Integral returns itself.

        Returns:
            int: Same integer.
        """
        with self._lock:
            return self._value

    def __format__(self, format_spec):
        """
        Convert to a string according to format_spec.

        Parameters:
            format_spec (str): Format specification.

        Returns:
            str: Formatted string.
        """
        with self._lock:
            return format(self._value, format_spec)

    def __ge__(self, other):
        """
        Return self >= other.

        Parameters:
            other (Any): Value to compare.

        Returns:
            bool: True if greater than or equal.
        """
        with self._lock:
            return self._value >= other

    def __gt__(self, other):
        """
        Return self > other.

        Parameters:
            other (Any): Value to compare.

        Returns:
            bool: True if greater.
        """
        with self._lock:
            return self._value > other

    def __hash__(self):
        """
        Return hash(self).

        Returns:
            int: Hash value of the integer.
        """
        with self._lock:
            return hash(self._value)

    def __index__(self):
        """
        Return self converted to an integer for use as list index.

        Returns:
            int: Index value.
        """
        with self._lock:
            return self._value

    def __invert__(self):
        """
        Return ~self (bitwise NOT).

        Returns:
            int: Bitwise inversion of value.
        """
        with self._lock:
            return ~self._value

    def __le__(self, other):
        """
        Return self <= other.

        Parameters:
            other (Any): Value to compare.

        Returns:
            bool: True if less than or equal.
        """
        with self._lock:
            return self._value <= other

    def __lshift__(self, other):
        """
        Return self << other.

        Parameters:
            other (int): Shift amount.

        Returns:
            int: Shifted value.
        """
        with self._lock:
            return self._value << other

    def __lt__(self, other):
        """
        Return self < other.

        Parameters:
            other (Any): Value to compare.

        Returns:
            bool: True if less.
        """
        with self._lock:
            return self._value < other

    def __mod__(self, other):
        """
        Return self % other.

        Parameters:
            other (Any): Modulus value.

        Returns:
            int: Result of modulus.
        """
        with self._lock:
            return self._value % other

    def __mul__(self, other):
        """
        Return self * other.

        Parameters:
            other (Any): Value to multiply.

        Returns:
            int: Product of self and other.
        """
        with self._lock:
            return self._value * other

    def __neg__(self):
        """
        Return -self.

        Returns:
            int: Negative value of self.
        """
        with self._lock:
            return -self._value

    def __pos__(self):
        """
        Return +self.

        Returns:
            int: Positive value (same as self).
        """
        with self._lock:
            return +self._value

    # Add this helper method back
    # ADD THIS NEW HELPER METHOD:
    def _unwrap_other(self, other):
        if isinstance(other, SyncInt):
            return other.get()
        return other

    def __pow__(self, other, modulo=None):
        with self._lock:
            # Ensure 'other' (exponent) is unwrapped if it's a SyncInt
            other_val = self._unwrap_other(other)

            if modulo is not None:
                # Ensure 'modulo' is unwrapped if it's a SyncInt
                mod_val = self._unwrap_other(modulo)
                return pow(self._value, other_val, mod_val)
            return pow(self._value, other_val)

    def __rpow__(self, other, modulo=None):
        with self._lock:
            # Ensure 'other' (base) is unwrapped if it's a SyncInt
            base_val = self._unwrap_other(other)
            mod_val = self._unwrap_other(modulo) if modulo is not None else None

            if mod_val is not None:
                return pow(base_val, self._value, mod_val)
            return pow(base_val, self._value)

    def __radd__(self, other):
        """
        Return other + self.

        Parameters:
            other (Any): Value to add.

        Returns:
            int: Sum.
        """
        with self._lock:
            return other + self._value

    def __rand__(self, other):
        """
        Return other & self.

        Parameters:
            other (Any): Value for bitwise AND.

        Returns:
            int: Result.
        """
        with self._lock:
            return other & self._value

    def __rdivmod__(self, other):
        """
        Return divmod(other, self).

        Parameters:
            other (Any): Dividend.

        Returns:
            Tuple[int, int]: Quotient and remainder.
        """
        with self._lock:
            return divmod(other, self._value)

    def __rfloordiv__(self, other):
        """
        Return other // self.

        Parameters:
            other (Any): Dividend.

        Returns:
            int: Floor division result.
        """
        with self._lock:
            return other // self._value

    def __rlshift__(self, other):
        """
        Return other << self.

        Parameters:
            other (Any): Value to shift.

        Returns:
            int: Result of left shift.
        """
        with self._lock:
            return other << self._value

    def __rmod__(self, other):
        """
        Return other % self.

        Parameters:
            other (Any): Dividend.

        Returns:
            int: Remainder.
        """
        with self._lock:
            return other % self._value

    def __rmul__(self, other):
        """
        Return other * self.

        Parameters:
            other (Any): Multiplier.

        Returns:
            int: Product.
        """
        with self._lock:
            return other * self._value

    def __ror__(self, other):
        """
        Return other | self.

        Parameters:
            other (Any): Operand.

        Returns:
            int: Result of bitwise OR.
        """
        with self._lock:
            return other | self._value

    def __round__(self, ndigits=None):
        """
        Rounding an Integral returns itself.

        Parameters:
            ndigits (Optional[int]): Number of digits to round to.

        Returns:
            int: Rounded value.
        """
        with self._lock:
            return round(self._value, ndigits) if ndigits is not None else round(self._value)

    def __rrshift__(self, other):
        """
        Return other >> self.

        Parameters:
            other (Any): Value.

        Returns:
            int: Right-shifted value.
        """
        with self._lock:
            return other >> self._value

    def __rshift__(self, other):
        """
        Return self >> other.

        Parameters:
            other (Any): Shift amount.

        Returns:
            int: Shifted value.
        """
        with self._lock:
            return self._value >> other

    def __rsub__(self, other):
        """
        Return other - self.

        Parameters:
            other (Any): Minuend.

        Returns:
            int: Difference.
        """
        with self._lock:
            return other - self._value

    def __rtruediv__(self, other):
        """
        Return other / self.

        Parameters:
            other (Any): Dividend.

        Returns:
            float: Quotient.
        """
        with self._lock:
            return other / self._value

    def __rxor__(self, other):
        """
        Return other ^ self.

        Parameters:
            other (Any): Value.

        Returns:
            int: Bitwise XOR.
        """
        with self._lock:
            return other ^ self._value

    def __sizeof__(self):
        """
        Return memory size in bytes.

        Returns:
            int: Size in memory.
        """
        with self._lock:
            return self._value.__sizeof__()
    def __sub__(self, other):
        """
        Return self - other.

        Parameters:
            other (Any): Value to subtract.

        Returns:
            int: Difference.
        """
        with self._lock:
            return self._value - other

    def __truediv__(self, other):
        """
        Return self / other.

        Parameters:
            other (Any): Divisor.

        Returns:
            float: Quotient.
        """
        with self._lock:
            return self._value / other

    def __trunc__(self):
        """
        Truncating an Integral returns itself.

        Returns:
            int: Truncated value.
        """
        with self._lock:
            return int(self._value)

    def __xor__(self, other):
        """
        Return self ^ other.

        Parameters:
            other (Any): Value to XOR.

        Returns:
            int: Bitwise XOR.
        """
        with self._lock:
            return self._value ^ other

    @property
    def numerator(self):
        """
        The numerator of the rational representation.

        Returns:
            int: Numerator.
        """
        with self._lock:
            return self._value.numerator

    @property
    def denominator(self):
        """
        The denominator of the rational representation.

        Returns:
            int: Denominator (always 1 for ints).
        """
        with self._lock:
            return self._value.denominator

    @property
    def real(self):
        """
        The real part of the number.

        Returns:
            int: Real value (itself).
        """
        with self._lock:
            return self._value.real

    @property
    def imag(self):
        """
        The imaginary part of the number.

        Returns:
            int: Always 0 for integers.
        """
        with self._lock:
            return self._value.imag

    def is_integer(self):
        """
        Always True. Exists for compatibility with float.

        Returns:
            bool: Always True for integers.
        """
        return True
    def __getattribute__(self, name):
        """
        Return an attribute of the object.

        Parameters:
            name (str): Name of the attribute.

        Returns:
            Any: Value of the attribute.
        """
        return object.__getattribute__(self, name)

    def __getnewargs__(self):
        """
        Used by pickle to get arguments for reconstructing the object.

        Returns:
            tuple: A single-element tuple containing the current value.
        """
        with self._lock:
            return (self._value,)

    def __int__(self):
        """
        Return the integer representation of the object.

        Returns:
            int: The internal value.
        """
        with self._lock:
            return int(self._value)

    @staticmethod
    def __new__(cls, *args, **kwargs):
        """
        Create and return a new SyncInt instance.

        Parameters:
            cls: The class type.

        Returns:
            SyncInt: A new instance.
        """
        return super(SyncInt, cls).__new__(cls)

    def __ne__(self, other):
        """
        Check if self is not equal to another value.

        Parameters:
            other (Any): The value to compare.

        Returns:
            bool: True if not equal, False otherwise.
        """
        with self._lock:
            return self._value != other

    def __or__(self, other):
        """
        Perform bitwise OR with another value.

        Parameters:
            other (Any): Value to OR.

        Returns:
            int: Result of bitwise OR.
        """
        with self._lock:
            return self._value | other

    def __repr__(self):
        """
        Return the official string representation of the object.

        Returns:
            str: Formatted like a native int.
        """
        with self._lock:
            return repr(self._value)
