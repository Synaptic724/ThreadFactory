# tests/test_package.py
import inspect
import math
import types
import unittest
from functools import partial
from thread_factory.utils.coordination.package import Package, Pack


def _square(x):          # Helper functions used in several tests
    return x * x


def _add(a, b):
    return a + b


class TestPackage(unittest.TestCase):
    # ─────────────────────────── construction ─────────────────────────── #
    def test_ctor_valid(self):
        p = Package(_square, 3)
        self.assertIsInstance(p, Package)

    def test_ctor_rejects_non_callable(self):
        with self.assertRaises(TypeError):
            Package(123)

    # ───────────────────────────── __call__ ───────────────────────────── #
    def test_call_without_extra_args(self):
        p = Package(_square, 4)
        self.assertEqual(p(), 16)

    def test_call_with_extra_args(self):
        p = Package(_add, 2)
        self.assertEqual(p(5), 7)

    def test_call_with_extra_kwargs(self):
        def foo(a, b=0):
            return a - b
        p = Package(foo, 10)
        self.assertEqual(p(b=4), 6)

    # ────────────────────────── attribute access ──────────────────────── #
    def test_getattr_fallback(self):
        p = Package(math.sqrt)
        # math.sqrt.__name__ exists – should be exposed via __getattr__
        self.assertEqual(p.__name__, "sqrt")

    # ─────────────────────── args / kwargs storage ─────────────────────── #
    def test_args_property(self):
        p = Package(_add, 1, 2)
        self.assertEqual(p.args, (1, 2))

    def test_kwargs_property(self):
        p = Package(pow, 2, exp=3)
        self.assertEqual(p.kwargs, {"exp": 3})

    # ──────────────────────────── __repr__ ────────────────────────────── #
    def test_repr_contains_func_name(self):
        p = Package(_square, 5)
        self.assertIn("_square", repr(p))

    # ───────────────────────── equality / hashing ─────────────────────── #
    def test_equality_same_content(self):
        p1 = Package(_square, 3)
        p2 = Package(_square, 3)
        self.assertEqual(p1, p2)
        self.assertEqual(hash(p1), hash(p2))

    def test_inequality_different_args(self):
        self.assertNotEqual(Package(_square, 2), Package(_square, 3))

    def test_hashability_in_set(self):
        s = {Package(_square, 2), Package(_square, 2)}
        self.assertEqual(len(s), 1)

    # ──────────────────────────── pipeline (|) ─────────────────────────── #
    def test_pipeline_basic(self):
        p = Package(_square, 3) | Package(_square)
        self.assertEqual(p(), 81)

    def test_pipeline_chains_three(self):
        triple = (Package(_square, 2)
                  | Package(_square)
                  | Package(lambda x: x + 1))
        self.assertEqual(triple(), 17)

    def test_pipeline_type_safety(self):
        with self.assertRaises(TypeError):
            _ = Package(_square, 2) | 123  # not a Package

    # ─────────────────────────── addition (+) ─────────────────────────── #
    def test_addition_results(self):
        p = Package(int, "5") + Package(int, "7")
        self.assertEqual(p(), 12)

    def test_addition_propogates_args(self):
        inc = Package(lambda x: x + 1)
        dbl = Package(lambda x: x * 2)
        combo = inc + dbl
        self.assertEqual(combo(3), 10)  # (3+1) + (3*2)

    def test_addition_type_safety(self):
        with self.assertRaises(TypeError):
            _ = Package(_square, 2) + "not-a-package"

    # ───────────────────── bind / curry helpers ───────────────────────── #
    def test_bind_mutates_kwargs(self):
        p = Package(pow, 2, exp=3)
        p.bind(exp=4)
        self.assertEqual(p(), 16)  # 2**4

    def test_curry_returns_new_instance(self):
        p1 = Package(_add, 1)
        p2 = p1.curry(4)
        self.assertIsNot(p1, p2)
        self.assertEqual(p1(), 1 + 0)    # missing arg defaults to 0?
        self.assertEqual(p2(), 5)

    def test_signature_includes_bound_args(self):
        p = Package(_add, 10)
        sig = p.signature
        self.assertEqual(sig.arguments["arg0"], 10)

    def test_signature_cache_clears_on_bind(self):
        p = Package(pow, 2)
        _ = p.signature             # populate cache
        p.bind(exp=5)
        self.assertEqual(p.signature.arguments["exp"], 5)

    # ───────────────────────── misc edge cases ─────────────────────────── #
    def test_func_with_varargs(self):
        def collect(*vals):
            return vals
        p = Package(collect, 1, 2)
        self.assertEqual(p(3, 4), (1, 2, 3, 4))

    def test_func_with_varkw(self):
        def kw(**d):
            return d
        p = Package(kw, a=1)
        self.assertEqual(p(b=2), {"a": 1, "b": 2})

    def test_zero_arg_function(self):
        p = Package(lambda: 123)
        self.assertEqual(p(), 123)

    def test_repeated_curry(self):
        p = Package(_add, 1).curry(2).curry()  # second curry no args
        self.assertEqual(p(), 3)

    def test_repr_roundtrip_eval(self):
        p = Package(_square, 6)
        # eval(repr(p)) won't work automatically, but repr shouldn't raise
        self.assertIsInstance(repr(p), str)

    def test_attribute_passthrough_dir(self):
        p = Package(math.sin)
        self.assertIn("__call__", dir(p))  # from Package
        self.assertIn("__name__", dir(p))  # from wrapped func

    def test_pipeline_preserves_extra_call_args(self):
        add1 = Package(lambda x: x + 1)
        dbl = Package(lambda x: x * 2)
        pipeline = (add1 | dbl)
        self.assertEqual(pipeline(5), 12)

    def test_addition_preserves_kwargs(self):
        def foo(x, bonus=0):
            return x + bonus
        p = Package(foo, bonus=2) + Package(foo, bonus=3)
        self.assertEqual(p(10), 25)

    def test_hash_equality_after_bind(self):
        p1 = Package(_square, 4)
        p2 = Package(_square, 4)
        self.assertEqual(hash(p1), hash(p2))
        p2.bind(debug=True)
        self.assertNotEqual(hash(p1), hash(p2))

    def test_using_partial_directly(self):
        p = Package(partial(_add, 2), 3)
        self.assertEqual(p(), 5)

    def test_callable_object_instance(self):
        class Mult:
            def __init__(self, factor):
                self.factor = factor
            def __call__(self, x):
                return x * self.factor
        mul3 = Mult(3)
        p = Package(mul3, 7)
        self.assertEqual(p(), 21)

    def test_fallback_getattr_magic(self):
        p = Package(len)
        self.assertTrue(callable(p.__call__))

    def test_eq_handles_non_package(self):
        self.assertNotEqual(Package(len), 123)

    def test_package_is_hashable_after_curry(self):
        p = Package(int, "10")
        p2 = p.curry()  # new package
        d = {p: "ten", p2: "ten-again"}
        self.assertEqual(len(d), 2)

    def test_or_chain_with_add(self):
        inc = Package(lambda x: x + 1)
        dbl = Package(lambda x: x * 2)
        combo = (inc | dbl) + Package(lambda x: x - 3)
        self.assertEqual(combo(4), (4 + 1) * 2 + (4 - 3))  # → 10 + 1 = 11

    def test_signature_after_curry(self):
        p = Package(pow, 2)
        q = p.curry(5)
        self.assertEqual(q.signature.arguments["arg0"], 2)  # first positional
        # pow signature is (x, y, /); inspect binds as positional "arg0", "arg1"

    def test_bind_returns_self(self):
        p = Package(str.upper, "hi")
        self.assertIs(p.bind(), p)  # bind with no kwargs returns same obj


if __name__ == "__main__":
    unittest.main()
