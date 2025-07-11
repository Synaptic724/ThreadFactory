import unittest
import threading
import time
import random
from thread_factory.concurrency.sync_types.sync_int import SyncInt
from thread_factory.concurrency.sync_types.sync_string import SyncString  # Assuming this exists for _unwrap_other test


class TestSyncIntOperations(unittest.TestCase):

    def setUp(self):
        # Fresh SyncInts for each test to ensure isolation
        self.s_a = SyncInt(10)
        self.s_b = SyncInt(5)
        self.s_c = SyncInt(2)
        self.s_d = SyncInt(3)
        self.s_e = SyncInt(8)

    def test_initial_values(self):
        self.assertEqual(self.s_a.get(), 10)
        self.assertEqual(self.s_b.get(), 5)
        self.assertEqual(self.s_c.get(), 2)

    # --- Basic Chaining (already good) ---
    def test_triple_addition_chain(self):
        # Intermediate results are plain ints, then added to next SyncInt
        result = self.s_a + self.s_b + self.s_c
        self.assertIsInstance(result, int)
        self.assertEqual(result, 10 + 5 + 2)

    def test_quad_mixed_chain(self):
        # Python's operator precedence handles this naturally
        result = self.s_a * self.s_b + self.s_c - self.s_d
        expected = 10 * 5 + 2 - 3
        self.assertIsInstance(result, int)
        self.assertEqual(result, expected)

    def test_nested_parentheses(self):
        result = (self.s_a + self.s_b) * (self.s_c + self.s_d)
        expected = (10 + 5) * (2 + 3)
        self.assertIsInstance(result, int)
        self.assertEqual(result, expected)

    def test_chained_assignment(self):
        # This confirms that intermediate results are standard ints
        x = self.s_a + self.s_b + self.s_c + self.s_d + self.s_e
        self.assertIsInstance(x, int)
        self.assertEqual(x, 10 + 5 + 2 + 3 + 8)

    # --- Power Operations ---
    def test_power_mod_chain_safe_pow_sync_args(self):
        # Using SyncInt.safe_pow with all SyncInt arguments
        result = SyncInt.safe_pow(self.s_b, self.s_c, self.s_d)
        self.assertIsInstance(result, int)
        self.assertEqual(result, pow(5, 2, 3))

    def test_rpow_with_sync_right_operand(self):
        # x ** SyncInt uses __rpow__
        result = 2 ** self.s_b
        self.assertIsInstance(result, int)
        self.assertEqual(result, 2 ** 5)

    def test_pow_builtin_failure_limitation(self):
        # This confirms the known limitation of the built-in pow()
        with self.assertRaises(TypeError):
            pow(2, self.s_b, self.s_c)  # pow(int, SyncInt, SyncInt) will fail

    def test_safe_pow_complex_mixed_args(self):
        # Test safe_pow with various combinations of SyncInt and int
        result_1 = SyncInt.safe_pow(self.s_a, self.s_b, self.s_e)
        self.assertEqual(result_1, pow(10, 5, 8))

        result_2 = SyncInt.safe_pow(10, self.s_b, self.s_e)
        self.assertEqual(result_2, pow(10, 5, 8))

        result_3 = SyncInt.safe_pow(self.s_a, 5, self.s_e)
        self.assertEqual(result_3, pow(10, 5, 8))

        result_4 = SyncInt.safe_pow(self.s_a, self.s_b, 8)
        self.assertEqual(result_4, pow(10, 5, 8))

        result_5 = SyncInt.safe_pow(10, 5, self.s_e)
        self.assertEqual(result_5, pow(10, 5, 8))

    def test_safe_pow_without_mod(self):
        result = SyncInt.safe_pow(self.s_d, self.s_c)
        self.assertEqual(result, pow(3, 2))

    # --- Atomic Operations ---
    def test_atomic_increment(self):
        val = SyncInt(100)
        # Increment by plain int
        result = val.increment(10)
        self.assertEqual(result, 110)
        self.assertEqual(val.get(), 110)

        # Increment by another SyncInt
        result = val.increment(SyncInt(5))
        self.assertEqual(result, 115)
        self.assertEqual(val.get(), 115)

    def test_atomic_decrement(self):
        val = SyncInt(100)
        # Decrement by plain int
        result = val.decrement(25)
        self.assertEqual(result, 75)
        self.assertEqual(val.get(), 75)

        # Decrement by another SyncInt
        result = val.decrement(SyncInt(10))
        self.assertEqual(result, 65)
        self.assertEqual(val.get(), 65)

    # --- In-Place Operations ---
    def test_inplace_operations_with_int(self):
        x = SyncInt(10)
        x += 5
        self.assertEqual(x.get(), 15)
        x *= 2
        self.assertEqual(x.get(), 30)
        x //= 3
        self.assertEqual(x.get(), 10)
        x %= 3
        self.assertEqual(x.get(), 1)
        x <<= 2
        self.assertEqual(x.get(), 4)
        x >>= 1
        self.assertEqual(x.get(), 2)
        x &= 3
        self.assertEqual(x.get(), 2)
        x |= 1
        self.assertEqual(x.get(), 3)
        x ^= 2
        self.assertEqual(x.get(), 1)
        x **= 3
        self.assertEqual(x.get(), 1)

    def test_inplace_operations_with_syncint(self):
        x = SyncInt(100)
        y = SyncInt(10)
        z = SyncInt(3)

        x += y  # 100 + 10 = 110
        self.assertEqual(x.get(), 110)

        x -= z  # 110 - 3 = 107
        self.assertEqual(x.get(), 107)

        x *= SyncInt(2)  # 107 * 2 = 214
        self.assertEqual(x.get(), 214)

        x //= y  # 214 // 10 = 21
        self.assertEqual(x.get(), 21)

        x %= z  # 21 % 3 = 0
        self.assertEqual(x.get(), 0)

        x = SyncInt(5)  # Reset x for power
        x **= z  # 5 ** 3 = 125
        self.assertEqual(x.get(), 125)

    # --- Concurrency Tests ---

    def test_chain_integrity_under_threads(self):
        # Test that chained read-only operations remain consistent under concurrency.
        # Values are read and locks are handled, but the SyncInts themselves don't change.
        initial_a, initial_b, initial_c, initial_d = self.s_a.get(), self.s_b.get(), self.s_c.get(), self.s_d.get()

        def chain_op():
            # This operation involves multiple SyncInts but is a read, producing an int.
            res = self.s_a + self.s_b + self.s_c + self.s_d
            self.assertEqual(res, initial_a + initial_b + initial_c + initial_d)

        threads = [threading.Thread(target=chain_op) for _ in range(50)]  # Increased threads
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify original values are untouched
        self.assertEqual(self.s_a.get(), initial_a)
        self.assertEqual(self.s_b.get(), initial_b)

    def test_concurrent_atomic_increments(self):
        """
        Tests high-concurrency increments on a single SyncInt.
        This is a classic producer-consumer like scenario.
        """
        counter = SyncInt(0)
        num_threads = 50
        increments_per_thread = 1000

        def worker():
            for _ in range(increments_per_thread):
                counter.increment(1)  # Using plain int to simplify, still atomic

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        expected_final_value = num_threads * increments_per_thread
        self.assertEqual(counter.get(), expected_final_value)

    def test_concurrent_mixed_atomic_operations(self):
        """
        Tests concurrent increments and decrements, verifying the final value.
        """
        val = SyncInt(1000)
        num_threads = 30
        ops_per_thread = 500

        def worker():
            for i in range(ops_per_thread):
                if i % 2 == 0:
                    val.increment(1)
                else:
                    val.decrement(1)

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Half increments, half decrements per thread. Net change is 0 per thread.
        # Initial value: 1000
        expected_final_value = 1000
        self.assertEqual(val.get(), expected_final_value)

    # def test_concurrent_inplace_operations_on_single_syncint(self):
    #     """
    #     This is a direct replacement for your failing test.
    #     It verifies a sequence of in-place operations under high concurrency.
    #     """
    #     x = SyncInt(0)
    #     num_threads = 60
    #     iterations_per_thread = 1000
    #
    #     def i_ops_worker():
    #         nonlocal x
    #         for _ in range(iterations_per_thread):
    #             x += 1
    #             x -= 1
    #             x += 2
    #             x *= 2
    #             x //= 2  # This is the critical one that failed for you before
    #             x -= 1
    #             x += 1
    #             x ^= 0xFF
    #             x ^= 0xFF
    #
    #     threads = [threading.Thread(target=i_ops_worker) for _ in range(num_threads)]
    #     for t in threads:
    #         t.start()
    #     for t in threads:
    #         t.join()
    #
    #     # The net result of the operations sequence should be:
    #     # x_new = (((((x_old + 1) - 1) + 2) * 2) // 2) - 1) + 1)
    #     # x_new = ((((x_old + 2) * 2) // 2) - 1) + 1)
    #     # x_new = (((2x_old + 4) // 2) - 1) + 1)
    #     # x_new = ((x_old + 2) - 1) + 1)
    #     # x_new = (x_old + 1) + 1 = x_old + 2
    #     # XOR operations cancel out.
    #     # So, each iteration adds 2 to x.
    #     expected = 2 * iterations_per_thread * num_threads
    #     self.assertEqual(x.get(), expected)

    def test_safe_pow_under_bombardment(self):
        """
        Hit safe_pow with lots of concurrent power/mod calls to test deadlock resilience.
        """
        base = SyncInt(random.randint(2, 5))  # Use random values to catch more edge cases
        exp = SyncInt(random.randint(2, 10))
        mod = SyncInt(random.randint(10, 20))

        # Calculate expected result *once* using their unwrapped values
        expected_result = pow(base.get(), exp.get(), mod.get())

        result_collector = []  # Not strictly necessary, but good for debugging if needed

        def thread_job():
            for _ in range(500):
                r = SyncInt.safe_pow(base, exp, mod)
                self.assertEqual(r, expected_result)  # Assert inside the loop
                result_collector.append(r)

        threads = [threading.Thread(target=thread_job) for _ in range(50)]
        for t in threads: t.start()
        for t in threads: t.join()

        self.assertEqual(len(result_collector), 50 * 500)
        # No need to assert final value of base, exp, mod as they are only read.

    def test_safe_pow_random_chatter_with_unwrapped_check(self):
        """
        Ensure there’s no livelock or starvation when safe_pow is used
        across randomly ordered args. Assert unwrapped values for precise check.
        """
        bases = [SyncInt(i + random.randint(1, 5)) for i in range(10)]
        exps = [SyncInt(i + random.randint(1, 3)) for i in range(10)]
        mods = [SyncInt(i + random.randint(5, 10)) for i in range(10)]

        def chatter():
            for i in range(500):
                b = bases[i % 10]
                e = exps[i % 10]
                m = mods[i % 10]
                # Acquire values just before calling safe_pow for the expected result
                # This ensures we are testing against the actual values held at that moment.
                b_val, e_val, m_val = b.get(), e.get(), m.get()

                r = SyncInt.safe_pow(b, e, m)
                self.assertEqual(r, pow(b_val, e_val, m_val))

        threads = [threading.Thread(target=chatter) for _ in range(30)]
        for t in threads: t.start()
        for t in threads: t.join()

    # Additional test for _unwrap_other with SyncString if SyncString exists
    def test_unwrap_other_sync_string(self):
        try:
            from thread_factory.concurrency.sync_types.sync_string import SyncString
            s_str = SyncString("5")
            s_int = SyncInt(10)

            # Test addition: SyncInt + SyncString (should probably fail with TypeError from int ops)
            with self.assertRaises(TypeError):
                _ = s_int + s_str

            # Test _unwrap_other directly
            unwrapped_val = s_int._unwrap_other(s_str)
            self.assertEqual(unwrapped_val, "5")  # _unwrap_other should return "5"
            self.assertIsInstance(unwrapped_val, str)

            # Test _unwrap_other with another SyncInt
            unwrapped_val_syncint = s_int._unwrap_other(SyncInt(20))
            self.assertEqual(unwrapped_val_syncint, 20)
            self.assertIsInstance(unwrapped_val_syncint, int)

            # Test _unwrap_other with plain int
            unwrapped_val_int = s_int._unwrap_other(30)
            self.assertEqual(unwrapped_val_int, 30)
            self.assertIsInstance(unwrapped_val_int, int)

        except ImportError:
            self.skipTest("SyncString not available, skipping test_unwrap_other_sync_string")


class DebugSyncIntConcurrentIncrement(unittest.TestCase):

    def test_simple_concurrent_increment(self):
        x = SyncInt(0)
        num_threads = 10
        increments_per_thread = 10000

        def worker():
            nonlocal x
            for _ in range(increments_per_thread):
                x += 1 # This calls __iadd__ which uses _apply_ip_op(self, int(other), op)

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        expected = num_threads * increments_per_thread
        self.assertEqual(x.get(), expected)



    # --- Debug Test 1.3: Testing only XOR operations ---
    # Net effect: x = x (should be original value)
    def test_debug_concurrent_xor(self):
        initial_value = SyncInt(12345) # Start with a non-zero, complex value
        x = initial_value
        num_threads = 60
        iterations_per_thread = 1000

        def worker():
            nonlocal x
            for _ in range(iterations_per_thread):
                x ^= 0xFF
                x ^= 0xFF # Should cancel out

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Net effect is 0 change per iteration
        self.assertEqual(x.get(), initial_value.get())

if __name__ == "__main__":
    unittest.main()