import unittest
from thread_factory.utilities.coordination.package import Package


def sample_func(a, b=0, c=0):
    return f"{a},{b},{c}"


class TestPackageOverrides(unittest.TestCase):

    def test_bind_args_overrides_positional_arguments(self):
        p = Package(sample_func, 1, 2)
        p.bind_args(10, 20)
        self.assertEqual(p(), "10,20,0")

    def test_bind_kwargs_overrides_keyword_arguments(self):
        p = Package(sample_func, 1)
        p.bind(c=42)
        self.assertEqual(p(), "1,0,42")

    def test_override_replaces_args_and_kwargs(self):
        p = Package(sample_func, 5, 6, c=7)
        p.override(100, 200, c=300)
        self.assertEqual(p(), "100,200,300")

    def test_override_only_args(self):
        p = Package(sample_func, 1, 2)
        p.override(9, 8)
        self.assertEqual(p(), "9,8,0")

    def test_override_only_kwargs(self):
        def sample_func(a, b=0, c=0): return f"{a},{b},{c}"

        p = Package(sample_func, 1, 2, 3)
        p.override(1, c=99)  # explicitly keep a=1
        self.assertEqual(p(), "1,0,99")  # b reset to 0

    def test_override_resets_previous_state(self):
        p = Package(sample_func, 3, 4, c=5)
        p.override(7)
        self.assertEqual(p(), "7,0,0")

    def test_override_respects_freeze(self):
        p = Package(sample_func, 1, 2)
        p.freeze()
        with self.assertRaises(RuntimeError):
            p.override(9, 8)

    def test_bind_args_respects_freeze(self):
        p = Package(sample_func, 1)
        p.freeze()
        with self.assertRaises(RuntimeError):
            p.bind_args(5)

    def test_bind_respects_freeze(self):
        p = Package(sample_func, 1)
        p.freeze()
        with self.assertRaises(RuntimeError):
            p.bind(c=3)

if __name__ == "__main__":
    unittest.main()