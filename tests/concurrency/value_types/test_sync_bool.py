import threading
import unittest
from threading import Thread
from time import sleep
from thread_factory.concurrency.value_types.sync_bool import SyncBool

class TestSyncBool(unittest.TestCase):

    def test_index(self):
        b = SyncBool(True)
        self.assertEqual(b.__index__(), 1)

    def test_float_conversion(self):
        b = SyncBool(True)
        self.assertEqual(float(b), 1.0)
        b.set(False)
        self.assertEqual(float(b), 0.0)

    def test_toggle_functionality(self):
        b = SyncBool(False)
        b.toggle()
        self.assertTrue(b.get())
        b.toggle()
        self.assertFalse(b.get())

    def test_thread_safe_toggle(self):
        b = SyncBool(False)
        def toggler():
            for _ in range(1000): b.toggle()
        threads = [Thread(target=toggler) for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertIn(b.get(), [True, False])

    def test_and_operation(self):
        b = SyncBool(True)
        self.assertTrue(b & True)
        self.assertFalse(b & False)

    def test_or_operation(self):
        b = SyncBool(False)
        self.assertTrue(b | True)
        self.assertFalse(b | False)

    def test_xor_operation(self):
        b = SyncBool(True)
        self.assertFalse(b ^ True)
        self.assertTrue(b ^ False)

    def test_invert_behavior(self):
        b = SyncBool(True)
        self.assertEqual(~b, -2)
        b.set(False)
        self.assertEqual(~b, -1)

    def test_repr_and_str(self):
        b = SyncBool(True)
        self.assertEqual(str(b), "True")
        self.assertEqual(repr(b), "True")
        b.set(False)
        self.assertEqual(str(b), "False")
        self.assertEqual(repr(b), "False")

    def test_reverse_and(self):
        b = SyncBool(True)
        self.assertTrue(True & b)
        self.assertFalse(False & b)

    def test_reverse_or(self):
        b = SyncBool(False)
        self.assertTrue(True | b)
        self.assertFalse(False | b)

    def test_reverse_xor(self):
        b = SyncBool(True)
        self.assertFalse(True ^ b)
        self.assertTrue(False ^ b)

    def test_syncbool_to_syncbool_comparison(self):
        b1 = SyncBool(True)
        b2 = SyncBool(True)
        b3 = SyncBool(False)
        self.assertTrue(b1 == b2)
        self.assertFalse(b1 == b3)
        self.assertTrue(b1 != b3)

    def test_syncbool_to_syncbool_bitwise_ops(self):
        b_true = SyncBool(True)
        b_false = SyncBool(False)
        self.assertFalse(b_false & b_true)
        self.assertTrue(b_false | b_true)
        self.assertTrue(b_true ^ b_false)

    def test_deadlock_prevention_on_binary_op(self):
        """
        Simulates a classic deadlock scenario to test the lock-ordering mechanism.
        Two threads attempt to operate on two SyncBool instances in reverse order.
        """
        b1 = SyncBool(True)
        b2 = SyncBool(False)

        # A barrier to synchronize the start of the threads
        # to increase the chance of a race condition.
        barrier = threading.Barrier(2)

        exceptions = []

        def thread1_task():
            try:
                barrier.wait()
                for _ in range(10000000):
                    _ = b1 & b2  # Access b1 then b2
            except Exception as e:
                exceptions.append(e)

        def thread2_task():
            try:
                barrier.wait()
                for _ in range(10000000):
                    _ = b2 | b1  # Access b2 then b1
            except Exception as e:
                exceptions.append(e)

        t1 = Thread(target=thread1_task)
        t2 = Thread(target=thread2_task)

        t1.start()
        t2.start()

        t1.join(timeout=30)
        t2.join(timeout=30)

        self.assertFalse(t1.is_alive(), "Thread 1 deadlocked or timed out")
        self.assertFalse(t2.is_alive(), "Thread 2 deadlocked or timed out")
        self.assertEqual(exceptions, [], "Threads raised exceptions")
    def test_comparisons(self):
        b = SyncBool(True)
        self.assertTrue(b == True)
        self.assertFalse(b != True)
        self.assertTrue(b != False)

    def test_indexing_behavior(self):
        lst = ["zero", "one"]
        b = SyncBool(True)
        self.assertEqual(lst[b.__index__()], "one")
        b.set(False)
        self.assertEqual(lst[b.__index__()], "zero")

    def test_int_conversion(self):
        b = SyncBool(True)
        self.assertEqual(int(b), 1)
        b.set(False)
        self.assertEqual(int(b), 0)

    def test_hash(self):
        b = SyncBool(True)
        self.assertEqual(hash(b), hash(True))
        b.set(False)
        self.assertEqual(hash(b), hash(False))

    def test_format(self):
        b = SyncBool(True)
        self.assertEqual(format(b, ""), "True")
        b.set(False)
        self.assertEqual(format(b, ""), "False")
    def test_initial_true(self):
        b = SyncBool(True)
        self.assertTrue(b.get())

    def test_initial_false(self):
        b = SyncBool(False)
        self.assertFalse(b.get())

    def test_set_true(self):
        b = SyncBool()
        b.set(True)
        self.assertTrue(b.get())

    def test_set_false(self):
        b = SyncBool(True)
        b.set(False)
        self.assertFalse(b.get())

    def test_invert_operation(self):
        b = SyncBool(True)
        self.assertEqual(~b, -2)  # ~True == -2

    def test_rand_operation(self):
        b = SyncBool(True)
        self.assertEqual(True & b, True)
        self.assertEqual(False & b, False)

    def test_ror_operation(self):
        b = SyncBool(False)
        self.assertEqual(True | b, True)
        self.assertEqual(False | b, False)

    def test_rxor_operation(self):
        b = SyncBool(True)
        self.assertEqual(False ^ b, True)
        self.assertEqual(True ^ b, False)

    def test_repr_true(self):
        b = SyncBool(True)
        self.assertEqual(repr(b), "True")

    def test_repr_false(self):
        b = SyncBool(False)
        self.assertEqual(repr(b), "False")

    def test_thread_safety_set_get(self):
        b = SyncBool()
        def set_true():
            for _ in range(1000):
                b.set(True)
        def set_false():
            for _ in range(1000):
                b.set(False)

        t1 = Thread(target=set_true)
        t2 = Thread(target=set_false)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertIn(b.get(), [True, False])  # should not crash

    def test_truthiness(self):
        b = SyncBool(True)
        self.assertTrue(bool(b))
        b.set(False)
        self.assertFalse(bool(b))


if __name__ == '__main__':
    unittest.main()