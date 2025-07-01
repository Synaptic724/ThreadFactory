# test_sync_string_extended.py
import unittest
import threading
import time
import random
from concurrent.futures import ThreadPoolExecutor

# Assuming SyncString is importable from its location
# Adjust this import path based on your project structure
# For example, if your SyncString.py is in a 'my_lib' folder, it might be:
# from my_lib.sync_string import SyncString
from thread_factory.concurrency.value_types.sync_string import SyncString
from thread_factory.utils.interfaces.isync import ISync


class TestSyncStringExtended(unittest.TestCase):

    def setUp(self):
        # Optional: Reset or initialize common objects for each test
        pass

    def tearDown(self):
        # Optional: Clean up after each test
        pass

    # --- New Tests Start Here ---

    def test_getattr_passthrough_behavior_on_complex_method(self):
        s = SyncString("  hello world  ")
        # Test a method that involves both stripping and replacing
        # This confirms __getattr__ correctly wraps the underlying method
        self.assertEqual(s.strip().replace(" ", "-"), "hello-world")
        self.assertEqual(s.strip().upper(), "HELLO WORLD")

    def test_getattr_with_non_existent_method(self):
        s = SyncString("test")
        with self.assertRaises(AttributeError):
            s.non_existent_method()

    def test_concatenation_with_empty_string(self):
        s = SyncString("abc")
        self.assertEqual(s + "", "abc")
        self.assertEqual("" + s, "abc")
        s += ""
        self.assertEqual(s.get(), "abc")

    def test_multiplication_by_zero(self):
        s = SyncString("abc")
        self.assertEqual(s * 0, "")
        self.assertEqual(0 * s, "")
        s *= 0
        self.assertEqual(s.get(), "")

    def test_multiplication_by_negative_number(self):
        s = SyncString("abc")
        self.assertEqual(s * -1, "")
        self.assertEqual(-2 * s, "")
        # In-place multiplication by negative number is also an empty string
        s.set("abc")
        s *= -5
        self.assertEqual(s.get(), "")

    def test_replace_with_empty_string(self):
        s = SyncString("banana")
        self.assertEqual(s.replace("a", ""), "bnn")
        self.assertEqual(s.replace("ban", "foo"), "foona")

    def test_replace_with_max_count(self):
        s = SyncString("aaaaa")
        self.assertEqual(s.replace("a", "b", 2), "bbaaa")
        self.assertEqual(s.replace("a", "b", 0), "aaaaa")

    def test_split_with_empty_separator(self):
        s = SyncString("abc")
        with self.assertRaises(ValueError):
            s.split("")

    def test_split_with_multiple_spaces(self):
        s = SyncString("a   b  c")
        self.assertEqual(s.split(), ["a", "b", "c"])

    def test_split_with_explicit_maxsplit(self):
        s = SyncString("one,two,three,four")
        self.assertEqual(s.split(",", 1), ["one", "two,three,four"])
        self.assertEqual(s.rsplit(",", 1), ["one,two,three", "four"])

    def test_strip_with_specific_chars(self):
        s = SyncString("---hello---")
        self.assertEqual(s.strip("-"), "hello")
        self.assertEqual(s.lstrip("-"), "hello---")
        self.assertEqual(s.rstrip("-"), "---hello")

    def test_find_not_found(self):
        s = SyncString("teststring")
        self.assertEqual(s.find("xyz"), -1)
        self.assertEqual(s.rfind("xyz"), -1)

    def test_index_not_found_raises_error(self):
        s = SyncString("teststring")
        with self.assertRaises(ValueError):
            s.index("xyz")
        with self.assertRaises(ValueError):
            s.rindex("xyz")

    def test_getitem_out_of_bounds(self):
        s = SyncString("abc")
        with self.assertRaises(IndexError):
            _ = s[5]
        with self.assertRaises(IndexError):
            _ = s[-4]

    def test_getitem_slice_step(self):
        s = SyncString("abcdef")
        self.assertEqual(s[::2], "ace")
        self.assertEqual(s[::-1], "fedcba")
        self.assertEqual(s[1:5:2], "bd")

    def test_contains_empty_string(self):
        s = SyncString("abc")
        self.assertTrue("" in s)  # Empty string is always considered in any string

    def test_format_map_with_dict(self):
        s = SyncString("Hello, {name}! Your age is {age}.")
        data = {"name": "Alice", "age": 30}
        self.assertEqual(s.format_map(data), "Hello, Alice! Your age is 30.")

    def test_encode_decode_roundtrip(self):
        s = SyncString("Hello, World!")
        encoded = s.encode("utf-8")
        self.assertEqual(encoded.decode("utf-8"), s.get())

        s_unicode = SyncString("你好世界")
        encoded_unicode = s_unicode.encode("utf-8")
        self.assertEqual(encoded_unicode.decode("utf-8"), s_unicode.get())

    def test_join_empty_iterable(self):
        s = SyncString("-")
        self.assertEqual(s.join([]), "")

    def test_join_single_element_iterable(self):
        s = SyncString("-")
        self.assertEqual(s.join(["hello"]), "hello")

    def test_isidentifier_valid_and_invalid(self):
        self.assertTrue(SyncString("my_var").isidentifier())
        self.assertFalse(SyncString("1var").isidentifier())
        self.assertFalse(SyncString("my-var").isidentifier())
        self.assertFalse(SyncString("if").isidentifier())  # Keywords are not identifiers

    def test_isprintable_with_unprintable_chars(self):
        self.assertTrue(SyncString("hello\nworld").isprintable())  # Newline is printable in Python's str.isprintable
        self.assertFalse(SyncString("hello\x00world").isprintable())  # Null byte is not printable

    def test_maketrans_usage_static_method(self):
        # maketrans is a static method, so we test it directly
        table = SyncString.maketrans("aeiou", "12345")
        s = SyncString("hello world")
        self.assertEqual(s.translate(table), "h2ll4 w5rld")

    def test_partition_no_separator(self):
        s = SyncString("nosplit")
        self.assertEqual(s.partition("-"), ("nosplit", "", ""))
        self.assertEqual(s.rpartition("-"), ("", "", "nosplit"))

    def test_removeprefix_removesuffix(self):
        s = SyncString("prefix_value_suffix")
        self.assertEqual(s.removeprefix("prefix_"), "value_suffix")
        self.assertEqual(s.removesuffix("_suffix"), "prefix_value")
        self.assertEqual(s.removeprefix("nonexistent_"), "prefix_value_suffix")
        self.assertEqual(s.removesuffix("_nonexistent"), "prefix_value_suffix")

    def test_zfill_with_negative_number(self):
        s = SyncString("-123")
        self.assertEqual(s.zfill(5), "-0123")
        self.assertEqual(s.zfill(3), "-123")  # Width less than length, no change

    def test_center_with_fillchar(self):
        s = SyncString("test")
        self.assertEqual(s.center(10, '*'), "***test***")
        self.assertEqual(s.ljust(10, '-'), "test------")
        self.assertEqual(s.rjust(10, '='), "======test")

    def test_expandtabs(self):
        s = SyncString("col1\tcol2\tcol3")
        self.assertEqual(s.expandtabs(4), "col1    col2    col3")
        self.assertEqual(s.expandtabs(1), "col1 col2 col3")

    def test_mod_with_multiple_placeholders(self):
        s = SyncString("Name: %s, Age: %d")
        self.assertEqual(s % ("Bob", 25), "Name: Bob, Age: 25")

    def test_rmod_with_different_types(self):
        s = SyncString("World")
        self.assertEqual("Hello, %s!" % s, "Hello, World!")
        self.assertEqual("%s is %s" % (SyncString("Name"), SyncString("Value")), "Name is Value")

    def test_concatenation_and_type_check(self):
        s = SyncString("val")
        result = s + "ue"
        self.assertIsInstance(result, str)  # Result of + should be a plain str


    def test_imul_thread_safety_stress_scaled(self):
        s = SyncString("A")
        # Reduce the multiplier and repetitions to avoid exponential explosion
        # Goal: final string length = 1 * (3 ^ (5 * 2)) = 3^10 = 59049
        multiplier = 3 # Change from 2 to illustrate a different multiplier
        repetitions_per_thread = 2 # Each thread repeats 2 times
        num_threads = 5 # 5 threads

        def repeat_task():
            nonlocal s
            for _ in range(repetitions_per_thread):
                s *= multiplier # Atomic operation

        threads = [threading.Thread(target=repeat_task) for _ in range(num_threads)]

        start_time = time.time() # Added timing for observation
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        end_time = time.time()

        expected_len = 1 * (multiplier ** (repetitions_per_thread * num_threads))
        self.assertEqual(len(s.get()), expected_len)
        print(f"\nIMUL Stress Test completed in {end_time - start_time:.4f} seconds.")
        print(f"Final string length: {len(s.get())}")
        # Optionally, check content for smaller strings
        # self.assertEqual(s.get(), "A" * expected_len)

    # Similar scaling for __iadd__ test
    def test_iadd_thread_safety_stress_scaled(self):
        s = SyncString("")
        char_to_add = "x"
        adds_per_thread = 100 # Each thread adds 'x' 100 times
        num_threads = 20 # 20 threads

        def append_task():
            nonlocal s
            for _ in range(adds_per_thread):
                s += char_to_add # Atomic operation

        threads = [threading.Thread(target=append_task) for _ in range(num_threads)]

        start_time = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        end_time = time.time()

        expected_length = adds_per_thread * num_threads
        self.assertEqual(len(s.get()), expected_length)
        self.assertTrue(s.get().count(char_to_add) == expected_length)
        print(f"\nIADD Stress Test completed in {end_time - start_time:.4f} seconds.")
        print(f"Final string length: {len(s.get())}")

    def test_iadd_thread_safety_stress(self):
        s = SyncString("")
        char_to_add = "x"
        adds_per_thread = 100
        num_threads = 20

        def append_task():
            nonlocal s
            for _ in range(adds_per_thread):
                s += char_to_add

        threads = [threading.Thread(target=append_task) for _ in range(num_threads)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        expected_length = adds_per_thread * num_threads
        self.assertEqual(len(s.get()), expected_length)
        self.assertTrue(s.get().count(char_to_add) == expected_length)

    def test_concurrent_set_get_multiple_values(self):
        s = SyncString("initial")
        values = [f"value_{i}" for i in range(50)]
        num_threads = 10

        def worker(thread_id):
            for i in range(100):
                # Write a value
                s.set(values[thread_id % len(values)])
                # Read it back immediately (may not be what we just wrote due to other threads)
                _ = s.get()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertIn(s.get(), values)

    def test_concurrent_method_calls(self):
        s = SyncString("hello_world_python")
        num_threads = 10
        iterations = 50

        def worker():
            for _ in range(iterations):
                # Call various read-only methods concurrently
                _ = s.upper()
                _ = s.lower()
                _ = s.count('o')
                _ = s.startswith('hello')
                _ = s.endswith('python')
                _ = s.replace('o', '0')
                _ = len(s)
                _ = 'world' in s
                _ = s[5:10]

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # The final value should remain unchanged as all operations were read-only
        self.assertEqual(s.get(), "hello_world_python")

    def test_concurrent_pickling_unpickling(self):
        import pickle
        s = SyncString("concurrent_pickle")
        num_threads = 5

        def pickle_unpickle_task():
            nonlocal s
            for _ in range(10):
                pickled_s = pickle.dumps(s)
                unpickled_s = pickle.loads(pickled_s)
                self.assertEqual(unpickled_s.get(), s.get())  # Ensure value matches

        threads = [threading.Thread(target=pickle_unpickle_task) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(s.get(), "concurrent_pickle")  # Original should be fine

    def test_concurrent_copying(self):
        s = SyncString("original_value")
        num_threads = 5
        copies_list = []

        def copy_task():
            nonlocal s
            for _ in range(5):
                copied_s = s.__copy__()
                copies_list.append(copied_s)
                deep_copied_s = s.__deepcopy__({})
                copies_list.append(deep_copied_s)

        threads = [threading.Thread(target=copy_task) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(s.get(), "original_value")
        for copied_s in copies_list:
            self.assertEqual(copied_s.get(), "original_value")
            # Ensure copies are distinct objects
            self.assertIsNot(copied_s, s)

    def test_comparison_with_non_string_types(self):
        s = SyncString("123")
        self.assertFalse(s == 123)
        self.assertFalse(s == [1, 2, 3])
        self.assertFalse(s < 100)  # Should still perform comparisons where possible, but for str vs int this is false

    def test_empty_string_methods(self):
        s = SyncString("")
        self.assertEqual(s.get(), "")
        self.assertEqual(s.upper(), "")
        self.assertEqual(s.count("a"), 0)
        self.assertFalse(bool(s))
        self.assertEqual(len(s), 0)
        self.assertEqual(s.split(), [])
        self.assertEqual(s.strip(), "")

    def test_non_string_initialization_type_coercion(self):
        s_int = SyncString(123)
        self.assertEqual(s_int.get(), "123")
        self.assertIsInstance(s_int.get(), str)

        s_float = SyncString(3.14)
        self.assertEqual(s_float.get(), "3.14")

        s_bool = SyncString(True)
        self.assertEqual(s_bool.get(), "True")

    def test_set_non_string_value_coercion(self):
        s = SyncString("initial")
        s.set(12345)
        self.assertEqual(s.get(), "12345")
        s.set(False)
        self.assertEqual(s.get(), "False")

    def test_repr_contains_quotes(self):
        s = SyncString("test_repr")
        self.assertTrue(repr(s).startswith("'") and repr(s).endswith("'") or \
                        repr(s).startswith('"') and repr(s).endswith('"'))
        self.assertIn("test_repr", repr(s))

    def test_strip_none_chars(self):
        s = SyncString("  abc  ")
        # Strip with None or no argument defaults to whitespace
        self.assertEqual(s.strip(None), "abc")
        self.assertEqual(s.lstrip(None), "abc  ")
        self.assertEqual(s.rstrip(None), "  abc")

    def test_multithreaded_getattr_performance(self):
        s = SyncString("a" * 1000)  # Large string to make operations noticeable
        num_threads = 20
        iterations = 1000

        def worker():
            for _ in range(iterations):
                _ = s.count('a')
                _ = s.upper()

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        start_time = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        end_time = time.time()
        # This test is more about not crashing/deadlocking, less about specific performance.
        # But we can add a rough check.
        self.assertLess(end_time - start_time, 2.0)  # Should complete reasonably fast

    def test_thread_safe_iter_consistency(self):
        s = SyncString("0123456789")

        def concurrent_iteration():
            current_value_at_iter_start = s.get()
            # Iterate over the string. This uses the shallow copy.
            iterated_chars = "".join(list(s))
            # The iterated_chars should match the value when iterator was created,
            # even if the SyncString was changed mid-iteration.
            self.assertEqual(iterated_chars, current_value_at_iter_start)

        def modifier():
            # Randomly change the string to a different length or content
            time.sleep(random.uniform(0.001, 0.01))
            s.set(str(random.randint(1000, 999999)))

        threads = []
        for _ in range(5):
            threads.append(threading.Thread(target=concurrent_iteration))
            threads.append(threading.Thread(target=modifier))

        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertIsInstance(s.get(), str)

    def test_thread_safe_contains_consistency(self):
        s = SyncString("apples_bananas_cherries")
        target_substring = "bananas"

        def check_contains():
            for _ in range(50):
                self.assertTrue(target_substring in s)
                time.sleep(0.001)  # Simulate some work

        def modify_string():
            nonlocal s
            for _ in range(50):
                # Ensure the target substring is sometimes present, sometimes not
                if random.random() < 0.5:
                    s.set("apples_bananas_cherries")
                else:
                    s.set("pears_grapes_oranges")
                time.sleep(0.001)

        threads = [
            threading.Thread(target=check_contains),
            threading.Thread(target=modify_string)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # Final state check, it should be one of the two possibilities
        self.assertTrue(s.get() in ["apples_bananas_cherries", "pears_grapes_oranges"])

    def test_isascii_with_various_chars(self):
        self.assertTrue(SyncString("Hello123!@#").isascii())
        self.assertFalse(SyncString("你好").isascii())
        self.assertFalse(SyncString("résumé").isascii())
        self.assertTrue(SyncString("").isascii())

    def test_isdecimal_numeric_digit(self):
        # isdecimal() - only decimal digits
        self.assertTrue(SyncString("123").isdecimal())
        self.assertFalse(SyncString("½").isdecimal())  # Not decimal
        self.assertFalse(SyncString("一").isdecimal())  # Not decimal

        # isdigit() - includes decimal digits, and some others like superscript digits
        self.assertTrue(SyncString("123").isdigit())
        self.assertTrue(SyncString("²").isdigit())  # Superscript 2
        self.assertFalse(SyncString("½").isdigit())  # Still not a digit

        # isnumeric() - includes digits, fractions, subscripts, superscripts, etc.
        self.assertTrue(SyncString("123").isnumeric())
        self.assertTrue(SyncString("½").isnumeric())  # Fraction
        self.assertTrue(SyncString("一").isnumeric())  # Chinese numeral one

    def test_compare_with_none(self):
        s = SyncString("test")
        self.assertFalse(s == None)
        self.assertTrue(s != None)
        with self.assertRaises(TypeError):
            s < None

    def test_add_operation_does_not_modify_original(self):
        s = SyncString("original")
        new_s = s + "_appended"
        self.assertEqual(s.get(), "original")
        self.assertEqual(new_s, "original_appended")

    def test_mul_operation_does_not_modify_original(self):
        s = SyncString("abc")
        new_s = s * 3
        self.assertEqual(s.get(), "abc")
        self.assertEqual(new_s, "abcabcabc")

    def test_init_safe_protection_effectiveness(self):
        # This is hard to "prove" with a simple assertion, but we can try to
        # trigger contention and ensure no errors/race conditions occur
        # that would lead to uninitialized state.
        results = []

        def create_and_check():
            try:
                s = SyncString("initial_value", init_safe=True)
                results.append(s.get())
            except Exception as e:
                results.append(f"Error: {e}")

        threads = [threading.Thread(target=create_and_check) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), 100)
        self.assertTrue(all(val == "initial_value" for val in results))
        self.assertFalse(any("Error:" in val for val in results))

    def test_init_not_safe_behavior_no_central_lock(self):
        # This test ensures that when init_safe=False, the central lock is indeed skipped.
        # It's hard to directly test a lock NOT being used, but we can verify performance
        # or the absence of the central lock's influence if it were to somehow fail.
        # Practically, just confirming it initializes correctly is enough for init_safe=False.
        results = []

        def create_and_check():
            try:
                s = SyncString("fast_init", init_safe=False)
                results.append(s.get())
            except Exception as e:
                results.append(f"Error: {e}")

        threads = [threading.Thread(target=create_and_check) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), 100)
        self.assertTrue(all(val == "fast_init" for val in results))
        self.assertFalse(any("Error:" in val for val in results))

    def test_complex_chained_operations_thread_safety(self):
        s = SyncString("  aBcDeFgH  ")

        def transform_and_check():
            transformed = s.strip().lower().replace("b", "x").capitalize()
            self.assertEqual(transformed, " Axcodefgh")  # Expected result after sequence
            # Note: the original s is unchanged
            self.assertEqual(s.get(), "  aBcDeFgH  ")

        num_threads = 10
        threads = [threading.Thread(target=transform_and_check) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    def test_passing_syncstring_to_function_requiring_str(self):
        s = SyncString("test_value")

        def takes_string(val: str):
            self.assertIsInstance(val, str)
            return len(val)

        self.assertEqual(takes_string(s), 10)  # __str__ is implicitly called or get() for len

        def takes_sync_string(val: SyncString):
            self.assertIsInstance(val, SyncString)
            return val.get()

        self.assertEqual(takes_sync_string(s), "test_value")

    def test_mixed_type_comparisons(self):
        s = SyncString("10")
        self.assertTrue(s == "10")
        self.assertFalse(s == 10)  # String "10" is not equal to integer 10
        self.assertTrue(s < "2")
        self.assertTrue(s > "0")
        self.assertFalse(s == SyncString(10))  # SyncString("10") vs SyncString(10) -> "10" vs "10"

    def test_reverse_iteration_empty(self):
        s = SyncString("")
        self.assertEqual(list(reversed(s)), [])

    def test_reverse_iteration_single_char(self):
        s = SyncString("a")
        self.assertEqual(list(reversed(s)), ['a'])

    def test_complex_slice(self):
        s = SyncString("0123456789")
        self.assertEqual(s[-3:], "789")
        self.assertEqual(s[::3], "0369")
        self.assertEqual(s[7:2:-2], "753")  # Start 7, stop 2 (exclusive), step -2

    def test_format_spec_with_non_string_values(self):
        s = SyncString("Value: {}")
        self.assertEqual(format(s.get(), ".2f").format(3.14159), "Value: 3.14")
        self.assertEqual(format(s.get(), "s").format(123), "Value: 123")

    def test_multiline_string_methods(self):
        s = SyncString("line1\nline2\r\nline3")
        self.assertEqual(s.splitlines(), ["line1", "line2", "line3"])
        self.assertEqual(s.splitlines(keepends=True), ["line1\n", "line2\r\n", "line3"])

    def test_bytes_roundtrip_with_encoding_errors(self):
        s = SyncString("Café")
        self.assertEqual(s.__bytes__().decode('utf-8'), "Café")
        self.assertEqual(s.encode('latin-1').decode('latin-1'), "Café")

        # Test error handling during decode
        s_invalid_utf8 = SyncString(
            b'\xed\xa0\x80'.decode('latin1', errors='ignore'))  # Simulates invalid byte sequence for utf-8
        with self.assertRaises(UnicodeDecodeError):
            # This will fail if not explicitly handled, which is expected for raw str.decode
            # We can't directly test encode from SyncString to invalid encoding without prior decoding
            # (bytes(s) gives utf-8, s.encode allows specifying)
            s.encode('ascii')  # This will raise if 'é' is in string

    def test_pickling_across_versions(self):
        import pickle
        s = SyncString("test_pickle_version")
        # Try pickling with different protocols (if supported/relevant)
        for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
            if protocol >= 2:  # Older protocols might not fully support __reduce__
                try:
                    pickled_data = pickle.dumps(s, protocol=protocol)
                    unpickled_s = pickle.loads(pickled_data)
                    self.assertEqual(unpickled_s.get(), "test_pickle_version")
                    self.assertIsInstance(unpickled_s._lock, threading.RLock)  # Lock should be recreated
                except Exception as e:
                    self.fail(f"Pickling with protocol {protocol} failed: {e}")

    def test_dir_includes_underlying_string_methods(self):
        s = SyncString("test")
        d = dir(s)
        self.assertIn('upper', d)
        self.assertIn('split', d)
        self.assertIn('replace', d)
        self.assertIn('_value', d)  # Should include internal attributes
        self.assertIn('_lock', d)

    def test_getattr_method_binds_to_current_value(self):
        s = SyncString("initial")
        get_upper = s.upper  # Get the wrapped method

        s.set("CHANGED")  # Change the internal value

        # The captured method should operate on the *current* value due to re-fetching
        self.assertEqual(get_upper(), "CHANGED")

    def test_comparison_with_different_syncstring_instances(self):
        s1 = SyncString("alpha")
        s2 = SyncString("beta")
        s3 = SyncString("alpha")

        self.assertTrue(s1 == s3)
        self.assertTrue(s1 != s2)
        self.assertTrue(s1 < s2)
        self.assertTrue(s1 <= s3)
        self.assertTrue(s2 > s1)
        self.assertTrue(s3 >= s1)
        self.assertFalse(s1 == s2)  # Explicitly false

    def test_str_conversion_on_other_for_binary_ops(self):
        s = SyncString("value")
        self.assertEqual(s + 123, "value123")  # int converted to str
        self.assertEqual(s + [1, 2], "value[1, 2]")  # list converted to str
        self.assertEqual(s * 2.5,
                         "")  # float multiplication implicitly converts to int, then fails if not int. str * float is not allowed.
        with self.assertRaises(TypeError):
            s * 2.5  # Expected to raise TypeError, as str does not support float multiplication

    def test_binary_op_coercion_consistency(self):
        s = SyncString("a")
        # Test that _unwrap_other correctly handles SyncString and non-SyncString
        # for various binary operations.
        # Equality
        self.assertTrue(s == SyncString("a"))
        self.assertTrue(s == "a")
        # Addition
        self.assertEqual(s + SyncString("b"), "ab")
        self.assertEqual(s + "b", "ab")
        # Reverse addition
        self.assertEqual(SyncString("b") + s, "ba")
        self.assertEqual("b" + s, "ba")

    def test_len_consistency_under_load(self):
        s = SyncString("a")

        def append_and_check_len():
            nonlocal s
            for i in range(100):
                s += "a"
                length = len(s)
                self.assertGreater(length, 0)  # Ensure it's not unexpectedly empty

        threads = [threading.Thread(target=append_and_check_len) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertGreater(len(s), 500)  # Should be at least initial + 5*100

    def test_concurrent_format_and_mod(self):
        s_format = SyncString("Test: {}")
        s_mod = SyncString("Test: %s")
        values = ["alpha", "beta", "gamma", "delta"]

        def worker_format():
            for val in values:
                result = s_format.format(val)
                self.assertIn(val, result)

        def worker_mod():
            for val in values:
                result = s_mod % val
                self.assertIn(val, result)

        threads = [
            threading.Thread(target=worker_format),
            threading.Thread(target=worker_mod),
            threading.Thread(target=worker_format),
            threading.Thread(target=worker_mod)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

    def test_casefold_unicode(self):
        s = SyncString("Straße")  # German Eszett
        self.assertEqual(s.casefold(), "strasse")
        s2 = SyncString("ẞ")  # Capital sharp s
        self.assertEqual(s2.casefold(), "ss")

    def test_strip_whitespace_variations(self):
        s = SyncString(" \t \n string \r\n ")
        self.assertEqual(s.strip(), "string")
        self.assertEqual(s.lstrip(), "string \r\n ")
        self.assertEqual(s.rstrip(), " \t \n string")

    def test_comparison_with_non_sync_string(self):
        s = SyncString("apple")
        self.assertTrue(s == "apple")
        self.assertFalse(s == "orange")
        self.assertTrue(s > "apricot")
        self.assertFalse(s < "apricot")

    def test_empty_string_to_bytes(self):
        s = SyncString("")
        self.assertEqual(bytes(s), b"")

    def test_string_interpolation_methods(self):
        s = SyncString("{}, {}!")
        self.assertEqual(s.format("Hello", "World"), "Hello, World!")
        s2 = SyncString("%s, %s!")
        self.assertEqual(s2 % ("Hello", "World"), "Hello, World!")

    def test_custom_object_conversion_to_string(self):
        class MyCustomObj:
            def __str__(self):
                return "custom_str"

            def __repr__(self):
                return "custom_repr"

        s = SyncString("prefix_")
        s += MyCustomObj()
        self.assertEqual(s.get(), "prefix_custom_str")

        s.set(MyCustomObj())
        self.assertEqual(s.get(), "custom_str")
        self.assertEqual(repr(s), "custom_repr")

    def test_boolean_evaluation_of_syncstring(self):
        self.assertTrue(bool(SyncString("hello")))
        self.assertFalse(bool(SyncString("")))

    def test_hash_collision_awareness(self):
        s1 = SyncString("test_hash")
        s2 = SyncString("test_hash")
        s3 = SyncString("different")
        self.assertEqual(hash(s1), hash(s2))
        self.assertNotEqual(hash(s1), hash(s3))

    def test_passing_mutable_object_to_methods(self):
        # String methods don't typically take mutable objects that they modify,
        # but ensuring that the SyncString doesn't try to deepcopy/lock them
        # if they are just arguments is good.
        s = SyncString("base")
        mutable_list = ["a", "b", "c"]
        # .join expects iterable of strings
        self.assertEqual(s.join(mutable_list), "a-base-b-base-c")  # Using s as delimiter

    def test_complex_thread_interplay_with_set(self):
        s = SyncString("A")
        num_writers = 5
        num_readers = 5
        iterations = 100

        def writer_task(idx):
            for i in range(iterations):
                s.set(f"Writer_{idx}_Loop_{i}")
                time.sleep(0.001)  # Small delay to increase context switching

        def reader_task(idx):
            for i in range(iterations):
                current_val = s.get()
                self.assertIsInstance(current_val, str)
                self.assertTrue(current_val.startswith("Writer_") or current_val == "A")
                time.sleep(0.001)

        writers = [threading.Thread(target=writer_task, args=(i,)) for i in range(num_writers)]
        readers = [threading.Thread(target=reader_task, args=(i,)) for i in range(num_readers)]

        all_threads = writers + readers
        random.shuffle(all_threads)  # Shuffle to make race conditions more probable

        for t in all_threads:
            t.start()
        for t in all_threads:
            t.join()

        final_val = s.get()
        self.assertTrue(final_val.startswith("Writer_") or final_val == "A")

    def test_long_string_operations_consistency(self):
        long_base = "abcde" * 2000
        s = SyncString(long_base)
        self.assertEqual(len(s), len(long_base))
        self.assertEqual(s.count('c'), 2000)
        self.assertEqual(s.replace('a', 'x', 1), 'x' + long_base[1:])
        self.assertTrue(s.startswith("abcde"))
        self.assertTrue(s.endswith("cde"))

    def test_thread_safe_iter_behavior_with_modification(self):
        s = SyncString("abcdef")
        iterator_start_value = ""

        # Thread 1: Starts iteration, then holds onto the iterator
        def iterator_thread():
            nonlocal iterator_start_value
            with s._lock:  # Acquire lock to get a consistent snapshot for iterator_start_value
                iterator_start_value = s._value
            # Release lock, then iterate. The iteration uses the *copied* value
            # from __iter__, so subsequent changes to s won't affect it.
            time.sleep(0.01)  # Give modifier a chance to run
            iter_result = "".join(list(s))  # This will use the copy from __iter__
            self.assertEqual(iter_result, iterator_start_value)

        # Thread 2: Modifies the SyncString after the iterator thread started
        def modifier_thread():
            time.sleep(0.005)  # Ensure iterator_thread starts first
            s.set("xyz")

        t1 = threading.Thread(target=iterator_thread)
        t2 = threading.Thread(target=modifier_thread)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(s.get(), "xyz")  # Final state is modified

    def test_binary_op_with_empty_syncstring(self):
        s1 = SyncString("")
        s2 = SyncString("test")

        self.assertEqual(s1 + s2, "test")
        self.assertEqual(s2 + s1, "test")
        self.assertEqual(s1 * 5, "")
        self.assertTrue(s1 == "")
        self.assertFalse(s1 == s2)

    def test_unicode_case_methods(self):
        s = SyncString("Grüß Gott")
        self.assertEqual(s.upper(), "GRÜSS GOTT")  # Ü becomes Ü
        self.assertEqual(s.lower(), "grüß gott")  # ß remains ß
        self.assertEqual(s.capitalize(), "Grüß gott")
        self.assertEqual(s.title(), "Grüß Gott")

    def test_imul_large_multiplier(self):
        s = SyncString("a")
        s *= 10000
        self.assertEqual(len(s), 10000)
        self.assertEqual(s.get(), "a" * 10000)

    def test_iadd_large_string(self):
        s = SyncString("start_")
        s += "x" * 100000
        self.assertEqual(len(s), len("start_") + 100000)
        self.assertTrue(s.endswith("x" * 10000))

    def test_deadlock_prevention_on_iadd(self):
        s1 = SyncString("A")
        s2 = SyncString("B")

        barrier = threading.Barrier(2)
        exceptions = []

        def task1():
            nonlocal s1
            try:
                barrier.wait()
                for _ in range(100):
                    s1 += s2.get()  # s1 locks, then s2.get() locks s2
            except Exception as e:
                exceptions.append(e)

        def task2():
            nonlocal s2
            try:
                barrier.wait()
                for _ in range(100):
                    s2 += s1.get()  # s2 locks, then s1.get() locks s1
            except Exception as e:
                exceptions.append(e)

        t1 = threading.Thread(target=task1)
        t2 = threading.Thread(target=task2)

        t1.start()
        t2.start()

        t1.join(timeout=5)
        t2.join(timeout=5)

        self.assertFalse(t1.is_alive(), "Thread 1 deadlocked or timed out")
        self.assertFalse(t2.is_alive(), "Thread 2 deadlocked or timed out")
        self.assertEqual(exceptions, [], "Threads raised exceptions")

    def test_deadlock_prevention_with_binary_op_and_get(self):
        s1 = SyncString("x")
        s2 = SyncString("y")

        barrier = threading.Barrier(2)
        exceptions = []

        def task1():
            try:
                barrier.wait()
                for _ in range(100):
                    _ = s1 == s2  # Calls _perform_binary_op, handles locking
            except Exception as e:
                exceptions.append(e)

        def task2():
            try:
                barrier.wait()
                for _ in range(100):
                    _ = s2.get() + s1.get()  # Explicitly calls get() which acquires lock
            except Exception as e:
                exceptions.append(e)

        t1 = threading.Thread(target=task1)
        t2 = threading.Thread(target=task2)

        t1.start()
        t2.start()

        t1.join(timeout=5)
        t2.join(timeout=5)

        self.assertFalse(t1.is_alive(), "Thread 1 deadlocked or timed out")
        self.assertFalse(t2.is_alive(), "Thread 2 deadlocked or timed out")
        self.assertEqual(exceptions, [], "Threads raised exceptions")

    def test_recursive_lock_acquisition_in_same_thread(self):
        s = SyncString("test")

        # An RLock allows the same thread to acquire it multiple times.
        # This test ensures that operations within the same thread that
        # implicitly re-acquire the lock (e.g., calling get() from within a set()
        # if such a thing happened, or chaining methods that internally call
        # other SyncString methods) do not deadlock.
        # While not directly demonstrating a common deadlock, it confirms RLock behavior.
        with s._lock:
            s.set("first_level")
            with s._lock:
                self.assertEqual(s.get(), "first_level")
                s.set("second_level")
                self.assertEqual(s.get(), "second_level")
        self.assertEqual(s.get(), "second_level")  # Final state after all releases

    def test_getattr_passthrough_for_non_string_methods_that_might_exist(self):
        # If the _value was a custom object with a 'custom_method', __getattr__ should forward it.
        # Since _value is always str, this primarily tests the forwarding mechanism.
        s = SyncString("hello")
        self.assertTrue(callable(s.count))
        self.assertEqual(s.count('l'), 2)
        # Test a method which may not be defined by str, but the fallback handles it gracefully.
        # No lock here for the initial getattr call.
        with self.assertRaises(AttributeError):
            s.nonexistent_str_method()

    def test_comparison_against_non_string_sync_type(self):
        # This assumes you might have other ISync types, e.g., SyncInt.
        # If SyncInt existed, SyncString("5") == SyncInt(5) should be false by default
        # unless explicit coercion rules allow it.
        class MockSyncInt(ISync):
            __slots__ = ["_value", "_lock"]

            def __init__(self, initial: int):
                self._value = initial
                self._lock = threading.RLock()

            def get(self):
                return self._value

            @classmethod
            def _coerce(cls, val):
                return int(val)

        s = SyncString("5")
        mock_int = MockSyncInt(5)

        # String "5" is not equal to int 5, so the comparison should be false.
        # _perform_binary_op will attempt to unwrap mock_int to its scalar (5),
        # then compare str("5") with int(5), which results in False.
        self.assertFalse(s == mock_int)
        self.assertFalse(mock_int == s)  # Test reverse order too

    def test_iteration_order(self):
        s = SyncString("abcdef")
        expected_chars = ['a', 'b', 'c', 'd', 'e', 'f']
        actual_chars = []
        for char in s:
            actual_chars.append(char)
        self.assertEqual(actual_chars, expected_chars)

    def test_bool_empty_string(self):
        s = SyncString("")
        self.assertFalse(bool(s))
        if not s:  # Test directly in a boolean context
            self.assertTrue(True)
        else:
            self.fail("Empty SyncString evaluated as True")

    def test_bool_non_empty_string(self):
        s = SyncString("content")
        self.assertTrue(bool(s))
        if s:  # Test directly in a boolean context
            self.assertTrue(True)
        else:
            self.fail("Non-empty SyncString evaluated as False")


if __name__ == '__main__':
    unittest.main()