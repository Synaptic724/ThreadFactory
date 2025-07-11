from __future__ import annotations    # MUST be first
import copy
import threading
from decimal import Decimal
from thread_factory.utilities.interfaces.isync import ISync

class SyncBool(ISync):
    """
    SyncBool
    --------
    A thread-safe boolean wrapper that emulates Python's `bool` behavior.

    This class provides atomic access and mutation of the internal boolean value,
    along with logical and bitwise operations such as AND, OR, XOR, and NOT.

    SyncBool does not inherit from bool or int to avoid unintentional coercion,
    but behaves identically for boolean logic and thread-safe use cases.
    """

    __slots__ = ["_value", "_lock"]

    def __init__(self, initial: bool = False):
        """
        Initialize the SyncBool with a boolean value.

        Parameters:
            initial (bool): The initial boolean state. Defaults to False.
        """
        self._value = bool(initial)
        self._lock = threading.RLock()


    def _apply_ip_op(self, other, op):
        """
        Thread-safe helper for __iand__, __ior__, __ixor__.

        • If *other* is any ISync, lock both operands in id() order
        • Otherwise just lock self
        """
        if ISync._is_sync(other):
            first, second = ISync._acquire_two(self, other)
            with first._lock, second._lock:
                rhs = bool(other._value)  # safe: we hold its lock
                self._value = op(self._value, rhs)
        else:
            with self._lock:
                self._value = op(self._value, bool(other))
        return self

    @classmethod
    def _coerce(cls, val):  # bool cast (Python truthiness)
        return bool(val)

    # Revised to satisfy the new test-cases
    def _unwrap_other(self, other):
        """
        Convert *other* into a value usable for arithmetic / bitwise ops.

        • Sync*               → underlying scalar
        • int / float / Decimal (non-bool) → return as-is
        • numeric strings     → float(value)
        • everything else     → returned unchanged (no implicit ``bool()``)
        """
        raw = other.get() if ISync._is_sync(other) else other

        if isinstance(raw, (int, float, Decimal)) and type(raw) is not bool:
            return raw

        if isinstance(raw, str):
            try:
                return float(raw)                       # “1” → 1.0, “-5.5” → -5.5
            except ValueError:
                return raw                              # non-numeric str

        return raw                                      # objects / None / lists …

    def get(self) -> bool:
        """
        Get the current boolean value in a thread-safe way.

        Returns:
            bool: The current state of the SyncBool.
        """
        with self._lock:
            return self._value

    def set(self, new_value: bool):
        """
        Set the boolean value in a thread-safe way.

        Parameters:
            new_value (bool): The new boolean state to apply.
        """
        with self._lock:
            self._value = bool(new_value)

    def toggle(self):
        """
        Atomically invert the current boolean value.

        Changes True to False, or False to True, in a thread-safe manner.
        """
        with self._lock:
            self._value = not self._value

    # helper: integer view of the current value (saves one lock nest)
    def _as_int(self) -> int:
        """
        Internal helper: Return the integer form of the current boolean.

        This is a lightweight version of `int(self.get())` without locking.
        Assumes the caller already holds `_lock`, or is inside a safe context.

        Returns:
            int: 1 if True, 0 if False
        """
        return 1 if self._value else 0


    def __int__(self):
        """
        Return the integer representation of the boolean.

        Returns:
            int: 0 or 1 depending on the value.
        """
        with self._lock:
            return int(self._value)

    def __float__(self):
        """
        Return the float representation of the boolean.

        Returns:
            float: 0.0 or 1.0 depending on the value.
        """
        with self._lock:
            return float(self._value)

    # In SyncBool class
    def __index__(self):
        """
        Return the integer index equivalent of the boolean.
        Returns:
            int: 0 or 1.
        """
        with self._lock:
            return int(self._value)  # Explicitly cast to int

    def __bool__(self):
        """
        Evaluate the truthiness of the object.

        Returns:
            bool: The current state, used for truth-value testing.
        """
        with self._lock:
            return self._value

    def __str__(self):
        """
        Return the informal string representation of the object.

        Returns:
            str: 'True' or 'False'.
        """
        with self._lock:
            return str(bool(self._value))

    def __hash__(self):
        """
        Return a hash value based on the internal boolean.

        Returns:
            int: Hash value matching that of a native bool.
        """
        with self._lock:
            return hash(self._value)

    def __repr__(self):
        """
        Return the official string representation of the object.

        Returns:
            str: 'True' or 'False', just like the native bool repr.
        """
        with self._lock:
            return repr(bool(self._value))  # Matches bool behavior

    def __eq__(self, other):
        """
        Check equality with another value.

        Parameters:
            other (Any): The value to compare against.

        Returns:
            bool: True if equal, False otherwise.
        """
        return self._perform_binary_op(other, lambda v_self, v_other: v_self == v_other)

    def __ne__(self, other):
        """
        Check inequality with another value.

        Parameters:
            other (Any): The value to compare against.

        Returns:
            bool: True if not equal, False otherwise.
        """
        return self._perform_binary_op(other, lambda v_self, v_other: v_self != v_other)


    def __and__(self, other):
        """
        Perform bitwise AND with another value.

        Parameters:
            other (Any): The value to AND with.

        Returns:
            bool: The result of self & other.
        """
        return self._perform_binary_op(other, lambda v_self, v_other: v_self & v_other)

    def __or__(self, other):
        """
        Perform bitwise OR with another value.

        Parameters:
            other (Any): The value to OR with.

        Returns:
            bool: The result of self | other.
        """
        return self._perform_binary_op(other, lambda v_self, v_other: v_self | v_other)

    def __xor__(self, other):
        """
        Perform bitwise XOR with another value.

        Parameters:
            other (Any): The value to XOR with.

        Returns:
            bool: The result of self ^ other.
        """
        return self._perform_binary_op(other, lambda v_self, v_other: v_self ^ v_other)

    def __invert__(self):
        """
        Perform a bitwise NOT operation (~self) on the internal boolean.

        Returns:
            int: Bitwise inversion of the integer value (i.e., ~0 or ~1).
        """
        with self._lock:
            return ~int(self._value)  # explicitly cast to avoid warning

    def __rand__(self, other):
        """
        Perform reverse bitwise AND.

        Parameters:
            other (Any): The value to AND with.

        Returns:
            bool: The result of other & self.
        """
        # The order of operands in the lambda is reversed to match the operation.
        return self._perform_binary_op(other, lambda v_self, v_other: v_other & v_self)


    def __copy__(self):
        """
        Create a shallow copy of the SyncBool.

        Returns:
            SyncBool: A new instance with the same boolean value.
        """
        with self._lock:
            return SyncBool(self._value)

    def __deepcopy__(self, memo):
        """
        Create a deep copy of the SyncBool.

        Parameters:
            memo (dict): The memoization dictionary for deep copies.

        Returns:
            SyncBool: A deep-copied instance with the same boolean value.
        """
        with self._lock:
            copied_value = copy.deepcopy(self._value, memo)
            return SyncBool(copied_value)

    def __format__(self, format_spec):
        """
        Format the boolean value using a format specifier.

        Parameters:
            format_spec (str): The format string.

        Returns:
            str: Formatted representation of the internal boolean.
        """
        with self._lock:
            return format(self._value, format_spec)

    def __reduce__(self):
        """
        Return a tuple for pickle support.

        Returns:
            tuple: (constructor, args)
        """
        with self._lock:
            return (self.__class__, (self._value,))

    def __lt__(self, other):
        """
        Less than comparison.

        Parameters:
            other (Any): The value to compare against.

        Returns:
            bool: True if self < other.
        """
        return self._perform_binary_op(other, lambda a, b: a < b)

    def __le__(self, other):
        """
        Less than or equal comparison.

        Parameters:
            other (Any): The value to compare against.

        Returns:
            bool: True if self <= other.
        """
        return self._perform_binary_op(other, lambda a, b: a <= b)

    def __gt__(self, other):
        """
        Greater than comparison.

        Parameters:
            other (Any): The value to compare against.

        Returns:
            bool: True if self > other.
        """
        return self._perform_binary_op(other, lambda a, b: a > b)

    def __ge__(self, other):
        """
        Greater than or equal comparison.

        Parameters:
            other (Any): The value to compare against.

        Returns:
            bool: True if self >= other.
        """
        return self._perform_binary_op(other, lambda a, b: a >= b)

    def __ror__(self, other):
        """
        Perform reverse bitwise OR.

        Parameters:
            other (Any): The value to OR with.

        Returns:
            bool: The result of other | self.
        """
        # The order of operands in the lambda is reversed to match the operation.
        return self._perform_binary_op(other, lambda v_self, v_other: v_other | v_self)

    def __rxor__(self, other):
        """
        Perform reverse bitwise XOR.

        Parameters:
            other (Any): The value to XOR with.

        Returns:
            bool: The result of other ^ self.
        """
        # The order of operands in the lambda is reversed to match the operation.
        return self._perform_binary_op(other, lambda v_self, v_other: v_other ^ v_self)

    @staticmethod
    def __new__(cls, *args, **kwargs):
        """
        Create and return a new SyncBool instance.

        This method ensures consistent object creation behavior
        even if inherited or used via subclassing mechanisms.

        Parameters:
            cls (Type): The class being instantiated.

        Returns:
            SyncBool: A new instance of SyncBool.
        """
        return super(SyncBool, cls).__new__(cls)

    # ──────────────────────────────────────────────────────────────
    #  Reverse-operand numeric operators  (other  OP  self)
    # ──────────────────────────────────────────────────────────────

    def __radd__(self, other):
        """
        Reversed addition (``other + self``).

        Treats the boolean as its integer value (0 or 1).
        """
        with self._lock:
            return other + int(self._value)

    def __rsub__(self, other):
        """
        Reversed subtraction (``other - self``).
        """
        with self._lock:
            return other - int(self._value)

    def __rmul__(self, other):
        """
        Reversed multiplication (``other * self``).
        """
        with self._lock:
            return other * int(self._value)

    def __rtruediv__(self, other):
        """
        Reversed true-division (``other / self``).

        Raises ``ZeroDivisionError`` when ``self`` is ``False``.
        """
        with self._lock:
            denom = int(self._value)
            if denom == 0:
                raise ZeroDivisionError("division by zero")
            return other / denom

    def __rfloordiv__(self, other):
        """
        Reversed floor-division (``other // self``).

        Raises ``ZeroDivisionError`` when ``self`` is ``False``.
        """
        with self._lock:
            denom = int(self._value)
            if denom == 0:
                raise ZeroDivisionError("division by zero")
            return other // denom

    def __rmod__(self, other):
        """
        Reversed modulo (``other % self``).

        Raises ``ZeroDivisionError`` when ``self`` is ``False``.
        """
        with self._lock:
            denom = int(self._value)
            if denom == 0:
                raise ZeroDivisionError("modulo by zero")
            return other % denom

    def __rpow__(self, other, mod=None):
        """
        Reversed exponentiation (``other ** self``).

        The 3-argument ``pow(x, y, z)`` form is **not supported**.
        """
        if mod is not None:
            raise TypeError("pow() 3-arg form not supported for SyncBool")
        with self._lock:
            return other ** int(self._value)

    # ──────────────────────────────────────────────────────────────
    #  Forward numeric operators   (self  OP  other)
    #  These allow SyncBool to behave like a numeric value (0 or 1)
    #  when used in arithmetic expressions.
    # ──────────────────────────────────────────────────────────────

    def __add__(self, other):
        """
        Add SyncBool to another value.

        Parameters:
            other (Any): Value to add.

        Returns:
            Result of `int(self) + other`. Allows expressions like `SyncBool(True) + 5`.
        """
        with self._lock:
            return int(self._value) + other

    def __sub__(self, other):
        """
        Subtract another value from SyncBool.

        Parameters:
            other (Any): Value to subtract.

        Returns:
            Result of `int(self) - other`.
        """
        with self._lock:
            return int(self._value) - other

    def __mul__(self, other):
        """
        Multiply SyncBool with another value.

        Parameters:
            other (Any): Value to multiply.

        Returns:
            Result of `int(self) * other`. Enables use in expressions like `SyncBool(True) * 10`.
        """
        with self._lock:
            return int(self._value) * other

    def __truediv__(self, other):
        """
        Divide SyncBool by another value (true division).

        Parameters:
            other (Any): Divisor.

        Returns:
            Result of `int(self) / other`. May raise ZeroDivisionError if `other == 0`.
        """
        with self._lock:
            return int(self._value) / other

    def __floordiv__(self, other):
        """
        Perform floor division.

        Parameters:
            other (Any): Divisor.

        Returns:
            Result of `int(self) // other`. Truncates toward negative infinity.
        """
        with self._lock:
            return int(self._value) // other

    def __mod__(self, other):
        """
        Compute modulo of SyncBool by another value.

        Parameters:
            other (Any): Divisor.

        Returns:
            Result of `int(self) % other`.
        """
        with self._lock:
            return int(self._value) % other

    def __pow__(self, other, mod=None):
        """
        Raise SyncBool to the power of `other`.

        Parameters:
            other (Any): The exponent.
            mod (Optional[Any]): A third argument is not supported.

        Returns:
            Result of `int(self) ** other`.

        Raises:
            TypeError: If 3-argument form of pow() is used.
        """
        if mod is not None:
            raise TypeError("pow() 3-arg form not supported for SyncBool")
        with self._lock:
            return int(self._value) ** other

    # ──────────────────────────────────────────────────────────────
    #  In-place bitwise operators  (self  OP=  other)
    # ──────────────────────────────────────────────────────────────
    def __iand__(self, other):
        """
        In-place bitwise **AND** (``x &= y``).

        Keeps the object a *SyncBool* instead of falling back to ``int``.
        """
        # __and__ may return int when `other` is int → cast to bool
        return self._apply_ip_op(other, lambda a, b: a & b)

    def __ior__(self, other):
        """
        In-place bitwise **OR** (``x |= y``).
        """
        return self._apply_ip_op(other, lambda a, b: a | b)

    def __ixor__(self, other):
        """
        In-place bitwise **XOR** (``x ^= y``).
        """
        return self._apply_ip_op(other, lambda a, b: a ^ b)
