import unittest
import threading
import time
from thread_factory.primitives.signal_barrier import SignalBarrier, Group


class TestSignalBarrier(unittest.TestCase):

    def test_single_group_auto_release(self):
        hit = []

        def cb():
            hit.append("done")

        barrier = SignalBarrier([Group(threshold=2, callback=cb)], reusable=False, manual_release=False)

        def worker():
            barrier.wait(0)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start(); t2.start()
        t1.join(); t2.join()

        self.assertEqual(hit, ["done"])
        self.assertTrue(barrier.is_spent())

    def test_multiple_groups_auto_release(self):
        results = []

        def cb1(): results.append("g1")
        def cb2(): results.append("g2")

        g1 = Group(threshold=1, callback=cb1)
        g2 = Group(threshold=2, callback=cb2)

        barrier = SignalBarrier([g1, g2], reusable=False)

        def group1(): barrier.wait(0)
        def group2(): barrier.wait(1)

        t1 = threading.Thread(target=group2)
        t2 = threading.Thread(target=group2)
        t3 = threading.Thread(target=group1)

        t1.start(); t2.start(); t3.start()
        t1.join(); t2.join(); t3.join()

        self.assertCountEqual(results, ["g1", "g2"])
        self.assertTrue(barrier.is_spent())

    def test_manual_release(self):
        g = Group(threshold=2)
        barrier = SignalBarrier([g], manual_release=True)

        def worker():
            barrier.wait(0)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)

        t1.start(); t2.start()
        time.sleep(0.1)
        self.assertFalse(barrier.is_spent())

        barrier.release()
        t1.join(); t2.join()

        self.assertTrue(barrier.is_spent())

    def test_reusable_barrier(self):
        g = Group(threshold=2)
        barrier = SignalBarrier([g], reusable=True)

        def run_phase():
            t1 = threading.Thread(target=lambda: barrier.wait(0))
            t2 = threading.Thread(target=lambda: barrier.wait(0))
            t1.start(); t2.start()
            t1.join(); t2.join()

        run_phase()
        self.assertFalse(barrier.is_spent())
        run_phase()
        self.assertFalse(barrier.is_spent())

    def test_notify_all_override(self):
        g = Group(threshold=10)  # unreachable normally
        barrier = SignalBarrier([g], reusable=False)

        def worker():
            barrier.wait(0)

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads: t.start()

        time.sleep(0.1)
        barrier.notify_all_override()

        for t in threads: t.join()
        self.assertTrue(barrier.is_spent())

    def test_timeout_behavior(self):
        g = Group(threshold=5)
        barrier = SignalBarrier([g])

        def wait_short():
            result = barrier.wait(0, timeout=0.1)
            self.assertFalse(result)

        t = threading.Thread(target=wait_short)
        t.start(); t.join()

    def test_dispose_behavior(self):
        g = Group(threshold=2)
        barrier = SignalBarrier([g])

        triggered = []

        def wait_and_mark():
            if barrier.wait(0):
                triggered.append("unblocked")

        t1 = threading.Thread(target=wait_and_mark)
        t2 = threading.Thread(target=wait_and_mark)

        t1.start(); t2.start()
        time.sleep(0.1)
        barrier.dispose()
        t1.join(); t2.join()

        self.assertTrue(barrier._disposed)
        self.assertEqual(len(triggered), 2)  # Both were woken up due to dispose but did not proceed with work

    def test_multiple_groups_all_synchronize(self):
        triggered_groups = []

        def make_callback(index):
            def callback():
                triggered_groups.append(index)
            return callback

        groups = [Group(threshold=2, callback=make_callback(i)) for i in range(3)]
        barrier = SignalBarrier(groups, reusable=False)

        def worker(g_index, result_list):
            released = barrier.wait(g_index, timeout=2)
            result_list.append((g_index, released))

        results: list[tuple[int, bool]] = []
        threads = []

        # Launch 2 threads for each group (6 total)
        for i in range(3):
            for _ in range(2):
                t = threading.Thread(target=worker, args=(i, results))
                threads.append(t)
                t.start()

        for t in threads:
            t.join()

        self.assertEqual(len(results), 6)
        self.assertTrue(all(released for (_, released) in results))
        self.assertEqual(sorted(triggered_groups), [0, 1, 2])  # All callbacks ran

    def test_reusable_barrier_allows_multiple_cycles(self):
        call_count = [0, 0]

        def make_callback(index):
            def callback():
                call_count[index] += 1
            return callback

        groups = [
            Group(threshold=2, callback=make_callback(0)),
            Group(threshold=2, callback=make_callback(1))
        ]
        barrier = SignalBarrier(groups, reusable=True)

        def run_cycle(result_store: list[bool]):
            local = []

            def thread_fn(idx):
                result = barrier.wait(idx, timeout=2)
                local.append(result)

            threads = [threading.Thread(target=thread_fn, args=(i % 2,)) for i in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            result_store.append(local)

        result_storage: list[list[bool]] = []
        run_cycle(result_storage)
        run_cycle(result_storage)

        # Two full cycles
        self.assertEqual(call_count, [2, 2])
        for cycle_result in result_storage:
            self.assertTrue(all(cycle_result))

    def test_manual_release_required(self):
        released = []

        groups = [
            Group(threshold=2, callback=lambda: released.append("group0")),
            Group(threshold=2, callback=lambda: released.append("group1"))
        ]
        barrier = SignalBarrier(groups, reusable=False, manual_release=True)

        def thread_fn(group_index, results):
            result = barrier.wait(group_index)
            results.append(result)

        results = []
        threads = [threading.Thread(target=thread_fn, args=(i % 2, results)) for i in range(4)]

        for t in threads:
            t.start()

        time.sleep(0.2)  # Let threads reach barrier
        barrier.release()

        for t in threads:
            t.join()

        self.assertEqual(len(results), 4)
        self.assertTrue(all(results))
        self.assertIn("group0", released)
        self.assertIn("group1", released)


if __name__ == "__main__":
    unittest.main()
