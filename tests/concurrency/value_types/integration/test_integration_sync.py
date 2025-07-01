import unittest
import threading
import time
import random
import pickle
import copy

# Adapt the import path to your project structure
from thread_factory.concurrency.value_types.sync_string import SyncString
from thread_factory.concurrency.value_types.sync_int import SyncInt
from thread_factory.concurrency.value_types.sync_float import SyncFloat
from thread_factory.concurrency.value_types.sync_bool import SyncBool


TIMEOUT = 5  # seconds – used for join time‑outs to reveal deadlocks


class TestSyncIntegration(unittest.TestCase):

    # ------------------------------------------------------------------
    #  Helper utilities
    # ------------------------------------------------------------------
    def _spawn(self, *targets):
        """Start all callables in individual threads and return list."""
        threads = [threading.Thread(target=fn) for fn in targets]
        for t in threads:
            t.start()
        return threads

    def _assert_threads_complete(self, threads):
        for t in threads:
            t.join(timeout=TIMEOUT)
        self.assertTrue(all(not t.is_alive() for t in threads), "Deadlock or timeout detected")

    # ------------------------------------------------------------------
    #  1. Increment Int / Float coherence
    # ------------------------------------------------------------------
    def test_increment_int_float_coherence(self):
        i = SyncInt(0)
        f = SyncFloat(0.0)
        barrier = threading.Barrier(6)

        def adders():
            nonlocal i, f
            barrier.wait()
            for _ in range(10_000):
                i += 1
                f += 1.0

        threads = self._spawn(*[adders for _ in range(5)],)
        self._assert_threads_complete(threads)
        self.assertEqual(i.get(), 50_000)
        self.assertAlmostEqual(f.get(), 50_000.0)

    # ------------------------------------------------------------------
    # 2. String‑Int concatenation atomicity
    # ------------------------------------------------------------------
    def test_string_int_concat_atomicity(self):
        s = SyncString("count:")
        i = SyncInt(0)
        barrier = threading.Barrier(4)

        def worker():
            nonlocal s, i
            barrier.wait()
            for _ in range(1_000):
                s += str(i.get())
                i += 1

        threads = self._spawn(worker, worker, worker, worker)
        self._assert_threads_complete(threads)
        self.assertEqual(i.get(), 4_000)
        self.assertTrue(s.get().startswith("count:"))

    # ------------------------------------------------------------------
    # 3. Bool flip atomicity under race
    # ------------------------------------------------------------------
    def test_bool_flip_atomicity(self):
        b = SyncBool(True)
        barrier = threading.Barrier(3)

        def flipper():
            barrier.wait()
            for _ in range(10_000):
                b.set(not b.get())

        threads = self._spawn(flipper, flipper)
        self._assert_threads_complete(threads)
        self.assertIn(b.get(), (True, False))

    # ------------------------------------------------------------------
    # 4. Cross‑type addition (int into float)
    # ------------------------------------------------------------------
    def test_cross_addition(self):
        f = SyncFloat(0.0)
        i = SyncInt(10)
        f += i.get()
        self.assertEqual(f.get(), 10.0)

    # ------------------------------------------------------------------
    # 5. Cross‑type comparisons stay Pythonic
    # ------------------------------------------------------------------
    def test_cross_comparison(self):
        s = SyncString("123")
        i = SyncInt(123)
        self.assertFalse(s == i)  # string vs int
        with self.assertRaises(TypeError):
            _ = s < i

    # ------------------------------------------------------------------
    # 6. Dual lock ordering — to prevent deadlock
    # ------------------------------------------------------------------
    def test_lock_ordering(self):
        s1, s2 = SyncString("a"), SyncString("b")
        barrier = threading.Barrier(3)

        def t1():
            barrier.wait()
            for _ in range(1_000):
                _ = s1 + s2

        def t2():
            barrier.wait()
            for _ in range(1_000):
                _ = s2 == s1

        threads = self._spawn(t1, t2)
        self._assert_threads_complete(threads)

    # ------------------------------------------------------------------
    # 7. Massive mixed‑type race
    # ------------------------------------------------------------------
    def test_massive_mixed_race(self):
        s = SyncString("")
        i = SyncInt(0)
        f = SyncFloat(0.0)
        b = SyncBool(True)
        barrier = threading.Barrier(6)

        def mix():
            nonlocal s, i, f, b
            barrier.wait()
            for _ in range(2_000):
                s += "x" if b.get() else "y"
                i += 1
                f += 0.5
                b.set(not b.get())

        threads = self._spawn(mix, mix, mix, mix, mix)
        self._assert_threads_complete(threads)
        self.assertEqual(i.get(), 5 * 2_000)
        self.assertAlmostEqual(f.get(), 5 * 2_000 * 0.5)

    # ------------------------------------------------------------------
    # 8. Simultaneous set/get integrity
    # ------------------------------------------------------------------
    def test_simultaneous_set_get(self):
        s = SyncString("init")
        barrier = threading.Barrier(4)

        def writer():
            barrier.wait()
            for _ in range(5_000):
                s.set(str(random.randint(100, 999)))

        def reader():
            barrier.wait()
            for _ in range(5_000):
                _ = s.get()

        threads = self._spawn(writer, writer, reader, reader)
        self._assert_threads_complete(threads)
        self.assertIsInstance(s.get(), str)

    # ------------------------------------------------------------------
    # 9. Pickle round‑trip across threads
    # ------------------------------------------------------------------
    def test_pickle_roundtrip(self):
        s = SyncString("pickle_me")
        data = pickle.dumps(s)
        new_s = pickle.loads(data)
        self.assertEqual(new_s.get(), "pickle_me")

    # ------------------------------------------------------------------
    # 10. Shallow / deep copy integrity
    # ------------------------------------------------------------------
    def test_copy_roundtrip(self):
        s = SyncString("copy")
        self.assertEqual(copy.copy(s).get(), "copy")
        self.assertEqual(copy.deepcopy(s).get(), "copy")

    # ------------------------------------------------------------------
    # 11. Hash consistency under mutation lock
    # ------------------------------------------------------------------
    def test_hash_consistency(self):
        s = SyncString("hashme")
        initial_hash = hash(s)
        s += "!"  # mutate
        self.assertNotEqual(initial_hash, hash(s))

    # ------------------------------------------------------------------
    # 12. Iterate while mutating different instance
    # ------------------------------------------------------------------
    def test_iterate_during_mutation(self):
        s = SyncString("abcdef")
        barrier = threading.Barrier(2)
        result_holder = []

        def iterator():
            barrier.wait()
            result_holder.append("".join(ch for ch in s))

        def mutator():
            barrier.wait()
            s.set("xyz")

        threads = self._spawn(iterator, mutator)
        self._assert_threads_complete(threads)
        self.assertIn(result_holder[0], ("abcdef", "xyz"))

    # ------------------------------------------------------------------
    # 13. contains check during modification
    # ------------------------------------------------------------------
    def test_contains_during_modification(self):
        s = SyncString("foo_bar")
        barrier = threading.Barrier(3)
        flag = threading.Event()

        def checker():
            barrier.wait()
            while not flag.is_set():
                _ = "bar" in s

        def toggler():
            barrier.wait()
            for _ in range(2_000):
                s.set("foo_bar") if _ % 2 == 0 else s.set("baz_qux")
            flag.set()

        threads = self._spawn(checker, toggler)
        self._assert_threads_complete(threads)

    # ------------------------------------------------------------------
    # 14. String represents int value snapshot
    # ------------------------------------------------------------------
    def test_string_represents_int_value(self):
        i = SyncInt(42)
        s = SyncString(str(i.get()))
        self.assertEqual(s.get(), "42")
        i += 1
        self.assertEqual(s.get(), "42")  # snapshot, not live link

    # ------------------------------------------------------------------
    # 15. Float precision after many increments
    # ------------------------------------------------------------------
    def test_float_precision_under_load(self):
        f = SyncFloat(0.0)
        for _ in range(1_000_000):
            f += 0.1
        self.assertAlmostEqual(f.get(), 100_000.0, places=4)

    # ------------------------------------------------------------------
    # 16. Mixed math & string threading stress
    # ------------------------------------------------------------------
    def test_threaded_math_and_string(self):
        s = SyncString("A")
        i = SyncInt(1)
        barrier = threading.Barrier(4)

        def math_text():
            nonlocal s, i
            barrier.wait()
            for _ in range(10_000):
                i += 1
                s += "B"

        threads = self._spawn(math_text, math_text, math_text)
        self._assert_threads_complete(threads)
        self.assertEqual(i.get(), 1 + 3 * 10_000)
        self.assertEqual(len(s.get()), 1 + 3 * 10_000)

    # ------------------------------------------------------------------
    # 17. Stress timeout watchdog (should not deadlock)
    # ------------------------------------------------------------------
    def test_timeout_safety(self):
        s = SyncString("x")
        done = threading.Event()

        def busy():
            nonlocal s
            for _ in range(50_000):
                s += "y"
            done.set()

        t = threading.Thread(target=busy)
        t.start()
        t.join(timeout=TIMEOUT)
        self.assertFalse(t.is_alive(), "Thread exceeded timeout")
        self.assertTrue(done.is_set())

    # ------------------------------------------------------------------
    # 18. Race read‑write mix with bool gate
    # ------------------------------------------------------------------
    def test_race_read_write_mix(self):
        gate = SyncBool(True)
        s = SyncString("")
        barrier = threading.Barrier(3)

        def reader():
            barrier.wait()
            for _ in range(5_000):
                if gate.get():
                    _ = len(s)


        def writer():
            nonlocal s
            barrier.wait()
            for _ in range(5_000):
                gate.set(not gate.get())
                s += "a"

        threads = self._spawn(reader, reader, writer)
        self._assert_threads_complete(threads)

    # ------------------------------------------------------------------
    # 19. Mixed‑type equality (string vs float str rep)
    # ------------------------------------------------------------------
    def test_mixed_type_equality(self):
        f = SyncFloat(3.0)
        s = SyncString("3.0")
        self.assertFalse(s == f)

    # ------------------------------------------------------------------
    # 20. Reverse lock order between different types
    # ------------------------------------------------------------------
    def test_no_deadlock_reverse_lock(self):
        s = SyncString("txt")
        i = SyncInt(99)
        barrier = threading.Barrier(3)

        def t1():
            barrier.wait()
            for _ in range(2_000):
                _ = str(i.get()) + s.get()

        def t2():
            barrier.wait()
            for _ in range(2_000):
                _ = s.get() == str(i.get())

        threads = self._spawn(t1, t2)
        self._assert_threads_complete(threads)


if __name__ == "__main__":
    unittest.main()
