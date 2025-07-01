# test_sync_float.py
import math
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

# ---- import your concrete classes ----------------------------------
from thread_factory.concurrency.value_types.sync_float import SyncFloat   # adjust the path!
from thread_factory.concurrency.value_types.sync_int   import SyncInt
from thread_factory.concurrency.value_types.sync_bool  import SyncBool


# --------------------------------------------------------------------
# ------------------------------------------------------------------ #
# Helper used in several tests
# ------------------------------------------------------------------ #
def _spawn_threads(fn, n=8):
    with ThreadPoolExecutor(max_workers=n) as ex:
        list(ex.map(lambda _: fn(), range(n)))

class TestSyncFloat(unittest.TestCase):
    # ────────────────────────────────────────────────────────────────
    # Construction & basic access
    # ────────────────────────────────────────────────────────────────
    def test_default_and_custom_init(self):
        self.assertEqual(SyncFloat().get(), 0.0)
        self.assertEqual(SyncFloat(3.14).get(), 3.14)
        self.assertEqual(SyncFloat("2.5").get(), 2.5)

    def test_set_and_get(self):
        f = SyncFloat()
        f.set(9.81)
        self.assertEqual(f.get(), 9.81)

    # ────────────────────────────────────────────────────────────────
    # Arithmetic (forward, reverse, in-place)
    # ────────────────────────────────────────────────────────────────
    def test_basic_arithmetic(self):
        a, b = SyncFloat(3.0), SyncFloat(2.0)
        self.assertEqual(a + b, 5.0)
        self.assertEqual(a - b, 1.0)
        self.assertEqual(a * b, 6.0)
        self.assertEqual(a / b, 1.5)
        self.assertEqual(a // b, 1.0)
        self.assertAlmostEqual(a % b, 1.0)
        self.assertEqual(divmod(a, b), (1.0, 1.0))

    def test_reverse_arithmetic(self):
        a = SyncFloat(2.5)
        self.assertEqual(5 + a, 7.5)
        self.assertEqual(7 - a, 4.5)
        self.assertEqual(2 * a, 5.0)
        self.assertAlmostEqual(5 / a, 2.0)
        self.assertEqual(5 // a, 2.0)
        self.assertAlmostEqual(5 % a, 0.0)

    def test_inplace_ops(self):
        f = SyncFloat(1.0)
        f += 4         # 5
        f *= 2         # 10
        f /= 4         # 2.5
        f //= 2        # 1.0
        f %= 0.6       # 0.4
        f **= 2        # 0.16
        self.assertAlmostEqual(f.get(), 0.16, places=8)

    # ────────────────────────────────────────────────────────────────
    # Comparison / bool / hash
    # ────────────────────────────────────────────────────────────────
    def test_comparisons_and_hash(self):
        a, b = SyncFloat(2.0), SyncFloat(3.0)
        self.assertTrue(a < b)
        self.assertTrue(a <= b)
        self.assertTrue(b > a)
        self.assertTrue(b >= a)
        self.assertFalse(a == b)
        self.assertTrue(a != b)
        # hash consistency
        self.assertEqual(hash(a), hash(2.0))

    # ────────────────────────────────────────────────────────────────
    # Conversion helpers
    # ────────────────────────────────────────────────────────────────
    def test_hex_and_fromhex(self):
        f = SyncFloat(3.14159)
        hx = f.hex()
        self.assertEqual(SyncFloat.fromhex(hx).get(), float.fromhex(hx))

    def test_integer_ratio_and_round(self):
        f = SyncFloat(10.0)
        self.assertEqual(f.as_integer_ratio(), (10, 1))
        self.assertEqual(round(SyncFloat(3.14159), 2), 3.14)

    def test_real_imag_properties(self):
        f = SyncFloat(5.5)
        self.assertEqual(f.real, 5.5)
        self.assertEqual(f.imag, 0.0)

    # ────────────────────────────────────────────────────────────────
    # Increment / decrement helpers
    # ────────────────────────────────────────────────────────────────
    def test_increment_decrement(self):
        f = SyncFloat(1.5)
        self.assertEqual(f.increment(), 2.5)
        self.assertEqual(f.increment(0.5), 3.0)
        i = SyncInt(2)
        self.assertEqual(f.increment(i), 5.0)
        self.assertEqual(f.decrement(1.0), 4.0)
        self.assertEqual(f.decrement(i), 2.0)
    # ───────────────────────────────────────────────────────────────
    # Construction & basic access
    # ───────────────────────────────────────────────────────────────
    def test_init_variants(self):
        self.assertEqual(SyncFloat().get(), 0.0)
        self.assertAlmostEqual(SyncFloat(3.14).get(), 3.14)
        self.assertAlmostEqual(SyncFloat("2.5").get(), 2.5)
        self.assertAlmostEqual(SyncFloat(Decimal("1.23")).get(), 1.23)

    def test_set_get_roundtrip(self):
        f = SyncFloat()
        f.set(9.81)
        self.assertEqual(f.get(), 9.81)

    # ───────────────────────────────────────────────────────────────
    # Forward arithmetic
    # ───────────────────────────────────────────────────────────────
    def test_forward_arithmetic(self):
        a, b = SyncFloat(7.0), SyncFloat(3.0)
        self.assertEqual(a + b, 10.0)
        self.assertEqual(a - b, 4.0)
        self.assertEqual(a * b, 21.0)
        self.assertEqual(a / b, 7/3)
        self.assertEqual(a // b, 2.0)
        self.assertEqual(a % b, 1.0)
        self.assertEqual(divmod(a, b), (2.0, 1.0))
        self.assertEqual(a ** b, 343.0)

    # ───────────────────────────────────────────────────────────────
    # Reverse arithmetic
    # ───────────────────────────────────────────────────────────────

    # ───────────────────────────────────────────────────────────────
    # In-place arithmetic
    # ───────────────────────────────────────────────────────────────
    def test_inplace_each_operator(self):
        cases = [
            ("__iadd__",      lambda x: (x.__iadd__(1),      6.0)),
            ("__isub__",      lambda x: (x.__isub__(1),      4.0)),
            ("__imul__",      lambda x: (x.__imul__(2),     10.0)),
            ("__itruediv__",  lambda x: (x.__itruediv__(4), 1.25)),
            ("__ifloordiv__", lambda x: (x.__ifloordiv__(2), 2.0)),
            ("__imod__",      lambda x: (x.__imod__(0.6),   0.2)),
            ("__ipow__",      lambda x: (x.__ipow__(2),     25.0)),
        ]
        for name, fn in cases:
            with self.subTest(name=name):
                f = SyncFloat(5.0)            # fresh value each time
                val, expected = fn(f)
                self.assertIs(val, f)         # in-place returns self
                self.assertAlmostEqual(f.get(), expected, places=8)

    # ───────────────────────────────────────────────────────────────
    # Comparison & bool/hash
    # ───────────────────────────────────────────────────────────────
    def test_comparisons_bool_hash(self):
        a, b = SyncFloat(1.0), SyncFloat(2.0)
        self.assertTrue(a < b)
        self.assertTrue(a <= b)
        self.assertTrue(b > a)
        self.assertTrue(b >= a)
        self.assertFalse(a == b)
        self.assertTrue(a != b)
        self.assertTrue(bool(b))
        self.assertFalse(bool(SyncFloat(0.0)))
        self.assertEqual(hash(a), hash(1.0))

    # ───────────────────────────────────────────────────────────────
    # Numeric helpers
    # ───────────────────────────────────────────────────────────────
    def test_abs_neg_pos(self):
        f = SyncFloat(-3.5)
        # abs() returns a **float**
        self.assertIsInstance(abs(f), float)
        self.assertEqual(abs(f), 3.5)
        self.assertEqual(-f, 3.5)   # (-f) is also a float
        self.assertEqual(+f, -3.5)  # (+f) leaves the sign


    def test_round_trunc_ceil_floor(self):
        f = SyncFloat(3.75)
        self.assertEqual(round(f), 4)
        self.assertEqual(round(f, 1), 3.8)
        self.assertEqual(math.trunc(f), 3)
        self.assertEqual(math.ceil(f), 4)
        self.assertEqual(math.floor(f), 3)

    def test_integer_ratio_and_conjugate(self):
        f = SyncFloat(6.25)
        self.assertEqual(f.as_integer_ratio(), (25, 4))
        self.assertEqual(f.conjugate(), 6.25)

    # ───────────────────────────────────────────────────────────────
    # Conversion helpers
    # ───────────────────────────────────────────────────────────────
    def test_float_int_str_format(self):
        f = SyncFloat(8.5)
        self.assertEqual(float(f), 8.5)
        self.assertEqual(int(SyncFloat(8.99)), 8)
        self.assertEqual(str(f), "8.5")
        self.assertEqual(format(f, ".1f"), "8.5")

    def test_hex_fromhex_negative(self):
        neg = SyncFloat(-0.1)
        hx = neg.hex()
        self.assertEqual(SyncFloat.fromhex(hx).get(), float.fromhex(hx))

    # ───────────────────────────────────────────────────────────────
    # divmod / rdivmod with mixed types
    # ───────────────────────────────────────────────────────────────
    def test_divmod_cross_types(self):
        f = SyncFloat(7.5)
        i = SyncInt(2)
        self.assertEqual(divmod(f, i), (3.0, 1.5))
        self.assertEqual(divmod(i, f), (0.0, 2.0))

    # ───────────────────────────────────────────────────────────────
    # Increment / decrement (int, SyncInt, SyncFloat)
    # ───────────────────────────────────────────────────────────────
    def test_increment_decrement_variants(self):
        f = SyncFloat(0.0)
        f.increment()               # +1
        f.increment(2.5)            # +2.5
        f.increment(SyncInt(2))     # +2
        f.increment(SyncFloat(0.5)) # +0.5
        self.assertEqual(f.get(), 6.0)
        f.decrement()               # -1
        f.decrement(1.0)            # -1
        f.decrement(SyncInt(1))     # -1
        f.decrement(SyncFloat(1))   # -1
        self.assertEqual(f.get(), 2.0)

    # ───────────────────────────────────────────────────────────────
    # Cross-type arithmetic
    # ───────────────────────────────────────────────────────────────
    def test_cross_type_operations(self):
        f = SyncFloat(2.5)
        i = SyncInt(3)
        b = SyncBool(True)          # coerces to 1
        self.assertEqual(f + i, 5.5)
        self.assertEqual(i + f, 5.5)
        self.assertEqual(f - b, 1.5)
        self.assertEqual(b * f, 2.5)
        self.assertEqual(i // f, 1.0)   # int // float → float result because SyncFloat handles

    # ───────────────────────────────────────────────────────────────
    # Thread-safety: atomic increment under load
    # ───────────────────────────────────────────────────────────────
    def test_concurrent_increment(self):
        counter = SyncFloat(0.0)

        def bump():
            for _ in range(1000):
                counter.increment(0.1)

        _spawn_threads(bump, n=8)   # 8 × 1000 × 0.1 = 800
        self.assertAlmostEqual(counter.get(), 800.0, places=6)

    # ───────────────────────────────────────────────────────────────
    # Dead-lock prevention with dual-lock ops
    # ───────────────────────────────────────────────────────────────
    def test_no_deadlock_two_floats(self):
        a, b = SyncFloat(1.0), SyncFloat(2.0)
        barrier = threading.Barrier(2)
        errors = []

        def t_left():
            try:
                barrier.wait()
                for _ in range(5000):
                    _ = a + b
            except Exception as e:
                errors.append(e)

        def t_right():
            try:
                barrier.wait()
                for _ in range(5000):
                    _ = b - a
            except Exception as e:
                errors.append(e)

        t1, t2 = threading.Thread(target=t_left), threading.Thread(target=t_right)
        t1.start(); t2.start()
        t1.join(1); t2.join(1)
        self.assertFalse(t1.is_alive() or t2.is_alive())
        self.assertEqual(errors, [])

    # ───────────────────────────────────────────────────────────────
    # Edge-case values: NaN, Inf (+/-)
    # ───────────────────────────────────────────────────────────────
    def test_nan_inf_behavior(self):
        nan  = SyncFloat(float('nan'))
        pinf = SyncFloat(float('inf'))
        ninf = SyncFloat(float('-inf'))

        self.assertTrue(math.isnan(nan.get()))
        self.assertTrue(math.isinf(pinf.get()) and pinf.get() > 0)
        self.assertTrue(math.isinf(ninf.get()) and ninf.get() < 0)

        # NaN never compares equal, even to itself
        self.assertFalse(nan == nan)
        self.assertFalse(nan < SyncFloat(1.0))
        self.assertFalse(nan > SyncFloat(1.0))
        # Infinities compare as expected
        self.assertTrue(pinf > SyncFloat(1e308))
        self.assertTrue(ninf < SyncFloat(-1e308))

    # ───────────────────────────────────────────────────────────────
    # __getformat__ passthrough
    # ───────────────────────────────────────────────────────────────
    def test_getformat_passthrough(self):
        self.assertIn(SyncFloat.__getformat__("double"), ("unknown",
                                                          "IEEE, little-endian",
                                                          "IEEE, big-endian"))

    # ────────────────────────────────────────────────────────────────
    # Cross-type operations (SyncInt, SyncBool, raw)
    # ────────────────────────────────────────────────────────────────
    def test_cross_type_math(self):
        f = SyncFloat(2.5)
        i = SyncInt(3)
        b = SyncBool(True)   # truthy → 1
        self.assertEqual(f + i, 5.5)
        self.assertEqual(i + f, 5.5)
        self.assertEqual(f - b, 1.5)
        self.assertEqual(b * f, 2.5)

    # ────────────────────────────────────────────────────────────────
    # Thread-safety stress tests
    # ────────────────────────────────────────────────────────────────
    def test_concurrent_increment(self):
        shared = SyncFloat(0.0)

        def worker():
            for _ in range(1_000):
                shared.increment(0.1)

        with ThreadPoolExecutor(max_workers=8) as ex:
            ex.map(lambda _: worker(), range(8))

        # 8 threads × 1000 × 0.1 = 800.0
        self.assertAlmostEqual(shared.get(), 800.0, places=6)

    def test_dual_lock_deadlock_prevention(self):
        f1, f2 = SyncFloat(1.0), SyncFloat(2.0)
        barrier = threading.Barrier(2)
        errors = []

        def t1():
            try:
                barrier.wait()
                for _ in range(10_000):
                    _ = f1 + f2
            except Exception as e:
                errors.append(e)

        def t2():
            try:
                barrier.wait()
                for _ in range(10_000):
                    _ = f2 - f1
            except Exception as e:
                errors.append(e)

        th1 = threading.Thread(target=t1)
        th2 = threading.Thread(target=t2)
        th1.start(); th2.start()
        th1.join(2); th2.join(2)

        self.assertFalse(th1.is_alive(), "Thread 1 deadlocked")
        self.assertFalse(th2.is_alive(), "Thread 2 deadlocked")
        self.assertEqual(errors, [])

    # ────────────────────────────────────────────────────────────────
    # Edge cases (NaN, Inf)
    # ────────────────────────────────────────────────────────────────
    def test_nan_and_inf(self):
        nan_f = SyncFloat(float('nan'))
        inf_f = SyncFloat(float('inf'))

        self.assertTrue(math.isnan(nan_f.get()))
        self.assertTrue(math.isinf(inf_f.get()))

        # comparisons with NaN always False, even for self == self
        self.assertFalse(nan_f == nan_f)
        self.assertFalse(nan_f < SyncFloat(1.0))
        self.assertTrue(inf_f > SyncFloat(1e308))


if __name__ == "__main__":
    unittest.main()
