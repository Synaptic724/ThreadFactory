import inspect
import unittest
from functools import wraps
from thread_factory.utils.coordination.package import Pack


def simple_decorator(f):
    def wrapper(*a, **k): return f(*a, **k)
    return wrapper

def good_decorator(f):
    @wraps(f)
    def wrapper(*a, **k): return f(*a, **k)
    return wrapper

def async_decorator(f):
    async def wrapper(*a, **k): return await f(*a, **k)
    return wrapper


class TestPackDecorators(unittest.TestCase):

    def test_good_decorator_is_wrapped_clean(self):
        @good_decorator
        def greet(name): return f"hi {name}"

        p = Pack(greet, "Mark")  # ← pre-bind one positional argument
        self.assertEqual(p(), "hi Mark")  # call with no extras, still works
        self.assertIn("arg0", p.signature.arguments)  # now arg0 exists

    def test_bad_decorator_still_executes(self):
        """
        Test that a function with a non-@wraps decorator still executes under Pack.
        Signature will reflect the wrapper, not the original.
        """

        @simple_decorator
        def shout(name): return f"yo {name}"

        p = Pack(shout)
        self.assertEqual(p("Zen"), "yo Zen")

        sig = inspect.signature(p._func)
        self.assertIsInstance(sig, inspect.Signature)

        # Decorator wrapper has parameters *a, **k (as named)
        self.assertIn("a", sig.parameters)
        self.assertIn("k", sig.parameters)

        # Ensure their kinds are VAR_POSITIONAL and VAR_KEYWORD
        self.assertEqual(sig.parameters["a"].kind, inspect.Parameter.VAR_POSITIONAL)
        self.assertEqual(sig.parameters["k"].kind, inspect.Parameter.VAR_KEYWORD)


    def test_double_decorated_still_works(self):
        @good_decorator
        @simple_decorator
        def echo(x): return x

        p = Pack(echo)
        self.assertEqual(p("sound"), "sound")

    def test_async_decorated_function_rejected(self):
        async def coro(x): return x
        wrapped = async_decorator(coro)

        with self.assertRaises(TypeError):
            _ = Pack(wrapped)

    def test_decorator_without_wrapping_name_fallback(self):
        @simple_decorator
        def greet(name): return f"hello {name}"

        p = Pack(greet)
        self.assertTrue(callable(p))
        self.assertEqual(p("Neo"), "hello Neo")

    def test_plain_function_works(self):
        def double(x): return x * 2
        p = Pack(double)
        self.assertEqual(p(10), 20)


if __name__ == "__main__":
    unittest.main()
