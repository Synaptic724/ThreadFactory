from __future__ import annotations    # MUST be first
import threading
import math
from copy import deepcopy
from numbers import Real
from thread_factory.utilities.interfaces.isync import ISync

class SyncFloat(ISync):
    """
    SyncFloat
    ---------
    A thread-safe floating-point wrapper that mimics Python's built-in `float` type,
    designed for safe concurrent use in multithreaded environments.

    🔐 Core Purpose
    --------------
    SyncFloat provides synchronized access to floating-point operations, ensuring
    that multiple threads can safely read and modify the value without race conditions.

    🔧 Features
    ----------
    - Full support for arithmetic operations (`+`, `-`, `*`, `/`, `//`, `%`, `**`, etc.)
    - Comparison operators (`==`, `<`, `>`, etc.)
    - Type conversion (`int()`, `float()`, `str()`)
    - Manual and atomic value access via `.get()` and `.set()`
    - Safe thread-aware binary operations with locking on both operands
    - Cross-compatible operations with other Sync types (e.g., `SyncInt`, `SyncBool`)
    - Reverse operation support (`__radd__`, `__rsub__`, etc.)
    - CPython compatibility with `as_integer_ratio`, `hex`, and `fromhex`

    🧠 Deadlock Prevention
    ----------------------
    For binary operations involving multiple Sync types, locks are always acquired in order
    of object ID to avoid deadlocks.

    This makes operations like `SyncFloat(3.14) + SyncFloat(2.0)` safe across threads.

    🔁 Sync Type Interop
    --------------------
    The `_unwrap_other()` method allows flexible interaction between SyncFloat and:

    - Other `SyncFloat`, `SyncInt`, or any object with a `get()` method
    - Primitive types like `float`, `int`, `str` (auto-converted via `float()`)

    ✅ Recommended Usage:
        a = SyncFloat(3.0)
        b = SyncInt(2)
        c = a + b           # Thread-safe: unwrapped and locked
        d = SyncFloat(2.5)
        e = SyncFloat.safe_pow(a, d, 2)  # Apply ternary pow safely (custom)
    """

    __slots__ = ["_value", "_lock"]

    def __init__(self, initial: float = 0.0):
        """
        Initialize the SyncFloat with an initial floating-point value.

        Parameters:
            initial (float): The float value to store.
        """
        self._value = float(initial)
        self._lock = threading.RLock()


    # ──────────────────────────────────────────────────────────────────
    # Core helpers
    # ──────────────────────────────────────────────────────────────────
    @classmethod
    def _coerce(cls, val):  # float-specific cast
        return float(val)

    def _apply_inplace_op(self, op, other):
        """
        Thread-safe helper for all __i*__ operators.

        • If *other* is an ISync subclass, lock both operands in id() order
        • Otherwise lock only self
        """
        if ISync._is_sync(other):
            first, second = ISync._acquire_two(self, other)
            with first._lock, second._lock:
                rhs = float(other._value)  # safe: we hold its lock
                self._value = op(self._value, rhs)
        else:
            with self._lock:
                self._value = op(self._value, float(other))
        return self

    # ──────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────

    def get(self) -> float:
        """
        Get the current float value in a thread-safe way.

        Returns:
            float: The current value.
        """
        with self._lock:
            return self._value

    def set(self, new_value: Real | str):
        """
        Set a new float value in a thread-safe way.

        Parameters:
            new_value (Real | str): A numeric or string value convertible to float.
        """
        with self._lock:
            self._value = float(new_value)

    def as_integer_ratio(self):
        """
        Return a pair of integers whose ratio is exactly equal to the float.

        Returns:
            tuple[int, int]: The numerator and denominator.

        Raises:
            OverflowError: If the float is infinity.
            ValueError: If the float is NaN.
        """
        with self._lock:
            return self._value.as_integer_ratio()

    def hex(self):
        """
        Return a hexadecimal string representation of the float.

        Returns:
            str: Hexadecimal float string (e.g., '0x1.999999999999ap-4').
        """
        with self._lock:
            return self._value.hex()

    def is_integer(self):
        """
        Check if the float is equivalent to an integer.

        Returns:
            bool: True if value is an integer.
        """
        with self._lock:
            return self._value.is_integer()

    def conjugate(self):
        """
        Return the complex conjugate of the float (always self for real numbers).

        Returns:
            float: The same value.
        """
        with self._lock:
            return self._value.conjugate()

    # ──────────────────────────────────────────────────────────────────
    # Dunder numeric / comparison
    # ──────────────────────────────────────────────────────────────────

    def __abs__(self):
        """
        Return the absolute value of the float.

        Returns:
            float: Absolute value.
        """
        with self._lock:
            return abs(self._value)
    # ------------------------------------------------------------------ #
    # Forward Arithmetic Operators
    # ------------------------------------------------------------------ #

    def __add__(self, other):
        """
        __add__(other)
        ----------------
        Thread-safe addition: self + other.

        Returns:
            float: The sum of the two values.
        """
        return self._perform_binary_op(other, lambda a, b: a + b)

    def __sub__(self, other):
        """
        __sub__(other)
        ----------------
        Thread-safe subtraction: self - other.

        Returns:
            float: The result of the subtraction.
        """
        return self._perform_binary_op(other, lambda a, b: a - b)

    def __mul__(self, other):
        """
        __mul__(other)
        ----------------
        Thread-safe multiplication: self * other.

        Returns:
            float: The product of the two values.
        """
        return self._perform_binary_op(other, lambda a, b: a * b)

    def __truediv__(self, other):
        """
        __truediv__(other)
        --------------------
        Thread-safe true division: self / other.

        Returns:
            float: Result of true division.
        """
        return self._perform_binary_op(other, lambda a, b: a / b)

    def __floordiv__(self, other):
        """
        __floordiv__(other)
        ---------------------
        Thread-safe floor division: self // other.

        Returns:
            float: Result of floor division.
        """
        return self._perform_binary_op(other, lambda a, b: a // b)

    def __mod__(self, other):
        """
        __mod__(other)
        ----------------
        Thread-safe modulo: self % other.

        Returns:
            float: The remainder after division.
        """
        return self._perform_binary_op(other, lambda a, b: a % b)

    # ------------------------------------------------------------------ #
    # Reverse Arithmetic Operators
    # ------------------------------------------------------------------ #

    def __radd__(self, other):
        """
        __radd__(other)
        ----------------
        Thread-safe reversed addition: other + self.

        Returns:
            float: Sum of values.
        """
        return self._perform_binary_op(other, lambda a, b: a + b, True)

    def __rsub__(self, other):
        """
        __rsub__(other)
        ----------------
        Thread-safe reversed subtraction: other - self.

        Returns:
            float: Result of subtraction.
        """
        return self._perform_binary_op(other, lambda a, b: a - b, True)

    def __rmul__(self, other):
        """
        __rmul__(other)
        ----------------
        Thread-safe reversed multiplication: other * self.

        Returns:
            float: Product of values.
        """
        return self._perform_binary_op(other, lambda a, b: a * b, True)

    def __rtruediv__(self, other):
        """
        __rtruediv__(other)
        ---------------------
        Thread-safe reversed true division: other / self.

        Returns:
            float: Result of division.
        """
        return self._perform_binary_op(other, lambda a, b: a / b, True)

    def __rfloordiv__(self, other):
        """
        __rfloordiv__(other)
        -----------------------
        Thread-safe reversed floor division: other // self.

        Returns:
            float: Result of floor division.
        """
        return self._perform_binary_op(other, lambda a, b: a // b, True)

    def __rmod__(self, other):
        """
        __rmod__(other)
        -----------------
        Thread-safe reversed modulo: other % self.

        Returns:
            float: Remainder after division.
        """
        return self._perform_binary_op(other, lambda a, b: a % b, True)

    # ------------------------------------------------------------------ #
    # In-Place Arithmetic Operators
    # ------------------------------------------------------------------ #

    def __iadd__(self, other):
        """
        __iadd__(other)
        ----------------
        In-place thread-safe addition: self += other.

        Returns:
            SyncFloat: The updated instance.
        """
        return self._apply_inplace_op(lambda a, b: a + b, other)

    def __isub__(self, other):
        """
        __isub__(other)
        ----------------
        In-place thread-safe subtraction: self -= other.

        Returns:
            SyncFloat: The updated instance.
        """
        return self._apply_inplace_op(lambda a, b: a - b, other)

    def __imul__(self, other):
        """
        __imul__(other)
        ----------------
        In-place thread-safe multiplication: self *= other.

        Returns:
            SyncFloat: The updated instance.
        """
        return self._apply_inplace_op(lambda a, b: a * b, other)

    def __itruediv__(self, other):
        """
        __itruediv__(other)
        ---------------------
        In-place thread-safe division: self /= other.

        Returns:
            SyncFloat: The updated instance.
        """
        return self._apply_inplace_op(lambda a, b: a / b, other)

    def __ifloordiv__(self, other):
        """
        __ifloordiv__(other)
        -----------------------
        In-place thread-safe floor division: self //= other.

        Returns:
            SyncFloat: The updated instance.
        """
        return self._apply_inplace_op(lambda a, b: a // b, other)

    def __imod__(self, other):
        """
        __imod__(other)
        -----------------
        In-place thread-safe modulo: self %= other.

        Returns:
            SyncFloat: The updated instance.
        """
        return self._apply_inplace_op(lambda a, b: a % b, other)

    def __ipow__(self, other):
        """
        __ipow__(other)
        ----------------
        In-place thread-safe exponentiation: self **= other.

        Returns:
            SyncFloat: The updated instance.
        """
        return self._apply_inplace_op(lambda a, b: a ** b, other)



    # ------------------------------------------------------------------ #
    # Comparison Operators
    # ------------------------------------------------------------------ #

    def __eq__(self, other):
        """
        __eq__(other)
        --------------
        Return True if self == other, comparing values thread-safely.

        Parameters:
            other: A SyncFloat, float, int, or compatible type.

        Returns:
            bool: True if values are equal, else False.
        """
        return self._perform_binary_op(other, lambda a, b: a == b)

    def __ne__(self, other):
        """
        __ne__(other)
        --------------
        Return True if self != other, comparing values thread-safely.

        Parameters:
            other: A SyncFloat, float, int, or compatible type.

        Returns:
            bool: True if values are not equal, else False.
        """
        return self._perform_binary_op(other, lambda a, b: a != b)

    def __lt__(self, other):
        """
        __lt__(other)
        --------------
        Return True if self < other in a thread-safe way.

        Parameters:
            other: A SyncFloat, float, int, or compatible type.

        Returns:
            bool: Comparison result.
        """
        return self._perform_binary_op(other, lambda a, b: a < b)

    def __le__(self, other):
        """
        __le__(other)
        --------------
        Return True if self <= other in a thread-safe way.

        Parameters:
            other: A SyncFloat, float, int, or compatible type.

        Returns:
            bool: Comparison result.
        """
        return self._perform_binary_op(other, lambda a, b: a <= b)

    def __gt__(self, other):
        """
        __gt__(other)
        --------------
        Return True if self > other in a thread-safe way.

        Parameters:
            other: A SyncFloat, float, int, or compatible type.

        Returns:
            bool: Comparison result.
        """
        return self._perform_binary_op(other, lambda a, b: a > b)

    def __ge__(self, other):
        """
        __ge__(other)
        --------------
        Return True if self >= other in a thread-safe way.

        Parameters:
            other: A SyncFloat, float, int, or compatible type.

        Returns:
            bool: Comparison result.
        """
        return self._perform_binary_op(other, lambda a, b: a >= b)

    # ------------------------------------------------------------------ #
    # Conversion & Unary Operators
    # ------------------------------------------------------------------ #

    def __float__(self):
        """
        __float__()
        ------------
        Return the float representation of this object.

        Returns:
            float: The current value.
        """
        return self.get()

    def __int__(self):
        """
        __int__()
        ----------
        Return the integer form of this float (truncated toward zero).

        Returns:
            int: The converted int value.
        """
        return int(self.get())

    def __bool__(self):
        """
        __bool__()
        -----------
        Return the truthiness of the float.

        Returns:
            bool: False if value == 0.0, otherwise True.
        """
        return bool(self.get())

    def __hash__(self):
        """
        __hash__()
        ------------
        Compute the hash value based on the internal float.

        Returns:
            int: A hash value suitable for use in sets and dicts.
        """
        return hash(self.get())

    def __neg__(self):
        """
        __neg__()
        ----------
        Return the negation of the float (-value).

        Returns:
            float: Negated value.
        """
        return -self.get()

    def __pos__(self):
        """
        __pos__()
        ----------
        Return the positive identity of the float (+value).

        Returns:
            float: Positive identity of the value.
        """
        return +self.get()

    def __pow__(self, other, mod=None):
        """
        Compute self ** other (power).

        Parameters:
            other: Right-hand side of power.
            mod: Not supported (included for compatibility).

        Returns:
            float: Result of self ** other.

        Raises:
            TypeError: If `mod` is not None.
        """
        if mod is not None:
            raise TypeError("pow() 3-arg form not supported for SyncFloat")
        return self._perform_binary_op(other, lambda a, b: a ** b)

    def __rpow__(self, other, mod=None):
        """
        Compute other ** self (reverse power).

        Parameters:
            other: Left-hand operand.
            mod: Not supported.

        Returns:
            float: Result of power.

        Raises:
            TypeError: If `mod` is not None.
        """
        if mod is not None:
            raise TypeError("pow() 3-arg form not supported for SyncFloat")
        return self._perform_binary_op(other, lambda a, b: a ** b, True)

    def __round__(self, ndigits=None):
        """
        Round the float to the nearest integer (or decimal places if specified).

        Parameters:
            ndigits (int, optional): Decimal precision. If None, rounds to nearest int.

        Returns:
            float: Rounded result.
        """
        with self._lock:
            return round(self._value, ndigits) if ndigits is not None else round(self._value)
    def __trunc__(self):
        """
        __trunc__()
        -----------
        Return the integer part of the float by truncating towards zero.

        This method is used by `math.trunc()` and ensures the call is made
        in a thread-safe context.

        Returns:
            int: The truncated value of the float.
        """
        with self._lock:
            return math.trunc(self._value)

    def __ceil__(self):
        """
        __ceil__()
        ----------
        Return the smallest integer value greater than or equal to the float.

        This method is used by `math.ceil()` and is thread-safe.

        Returns:
            int: The ceiling value of the float.
        """
        with self._lock:
            return math.ceil(self._value)

    def __floor__(self):
        """
        __floor__()
        -----------
        Return the largest integer value less than or equal to the float.

        This method is used by `math.floor()` and is thread-safe.

        Returns:
            int: The floor value of the float.
        """
        with self._lock:
            return math.floor(self._value)

    def __repr__(self):
        """
        __repr__()
        ----------
        Return an unambiguous string representation of the SyncFloat object.

        Returns:
            str: A string like `SyncFloat(3.14)` that includes the class name.
        """
        return f"SyncFloat({self.get()})"

    def __str__(self):
        """
        __str__()
        ---------
        Return a human-readable string representation of the float value.

        Returns:
            str: The float as a string.
        """
        return str(self.get())

    def __format__(self, spec):
        """
        __format__(spec)
        ----------------
        Format the internal float using the given format specifier.

        This is used by the built-in `format()` function and string
        interpolation expressions like `f"{x:.2f}"`.

        Parameters:
            spec (str): A format specifier string.

        Returns:
            str: The formatted float string.
        """
        with self._lock:
            return format(self._value, spec)

    def __copy__(self):
        """
        __copy__()
        ----------
        Create a shallow copy of this SyncFloat.

        The internal value is duplicated, but no new locks are shared.

        Returns:
            SyncFloat: A new SyncFloat with the same value.
        """
        return type(self)(self.get())

    def __deepcopy__(self, memo):
        """
        __deepcopy__(memo)
        ------------------
        Create a deep copy of this SyncFloat.

        Parameters:
            memo (dict): Memoization dictionary for deep copy.

        Returns:
            SyncFloat: A new instance with copied value.
        """
        return type(self)(deepcopy(self.get(), memo))

    def __getnewargs__(self):
        """
        __getnewargs__()
        ----------------
        Provide arguments used by `pickle` to reconstruct this object.

        Returns:
            tuple: A one-element tuple with the current float value.
        """
        return (self.get(),)

    @staticmethod
    def fromhex(s: str):
        """
        fromhex(s)
        ----------
        Create a SyncFloat from a hexadecimal string representation.

        Parameters:
            s (str): A hexadecimal float string (e.g., '0x1.91eb851eb851fp+1').

        Returns:
            SyncFloat: A new instance initialized with the parsed float.
        """
        return SyncFloat(float.fromhex(s))

    def __divmod__(self, other):
        """
        __divmod__(other)
        -----------------
        Return the result of `divmod(self, other)` in a thread-safe way.

        Parameters:
            other: The divisor operand.

        Returns:
            tuple: The quotient and remainder as a tuple.
        """
        return self._perform_binary_op(other, lambda a, b: divmod(a, b))

    def __rdivmod__(self, other):
        """
        __rdivmod__(other)
        ------------------
        Return the result of `divmod(other, self)` in a thread-safe way.

        Parameters:
            other: The left-hand operand.

        Returns:
            tuple: The quotient and remainder as a tuple.
        """
        return self._perform_binary_op(other, lambda a, b: divmod(a, b), r_operation=True)

    @staticmethod
    def __getformat__(typestr: str):
        """
        __getformat__(typestr)
        -----------------------
        Return the internal representation format of the float.

        Mainly used for test introspection and CPython compatibility.

        Parameters:
            typestr (str): Must be 'float' or 'double'.

        Returns:
            str: One of 'unknown', 'IEEE, big-endian', or 'IEEE, little-endian'.

        Raises:
            TypeError: If `typestr` is not a recognized float type.
        """
        return float.__getformat__(typestr)

    @staticmethod
    def __new__(cls, *args, **kwargs):
        """
        __new__(cls, *args, **kwargs)
        -----------------------------
        Override for object creation to ensure correct instancing.

        Required for compatibility with `pickle` and dynamic typing.

        Returns:
            SyncFloat: A new instance of SyncFloat.
        """
        return object.__new__(cls)

    @property
    def real(self) -> float:
        """
        real
        ----
        Return the real component of the float.

        This mirrors float behavior. For SyncFloat, it's always equal to `self.get()`.

        Returns:
            float: The real part of the float.
        """
        return self.get()

    @property
    def imag(self) -> float:
        """
        imag
        ----
        Return the imaginary component of the float.

        Since SyncFloat represents real numbers, this always returns 0.0.

        Returns:
            float: 0.0
        """
        return 0.0

    # ------------------------------------------------------------------ #
    # Atomic convenience helpers
    # ------------------------------------------------------------------ #
    def increment(self, value: Real | ISync = 1.0):
        """
        Atomically add *value* to the internal float and return the new total.
        """
        if ISync._is_sync(value):
            # lock-ordering to avoid dead-lock
            first, second = ISync._acquire_two(self, value)
            with first._lock, second._lock:
                # ✅ always use *value*’s payload, not **second**,
                # because second could be *self* when id(self) > id(value).
                self._value += float(value._value)
                return self._value
        else:  # plain numbers
            with self._lock:
                self._value += float(value)
                return self._value

    def decrement(self, value: Real | ISync = 1.0):
        """
        Atomically subtract *value* from the internal float and return the new total.
        """
        if ISync._is_sync(value):
            first, second = ISync._acquire_two(self, value)
            with first._lock, second._lock:
                # ✅ same fix – read from *value*, not **second**
                self._value -= float(value._value)
                return self._value
        else:
            with self._lock:
                self._value -= float(value)
                return self._value
