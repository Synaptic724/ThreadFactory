"""
test_sync_bool_extra.py
=======================

**Extended stress-tests** for :class:`thread_factory.concurrency.value_types.sync_bool.SyncBool`.

These go beyond functional correctness – they probe edge-cases such as
*massive contention, process pickling, GC ref-cycles, re-entrancy* and more.

Run standalone::

    python -m unittest tests.concurrency.value_types.test_sync_bool_extra

―――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――
"""
from __future__ import annotations

import gc
import multiprocessing as mp
import threading
import time
import unittest
from decimal import Decimal

from thread_factory.concurrency.value_types.sync_bool  import SyncBool
from thread_factory.concurrency.value_types.sync_int   import SyncInt
from thread_factory.concurrency.value_types.sync_float import SyncFloat


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------
def _mass_toggle(sb: SyncBool, count: int) -> None:
    """Toggle *sb* exactly *count* times."""
    for _ in range(count):
        sb.toggle()

def child_process_for_pickling(conn, sb: SyncBool):
    conn.send(sb)
    conn.close()
# ---------------------------------------------------------------------------
#  Test-Cases
# ---------------------------------------------------------------------------
class TestSyncBoolExtended(unittest.TestCase):
    """Deep-dive stress-suite for **SyncBool**."""

    # ──────────────────────────────────────────────────────────────
    #  1. Massive contention
    # ──────────────────────────────────────────────────────────────
    def test_massive_contention_toggle(self) -> None:
        sb          = SyncBool(False)
        num_threads = 250
        flips_each  = 2_000

        threads = [threading.Thread(target=_mass_toggle, args=(sb, flips_each))
                   for _ in range(num_threads)]

        for t in threads: t.start()
        for t in threads: t.join()

        # Even number of total flips → final state must equal initial (False)
        self.assertFalse(sb.get())

    # ──────────────────────────────────────────────────────────────
    #  2. Equality with exotic / unhashable objects
    # ──────────────────────────────────────────────────────────────
    def test_equality_with_exotic_types(self) -> None:
        sb = SyncBool(True)

        class Foo: pass
        self.assertFalse(sb == Foo())
        self.assertFalse(sb == {'a': 1})
        self.assertFalse(sb == object())

        # Numeric containers should *not* coerce implicitly
        self.assertFalse(sb == [1])
        self.assertFalse(sb == (1,))
        self.assertFalse(sb == {1})

    # ──────────────────────────────────────────────────────────────
    #  3. Re-entrancy – nested lock acquisition in same thread
    # ──────────────────────────────────────────────────────────────
    def test_lock_reentrancy_depth(self) -> None:
        sb = SyncBool(True)

        def nested(depth: int) -> None:
            if depth == 0:
                return
            with sb._lock:
                _ = sb.get()
                nested(depth - 1)

        # Acquire recursively 100 times – should *not* deadlock
        nested(100)

    # ──────────────────────────────────────────────────────────────
    #  4. Garbage-collector sanity – no ref-cycle leaks
    # ──────────────────────────────────────────────────────────────
    def test_gc_refcount_stability(self) -> None:
        gc.collect()
        before = sum(1 for obj in gc.get_objects() if isinstance(obj, SyncBool))

        tmp = [SyncBool(i % 2) for i in range(10_000)]
        del tmp
        gc.collect()

        after = sum(1 for obj in gc.get_objects() if isinstance(obj, SyncBool))
        self.assertLessEqual(after, before + 10, "SyncBool GC leak suspected")

    # ──────────────────────────────────────────────────────────────
    #  5. Multiprocessing – pickle / unpickle across processes
    # ──────────────────────────────────────────────────────────────
    def test_process_pickling(self) -> None:
        parent_conn, child_conn = mp.Pipe()
        sb = SyncBool(True)
        p = mp.Process(target=child_process_for_pickling, args=(child_conn, sb))
        p.start()
        received_sb = parent_conn.recv()
        p.join(timeout=5)

        self.assertIsInstance(received_sb, SyncBool)
        self.assertTrue(received_sb.get())
        self.assertIsNot(sb._lock, received_sb._lock)
    # ──────────────────────────────────────────────────────────────
    #  6. In-place operators fall-back semantics
    # ──────────────────────────────────────────────────────────────
    def test_inplace_and_or_xor_behavior(self):
        sb = SyncBool(True)
        sb &= 0
        self.assertIsInstance(sb, SyncBool)
        self.assertFalse(sb.get())

        sb = SyncBool(False)
        sb |= 1
        self.assertIsInstance(sb, SyncBool)
        self.assertTrue(sb.get())

        sb = SyncBool(True)
        sb ^= 1
        self.assertIsInstance(sb, SyncBool)
        self.assertFalse(sb.get())

    # ──────────────────────────────────────────────────────────────
    #  7. Quick performance sanity (not strict – just ratio check)
    # ──────────────────────────────────────────────────────────────
    def test_get_performance_ratio(self) -> None:
        sb = SyncBool(True)

        iterations = 1_000_000
        start      = time.perf_counter()
        for _ in range(iterations):
            _ = sb.get()
        sync_time = time.perf_counter() - start

        start = time.perf_counter()
        val   = True
        for _ in range(iterations):
            _ = bool(val)
        bool_time = time.perf_counter() - start

        # Locking overhead should be within ~10× of plain bool for *gets*
        self.assertLessEqual(sync_time, bool_time * 10)


# ---------------------------------------------------------------------------
#  Boilerplate
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)  # Windows safe
    unittest.main()
