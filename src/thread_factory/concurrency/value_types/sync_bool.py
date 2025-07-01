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
        with self._lock:
            return self._value == bool(other)

    def __ne__(self, other):
        """
        Check inequality with another value.

        Parameters:
            other (Any): The value to compare against.

        Returns:
            bool: True if not equal, False otherwise.
        """
        with self._lock:
            return self._value != bool(other)

    def __and__(self, other):
        """
        Perform bitwise AND with another value.

        Parameters:
            other (Any): The value to AND with.

        Returns:
            bool: The result of self & other.
        """
        with self._lock:
            return self._value & bool(other)

    def __or__(self, other):
        """
        Perform bitwise OR with another value.

        Parameters:
            other (Any): The value to OR with.

        Returns:
            bool: The result of self | other.
        """
        with self._lock:
            return self._value | bool(other)

    def __xor__(self, other):
        """
        Perform bitwise XOR with another value.

        Parameters:
            other (Any): The value to XOR with.

        Returns:
            bool: The result of self ^ other.
        """
        with self._lock:
            return self._value ^ bool(other)

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
        with self._lock:
            return bool(other) & self._value

    def __ror__(self, other):
        """
        Perform reverse bitwise OR.

        Parameters:
            other (Any): The value to OR with.

        Returns:
            bool: The result of other | self.
        """
        with self._lock:
            return bool(other) | self._value

    def __rxor__(self, other):
        """
        Perform reverse bitwise XOR.

        Parameters:
            other (Any): The value to XOR with.

        Returns:
            bool: The result of other ^ self.
        """
        with self._lock:
            return bool(other) ^ self._value
