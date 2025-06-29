import unittest
import threading
import time

# Assuming the corrected Group and SynchronizedSignalBarrier classes are available
# If not, you can place the robust Group class definition here for a self-contained test.
from typing import Optional, Callable, List, Union


class Group:
    """
    Group (Robust Version)
    -----
    Represents a subgroup of threads. This version gracefully handles
    either a single callback or a list of callbacks.
    """

    def __init__(self, threshold: int, callbacks: Optional[Union[Callable, List[Callable]]] = None):
        if threshold <= 0:
            raise ValueError("Threshold must be a positive integer.")

        self.threshold = threshold
        self.callbacks: List[Callable] = []
        self.count = 0
        self.ready = False
        self._released_once = False

        if callbacks is not None:
            if callable(callbacks):
                self.callbacks = [callbacks]
            elif isinstance(callbacks, list) and all(callable(cb) for cb in callbacks):
                self.callbacks = callbacks
            else:
                raise TypeError("callbacks must be a callable function or a list of callable functions.")


# Assume IDisposable is defined, e.g., class IDisposable: def __init__(self): self._disposed = False
# from thread_factory.utils import IDisposable
class IDisposable:
    def __init__(self):
        self._disposed = False

    def dispose(self):
        self._disposed = True


# Assuming SynchronizedSignalBarrier is in this path and uses the updated Group
from thread_factory.primitives.multi_conductor import SynchronizedSignalBarrier


