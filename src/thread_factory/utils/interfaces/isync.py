from __future__ import annotations    # MUST be first
import threading
from typing import Any, ClassVar

class ISync:
    """
    ISync
    -----
    Minimal marker & utility mix-in for *all* thread-safe value wrappers.

    What it provides
    ----------------
    • _is_sync_value     – fast `True/False` marker
    • _unwrap_other()    – convert *other* to your native scalar
    • _perform_binary_op() – deadlock-safe dual-lock helper

    What every subclass **must** provide
    ------------------------------------
    • _value             – your stored scalar
    • _lock              – a `threading.RLock`
    • get()              – returns the scalar
    • @classmethod _coerce(val) – cast any input to *your* scalar type
    """

    __slots__: ClassVar[tuple] = ()
    _is_sync_value: ClassVar[bool] = True

    # ----------  helpers shared by ALL Sync* types  -----------------
    @staticmethod
    def _is_sync(obj) -> bool:
        """Internal helper: True if *obj* is any ISync subclass."""
        return getattr(obj, "_is_sync_value", False)

    # NOTE: self._coerce(val) is defined in each concrete subclass
    def _unwrap_other(self, other):
        """
        Convert *other* (Sync* or primitive) into the scalar type of `self`.
        """
        if self._is_sync(other):          # another Sync value
            return self._coerce(other.get())
        try:                              # raw numeric / str
            return self._coerce(other)
        except Exception:
            return other                  # let caller raise if truly incompatible

    def _perform_binary_op(self, other, op, r_operation=False):
        if ISync._is_sync(other):
            first, second = ISync._acquire_two(self, other)
            with first._lock, second._lock:
                # figure out which side is left/right
                a = self._value if not r_operation else other._value
                b = other._value if not r_operation else self._value
                return op(a, b)
        else:
            other_val = self._unwrap_other(other)
            with self._lock:
                return op(other_val, self._value) if r_operation else op(self._value, other_val)

    @staticmethod
    def _acquire_two(a: "ISync", b: "ISync"):
        """Return the two locks in a deterministic order (smallest id first)."""
        return ((a, b) if id(a) <= id(b) else (b, a))

    # ------------------------------------------------------------------ #
    #  Pickle support – exclude the RLock and rebuild it on load
    # ------------------------------------------------------------------ #
    def __getstate__(self):
        """
        Return the instance state for pickling.

        We only pickle the numeric value.  The lock is **not** pickled and
        will be recreated in ``__setstate__``.
        """
        return {"_value": self.get()}        # plain float, fully picklable

    def __setstate__(self, state):
        """
        Re-initialise the object after unpickling.

        A fresh ``threading.RLock`` is created each time, ensuring the
        unpickled object is safe to share between threads.
        """
        self._value = float(state["_value"])
        self._lock  = threading.RLock()
