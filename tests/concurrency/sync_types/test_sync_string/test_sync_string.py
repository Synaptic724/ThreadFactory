import unittest
import threading
import copy
from concurrent.futures import ThreadPoolExecutor

from thread_factory.concurrency.sync_types.sync_string import SyncString

class TestSyncString(unittest.TestCase):

    def test_initial_value_empty(self):
        s = SyncString()
        self.assertEqual(s.get(), "")

    def test_initial_value_nonempty(self):
        s = SyncString("hello")
        self.assertEqual(s.get(), "hello")

    def test_set_and_get(self):
        s = SyncString("start")
        s.set("changed")
        self.assertEqual(s.get(), "changed")

    def test_str_dunder(self):
        s = SyncString("world")
        self.assertEqual(str(s), "world")

    def test_repr_dunder(self):
        s = SyncString("example")
        self.assertEqual(repr(s), repr("example"))

    def test_equality(self):
        self.assertTrue(SyncString("abc") == "abc")
        self.assertTrue(SyncString("abc") == SyncString("abc"))

    def test_inequality(self):
        self.assertTrue(SyncString("abc") != "xyz")

    def test_case_methods(self):
        s = SyncString("abc")
        self.assertEqual(s.upper(), "ABC")
        self.assertEqual(s.lower(), "abc")
        self.assertEqual(s.capitalize(), "Abc")
        self.assertEqual(s.swapcase(), "ABC")

    def test_len_contains_iter(self):
        s = SyncString("abc")
        self.assertEqual(len(s), 3)
        self.assertTrue("b" in s)
        self.assertEqual(list(iter(s)), ["a", "b", "c"])

    def test_dunder_add_radd(self):
        s = SyncString("world")
        self.assertEqual("hello " + s, "hello world")
        self.assertEqual(s + "!", "world!")

    def test_dunder_mul_rmul(self):
        s = SyncString("ab")
        self.assertEqual(s * 3, "ababab")
        self.assertEqual(2 * s, "abab")

    def test_indexing(self):
        s = SyncString("hello")
        self.assertEqual(s[1], "e")

    def test_thread_safety_set(self):
        s = SyncString("")

        def writer(index):
            s.set(str(index))

        with ThreadPoolExecutor(max_workers=10) as ex:
            ex.map(writer, range(10))

        self.assertIn(s.get(), {str(i) for i in range(10)})

    def test_thread_safety_concurrent_read_write(self):
        s = SyncString("")

        def writer():
            for i in range(50):
                s.set(f"val{i}")

        def reader():
            for _ in range(50):
                _ = s.get()

        threads = [threading.Thread(target=writer)] + [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertTrue(s.get().startswith("val"))

    def test_copy_and_deepcopy(self):
        s = SyncString("deep")
        shallow = copy.copy(s)
        deep = copy.deepcopy(s)
        self.assertEqual(shallow.get(), "deep")
        self.assertEqual(deep.get(), "deep")

    def test_hash_and_bool(self):
        s1 = SyncString("truth")
        self.assertTrue(bool(s1))
        self.assertIsInstance(hash(s1), int)

    def test_translate_zfill(self):
        s = SyncString("42")
        self.assertEqual(s.zfill(5), "00042")
        self.assertEqual(s.translate(str.maketrans("42", "ab")), "ab")

    def test_format_and_mod(self):
        s = SyncString("Name: {}")
        self.assertEqual(s.format("Alice"), "Name: Alice")

        s2 = SyncString("X: %d")
        self.assertEqual(s2 % 5, "X: 5")

    def test_partition_methods(self):
        s = SyncString("one-two-three")
        self.assertEqual(s.partition("-"), ("one", "-", "two-three"))
        self.assertEqual(s.rpartition("-"), ("one-two", "-", "three"))

    def test_strip_variants(self):
        s = SyncString("  spaced  ")
        self.assertEqual(s.strip(), "spaced")
        self.assertEqual(s.lstrip(), "spaced  ")
        self.assertEqual(s.rstrip(), "  spaced")

    def test_split_variants(self):
        s = SyncString("a b c")
        self.assertEqual(s.split(), ["a", "b", "c"])
        self.assertEqual(SyncString("line1\nline2").splitlines(), ["line1", "line2"])

    def test_replace_and_find(self):
        s = SyncString("bananas")
        self.assertEqual(s.replace("a", "o"), "bononos")
        self.assertEqual(s.find("n"), 2)
        self.assertEqual(s.rfind("a"), 5)

    def test_all_isa_methods(self):
        self.assertTrue(SyncString("abc").isalpha())
        self.assertTrue(SyncString("123").isdigit())
        self.assertTrue(SyncString("abc123").isalnum())
        self.assertTrue(SyncString("HELLO").isupper())
        self.assertTrue(SyncString("hello").islower())
        self.assertTrue(SyncString("Title Case").istitle())
        self.assertTrue(SyncString(" ").isspace())
        self.assertTrue(SyncString("A").isascii())  # ASCII
        self.assertFalse(SyncString("©").isascii())  # Non-ASCII
        self.assertTrue(SyncString("10").isdecimal())
        self.assertTrue(SyncString("10").isnumeric())
        self.assertTrue(SyncString("_var").isidentifier())
        self.assertTrue(SyncString("print").isprintable())

    def test_dunder_reduce(self):
        s = SyncString("pickle")
        self.assertIsInstance(s.__reduce__(), tuple)
        self.assertIsInstance(s.__reduce_ex__(4), tuple)

    def test_dunder_getnewargs(self):
        s = SyncString("newargs")
        self.assertEqual(s.__getnewargs__(), ("newargs",))

    def test_dunder_dir(self):
        s = SyncString("dirtest")
        self.assertIn("capitalize", s.__dir__())

    def test_class_getitem(self):
        self.assertEqual(SyncString.__class_getitem__(int), SyncString)


    def test_concurrent_set_and_get(self):
        s = SyncString("start")
        def writer(val):
            for _ in range(1000):
                s.set(val)

        def reader():
            for _ in range(1000):
                _ = s.get()

        threads = [
            threading.Thread(target=writer, args=(f"val_{i}",)) for i in range(5)
        ] + [threading.Thread(target=reader) for _ in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertIn(s.get(), [f"val_{i}" for i in range(5)])

    def test_concurrent_imul_simulation(self):
        s = SyncString("a")

        def multiplier():
            nonlocal s
            s *= 2

        # Start with "a", run multiplier twice.
        # If not atomic, one thread might read "a", the other "a", and both set to "aa".
        # If atomic, one thread sets to "aa", the other reads "aa" and sets to "aaaa".
        threads = [threading.Thread(target=multiplier) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(s.get(), "aaaa")

    def test_concurrent_contains_checks(self):
        s = SyncString("initial")

        def writer():
            for i in range(100):
                s.set(f"val_{i}")

        def checker():
            for _ in range(100):
                _ = "val_" in s

        threads = [threading.Thread(target=writer)] + [threading.Thread(target=checker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertTrue(s.get().startswith("val_"))

    def test_bytes_interaction(self):
        s = SyncString("data")
        self.assertEqual(bytes(s), b"data")
        s.set("binary\x00data")
        self.assertEqual(bytes(s), b"binary\x00data")

    def test_large_string_handling(self):
        large_str = "a" * (10 ** 6)
        s = SyncString(large_str)
        self.assertEqual(len(s), 10 ** 6)
        s.set(s.get() + "b")
        self.assertEqual(len(s), (10 ** 6) + 1)
        self.assertTrue(s.endswith("b"))

    def test_concurrent_iadd(self):
        s = SyncString("start")

        def append_x():
            nonlocal s
            for _ in range(100):
                s += "x"

        threads = [threading.Thread(target=append_x) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        expected_length = len("start") + (10 * 100)
        self.assertEqual(len(s), expected_length)

    def test_concurrent_append_simulation(self):
        s = SyncString("")

        def appender(ch):
            nonlocal s  # Tell the function to use the 's' from the outer scope
            for _ in range(100):
                s += ch  # Use the atomic in-place add operator

        threads = [threading.Thread(target=appender, args=(chr(65 + i),)) for i in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # This will now pass every time
        self.assertEqual(len(s.get()), 500)

    def test_concurrent_instantiation_init_safe(self):
        instances = []

        def create():
            instances.append(SyncString("test", init_safe=True))

        threads = [threading.Thread(target=create) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(instances), 100)
        self.assertTrue(all(s.get() == "test" for s in instances))

    def test_concurrent_instantiation_init_not_safe(self):
        instances = []

        def create():
            instances.append(SyncString("test", init_safe=False))

        threads = [threading.Thread(target=create) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(instances), 100)
        self.assertTrue(all(s.get() == "test" for s in instances))

    def test_getitem_slice(self):
        s = SyncString("abcdefgh")
        self.assertEqual(s[2:5], "cde")

    def test_all_comparisons_with_syncstring(self):
        s1 = SyncString("cat")
        s2 = SyncString("dog")
        s3 = SyncString("cat")

        self.assertTrue(s1 == s3)
        self.assertTrue(s1 != s2)
        self.assertTrue(s1 < s2)
        self.assertTrue(s1 <= s3)
        self.assertTrue(s2 > s1)
        self.assertTrue(s3 >= s1)

    def test_reverse_mod_operator(self):
        s = SyncString("World")
        self.assertEqual("Hello, %s" % s, "Hello, World")

    def test_deadlock_prevention_on_binary_op(self):
        """
        Simulates a classic deadlock scenario to test the lock-ordering mechanism.
        Two threads attempt to operate on two SyncString instances in reverse order.
        """
        s1 = SyncString("one")
        s2 = SyncString("two")

        # A barrier to synchronize the start of the threads
        # to increase the chance of a race condition.
        barrier = threading.Barrier(2)

        exceptions = []

        def thread1_task():
            try:
                barrier.wait()
                for _ in range(1000):
                    # Perform an operation that locks s1, then s2
                    _ = s1 + s2
            except Exception as e:
                exceptions.append(e)

        def thread2_task():
            try:
                barrier.wait()
                for _ in range(1000):
                    # Perform an operation that locks s2, then s1
                    _ = s2 == s1
            except Exception as e:
                exceptions.append(e)

        t1 = threading.Thread(target=thread1_task)
        t2 = threading.Thread(target=thread2_task)

        t1.start()
        t2.start()

        t1.join(timeout=2)
        t2.join(timeout=2)

        self.assertFalse(t1.is_alive(), "Thread 1 deadlocked or timed out")
        self.assertFalse(t2.is_alive(), "Thread 2 deadlocked or timed out")
        self.assertEqual(exceptions, [], "Threads raised exceptions")
    def test_join_unicode_separator(self):
        s = SyncString("🚀")
        self.assertEqual(s.join(["A", "B", "C"]), "A🚀B🚀C")

    def test_iter_safe_copy(self):
        s = SyncString("test")
        it = iter(s)
        s.set("changed")
        self.assertEqual(list(it), list("test"))

    def test_maketrans_usage(self):
        s = SyncString("abc")
        trans = str.maketrans("abc", "123")
        self.assertEqual(s.translate(trans), "123")

    def test_getattr_method_forwarding(self):
        s = SyncString("HELLO")
        self.assertTrue(callable(s.lower))
        self.assertEqual(s.lower(), "hello")

    def test_bytes_conversion(self):
        s = SyncString("abc")
        self.assertEqual(bytes(s), b"abc")

    def test_reversed_iteration(self):
        s = SyncString("hello")
        self.assertEqual(list(reversed(s)), list("olleh"))

    def test_sizeof_method(self):
        s = SyncString("hello world")
        self.assertIsInstance(s.__sizeof__(), int)

    def test_format_specifier(self):
        s = SyncString("Result: {:.2f}")
        self.assertEqual(format(s, ""), "Result: {:.2f}")
        self.assertEqual(s.get().format(3.14159), "Result: 3.14")

    def test_mod_operator(self):
        s = SyncString("Count: %d")
        self.assertEqual(s % 7, "Count: 7")

    def test_reduce_pickle_roundtrip(self):
        import pickle
        s = SyncString("pickle_test")
        result = pickle.loads(pickle.dumps(s))
        self.assertEqual(result.get(), "pickle_test")

    def test_class_getitem_noop(self):
        self.assertEqual(SyncString[str], SyncString)

    def test_dir_contains_builtin_methods(self):
        s = SyncString("test")
        methods = dir(s)
        self.assertIn("upper", methods)
        self.assertIn("lower", methods)
        self.assertIn("format", methods)

    def test_copy_and_isolation(self):
        s1 = SyncString("original")
        s2 = copy.copy(s1)
        s3 = copy.deepcopy(s1)
        s1.set("changed")
        self.assertEqual(s2.get(), "original")
        self.assertEqual(s3.get(), "original")

    def test_contains_operator(self):
        s = SyncString("hello world")
        self.assertTrue("hello" in s)
        self.assertFalse("bye" in s)

    def test_formatting_operator(self):
        s = SyncString("Value is: {}")
        self.assertEqual(s.get().format(42), "Value is: 42")

    def test_unicode_handling(self):
        s = SyncString("🚀🌟🔥")
        self.assertTrue(s.isprintable())
        self.assertEqual(len(s.get()), 3)

    def test_edge_empty_string(self):
        s = SyncString("")
        self.assertEqual(len(s.get()), 0)
        self.assertFalse(s)

    def test_startswith_and_endswith(self):
        s = SyncString("thread-safe-string")
        self.assertTrue(s.startswith("thread"))
        self.assertTrue(s.endswith("string"))

    def test_comparison_with_string(self):
        s = SyncString("abc")
        self.assertTrue(s == "abc")
        self.assertTrue(s < "def")
        self.assertFalse(s > "xyz")

    def test_join_behavior(self):
        s = SyncString("-")
        self.assertEqual(s.join(["a", "b", "c"]), "a-b-c")

if __name__ == "__main__":
    unittest.main()