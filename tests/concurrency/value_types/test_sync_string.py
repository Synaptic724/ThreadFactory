import unittest
import threading
import copy
from concurrent.futures import ThreadPoolExecutor

from thread_factory.concurrency.value_types.sync_string import SyncString

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

    def test_concurrent_append_simulation(self):
        s = SyncString("")
        def appender(ch):
            for _ in range(100):
                current = s.get()
                s.set(current + ch)

        threads = [threading.Thread(target=appender, args=(chr(65 + i),)) for i in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(s.get()), 500)

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