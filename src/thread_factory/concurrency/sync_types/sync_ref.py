from __future__ import annotations
import threading
import copy
from contextlib import contextmanager
from typing import (
    Any,
    Callable,
    Generic,
    Iterator,
    Optional,
    TypeVar,
)

from thread_factory.utils.interfaces.isync import ISync

T = TypeVar("T")
R = TypeVar("R")


class SyncRef(ISync, Generic[T]):
    """
    SyncRef(obj, *, init_safe=True)
    ===============================

    A **thread-safe mutable reference** to *any* Python object – a list, dict,
    user-defined class, function, you name it.  Think of it as “`SyncAny`”.

    ────────────────────────────────────────────────────────────────
    Quick-start
    ────────────────────────────────────────────────────────────────
    ```python
    cart = SyncRef({"items": [], "total": 0.0})

    # atomic one-liner mutation
    cart.update(lambda c: c["items"].append(("widget", 3.99)))

    # multi-line transaction
    with cart.locked() as c:
        c["total"] += 3.99
        c["discount"] = 0.1

    # read snapshot (no lock afterwards)
    snapshot = cart.get()

    # compare-and-set (CAS) – swap only if identical (identity, not ==)
    cart.cas(snapshot, {"items": [], "total": 0.0})
    ```

    ────────────────────────────────────────────────────────────────
    Goodies added in this version
    ────────────────────────────────────────────────────────────────
    * **`swap(new)`**    → replace value, *return old* (atomic)
    * **`modify(fn)`**  → `new = fn(old)` then *store & return new* (functional style)
    * **`transform(fn)` / `map(fn)`**  → read-only helpers
    * **`__enter__/__exit__`**   so you can simply `with ref as obj:`
    * **`snapshot` property**   alias for `get()`
    * **rich docstrings & inline comments**

    Thread-safety strategy
    ----------------------
    * Every public API that accesses or mutates the payload grabs
      `_lock` (a `threading.RLock`).
    * When interacting with another `Sync*` instance we can use
      `ISync._acquire_two()` for deterministic lock ordering (not strictly
      needed here but provided for external composition).
    * Pickle/deep-copy only serialises the payload – a fresh lock is created
      on load so the object remains shareable between threads.

    NOTE: Attribute forwarding (`__getattr__`) is intentionally **not** added
    – you keep full control over what executes under the lock.
    """

    # ────────────────────────────────────────────────────────────
    # construction
    # ────────────────────────────────────────────────────────────
    _central_lock = threading.Lock()
    __slots__ = ("_value", "_lock")

    def __init__(self, obj: T, *, init_safe: bool = True):
        if init_safe:
            with SyncRef._central_lock:
                self._value = obj
                self._lock = threading.RLock()
        else:
            self._value = obj
            self._lock = threading.RLock()

    # ────────────────────────────────────────────────────────────
    # ISync plumbing
    # ────────────────────────────────────────────────────────────
    @classmethod
    def _coerce(cls, val):
        return val

    def _unwrap_other(self, other):
        return other.get() if ISync._is_sync(other) else other

    # ────────────────────────────────────────────────────────────
    # core API
    # ────────────────────────────────────────────────────────────
    def get(self) -> T:                                       # snapshot
        with self._lock:
            return self._value

    snapshot = property(get)                                  # read-only alias

    def set(self, obj: T) -> None:                            # wholesale replace
        with self._lock:
            self._value = obj

    # -------- atomic single-lambda mutation --------------------
    def update(self, mutator: Callable[[T], Any]) -> T:
        """
        *Mutate in-place* inside the lock, returning the mutated object.

        The callback **must not** call back into this `SyncRef` (no nested locks).
        """
        with self._lock:
            mutator(self._value)
            return self._value

    # -------- functional replace helper -----------------------
    def modify(self, fn: Callable[[T], R]) -> R:
        """
        Functional update: `new = fn(old)` – store **and** return *new*.
        """
        with self._lock:
            new_val = fn(self._value)
            self._value = new_val
            return new_val

    # -------- compare-and-set ---------------------------------
    def cas(self, expected: T, new: T) -> bool:
        """
        Compare-and-set using **identity** (is).  Returns True on success.
        """
        with self._lock:
            if self._value is expected:
                self._value = new
                return True
            return False

    # -------- swap helper -------------------------------------
    def swap(self, new: T) -> T:
        """
        Atomically replace the value with *new* and **return the old value**.
        """
        with self._lock:
            old = self._value
            self._value = new
            return old

    # -------- read-only transforms ----------------------------
    def transform(self, fn: Callable[[T], R]) -> R:
        """
        Apply *fn* to the current value **under the lock** and return the result
        without changing the stored object.
        """
        with self._lock:
            return fn(self._value)

    map = transform                                            # synonym

    # -------- multi-line transaction --------------------------
    @contextmanager
    def locked(self) -> Iterator[T]:
        """
        ```python
        with ref.locked() as obj:
            # obj is the *live* payload; lock held for the entire block
            ...
        ```
        """
        with self._lock:
            yield self._value

    # Convenient “with ref as obj:” syntax
    def __enter__(self):
        self._lock.acquire()
        return self._value

    def __exit__(self, exc_type, exc, tb):
        self._lock.release()
        return False  # propagate exceptions

    # ────────────────────────────────────────────────────────────
    # represent / compare / hash
    # ────────────────────────────────────────────────────────────
    def __repr__(self):
        return f"SyncRef({self.get()!r})"

    def __eq__(self, other):
        if ISync._is_sync(other):
            return self.get() == other.get()
        return self.get() == other

    def __hash__(self):
        try:
            return hash(self.get())
        except TypeError:
            return id(self)

    # ────────────────────────────────────────────────────────────
    # pickle & deepcopy (same pattern as your other wrappers)
    # ────────────────────────────────────────────────────────────
    def __getstate__(self):
        return {"_value": copy.deepcopy(self.get())}

    def __setstate__(self, state):
        self._value = state["_value"]
        self._lock = threading.RLock()
