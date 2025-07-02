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

        p = Pack(greet)
        self.assertEqual(p("Mark"), "hi Mark")
        self.assertIn("arg0", p.signature.arguments)

    def test_bad_decorator_still_executes(self):
        @simple_decorator
        def shout(name): return f"yo {name}"

        p = Pack(shout)
        self.assertEqual(p("Zen"), "yo Zen")
        # But signature will not be introspectable — that’s user risk
        with self.assertRaises(ValueError):
            _ = inspect.signature(p._func).parameters

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
