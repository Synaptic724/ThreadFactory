from thread_factory.utils.interfaces.isync import ISync
import threading

class SyncInt(ISync):
    """
    SyncInt
    -------
    A thread-safe integer wrapper that mimics Python's built-in `int` type,
    designed for safe concurrent access in multithreaded environments.

    🔐 Core Purpose
    --------------
    SyncInt provides synchronized access to integer operations, ensuring that
    multiple threads can safely read and modify the value without race conditions.

    🔧 Features
    ----------
    - Full support for arithmetic operations (`+`, `-`, `*`, `//`, `%`, `**`, etc.)
    - Comparison operators (`==`, `<`, `>`, etc.)
    - Bitwise operations (`&`, `|`, `^`, `<<`, `>>`)
    - Type conversion (`int()`, `float()`, `str()`)
    - Manual and atomic value access via `.get()` and `.set()`
    - Safe thread-aware binary operations with locking on both operands
    - Optional **init-safe mode** using a centralized lock

    🧷 Central Lock Initialization
    -----------------------------
    The `SyncInt` class offers an optional `init_safe` parameter for thread-safe construction.

    - If `init_safe=True` (default), a global lock (`_central_lock`) ensures
      multiple threads can initialize `SyncInt` instances safely without race conditions.
    - This is **strongly recommended** when creating many SyncInt instances concurrently.

    ⚡ Power Operation Support
    --------------------------
    SyncInt includes custom implementations for `__pow__` and `__rpow__`:

    • `__pow__`: Handles `SyncInt ** x` — supports optional `modulo` as a third argument.
    • `__rpow__`: Handles `x ** SyncInt` when `x` cannot handle the pow itself.

    ⚠️ Important Limitation (Python dispatch rule)
    ----------------------------------------------
    The built-in `pow()` function in Python always dispatches based on the **left-most operand**.
    This means:

        ✅ pow(SyncInt, ..., ...) ➜ will invoke SyncInt.__pow__
        ✅ 3 ** SyncInt ➜ will invoke SyncInt.__rpow__ (if `int.__pow__` fails)
        ❌ pow(3, SyncInt, 5) ➜ SyncInt methods are NOT called (fails with TypeError)

    To work around these dispatch limitations for ternary power (`pow(a, b, c)`), use:

        SyncInt.safe_pow(a, b, c)

    This static utility:
    - Unwraps all `SyncInt` arguments
    - Acquires all relevant locks (if needed)
    - Performs the operation correctly, regardless of argument order

    🧠 Deadlock Prevention
    ----------------------
    For binary and ternary operations involving multiple `SyncInt` instances,
    locks are always acquired in order of object ID to avoid deadlocks.

    This makes operations like `SyncInt(3) ** SyncInt(4) % SyncInt(5)` safe across threads.

    ✅ Recommended Usage:
        result = SyncInt.safe_pow(a, b, c)        # Always works
        result = SyncInt(4) ** SyncInt(3) % 5     # Works if base is SyncInt
        result = 3 ** SyncInt(3)                  # Works (calls __rpow__)
        pow(3, SyncInt(3), 5)                     # ❌ Will raise TypeError
    """

    _central_lock = threading.Lock()  # Used for init safety
    __slots__ = ["_value", "_lock"]

    def __init__(self, initial: int = 0, init_safe: bool = True):
        """
        Initialize the SyncInt with an initial integer value.

        Parameters:
            initial (int): The integer value to store.
            init_safe (bool): If True (default), use a central lock to guarantee
                              thread-safe initialization. If False, skip central lock
                              and initialize independently (not recommended for concurrent use).
        """
        if init_safe:
            with SyncInt._central_lock:
                self._value = int(initial)
                self._lock = threading.RLock()
        else:
            self._value = int(initial)
            self._lock = threading.RLock()

    @classmethod
    def _coerce(cls, val):  # int-specific cast
        return int(val)

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

    # ADD THIS NEW HELPER METHOD:
    def _unwrap_other(self, other):
        """Helper to unwrap SyncInt objects to their underlying int value."""
        if isinstance(other, SyncInt):
            return other.get()
        return other

    def _perform_binary_op(self, other, operation, r_operation=False):
        """
        Perform a binary operation with another value in a thread-safe manner.

        If `other` is a SyncInt, it acquires both locks in a deterministic
        order to prevent deadlocks. Otherwise, it acquires only this object's lock.
        It then unwraps the values and applies the given operation.

        Parameters:
            other: Another value to operate with.
            operation: A function that accepts two unwrapped integer values (self_val, other_val).
            r_operation (bool): True if this is a reverse operation (other op self).

        Returns:
            The result of the operation.
        """
        if isinstance(other, SyncInt):
            # Lock in a deterministic order (by object id) to prevent deadlocks.
            # For reverse operations, 'self' is the second operand.
            if r_operation:
                first, second = (other, self) if id(other) < id(self) else (self, other)
            else:
                first, second = (self, other) if id(self) < id(other) else (other, self)

            with first._lock:
                with second._lock:
                    # Perform the operation using the underlying integer values
                    # based on whether it's a forward or reverse operation.
                    if r_operation:
                        return operation(other._value, self._value)
                    return operation(self._value, other._value)
        else:
            # For other types, only lock self.
            with self._lock:
                # The operation is performed on the original `self` and `other` values.
                if r_operation:
                    return operation(other, self._value)
                return operation(self._value, other)


    def __add__(self, other):
        """
        Return self + other.

        Parameters:
            other (Any): The value to add.

        Returns:
            int: Sum of self and other.
        """
        return self._perform_binary_op(other, lambda a, b: a + b)

    def __and__(self, other):
        """
        Return self & other.

        Parameters:
            other (Any): The value to bitwise-AND with.

        Returns:
            int: Result of AND operation.
        """
        return self._perform_binary_op(other, lambda a, b: a & b)

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
        return self._perform_binary_op(other, divmod)

    def __eq__(self, other):
        """
        Return self == other.

        Parameters:
            other (Any): Value to compare.

        Returns:
            bool: True if equal.
        """
        # Equality doesn't strictly need the _perform_binary_op with lock ordering
        # as it's a non-modifying read and doesn't risk deadlock on its own.
        # However, for consistency with unwrapping other SyncInts:
        with self._lock:
            return self._value == self._unwrap_other(other)

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
        return self._perform_binary_op(other, lambda a, b: a // b)

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
            return self._value >= self._unwrap_other(other)

    def __gt__(self, other):
        """
        Return self > other.

        Parameters:
            other (Any): Value to compare.

        Returns:
            bool: True if greater.
        """
        with self._lock:
            return self._value > self._unwrap_other(other)

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
            return self._value <= self._unwrap_other(other)

    def __lshift__(self, other):
        """
        Return self << other.

        Parameters:
            other (int): Shift amount.

        Returns:
            int: Shifted value.
        """
        return self._perform_binary_op(other, lambda a, b: a << b)

    def __lt__(self, other):
        """
        Return self < other.

        Parameters:
            other (Any): Value to compare.

        Returns:
            bool: True if less.
        """
        with self._lock:
            return self._value < self._unwrap_other(other)

    def __mod__(self, other):
        """
        Return self % other.

        Parameters:
            other (Any): Modulus value.

        Returns:
            int: Result of modulus.
        """
        return self._perform_binary_op(other, lambda a, b: a % b)

    def __mul__(self, other):
        """
        Return self * other.

        Parameters:
            other (Any): Value to multiply.

        Returns:
            int: Product of self and other.
        """
        return self._perform_binary_op(other, lambda a, b: a * b)

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

    def __pow__(self, other, modulo=None):
        """
        Performs thread-safe exponentiation: `self ** other % modulo`.
        Delegates to `SyncInt.safe_pow` for comprehensive handling.
        """
        # Call safe_pow, passing self as the base
        return SyncInt.safe_pow(self, other, modulo)


    def __rpow__(self, other, modulo=None):
        """
        Performs thread-safe reverse exponentiation: `other ** self % modulo`.
        Delegates to `SyncInt.safe_pow` for comprehensive handling.
        """
        # Call safe_pow, passing self as the exponent
        return SyncInt.safe_pow(other, self, modulo)

    def __radd__(self, other):
        """
        Return other + self.

        Parameters:
            other (Any): Value to add.

        Returns:
            int: Sum.
        """
        return self._perform_binary_op(other, lambda a, b: a + b, r_operation=True)

    def __rand__(self, other):
        """
        Return other & self.

        Parameters:
            other (Any): Value for bitwise AND.

        Returns:
            int: Result.
        """
        return self._perform_binary_op(other, lambda a, b: a & b, r_operation=True)

    def __rdivmod__(self, other):
        """
        Return divmod(other, self).

        Parameters:
            other (Any): Dividend.

        Returns:
            Tuple[int, int]: Quotient and remainder.
        """
        return self._perform_binary_op(other, divmod, r_operation=True)

    def __rfloordiv__(self, other):
        """
        Return other // self.

        Parameters:
            other (Any): Dividend.

        Returns:
            int: Floor division result.
        """
        return self._perform_binary_op(other, lambda a, b: a // b, r_operation=True)

    def __rlshift__(self, other):
        """
        Return other << self.

        Parameters:
            other (Any): Value to shift.

        Returns:
            int: Result of left shift.
        """
        return self._perform_binary_op(other, lambda a, b: a << b, r_operation=True)

    def __rmod__(self, other):
        """
        Return other % self.

        Parameters:
            other (Any): Dividend.

        Returns:
            int: Remainder.
        """
        return self._perform_binary_op(other, lambda a, b: a % b, r_operation=True)

    def __rmul__(self, other):
        """
        Return other * self.

        Parameters:
            other (Any): Multiplier.

        Returns:
            int: Product.
        """
        return self._perform_binary_op(other, lambda a, b: a * b, r_operation=True)

    def __ror__(self, other):
        """
        Return other | self.

        Parameters:
            other (Any): Operand.

        Returns:
            int: Result of bitwise OR.
        """
        return self._perform_binary_op(other, lambda a, b: a | b, r_operation=True)

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
        return self._perform_binary_op(other, lambda a, b: a >> b, r_operation=True)

    def __rshift__(self, other):
        """
        Return self >> other.

        Parameters:
            other (Any): Shift amount.

        Returns:
            int: Shifted value.
        """
        return self._perform_binary_op(other, lambda a, b: a >> b)

    def __rsub__(self, other):
        """
        Return other - self.

        Parameters:
            other (Any): Minuend.

        Returns:
            int: Difference.
        """
        return self._perform_binary_op(other, lambda a, b: a - b, r_operation=True)

    def __rtruediv__(self, other):
        """
        Return other / self.

        Parameters:
            other (Any): Dividend.

        Returns:
            float: Quotient.
        """
        return self._perform_binary_op(other, lambda a, b: a / b, r_operation=True)

    def __rxor__(self, other):
        """
        Return other ^ self.

        Parameters:
            other (Any): Value.

        Returns:
            int: Bitwise XOR.
        """
        return self._perform_binary_op(other, lambda a, b: a ^ b, r_operation=True)

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
        return self._perform_binary_op(other, lambda a, b: a - b)

    def __truediv__(self, other):
        """
        Return self / other.

        Parameters:
            other (Any): Divisor.

        Returns:
            float: Quotient.
        """
        return self._perform_binary_op(other, lambda a, b: a / b)

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
        return self._perform_binary_op(other, lambda a, b: a ^ b)

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
            return self._value != self._unwrap_other(other)



    def __or__(self, other):
        """
        Perform bitwise OR with another value.

        Parameters:
            other (Any): Value to OR.

        Returns:
            int: Result of bitwise OR.
        """
        return self._perform_binary_op(other, lambda a, b: a | b)

    def __repr__(self):
        """
        Return the official string representation of the object.

        Returns:
            str: Formatted like a native int.
        """
        with self._lock:
            return repr(self._value)

    @staticmethod
    def safe_pow(base, exp, mod=None):
        """
        Thread-safe pow() that locks all SyncInt operands (if any) using consistent locking order.

        Args:
            base (int or SyncInt): Base value.
            exp (int or SyncInt): Exponent.
            mod (int or SyncInt, optional): Modulo.

        Returns:
            int: Result of pow(base, exp, mod) or pow(base, exp)
        """

        def unwrap(x):
            return x.get() if isinstance(x, SyncInt) else x

        # Gather all SyncInt args to lock
        syncs = [x for x in (base, exp, mod) if isinstance(x, SyncInt)]
        if not syncs:
            # No locking needed
            return pow(base, exp, mod) if mod is not None else pow(base, exp)

        # Sort all SyncInt objects by id for deadlock-free acquisition
        sorted_syncs = sorted(syncs, key=id)
        try:
            for s in sorted_syncs:
                s._lock.acquire()

            # After locking, unwrap and compute
            base_val = unwrap(base)
            exp_val = unwrap(exp)
            mod_val = unwrap(mod) if mod is not None else None
            return pow(base_val, exp_val, mod_val) if mod_val is not None else pow(base_val, exp_val)

        finally:
            for s in reversed(sorted_syncs):
                s._lock.release()



    def increment(self, value=1):
        """
        Atomically increment the internal value by the specified amount.

        Parameters:
            value (int or SyncInt): The amount to add.

        Returns:
            int: The updated value after increment.
        """
        if isinstance(value, SyncInt):
            # Lock in a deterministic order (by object id) to prevent deadlocks.
            first, second = (self, value) if id(self) < id(value) else (value, self)
            with first._lock:
                with second._lock:
                    self._value += value._value
                    return self._value
        else:
            with self._lock:
                self._value += value
                return self._value

    def decrement(self, value=1):
        """
        Atomically decrement the internal value by the specified amount.

        Parameters:
            value (int or SyncInt): The amount to subtract.

        Returns:
            int: The updated value after decrement.
        """
        if isinstance(value, SyncInt):
            # Lock in a deterministic order (by object id) to prevent deadlocks.
            first, second = (self, value) if id(self) < id(value) else (value, self)
            with first._lock:
                with second._lock:
                    self._value -= value._value
                    return self._value
        else:
            with self._lock:
                self._value -= value
                return self._value

    def __iadd__(self, other):
        """
        In-place addition: self += other

        Parameters:
            other (int or SyncInt): Value to add.

        Returns:
            SyncInt: Modified instance.
        """
        if isinstance(other, SyncInt):
            # Lock in a deterministic order (by object id) to prevent deadlocks.
            first, second = (self, other) if id(self) < id(other) else (other, self)
            with first._lock:
                with second._lock:
                    self._value += other._value
        else:
            with self._lock:
                self._value += other
        return self

    def __isub__(self, other):
        """
        In-place subtraction: self -= other

        Parameters:
            other (int or SyncInt): Value to subtract.

        Returns:
            SyncInt: Modified instance.
        """
        if isinstance(other, SyncInt):
            # Lock in a deterministic order (by object id) to prevent deadlocks.
            first, second = (self, other) if id(self) < id(other) else (other, self)
            with first._lock:
                with second._lock:
                    self._value -= other._value
        else:
            with self._lock:
                self._value -= other
        return self

    def __imul__(self, other):
        """
        In-place multiplication: self *= other

        Parameters:
            other (int or SyncInt): Value to multiply.

        Returns:
            SyncInt: Modified instance.
        """
        if isinstance(other, SyncInt):
            # Lock in a deterministic order (by object id) to prevent deadlocks.
            first, second = (self, other) if id(self) < id(other) else (other, self)
            with first._lock:
                with second._lock:
                    self._value *= other._value
        else:
            with self._lock:
                self._value *= other
        return self

    def __ifloordiv__(self, other):
        """
        In-place floor division: self //= other

        Parameters:
            other (int or SyncInt): Divisor.

        Returns:
            SyncInt: Modified instance.
        """
        if isinstance(other, SyncInt):
            # Lock in a deterministic order (by object id) to prevent deadlocks.
            first, second = (self, other) if id(self) < id(other) else (other, self)
            with first._lock:
                with second._lock:
                    self._value //= other._value
        else:
            with self._lock:
                self._value //= other
        return self

    def __imod__(self, other):
        """
        In-place modulo: self %= other

        Parameters:
            other (int or SyncInt): Modulo divisor.

        Returns:
            SyncInt: Modified instance.
        """
        if isinstance(other, SyncInt):
            # Lock in a deterministic order (by object id) to prevent deadlocks.
            first, second = (self, other) if id(self) < id(other) else (other, self)
            with first._lock:
                with second._lock:
                    self._value %= other._value
        else:
            with self._lock:
                self._value %= other
        return self

    def __ipow__(self, other):
        """
        In-place power: self **= other

        Parameters:
            other (int or SyncInt): Exponent.

        Returns:
            SyncInt: Modified instance.
        """
        if isinstance(other, SyncInt):
            # Lock in a deterministic order (by object id) to prevent deadlocks.
            first, second = (self, other) if id(self) < id(other) else (other, self)
            with first._lock:
                with second._lock:
                    self._value **= other._value
        else:
            with self._lock:
                self._value **= other
        return self

    def __ilshift__(self, other):
        """
        In-place left shift: self <<= other

        Parameters:
            other (int or SyncInt): Shift amount.

        Returns:
            SyncInt: Modified instance.
        """
        if isinstance(other, SyncInt):
            # Lock in a deterministic order (by object id) to prevent deadlocks.
            first, second = (self, other) if id(self) < id(other) else (other, self)
            with first._lock:
                with second._lock:
                    self._value <<= other._value
        else:
            with self._lock:
                self._value <<= other
        return self

    def __irshift__(self, other):
        """
        In-place right shift: self >>= other

        Parameters:
            other (int or SyncInt): Shift amount.

        Returns:
            SyncInt: Modified instance.
        """
        if isinstance(other, SyncInt):
            # Lock in a deterministic order (by object id) to prevent deadlocks.
            first, second = (self, other) if id(self) < id(other) else (other, self)
            with first._lock:
                with second._lock:
                    self._value >>= other._value
        else:
            with self._lock:
                self._value >>= other
        return self

    def __getnewargs_ex__(self):
        """
        Used by pickle to get arguments for reconstructing the object,
        including keyword arguments.

        Returns:
            tuple: A tuple containing (args, kwargs) for __new__.
        """
        with self._lock:
            return (self._value,), {}

    def __str__(self):
        """
        Return the informal string representation of the object.

        Returns:
            str: String representation of the integer.
        """
        with self._lock:
            return str(self._value)

    def __itruediv__(self, other):
        """
        Raises TypeError because in-place true division would convert the
        internal value to a float, which is not supported by SyncInt.
        """
        raise TypeError(
            "In-place true division is not supported for SyncInt as it would "
            "change the underlying type to float. Use regular division "
            "and assign to a new variable, or use in-place floor division (//=)."
        )

    def __iand__(self, other):
        """
        In-place bitwise AND: self &= other

        Parameters:
            other (int or SyncInt): Operand.

        Returns:
            SyncInt: Modified instance.
        """
        if isinstance(other, SyncInt):
            # Lock in a deterministic order (by object id) to prevent deadlocks.
            first, second = (self, other) if id(self) < id(other) else (other, self)
            with first._lock:
                with second._lock:
                    self._value &= other._value
        else:
            with self._lock:
                self._value &= other
        return self

    def __ior__(self, other):
        """
        In-place bitwise OR: self |= other

        Parameters:
            other (int or SyncInt): Operand.

        Returns:
            SyncInt: Modified instance.
        """
        if isinstance(other, SyncInt):
            # Lock in a deterministic order (by object id) to prevent deadlocks.
            first, second = (self, other) if id(self) < id(other) else (other, self)
            with first._lock:
                with second._lock:
                    self._value |= other._value
        else:
            with self._lock:
                self._value |= other
        return self

    def __ixor__(self, other):
        """
        In-place bitwise XOR: self ^= other

        Parameters:
            other (int or SyncInt): Operand.

        Returns:
            SyncInt: Modified instance.
        """
        if isinstance(other, SyncInt):
            # Lock in a deterministic order (by object id) to prevent deadlocks.
            first, second = (self, other) if id(self) < id(other) else (other, self)
            with first._lock:
                with second._lock:
                    self._value ^= other._value
        else:
            with self._lock:
                self._value ^= other
        return self