class TestSignalBarrier(unittest.TestCase):

    def test_initialization(self):
        barrier = SynchronizedSignalBarrier(groups=[Group(2)], reusable=True, timeout=0.1)
        self.assertEqual(len(barrier.groups), 1)
        self.assertTrue(barrier.reusable)
        self.assertEqual(barrier.timeout, 0.1)
        self.assertFalse(barrier._released)
        self.assertFalse(barrier._broken)
        self.assertFalse(barrier._enabled)

    def test_add_group_and_enable(self):
        barrier = SynchronizedSignalBarrier()
        barrier.add_group(2)
        self.assertEqual(len(barrier.groups), 1)
        barrier.enable()
        self.assertTrue(barrier._enabled)
        with self.assertRaises(RuntimeError):
            barrier.add_group(3)

    def test_enable_without_groups_raises_error(self):
        barrier = SynchronizedSignalBarrier()
        with self.assertRaises(ValueError):
            barrier.enable()

    def test_group_threshold_met_with_callback(self):
        results = []
        # FIXED: Changed 'callback=' to 'callbacks=[]'
        barrier = SynchronizedSignalBarrier(groups=[Group(2, callbacks=[lambda: results.append("callback_fired")])])
        barrier.enable()

        def thread_func():
            released = barrier.wait(0)
            results.append(released)

        threads = [threading.Thread(target=thread_func) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertTrue(barrier._released)
        self.assertIn("callback_fired", results)
        self.assertEqual(results.count(True), 2)

    def test_timeout_behavior(self):
        barrier = SynchronizedSignalBarrier(groups=[Group(2)], timeout=0.1)
        barrier.enable()

        def thread_func():
            barrier.wait(0)

        thread1 = threading.Thread(target=thread_func)
        thread1.start()
        thread1.join(0.5)

        self.assertTrue(barrier._broken)
        self.assertTrue(barrier._released)

    def test_manual_release(self):
        barrier = SynchronizedSignalBarrier(groups=[Group(2)], manual_release=True)
        barrier.enable()
        released_flags = [False, False]

        def thread_func(idx):
            barrier.wait(0)
            released_flags[idx] = True

        threads = [threading.Thread(target=thread_func, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()

        time.sleep(0.1)
        self.assertFalse(barrier._released)
        barrier.release()
        for t in threads:
            t.join(0.5)

        self.assertTrue(barrier._released)
        self.assertTrue(all(released_flags))

    def test_reusable_behavior(self):
        barrier = SynchronizedSignalBarrier(groups=[Group(2)], reusable=True)
        barrier.enable()

        def thread_func():
            barrier.wait(0)

        # --- First wave ---
        threads1 = [threading.Thread(target=thread_func) for _ in range(2)]
        for t in threads1:
            t.start()
        for t in threads1:
            t.join()

        self.assertFalse(barrier._released, "Barrier should reset to not-released after wave 1")
        self.assertFalse(barrier._broken)
        self.assertEqual(barrier.groups[0].count, 0)

        # --- Second wave ---
        threads2 = [threading.Thread(target=thread_func) for _ in range(2)]
        for t in threads2:
            t.start()
        for t in threads2:
            t.join()

        self.assertFalse(barrier._released, "Barrier should reset to not-released after wave 2")
        self.assertEqual(barrier.groups[0].count, 0)

    def test_is_spent(self):
        barrier = SynchronizedSignalBarrier(groups=[Group(2)], reusable=False)
        barrier.enable()

        def thread_func():
            barrier.wait(0)

        threads = [threading.Thread(target=thread_func) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertTrue(barrier.is_spent())

    def test_notify_all_override(self):
        barrier = SynchronizedSignalBarrier(groups=[Group(3)])
        barrier.enable()
        threads = [threading.Thread(target=barrier.wait, args=(0,)) for _ in range(2)]
        for t in threads:
            t.start()

        time.sleep(0.1)
        self.assertFalse(barrier._released)
        barrier.notify_all_override()
        for t in threads:
            t.join(0.5)

        self.assertTrue(barrier._released)

    def test_dispose(self):
        barrier = SynchronizedSignalBarrier(groups=[Group(2)])
        barrier.enable()
        thread = threading.Thread(target=barrier.wait, args=(0,))
        thread.start()

        time.sleep(0.1)
        barrier.dispose()
        thread.join(0.5)

        self.assertTrue(barrier._disposed)
        self.assertTrue(barrier._broken)
        self.assertFalse(thread.is_alive())

    def test_multiple_groups(self):
        results = []
        # FIXED: Changed 'callback=' to 'callbacks=[]' for both groups
        barrier = SynchronizedSignalBarrier(groups=[
            Group(2, callbacks=[lambda: results.append("group_1_ready")]),
            Group(3, callbacks=[lambda: results.append("group_2_ready")])
        ], reusable=True)
        barrier.enable()

        def thread_func(group_index):
            return barrier.wait(group_index)

        threads = [
                      threading.Thread(target=thread_func, args=(0,)) for _ in range(2)
                  ] + [
                      threading.Thread(target=thread_func, args=(1,)) for _ in range(3)
                  ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertIn("group_1_ready", results)
        self.assertIn("group_2_ready", results)
        self.assertFalse(barrier._released)

    def test_broken_barrier_on_manual_release_timeout(self):
        barrier = SynchronizedSignalBarrier(groups=[Group(2)], manual_release=True, timeout=0.5)
        barrier.enable()

        def thread_func():
            return barrier.wait(0)

        thread1 = threading.Thread(target=thread_func)
        thread1.start()
        time.sleep(0.6)

        self.assertFalse(thread1.is_alive())
        self.assertTrue(barrier._broken)
        self.assertTrue(barrier._released)

    def test_early_thread_arrival(self):
        results = []
        # FIXED: Changed 'callback=' to 'callbacks=[]'
        barrier = SynchronizedSignalBarrier(groups=[Group(3, callbacks=[lambda: results.append("released")])],
                                            timeout=1)
        barrier.enable()

        def thread_func():
            barrier.wait(0)

        thread1 = threading.Thread(target=thread_func)
        thread2 = threading.Thread(target=thread_func)
        thread3 = threading.Thread(target=thread_func)
        thread1.start()
        thread2.start()
        thread3.start()
        for t in [thread1, thread2, thread3]:
            t.join()

        self.assertIn("released", results)
        self.assertTrue(barrier._released)

    def test_reset_after_timeout(self):
        barrier = SynchronizedSignalBarrier(groups=[Group(2)], timeout=0.5, reusable=True)
        barrier.enable()

        def thread_func():
            return barrier.wait(0)

        thread1 = threading.Thread(target=thread_func)
        thread1.start()
        thread1.join(1)

        self.assertTrue(barrier._broken)
        self.assertTrue(barrier._released)
        self.assertFalse(thread1.is_alive())

        # Reset is now called automatically for reusable barriers when the last thread leaves,
        # even after a timeout. However, if no threads are left, a manual reset is needed to test reuse.
        barrier.reset()

        self.assertFalse(barrier._released)
        self.assertFalse(barrier._broken)

        thread2 = threading.Thread(target=thread_func)
        thread3 = threading.Thread(target=thread_func)
        thread2.start()
        thread3.start()
        thread2.join()
        thread3.join()

        self.assertEqual(barrier.groups[0].count, 0)
        self.assertFalse(barrier._released)

    def test_thread_group_count_management(self):
        barrier = SynchronizedSignalBarrier(groups=[Group(3)], timeout=1)
        barrier.enable()

        def thread_func():
            return barrier.wait(0)

        thread1 = threading.Thread(target=thread_func)
        thread2 = threading.Thread(target=thread_func)
        thread1.start()
        thread2.start()
        time.sleep(0.1)

        self.assertEqual(barrier.groups[0].count, 2)
        self.assertFalse(barrier._released)

        thread3 = threading.Thread(target=thread_func)
        thread3.start()
        for t in [thread1, thread2, thread3]:
            t.join()

        # In a non-reusable barrier, the count remains after release.
        self.assertEqual(barrier.groups[0].count, 3)
        self.assertTrue(barrier._released)

    def test_broken_state_after_dispose(self):
        barrier = SynchronizedSignalBarrier(groups=[Group(2)], timeout=1)
        barrier.enable()
        thread1 = threading.Thread(target=barrier.wait, args=(0,))
        thread1.start()
        barrier.dispose()
        thread1.join(0.5)

        self.assertTrue(barrier._disposed)
        self.assertTrue(barrier._broken)
        self.assertFalse(thread1.is_alive())

    def test_timeout_raises_exception(self):
        barrier = SynchronizedSignalBarrier(groups=[Group(2)], timeout=0.1, raise_on_timeout=True)
        barrier.enable()
        self.result = []

        def thread_func():
            try:
                barrier.wait(0)
            except TimeoutError as e:
                self.result.append((True, str(e)))
                return
            self.result.append((False, None))

        thread1 = threading.Thread(target=thread_func)
        thread1.start()
        thread1.join(0.5)

        self.assertFalse(thread1.is_alive())
        self.assertEqual(len(self.result), 1)
        self.assertTrue(self.result[0][0])
        self.assertIn("Barrier wait timed out", self.result[0][1])
        self.assertTrue(barrier._broken)
        self.assertTrue(barrier._released)

        # =================================================================
        # ===== NEW TESTS FOR ADVANCED CALLBACK FUNCTIONALITY =====
        # =================================================================

    def test_group_with_single_direct_callback(self):
        """
        Tests that a group works correctly when a single callable is passed
        directly to the `callbacks` argument without being in a list.
        """
        results = []
        # Pass a single lambda function directly
        barrier = SynchronizedSignalBarrier(groups=[Group(2, callbacks=lambda: results.append("fired"))])
        barrier.enable()

        def thread_func():
            barrier.wait(0)

        threads = [threading.Thread(target=thread_func) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Assert that the single callback was executed
        self.assertEqual(results, ["fired"])

    def test_group_with_multiple_callbacks_in_list(self):
        """
        Tests that for a single group, a list of multiple callbacks are all executed.
        """
        results = []
        # Pass a list of two lambda functions to a single group
        callbacks = [
            lambda: results.append("cb1_fired"),
            lambda: results.append("cb2_fired")
        ]
        barrier = SynchronizedSignalBarrier(groups=[Group(2, callbacks=callbacks)])
        barrier.enable()

        def thread_func():
            barrier.wait(0)

        threads = [threading.Thread(target=thread_func) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Use assertCountEqual because the execution order isn't guaranteed
        self.assertCountEqual(results, ["cb1_fired", "cb2_fired"])

    def test_exception_in_group_callback_does_not_stop_others(self):
        """
        Tests that if one callback in a group's list raises an exception, the others still run.
        """
        results = []

        def faulty_callback():
            raise ValueError("This is a test exception")

        def working_callback():
            results.append("ok")

        # Create a list with a faulty callback and a working one for the group
        callbacks = [faulty_callback, working_callback]
        barrier = SynchronizedSignalBarrier(groups=[Group(1, callbacks=callbacks)])
        barrier.enable()

        def thread_func():
            barrier.wait(0)

        t = threading.Thread(target=thread_func)
        t.start()
        t.join()

        # Assert that the working callback still completed its job, even though the other failed.
        self.assertEqual(results, ["ok"])
    def test_late_thread_raises_exception_on_broken_barrier(self):
        barrier = SynchronizedSignalBarrier(groups=[Group(2)], timeout=0.1, raise_on_timeout=True)
        barrier.enable()

        def thread_func():
            try:
                barrier.wait(0)
            except TimeoutError:
                pass

        thread1 = threading.Thread(target=thread_func)
        thread1.start()
        thread1.join(0.5)
        self.assertTrue(barrier._broken)
        late_thread_raised = False

        def late_thread_func():
            nonlocal late_thread_raised
            try:
                barrier.wait(0)
            except TimeoutError:
                late_thread_raised = True

        thread2 = threading.Thread(target=late_thread_func)
        thread2.start()
        thread2.join(0.1)

        self.assertFalse(thread2.is_alive())
        self.assertTrue(late_thread_raised, "The late thread should have raised a TimeoutError.")


if __name__ == "__main__":
    # To run in a script or IDE, use this block.
    # It assumes your project structure allows these imports.
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(TestSignalBarrier))
    runner = unittest.TextTestRunner()
    runner.run(suite)