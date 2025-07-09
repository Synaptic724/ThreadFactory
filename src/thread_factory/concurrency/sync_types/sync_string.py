from __future__ import annotations    # MUST be first
import threading
import copy
from thread_factory.utilities.interfaces.isync import ISync

class SyncString(ISync):
    """
    SyncString(initial='') -> SyncString

    A thread-safe mutable wrapper around Python's built-in immutable `str`.

    🔐 Core Purpose
    ---------------
    Provides synchronized access to common string operations and behaviors using internal locking.
    Useful for concurrent environments where safe string manipulation is required.

    🔧 Features
    -----------
    - Thread-safe string access and mutation.
    - Supports method forwarding for many built-in string methods.
    - Can be safely used in multithreaded programs.

    ✅ Recommended Usage:
        shared = SyncString("init")
        shared.get()            # Read thread-safely
        shared.set("new val")   # Write thread-safely
        shared.append("...")    # Custom string manipulation methods
    """

    __slots__ = ["_value", "_lock"]

    def __init__(self, initial: str = ""):
        """
        Initialize a new thread-safe string wrapper.

        Args:
            initial (str): The initial string value. Defaults to an empty string.

        The instance will use an internal lock for all operations.
        """
        self._value = str(initial)
        self._lock = threading.RLock()

    # ──────────────────────────────────────────────────────────────
    #  NEW: generic in-place helper (drop it near the other helpers)
    # ──────────────────────────────────────────────────────────────
    def _apply_ip_op(self, other, op):
        """
        Thread-safe in-place operator helper (+=, *=).

        • If *other* is any ISync (e.g. another SyncString) acquire
          both locks in id-order via ISync._acquire_two() to avoid
          lock-order inversion dead-locks.
        • With both locks held read other._value directly – **never**
          call str(other) while the second lock is held.
        """
        if ISync._is_sync(other):
            first, second = ISync._acquire_two(self, other)
            with first._lock, second._lock:
                rhs = str(other._value)  # other is always the RHS object
                self._value = op(self._value, rhs)
        else:
            with self._lock:
                self._value = op(self._value, str(other))
        return self

    def _unwrap_other(self, other):
        if isinstance(other, SyncString):
            return other.get()
        if isinstance(other, str):
            return other
        return other  # no coercion

    def _perform_binary_op(self, other, op, r_operation: bool = False):
        """
        Dead-lock-safe binary helper for strings that works with *any*
        other operand (plain str, SyncString, or any other ISync).
        """
        if ISync._is_sync(other):
            first, second = ISync._acquire_two(self, other)
            with first._lock, second._lock:
                a = self._value if not r_operation else other._value
                b = other._value if not r_operation else self._value
                return op(a, b)
        else:
            # other is a plain object → only our own lock is needed
            with self._lock:
                return op(self._value, self._unwrap_other(other)) \
                    if not r_operation else \
                    op(self._unwrap_other(other), self._value)

    @classmethod
    def _coerce(cls, val):  # always cast to str
        return str(val)


    def get(self) -> str:
        """
        Return the current string value.

        Returns:
            str: The current string value held by this object.

        This method acquires the internal lock before reading the value.
        It is the thread-safe equivalent of accessing the string directly.
        """
        with self._lock:
            return self._value

    def set(self, new_value: str):
        """
        Set a new string value.

        Args:
            new_value (str): The new value to assign to the internal string.

        This method acquires the internal lock before updating the value.
        It allows atomic replacement of the internal string in concurrent settings.
        """
        with self._lock:
            self._value = str(new_value)

    def capitalize(self, *args, **kwargs):
        """
        Return a copy of the string with its first character capitalized and the rest lowercased.

        Thread-safe: Acquires internal lock during access.
        """
        with self._lock:
            return self._value.capitalize(*args, **kwargs)

    def casefold(self, *args, **kwargs):
        """
        Return a casefolded copy of the string, more aggressive than lower() for caseless matching.

        Thread-safe: Acquires internal lock during access.
        """
        with self._lock:
            return self._value.casefold(*args, **kwargs)

    def center(self, *args, **kwargs):
        """
        Return a centered string of given width with optional fill character (default is space).

        Thread-safe: Acquires internal lock during access.
        """
        with self._lock:
            return self._value.center(*args, **kwargs)

    def count(self, *args, **kwargs):
        """
        Return the number of non-overlapping occurrences of a substring in the string.

        Thread-safe: Acquires internal lock during access.
        """
        with self._lock:
            return self._value.count(*args, **kwargs)

    def encode(self, *args, **kwargs):
        """
        Encode the string using the codec registered for encoding. Default is 'utf-8'.

        Thread-safe: Acquires internal lock during access.
        """
        with self._lock:
            return self._value.encode(*args, **kwargs)

    def endswith(self, *args, **kwargs):
        """
        Return True if the string ends with the specified suffix; False otherwise.

        Thread-safe: Acquires internal lock during access.
        """
        with self._lock:
            return self._value.endswith(*args, **kwargs)

    def expandtabs(self, *args, **kwargs):
        """
        Return a copy where all tab characters are replaced by spaces using tabsize (default 8).

        Thread-safe: Acquires internal lock during access.
        """
        with self._lock:
            return self._value.expandtabs(*args, **kwargs)

    def find(self, *args, **kwargs):
        """
        Return the lowest index where the substring is found; -1 if not found.

        Thread-safe: Acquires internal lock during access.
        """
        with self._lock:
            return self._value.find(*args, **kwargs)

    def format(self, *args, **kwargs):
        """
        Perform a string formatting operation using format specifiers.

        Thread-safe: Acquires internal lock during access.
        """
        with self._lock:
            return self._value.format(*args, **kwargs)

    def format_map(self, *args, **kwargs):
        """
        Similar to format(), but uses a single mapping argument instead of positional and keyword.

        Thread-safe: Acquires internal lock during access.
        """
        with self._lock:
            return self._value.format_map(*args, **kwargs)


    def index(self, *args, **kwargs):
        """
        Return the lowest index where the substring is found.

        Same as str.index(). Raises ValueError if the substring is not found.

        This method is thread-safe.
        """
        with self._lock:
            return self._value.index(*args, **kwargs)

    def isalnum(self, *args, **kwargs):
        """
        Return True if the string is nonempty and all characters are alphanumeric.

        Thread-safe variant of str.isalnum().
        """
        with self._lock:
            return self._value.isalnum(*args, **kwargs)

    def isalpha(self, *args, **kwargs):
        """
        Return True if the string is nonempty and all characters are alphabetic.

        Thread-safe variant of str.isalpha().
        """
        with self._lock:
            return self._value.isalpha(*args, **kwargs)

    def isascii(self, *args, **kwargs):
        """
        Return True if all characters in the string are ASCII.

        Thread-safe version of str.isascii().
        """
        with self._lock:
            return self._value.isascii(*args, **kwargs)

    def isdecimal(self, *args, **kwargs):
        """
        Return True if the string is nonempty and all characters are decimal characters.

        Thread-safe wrapper around str.isdecimal().
        """
        with self._lock:
            return self._value.isdecimal(*args, **kwargs)

    def isdigit(self, *args, **kwargs):
        """
        Return True if all characters in the string are digits.

        Thread-safe variant of str.isdigit().
        """
        with self._lock:
            return self._value.isdigit(*args, **kwargs)

    def isidentifier(self, *args, **kwargs):
        """
        Return True if the string is a valid Python identifier.

        Thread-safe version of str.isidentifier().
        """
        with self._lock:
            return self._value.isidentifier(*args, **kwargs)

    def islower(self, *args, **kwargs):
        """
        Return True if all cased characters are lowercase and the string has at least one cased character.

        Thread-safe variant of str.islower().
        """
        with self._lock:
            return self._value.islower(*args, **kwargs)

    def isnumeric(self, *args, **kwargs):
        """
        Return True if all characters in the string are numeric characters.

        Thread-safe version of str.isnumeric().
        """
        with self._lock:
            return self._value.isnumeric(*args, **kwargs)

    def isprintable(self, *args, **kwargs):
        """
        Return True if all characters are printable or the string is empty.

        Thread-safe wrapper around str.isprintable().
        """
        with self._lock:
            return self._value.isprintable(*args, **kwargs)

    def isspace(self, *args, **kwargs):
        """
        Return True if all characters in the string are whitespace and the string is nonempty.

        Thread-safe variant of str.isspace().
        """
        with self._lock:
            return self._value.isspace(*args, **kwargs)

    def istitle(self, *args, **kwargs):
        """
        Return True if the string is titlecased (i.e. upper-case letters followed by lower-case letters).

        Thread-safe wrapper around str.istitle().
        """
        with self._lock:
            return self._value.istitle(*args, **kwargs)


    def isupper(self, *args, **kwargs):
        """Return True if all cased characters are uppercase and there is at least one cased character. Thread-safe."""
        with self._lock:
            return self._value.isupper(*args, **kwargs)

    def join(self, *args, **kwargs):
        """
        Concatenate any number of strings using the current string as a separator.
        Thread-safe.

        Equivalent to: s.join(iterable)
        """
        with self._lock:
            return self._value.join(*args, **kwargs)

    def ljust(self, *args, **kwargs):
        """
        Return the string left-justified in a string of given width.
        Thread-safe.

        Equivalent to: s.ljust(width[, fillchar])
        """
        with self._lock:
            return self._value.ljust(*args, **kwargs)

    def lower(self, *args, **kwargs):
        """
        Return a copy of the string converted to lowercase.

        Thread-safe.
        """
        with self._lock:
            return self._value.lower(*args, **kwargs)

    def lstrip(self, *args, **kwargs):
        """
        Return a copy of the string with leading whitespace removed.

        Thread-safe.
        """
        with self._lock:
            return self._value.lstrip(*args, **kwargs)

    def maketrans(self, *args, **kwargs):
        """
        Return a translation table usable for str.translate().
        Thread-safe.

        Can be used as: str.maketrans(x[, y[, z]])
        """
        # maketrans is a static method on str, so we don't need a lock or self._value
        return str.maketrans(*args, **kwargs)

    def partition(self, *args, **kwargs):
        """
        Split the string at the first occurrence of sep, and return a 3-tuple.
        Thread-safe.

        Equivalent to: s.partition(sep)
        """
        with self._lock:
            return self._value.partition(*args, **kwargs)

    def removeprefix(self, *args, **kwargs):
        """
        Return a string with the specified prefix removed if present.
        Thread-safe.

        Equivalent to: s.removeprefix(prefix)
        """
        with self._lock:
            return self._value.removeprefix(*args, **kwargs)

    def removesuffix(self, *args, **kwargs):
        """
        Return a string with the specified suffix removed if present.
        Thread-safe.

        Equivalent to: s.removesuffix(suffix)
        """
        with self._lock:
            return self._value.removesuffix(*args, **kwargs)

    def replace(self, *args, **kwargs):
        """
        Return a copy with all occurrences of substring replaced by another.
        Thread-safe.

        Equivalent to: s.replace(old, new[, count])
        """
        with self._lock:
            return self._value.replace(*args, **kwargs)

    def rfind(self, *args, **kwargs):
        """
        Return the highest index where the substring is found, or -1 if not found.
        Thread-safe.

        Equivalent to: s.rfind(sub[, start[, end]])
        """
        with self._lock:
            return self._value.rfind(*args, **kwargs)

    def rindex(self, *args, **kwargs):
        """
        Return the highest index where the substring is found, or raise ValueError.
        Thread-safe.

        Equivalent to: s.rindex(sub[, start[, end]])
        """
        with self._lock:
            return self._value.rindex(*args, **kwargs)

    def rjust(self, *args, **kwargs):
        """
        Return the string right-justified in a string of given width.
        Thread-safe.

        Equivalent to: s.rjust(width[, fillchar])
        """
        with self._lock:
            return self._value.rjust(*args, **kwargs)

    def rpartition(self, *args, **kwargs):
        """
        Return a 3-tuple where the string is split around the last occurrence of the separator.

        If the separator is found, returns (head, sep, tail). If not, returns ('', '', original).
        Thread-safe.
        """
        with self._lock:
            return self._value.rpartition(*args, **kwargs)

    def rsplit(self, *args, **kwargs):
        """
        Return a list of the words in the string, using sep as the delimiter string.

        Performs a right split. If maxsplit is given, splits at most maxsplit times.
        Thread-safe.
        """
        with self._lock:
            return self._value.rsplit(*args, **kwargs)

    def rstrip(self, *args, **kwargs):
        """
        Return a copy of the string with trailing whitespace removed.

        If chars is given and not None, remove characters in chars instead.
        Thread-safe.
        """
        with self._lock:
            return self._value.rstrip(*args, **kwargs)

    def split(self, *args, **kwargs):
        """
        Return a list of the words in the string, using sep as the delimiter string.

        If sep is not specified or is None, any whitespace string is a separator.
        Thread-safe.
        """
        with self._lock:
            return self._value.split(*args, **kwargs)

    def splitlines(self, *args, **kwargs):
        """
        Return a list of the lines in the string, breaking at line boundaries.

        Line breaks are not included unless keepends is given and True.
        Thread-safe.
        """
        with self._lock:
            return self._value.splitlines(*args, **kwargs)

    def startswith(self, *args, **kwargs):
        """
        Return True if the string starts with the specified prefix.

        Can be limited by optional start and end arguments.
        Thread-safe.
        """
        with self._lock:
            return self._value.startswith(*args, **kwargs)

    def strip(self, *args, **kwargs):
        """
        Return a copy of the string with leading and trailing whitespace removed.

        If chars is given and not None, remove characters in chars instead.
        Thread-safe.
        """
        with self._lock:
            return self._value.strip(*args, **kwargs)

    def swapcase(self, *args, **kwargs):
        """
        Return a copy of the string with uppercase characters converted to lowercase
        and vice versa.

        Thread-safe.
        """
        with self._lock:
            return self._value.swapcase(*args, **kwargs)

    def title(self, *args, **kwargs):
        """
        Return a titlecased version of the string.

        Words start with uppercase characters, all remaining characters are lowercase.
        Thread-safe.
        """
        with self._lock:
            return self._value.title(*args, **kwargs)

    def translate(self, *args, **kwargs):
        """
        Return a copy where each character has been mapped through the given translation table.

        The table must be a mapping of Unicode ordinals to Unicode ordinals, strings, or None.
        Thread-safe.
        """
        with self._lock:
            return self._value.translate(*args, **kwargs)

    def upper(self, *args, **kwargs):
        """
        Return a copy of the string converted to uppercase.

        Thread-safe.
        """
        with self._lock:
            return self._value.upper(*args, **kwargs)

    def zfill(self, *args, **kwargs):
        """
        Pad the string on the left with zeros to fill a field of the given width.

        The original string is never truncated.
        Thread-safe.
        """
        with self._lock:
            return self._value.zfill(*args, **kwargs)

    def __str__(self):
        """
        Return the informal string representation of the value.

        Equivalent to calling str(value). Thread-safe.
        """
        with self._lock:
            return str(self._value)

    def __repr__(self):
        """
        Return the official string representation of the value.

        Used for debugging and logging. Thread-safe.
        """
        with self._lock:
            return repr(self._value)

    def __eq__(self, other):
        """
        Return True if the stored string is equal to `other`.

        Supports comparison to strings and other compatible types.
        Thread-safe.
        """
        return self._perform_binary_op(other, lambda v_self, v_other: v_self == v_other)

    def __ne__(self, other):
        """
        Return True if the stored string is not equal to `other`.

        Thread-safe.
        """
        return self._perform_binary_op(other, lambda v_self, v_other: v_self != v_other)

    def __lt__(self, other):
        """
        Return True if the stored string is less than `other`.

        Comparison is lexicographic. Thread-safe.
        """
        return self._perform_binary_op(other, lambda v_self, v_other: v_self < v_other)

    def __le__(self, other):
        """
        Return True if the stored string is less than or equal to `other`.

        Thread-safe.
        """
        return self._perform_binary_op(other, lambda v_self, v_other: v_self <= v_other)

    def __gt__(self, other):
        """
        Return True if the stored string is greater than `other`.

        Thread-safe.
        """
        return self._perform_binary_op(other, lambda v_self, v_other: v_self > v_other)

    def __ge__(self, other):
        """
        Return True if the stored string is greater than or equal to `other`.

        Thread-safe.
        """
        return self._perform_binary_op(other, lambda v_self, v_other: v_self >= v_other)

    def __add__(self, other):
        """
        Concatenate the stored string with `other`.

        Returns a new string without modifying the internal value.
        Thread-safe.
        """
        return self._perform_binary_op(other, lambda v_self, v_other: v_self + v_other)

    def __radd__(self, other):
        """
        Concatenate `other` with the stored string.

        Returns a new string. Thread-safe.
        """
        return self._perform_binary_op(other, lambda v_self, v_other: v_other + v_self)

    def __iadd__(self, other):
        """
        Perform in-place concatenation (+=).

        This operation is atomic. It acquires the lock, appends the other
        string, and updates the internal value in a single operation.

        Args:
            other (str): The string to append.

        Returns:
            SyncString: self, after modification.
        """
        return self._apply_ip_op(other, lambda a, b: a + b)

    def __mul__(self, n):
        """
        Return the stored string repeated `n` times.

        Thread-safe.
        """
        with self._lock:
            return self._value * n

    def __rmul__(self, n):
        """
        Return the stored string repeated `n` times.

        Thread-safe.
        """
        with self._lock:
            return n * self._value

    def __getitem__(self, index):
        """
        Return the character or substring at `index`.

        Supports slicing. Thread-safe.
        """
        with self._lock:
            return self._value[index]


    def __contains__(self, item):
        """
        Check if `item` is a substring of the stored string.

        Thread-safe.
        """
        with self._lock:
            return item in self._value

    def __len__(self):
        """
        Return the length of the stored string.

        Thread-safe.
        """
        with self._lock:
            return len(self._value)

    def __iter__(self):
        """
        Return an iterator over the characters in the stored string.

        Thread-safe. A shallow copy of the string is used to avoid race conditions.
        """
        with self._lock:
            return iter(self._value[:])

    def __bool__(self):
        """
        Return True if the stored string is non-empty, False otherwise.

        Thread-safe.
        """
        with self._lock:
            return bool(self._value)

    def __hash__(self):
        """
        Return the hash of the stored string.

        Thread-safe.
        """
        with self._lock:
            return hash(self._value)

    def __format__(self, format_spec):
        """
        Format the stored string according to `format_spec`.

        Thread-safe.
        """
        with self._lock:
            return format(self._value, format_spec)

    def __mod__(self, other):
        """
        Return the result of string formatting using the `%` operator.

        Thread-safe.
        """
        with self._lock:
            return self._value % other

    def __reduce__(self):
        """
        Support pickling: return a tuple describing how to reconstruct this object.

        Thread-safe.
        """
        with self._lock:
            return (self.__class__, (self._value,))

    def __reduce_ex__(self, protocol):
        """
        Support pickling with a specified protocol.

        Thread-safe.
        """
        with self._lock:
            return (self.__class__, (self._value,))

    def __getnewargs__(self):
        """
        Support pickle protocol requiring __new__ arguments.

        Thread-safe.
        """
        with self._lock:
            return (self._value,)

    def __copy__(self):
        """
        Return a shallow copy of this object.

        Thread-safe.
        """
        with self._lock:
            return type(self)(self._value)

    def __deepcopy__(self, memo):
        """
        Return a deep copy of this object.

        Thread-safe.
        """
        with self._lock:
            return type(self)(copy.deepcopy(self._value, memo))

    def __dir__(self):
        """
        Return the list of valid attributes for the stored string.

        Thread-safe.
        """
        with self._lock:
            return dir(self._value)

    def __bytes__(self):
        """
        Converts the string to a bytes object using UTF-8 encoding.

        Returns:
            bytes: The UTF-8 encoded representation of the current value.
        """
        with self._lock:
            return bytes(self._value, 'utf-8')

    def __reversed__(self):
        """
        Returns a reverse iterator over the characters in the string.

        Returns:
            iterator: An iterator yielding characters in reverse order.
        """
        with self._lock:
            return reversed(self._value)

    def __sizeof__(self):
        """
        Returns the size of the underlying string object in memory.

        Returns:
            int: The memory size in bytes.
        """
        with self._lock:
            return self._value.__sizeof__()

    def __getattr__(self, name):
        """
        Fallback to underlying string methods not explicitly implemented.

        If a method or attribute is not found on SyncString, this method is called
        and will attempt to retrieve it from the internal string value.

        Args:
            name (str): The name of the method or attribute to retrieve.

        Returns:
            Any: The resolved method or attribute bound to the internal value.
        """
        # No lock here, as the returned method will handle its own locking.
        attr = getattr(self._value, name)
        if callable(attr):
            def thread_safe_method(*args, **kwargs):
                with self._lock:
                    # Re-fetch the value inside the lock to ensure it's current
                    current_value = self._value
                    # Get the method from the current value
                    method = getattr(current_value, name)
                    return method(*args, **kwargs)
            return thread_safe_method
        # For non-callable attributes, we should still lock to be safe.
        with self._lock:
            return getattr(self._value, name)

    def __imul__(self, n):
        """
        In-place repetition (x *= n) – atomic & dead-lock-safe.
        """
        with self._lock:
            self._value *= n  # real string repetition
            return self

    @classmethod
    def __class_getitem__(cls, item):
        """
        Support for generic class instantiation syntax (Python 3.9+).

        Example: `ConcurrentString[str]`
        """
        return cls

    @staticmethod
    def __new__(cls, *args, **kwargs):
        """
        Create and return a new instance of SyncString.

        This override exists to satisfy type-checkers and frameworks
        that expect a defined __new__ method.

        Returns:
            SyncString: A new instance.
        """
        return object.__new__(cls)

    def __rmod__(self, other):
        """
        Return value % self.

        Performs reverse string formatting where the left-hand operand
        formats the right-hand SyncString, like: "Hello, %s" % SyncString("World")

        Parameters:
            other (Any): The value that performs formatting on this SyncString.

        Returns:
            str: The formatted string.
        """
        with self._lock:
            return other % self._value
