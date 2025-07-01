import threading

class SyncBool:
    """
    SyncBool
    --------
    A thread-safe boolean wrapper that emulates Python's `bool` behavior.

    This class provides atomic access and mutation of the internal boolean value,
    along with logical and bitwise operations such as AND, OR, XOR, and NOT.

    SyncBool does not inherit from bool or int to avoid unintentional coercion,
    but behaves identically for boolean logic and thread-safe use cases.
    """

    __slots__ = ("_value", "_lock")

    def __init__(self, initial: bool = False):
        """
        Initialize the SyncBool with a boolean value.

        Parameters:
            initial (bool): The initial boolean state. Defaults to False.
        """
        self._value = bool(initial)
        self._lock = threading.RLock()

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

    def _perform_binary_op(self, other, operation):
        """
        Perform a binary operation with another value in a thread-safe manner.

        If `other` is a SyncBool, it acquires both locks in a deterministic
        order to prevent deadlocks. Otherwise, it acquires only this object's lock.
        It then unwraps the values and applies the given operation.

        Parameters:
            other: Another value to operate with.
            operation: A function that accepts two unwrapped boolean values (self_val, other_val).

        Returns:
            The result of the operation.
        """
        if isinstance(other, SyncBool):
            # Lock in a deterministic order (by object id) to prevent deadlocks.
            first, second = (self, other) if id(self) < id(other) else (other, self)
            with first._lock:
                with second._lock:
                    # The operation is performed on the original `self` and `other` values.
                    return operation(self._value, other._value)
        else:
            # For other types, only lock self and coerce the other value to a bool.
            with self._lock:
                return operation(self._value, bool(other))

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

    def __index__(self):
        """
        Return the integer index equivalent of the boolean.

        Returns:
            int: 0 or 1.
        """
        with self._lock:
            return self._value

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
