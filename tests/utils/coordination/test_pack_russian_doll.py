import unittest
import threading
from typing import Any, Callable, List, Dict, Tuple, Iterable, Union, Optional

# Assuming Pack is correctly imported from your project
from thread_factory.utilities.coordination.package import Pack


# --- Test Functions (the "dolls") ---

def innermost_func(val1: int, val2: int, multiplier: int = 1, offset: int = 0) -> int:
    """
    The innermost function. Performs a calculation based on its inputs.
    """
    return (val1 + val2) * multiplier + offset

def middle_func(inner_pack: Pack, factor: int = 1, add_on: int = 0) -> int:
    """
    The middle function. Takes an inner Pack *object*, calls it, and processes its result.
    """
    inner_result = inner_pack() # Call the inner Pack here
    return inner_result * factor + add_on

def outermost_func(middle_pack: Pack, final_divisor: int = 1, final_offset: int = 0) -> float:
    """
    The outermost function. Takes a middle Pack *object*, calls it, and performs a final calculation.
    """
    middle_result = middle_pack() # Call the middle Pack here
    if final_divisor == 0:
        raise ValueError("Final divisor cannot be zero.")
    return (middle_result + final_offset) / final_divisor

def simple_func(a: int, b: int) -> int:
    """A simple function for addition."""
    return a + b

def another_simple_func(x: int, y: int, z: int) -> int:
    """Another simple function for multiplication and addition."""
    return x * y + z

# --- Wrapper Functions to enable deeper nesting of Pack objects ---
# These functions accept a Pack object, call it, and then pass its result
# to a simple function that expects primitive types.

def pack_wrapper_simple_func(inner_pack: Pack, b_val: int) -> int:
    """Wrapper for simple_func that accepts a Pack and calls it."""
    return simple_func(inner_pack(), b_val)

def pack_wrapper_another_simple_func(inner_pack: Pack, y_val: int, z_val: int) -> int:
    """Wrapper for another_simple_func that accepts a Pack and calls it."""
    return another_simple_func(inner_pack(), y_val, z_val)

def pack_wrapper_add_one(inner_pack: Pack) -> int:
    """Simple wrapper to add one to the result of an inner Pack."""
    return inner_pack() + 1

def pack_wrapper_multiply_by_two(inner_pack: Pack) -> int:
    """Simple wrapper to multiply by two the result of an inner Pack."""
    return inner_pack() * 2

def pack_wrapper_negate(inner_pack: Pack) -> int:
    """Simple wrapper to negate the result of an inner Pack."""
    return -inner_pack()

def pack_wrapper_divide_by_constant(inner_pack: Pack, divisor: int) -> float:
    """Simple wrapper to divide the result of an inner Pack by a constant."""
    if divisor == 0:
        raise ValueError("Divisor cannot be zero.")
    return inner_pack() / divisor


# --- Russian Doll Test Case ---

