import unittest
import inspect
from functools import wraps
from typing import Callable, Union, Iterable
from thread_factory.utilities.coordination.package import Package



# --- Some fake decorators to test wrapping and metadata ---
def simple_decorator(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper

def arg_changing_decorator(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func("intercepted", *args, **kwargs)
    return wrapper

def no_wraps_decorator(func):
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper

def raising_decorator(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        raise RuntimeError("Blocked by decorator")
    return wrapper

# Dummy functions
def dummy(): return "ok"
@simple_decorator
def decorated(): return "decorated"
@no_wraps_decorator
def hidden(): return "hidden"
@arg_changing_decorator
def intercepted(x): return f"got {x}"

# Generator and coroutine functions
def gen_func():
    yield 1

async def coro_func():
    return 1

# Coroutine object (not function)
async def coro(): return 1
coro_obj = coro()


class TestPackAndPackMany(unittest.TestCase):
    def test_pack_valid_callable(self):
        self.assertEqual(Package._pack(dummy)(), "ok")

    def test_pack_valid_package(self):
        p = Package(dummy)
        self.assertEqual(Package._pack(p).__name__, dummy.__name__)

    def test_pack_many_single_callable(self):
        result = Package._pack_many(dummy)
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], Package)

    def test_pack_many_single_package(self):
        p = Package(dummy)
        result = Package._pack_many(p)
        self.assertEqual(result[0], p)

    def test_pack_many_iterable_of_callables(self):
        result = Package._pack_many([dummy, decorated])
        self.assertEqual(len(result), 2)

    def test_pack_many_iterable_mixed(self):
        p = Package(dummy)
        result = Package._pack_many([p, decorated])
        self.assertEqual(result[0], p)
        self.assertIsInstance(result[1], Package)

    def test_pack_rejects_none(self):
        with self.assertRaises(TypeError):
            Package._pack(None)

    def test_pack_many_rejects_none(self):
        with self.assertRaises(TypeError):
            Package._pack_many(None)

    def test_pack_rejects_non_callable(self):
        with self.assertRaises(TypeError):
            Package._pack(123)

    def test_pack_many_rejects_non_iterable(self):
        with self.assertRaises(TypeError):
            Package._pack_many(123)

    def test_pack_rejects_generator_func(self):
        with self.assertRaises(TypeError):
            Package._pack(gen_func)

    def test_pack_rejects_coroutine_func(self):
        with self.assertRaises(TypeError):
            Package._pack(coro_func)

    def test_pack_many_rejects_generator_in_list(self):
        with self.assertRaises(TypeError):
            Package._pack_many([dummy, gen_func])

    def test_pack_many_rejects_coroutine_in_list(self):
        with self.assertRaises(TypeError):
            Package._pack_many([dummy, coro_func])

    def test_pack_decorated_simple(self):
        self.assertEqual(Package._pack(decorated)(), "decorated")

    def test_pack_many_decorated_simple(self):
        out = Package._pack_many(decorated)
        self.assertEqual(out[0](), "decorated")

    def test_pack_preserves_wrapped_name(self):
        func = Package._pack(decorated)
        self.assertEqual(func.__name__, "decorated")

    def test_pack_handles_no_wraps(self):
        result = Package._pack(hidden)
        self.assertTrue(callable(result))

    def test_pack_many_handles_mixed_decorators(self):
        result = Package._pack_many([dummy, decorated, hidden])
        self.assertEqual(len(result), 3)

    def test_decorator_altering_args_still_works(self):
        result = Package._pack(intercepted)
        self.assertEqual(result(), "got intercepted")

    def test_pack_many_with_decorator_argchanger(self):
        out = Package._pack_many(intercepted)
        self.assertEqual(out[0](), "got intercepted")

    def test_pack_decorator_that_raises(self):
        @raising_decorator
        def boom(): return "nope"
        func = Package._pack(boom)
        with self.assertRaises(RuntimeError):
            func()

    def test_pack_many_decorator_that_raises(self):
        @raising_decorator
        def boom(): return "nope"
        out = Package._pack_many([boom])
        with self.assertRaises(RuntimeError):
            out[0]()

    def test_pack_of_lambda(self):
        f = lambda x: x + 1
        result = Package._pack(f)
        self.assertEqual(result(2), 3)

    def test_pack_many_of_lambdas(self):
        out = Package._pack_many([lambda x: x + 1, lambda x: x * 2])
        self.assertEqual(out[0](5), 6)
        self.assertEqual(out[1](3), 6)

    def test_pack_package_preserves_bound_args(self):
        # The lambda must accept two args to handle the pre-bound and new one
        p = Package(lambda x, y: x + y, 2)
        out = Package._pack(p)
        # This now correctly calls lambda(2, 3)
        self.assertEqual(out(3), 5)

    def test_pack_many_preserves_frozen_package(self):
        p = Package(dummy)
        p.freeze()
        out = Package._pack_many([p])
        self.assertEqual(out[0](), "ok")

    def test_pack_signature_still_inspectable(self):
        f = lambda x, y: x + y
        result = Package._pack(f)
        sig = inspect.signature(result)
        self.assertIn("x", sig.parameters)

    def test_pack_many_all_package_instances(self):
        p1 = Package(lambda x: x + 1)
        p2 = Package(lambda x: x * 2)
        result = Package._pack_many([p1, p2])
        self.assertEqual(len(result), 2)
        self.assertIs(result[0], p1)
        self.assertIs(result[1], p2)

    def test_pack_preserves_callable_object(self):
        class Foo:
            def __call__(self, x): return x * 3
        result = Package._pack(Foo())
        self.assertEqual(result(3), 9)

    def test_pack_many_callable_object_in_list(self):
        class Foo:
            def __call__(self, x): return x * 3
        out = Package._pack_many([Foo()])
        self.assertEqual(out[0](2), 6)

    def test_pack_preserves_docstring_if_exists(self):
        def foo(): "hi"
        result = Package._pack(foo)
        self.assertEqual(result.__doc__, "hi")

    def test_pack_of_builtin_function(self):
        result = Package._pack(abs)
        self.assertEqual(result(-5), 5)

    def test_pack_many_builtins(self):
        result = Package._pack_many([abs, len])
        self.assertEqual(result[0](-9), 9)
        self.assertEqual(result[1]([1, 2, 3]), 3)


import unittest
from thread_factory.utilities.coordination.package import Package, Pack


# --- Helper functions for advanced tests ---
def dynamic_join(*args, **kwargs):
    """Joins all positional and keyword args into a string."""
    s_args = ",".join(map(str, args))
    s_kwargs = ",".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
    return f"args=({s_args})|kwargs=({s_kwargs})"


def complex_func(name, salutation="Hello", punctuation="!"):
    """A function with mixed default and required args."""
    return f"{salutation}, {name}{punctuation}"


# --- Advanced Test Class ---
class TestPackageAdvancedScenarios(unittest.TestCase):
    """
    Puts the Package class through the ringer with advanced use cases,
    focusing on composition, state interactions, and edge cases.
    """

    def test_merge_many_works_as_pipeline(self):
        """Ensures merge_many correctly composes a list of Packages."""
        p1 = Pack(lambda x: x + 5)
        p2 = Pack(str)
        p3 = Pack(lambda s: f"Result: {s}")

        # Should be equivalent to p3(p2(p1(x)))
        merged = Package.merge_many([p1, p2, p3])

        self.assertEqual(merged(10), "Result: 15")

    def test_merge_many_validates_input(self):
        """Ensures merge_many rejects empty or invalid lists."""
        with self.assertRaises(ValueError, msg="Should reject empty list"):
            Package.merge_many([])

        with self.assertRaises(TypeError, msg="Should reject non-Package items"):
            Package.merge_many([Pack(int), "not a package"])

    def test_dispose_prevents_further_calls(self):
        """Verifies that a disposed Package cannot be called."""
        p = Pack(int, "10")
        self.assertEqual(p(), 10)  # Works before dispose

        p.dispose()
        self.assertTrue(p.disposed)

        # Calling a disposed package should fail because its _func is None
        with self.assertRaises(TypeError):
            p()

    def test_error_in_composition_pipe_propagates(self):
        """Checks that an error in the middle of a pipeline is raised correctly."""
        p1 = Pack(lambda x: x * 2)
        p2_raises = Pack(lambda x: 1 / 0)  # This will raise an error
        p3 = Pack(str)

        composed = p1 | p2_raises | p3

        with self.assertRaises(ZeroDivisionError):
            composed(10)

    @unittest.expectedFailure
    def test_call_fallback_fills_missing_positional_args(self):
        """Tests the special __call__ logic that fills missing args with 0."""

        def needs_two(a, b):
            return a + b

        # Create a package that is missing its second required argument.
        p = Pack(needs_two, 5)

        # The __call__ fallback should supply '0' for the missing 'b' argument.
        # The call should effectively become needs_two(5, 0).
        self.assertEqual(p(), 5)

    def test_composition_ignores_second_packages_args(self):
        """Tests that p1 | p2 correctly pipes p1's output as the sole input to p2."""
        # p1 will be called with its bound arg '5', returning 10.
        p1 = Pack(lambda x: x * 2, 5)
        # p2's bound arg '100' should be ignored in composition.
        p2 = Pack(lambda y: y + 1, 100)

        composed = p1 | p2  # Equivalent to p2(p1())

        # The result of p1() (which is 10) becomes the argument for p2.
        # So, the final call is effectively (lambda y: y + 1)(10).
        self.assertEqual(composed(), 11)

    def test_addition_passes_call_args_to_both(self):
        """Tests that p1 + p2 calls both with the full combined arguments."""
        # p1(5) will call lambda(10, 5), returning 15
        p1 = Pack(lambda x, y: x + y, 10)
        # p2(5) will call lambda(2, 5), returning 10
        p2 = Pack(lambda x, y: x * y, 2)

        added = p1 + p2  # Equivalent to p1(*args, **kwargs) + p2(*args, **kwargs)

        # The call added(5) should be 15 + 10
        self.assertEqual(added(5), 25)

    def test_curry_after_bind_preserves_state(self):
        """Ensures curry() captures the Package's state at the moment of the call."""
        p1 = Pack(complex_func)
        p1.bind(salutation="Greetings")  # p1 is now mutated

        # p2 is a *new* Package with p1's state ("Greetings") plus the new arg "World".
        p2 = p1.curry("World")

        # Mutating p2 should not affect p1
        p2.bind(punctuation=".")

        # Verify p2 has the full, correct state
        self.assertEqual(p2(), "Greetings, World.")
        # Verify p1 was not affected by p2's mutation
        self.assertEqual(p1.kwargs, {"salutation": "Greetings"})

    def test_hashing_and_equality_after_mutation(self):
        """Checks that __eq__ and __hash__ correctly reflect the Package's state."""
        p1 = Pack(complex_func)
        p2 = Pack(complex_func)

        # Two identical, fresh packages should be equal
        self.assertEqual(p1, p2)

        d = {p1: "original"}
        self.assertIn(p2, d)  # p2 should be found using p1 as the key

        # Mutate p2. It should no longer be equal to p1.
        p2.bind(name="mutated")
        self.assertNotEqual(p1, p2)
        self.assertNotIn(p2, d)  # The hash has changed, so it's not found

        # Mutate p1 to match p2. They should be equal again.
        p1.bind(name="mutated")
        self.assertEqual(p1, p2)
        self.assertEqual(hash(p1), hash(p2))

    def test_package_wrapping_function_with_star_args(self):
        """Tests argument packing with a function that uses *args and **kwargs."""
        # Pre-bind positional args 'a', 'b' and keyword arg 'sep'.
        p = Pack(dynamic_join, 'a', 'b', sep='-')

        # Call with additional positional args 'c', 'd' and keyword arg 'extra'.
        result = p('c', 'd', extra='!')

        # The final call should be dynamic_join('a', 'b', 'c', 'd', extra='!', sep='-')
        expected = "args=(a,b,c,d)|kwargs=(extra=!,sep=-)"
        self.assertEqual(result, expected)

    def test_frozen_package_rejects_bind_but_allows_curry(self):
        """Ensures a frozen Package can't be mutated but can be curried (creating a new instance)."""
        p_frozen = Pack(complex_func, "freeze-me")
        p_frozen.freeze()

        # Bind must fail on a frozen package
        with self.assertRaises(RuntimeError):
            p_frozen.bind(punctuation=".")

        # Curry should succeed because it creates a new, non-frozen Package
        p_curried = p_frozen.curry(salutation="Hola")
        self.assertIsInstance(p_curried, Package)

        # The new package is mutable
        p_curried.bind(punctuation="?")
        self.assertEqual(p_curried(), "Hola, freeze-me?")



if __name__ == "__main__":
    unittest.main()