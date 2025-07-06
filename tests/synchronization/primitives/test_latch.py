import unittest
import threading
import time
from thread_factory.synchronization.primitives.latch import Latch


class TestSimpleLatch(unittest.TestCase):

    def test_wait_blocks_until_open(self):
        latch = Latch()
        result = []

        def worker():
            latch.closed()
            result.append("released")

        t = threading.Thread(target=worker)
        t.start()
        time.sleep(0.1)
        self.assertEqual(result, [])
        latch.open()
        t.join()
        self.assertEqual(result, ["released"])

    def test_open_releases_all_threads(self):
        latch = Latch()
        result = []
        threads = []

        def worker(i):
            latch.closed()
            result.append(f"t{i}")

        for i in range(5):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        time.sleep(0.2)
        self.assertEqual(result, [])
        latch.open()
        for t in threads:
            t.join()
        self.assertEqual(len(result), 5)

    def test_reset_blocks_again(self):
        latch = Latch()
        latch.open()
        self.assertTrue(latch.closed(timeout=0.1))  # should pass immediately
        latch.close()

        result = []

        def worker():
            if latch.closed(timeout=0.2):
                result.append("released")

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        self.assertEqual(result, [])  # should not release

    def test_wait_timeout(self):
        latch = Latch()
        start = time.time()
        success = latch.closed(timeout=0.2)
        elapsed = time.time() - start
        self.assertFalse(success)
        self.assertGreaterEqual(elapsed, 0.2)

    def test_is_open(self):
        latch = Latch()
        self.assertFalse(latch.is_open())
        latch.open()
        self.assertTrue(latch.is_open())
        latch.close()
        self.assertFalse(latch.is_open())

    def test_multiple_opens_safe(self):
        latch = Latch()
        latch.open()
        latch.open()  # Should not raise
        self.assertTrue(latch.is_open())

    def test_wait_after_open_is_instant(self):
        latch = Latch()
        latch.open()
        start = time.time()
        latch.closed()
        elapsed = time.time() - start
        self.assertLess(elapsed, 0.01)

    def test_race_between_reset_and_open(self):
        latch = Latch()
        results = []

        def waiter():
            if latch.closed(timeout=0.5):
                results.append("released")

        threads = [threading.Thread(target=waiter) for _ in range(3)]
        for t in threads:
            t.start()

        time.sleep(0.1)
        latch.close()
        latch.open()

        for t in threads:
            t.join()
        self.assertEqual(results, ["released"] * 3)