class TestPackRussianDoll(unittest.TestCase):

    # Test 1: Basic 3-layer nesting (original test, fits criteria)
    def test_russian_doll_nesting_no_bind_curry(self):
        """
        Tests multi-layer nesting of Pack instances by passing Pack objects
        to the next layer's callable, which then calls the nested Pack.
        """
        # 1. Innermost Pack: innermost_func(10, 5, multiplier=2, offset=1)
        #    Result: (10 + 5) * 2 + 1 = 31
        pack_innermost = Pack(innermost_func, 10, 5, multiplier=2, offset=1)
        self.assertEqual(pack_innermost(), 31)

        # 2. Middle Pack: middle_func(inner_pack=pack_innermost, factor=3, add_on=2)
        #    middle_func will call pack_innermost() internally.
        #    Result: 31 * 3 + 2 = 95
        pack_middle = Pack(middle_func, pack_innermost, factor=3, add_on=2)
        self.assertEqual(pack_middle(), 95)

        # 3. Outermost Pack: outermost_func(middle_pack=pack_middle, final_divisor=5, final_offset=5)
        #    outermost_func will call pack_middle() internally.
        #    Result: (95 + 5) / 5 = 20.0
        pack_outermost = Pack(outermost_func, pack_middle, final_divisor=5, final_offset=5)
        self.assertEqual(pack_outermost(), 20.0)

        pack_outermost.cleanup()
        pack_middle.cleanup()
        pack_innermost.cleanup()
        self.assertTrue(pack_outermost.cleaned)
        self.assertTrue(pack_middle.cleaned)
        self.assertTrue(pack_innermost.cleaned)

    # Test 2: Two layers with positional args using wrapper
    def test_two_layers_positional_using_wrapper(self):
        """
        Tests two layers of nesting with positional arguments,
        using a wrapper function to call the inner Pack.
        """
        # Inner: simple_func(10, 20) -> 30
        pack_inner = Pack(simple_func, 10, 20)
        self.assertEqual(pack_inner(), 30)

        # Outer: pack_wrapper_another_simple_func(inner_pack=pack_inner, y_val=3, z_val=5)
        # pack_wrapper_another_simple_func will call pack_inner() internally.
        # Result: (30 * 3) + 5 = 95
        pack_outer = Pack(pack_wrapper_another_simple_func, pack_inner, 3, 5)
        self.assertEqual(pack_outer(), 95)

        pack_outer.cleanup()
        pack_inner.cleanup()
        self.assertTrue(pack_outer.cleaned)
        self.assertTrue(pack_inner.cleaned)

    # Test 3: Two layers with keyword args using wrapper
    def test_two_layers_keyword_using_wrapper(self):
        """
        Tests two layers of nesting with keyword arguments,
        using a wrapper function to call the inner Pack.
        """
        # Inner: simple_func(a=10, b=20) -> 30
        pack_inner = Pack(simple_func, a=10, b=20)
        self.assertEqual(pack_inner(), 30)

        # Outer: pack_wrapper_another_simple_func(inner_pack=pack_inner, y_val=3, z_val=5)
        # pack_wrapper_another_simple_func will call pack_inner() internally.
        # Result: (30 * 3) + 5 = 95
        pack_outer = Pack(pack_wrapper_another_simple_func, inner_pack=pack_inner, y_val=3, z_val=5)
        self.assertEqual(pack_outer(), 95)

        pack_outer.cleanup()
        pack_inner.cleanup()
        self.assertTrue(pack_outer.cleaned)
        self.assertTrue(pack_inner.cleaned)

    # Test 4: Deep nesting with mixed args using wrappers
    def test_deep_nesting_with_mixed_args_and_wrappers(self):
        """
        Tests deep nesting with a mix of positional and keyword arguments at each level,
        using wrapper functions to call nested Pack objects.
        """
        # Level 1: Innermost
        # innermost_func(val1=2, val2=3, multiplier=4, offset=1) -> (2+3)*4+1 = 5*4+1 = 21
        pack1 = Pack(innermost_func, 2, val2=3, multiplier=4, offset=1)
        self.assertEqual(pack1(), 21)

        # Level 2: Middle
        # middle_func(inner_pack=pack1, factor=2, add_on=10) -> 21 * 2 + 10 = 52
        pack2 = Pack(middle_func, pack1, factor=2, add_on=10)
        self.assertEqual(pack2(), 52)

        # Level 3: Outermost
        # outermost_func(middle_pack=pack2, final_divisor=2, final_offset=-2) -> (52 - 2) / 2 = 25.0
        pack3 = Pack(outermost_func, pack2, final_divisor=2, final_offset=-2)
        self.assertEqual(pack3(), 25.0)

        # Level 4: Wrapper for simple_func
        # pack_wrapper_simple_func(inner_pack=pack3, b_val=75) -> 25.0 + 75 = 100.0
        pack4 = Pack(pack_wrapper_simple_func, pack3, 75)
        self.assertEqual(pack4(), 100.0)

        # Level 5: Wrapper for another_simple_func
        # pack_wrapper_another_simple_func(inner_pack=pack4, y_val=2, z_val=0) -> 100.0 * 2 + 0 = 200.0
        pack5 = Pack(pack_wrapper_another_simple_func, pack4, 2, 0)
        self.assertEqual(pack5(), 200.0)

        pack5.cleanup()
        pack4.cleanup()
        pack3.cleanup()
        pack2.cleanup()
        pack1.cleanup()
        self.assertTrue(pack5.cleaned)
        self.assertTrue(pack4.cleaned)
        self.assertTrue(pack3.cleaned)
        self.assertTrue(pack2.cleaned)
        self.assertTrue(pack1.cleaned)

    # Test 5: Nesting with a no-argument function
    def test_nested_pack_with_no_args_function(self):
        """
        Tests nesting where one of the functions takes no arguments,
        passing Pack objects.
        """
        def no_arg_func():
            return 42

        # Innermost: no_arg_func() -> 42
        pack_no_arg = Pack(no_arg_func)
        self.assertEqual(pack_no_arg(), 42)

        # Middle: middle_func(inner_pack=pack_no_arg, factor=10, add_on=8) -> 42 * 10 + 8 = 428
        pack_middle = Pack(middle_func, pack_no_arg, factor=10, add_on=8)
        self.assertEqual(pack_middle(), 428)

        pack_middle.cleanup()
        pack_no_arg.cleanup()
        self.assertTrue(pack_middle.cleaned)
        self.assertTrue(pack_no_arg.cleaned)

    # Test 6: Error propagation through nested Packs
    def test_error_propagation_through_nested_packs(self):
        """
        Tests that exceptions raised in an inner Pack's callable propagate correctly
        when the inner Pack is passed as an object and called later.
        """
        def func_that_fails(x: int):
            if x < 0:
                raise ValueError("Negative input not allowed!")
            return x * 2

        # Innermost pack that will fail when called
        pack_failing_inner = Pack(func_that_fails, -5)

        # Middle pack that calls the failing inner pack
        # Pass the Pack object itself, not its immediate (failing) result
        pack_middle_wrapper = Pack(middle_func, pack_failing_inner, factor=1, add_on=0)

        # Outermost pack that calls the middle pack
        # Pass the Pack object itself
        pack_outer_wrapper = Pack(outermost_func, pack_middle_wrapper, final_divisor=1, final_offset=0)

        # The error should only be raised when pack_outer_wrapper() is called,
        # which triggers middle_func(), which triggers func_that_fails().
        with self.assertRaisesRegex(ValueError, "Negative input not allowed!"):
            pack_outer_wrapper()

        pack_outer_wrapper.cleanup()
        pack_middle_wrapper.cleanup()
        pack_failing_inner.cleanup()
        self.assertTrue(pack_outer_wrapper.cleaned)
        self.assertTrue(pack_middle_wrapper.cleaned)
        self.assertTrue(pack_failing_inner.cleaned)

    # Test 7: Nesting with default arguments
    def test_nested_packs_with_default_args(self):
        """
        Tests that default arguments are correctly used when not overridden by Pack,
        and inner Packs are passed as objects.
        """
        # Innermost: innermost_func(1, 1) -> (1+1)*1+0 = 2 (all defaults for multiplier, offset)
        pack_inner = Pack(innermost_func, 1, 1)
        self.assertEqual(pack_inner(), 2)

        # Middle: middle_func(inner_pack=pack_inner) -> 2 * 1 + 0 = 2 (all defaults for factor, add_on)
        pack_middle = Pack(middle_func, pack_inner)
        self.assertEqual(pack_middle(), 2)

        # Outermost: outermost_func(middle_pack=pack_middle) -> (2 + 0) / 1 = 2.0 (all defaults for final_divisor, final_offset)
        pack_outer = Pack(outermost_func, pack_middle)
        self.assertEqual(pack_outer(), 2.0)

        pack_outer.cleanup()
        pack_middle.cleanup()
        pack_inner.cleanup()
        self.assertTrue(pack_outer.cleaned)
        self.assertTrue(pack_middle.cleaned)
        self.assertTrue(pack_inner.cleaned)

    # Test 8: 4-layer nesting with simple arithmetic wrappers
    def test_four_layer_arithmetic_nesting(self):
        """
        Tests a 4-layer nesting using simple arithmetic wrapper functions.
        """
        # Layer 1: innermost_func(1, 2) -> 3
        pack1 = Pack(innermost_func, 1, 2)
        self.assertEqual(pack1(), 3)

        # Layer 2: pack_wrapper_add_one(pack1) -> 3 + 1 = 4
        pack2 = Pack(pack_wrapper_add_one, pack1)
        self.assertEqual(pack2(), 4)

        # Layer 3: pack_wrapper_multiply_by_two(pack2) -> 4 * 2 = 8
        pack3 = Pack(pack_wrapper_multiply_by_two, pack2)
        self.assertEqual(pack3(), 8)

        # Layer 4: pack_wrapper_negate(pack3) -> -8
        pack4 = Pack(pack_wrapper_negate, pack3)
        self.assertEqual(pack4(), -8)

        pack4.cleanup()
        pack3.cleanup()
        pack2.cleanup()
        pack1.cleanup()
        self.assertTrue(pack4.cleaned)
        self.assertTrue(pack3.cleaned)
        self.assertTrue(pack2.cleaned)
        self.assertTrue(pack1.cleaned)

    # Test 9: Mixed positional and keyword args across 3 layers
    def test_mixed_args_three_layers(self):
        """
        Tests 3-layer nesting with a mix of positional and keyword arguments.
        """
        # Layer 1: innermost_func(5, 5, multiplier=3) -> (5+5)*3 = 30
        pack1 = Pack(innermost_func, 5, 5, multiplier=3)
        self.assertEqual(pack1(), 30)

        # Layer 2: middle_func(pack1, add_on=10) -> 30 * 1 + 10 = 40 (factor defaults to 1)
        pack2 = Pack(middle_func, pack1, add_on=10)
        self.assertEqual(pack2(), 40)

        # Layer 3: outermost_func(pack2, final_offset=20, final_divisor=4) -> (40 + 20) / 4 = 15.0
        pack3 = Pack(outermost_func, pack2, final_offset=20, final_divisor=4)
        self.assertEqual(pack3(), 15.0)

        pack3.cleanup()
        pack2.cleanup()
        pack1.cleanup()
        self.assertTrue(pack3.cleaned)
        self.assertTrue(pack2.cleaned)
        self.assertTrue(pack1.cleaned)

    # Test 10: Complex 5-layer chain with different wrappers
    def test_complex_five_layer_chain(self):
        """
        Tests a complex 5-layer chain using various wrapper functions.
        """
        # Layer 1: innermost_func(1, 1) -> 2
        pack1 = Pack(innermost_func, 1, 1)
        self.assertEqual(pack1(), 2)

        # Layer 2: pack_wrapper_multiply_by_two(pack1) -> 2 * 2 = 4
        pack2 = Pack(pack_wrapper_multiply_by_two, pack1)
        self.assertEqual(pack2(), 4)

        # Layer 3: pack_wrapper_add_one(pack2) -> 4 + 1 = 5
        pack3 = Pack(pack_wrapper_add_one, pack2)
        self.assertEqual(pack3(), 5)

        # Layer 4: pack_wrapper_divide_by_constant(pack3, 2) -> 5 / 2 = 2.5
        pack4 = Pack(pack_wrapper_divide_by_constant, pack3, 2)
        self.assertEqual(pack4(), 2.5)

        # Layer 5: pack_wrapper_negate(pack4) -> -2.5
        pack5 = Pack(pack_wrapper_negate, pack4)
        self.assertEqual(pack5(), -2.5)

        pack5.cleanup()
        pack4.cleanup()
        pack3.cleanup()
        pack2.cleanup()
        pack1.cleanup()
        self.assertTrue(pack5.cleaned)
        self.assertTrue(pack4.cleaned)
        self.assertTrue(pack3.cleaned)
        self.assertTrue(pack2.cleaned)
        self.assertTrue(pack1.cleaned)

if __name__ == '__main__':
    unittest.main()