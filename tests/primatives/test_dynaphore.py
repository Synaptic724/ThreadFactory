import unittest
import threading
import time
import random
from thread_factory.primitives.dynaphore import Dynaphore

class TestDynaphore(unittest.TestCase):

    def test_basic_acquire_release(self):
        sema = Dynaphore(2)
        self.assertEqual(sema._permits, 2)

        acquired = sema.wait_for_permit(timeout=1)
        self.assertTrue(acquired)
        self.assertEqual(sema._permits, 1)

        sema.release_permit()
        self.assertEqual(sema._permits, 2)

    def test_increase_permits(self):
        sema = Dynaphore(1)
        sema.increase_permits(3)
        self.assertEqual(sema._permits, 4)

    def test_decrease_permits(self):
        sema = Dynaphore(8)
        sema.decrease_permits(3)
        self.assertEqual(sema._permits, 5)

        with self.assertRaises(ValueError):
            sema.decrease_permits(10)  # 10 > 5 triggers error

    def test_concurrent_acquire_release(self):
        sema = Dynaphore(0)
        acquired_threads = []
        lock = threading.Lock()

        def worker(thread_id):
            if sema.wait_for_permit(timeout=3):
                with lock:
                    acquired_threads.append(thread_id)
                time.sleep(random.uniform(0.1, 0.3))
                sema.release_permit()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads: t.start()

        time.sleep(0.5)
        sema.increase_permits(10)

        for t in threads:
            t.join(timeout=2)

        self.assertEqual(len(acquired_threads), 10)

    def test_stress_dynaphore(self):
        sema = Dynaphore(0)
        results = []
        lock = threading.Lock()
        num_threads = 20

        def worker(thread_id):
            if sema.wait_for_permit(timeout=5):
                with lock:
                    results.append(thread_id)
                time.sleep(random.uniform(0.2, 0.5))
                sema.release_permit()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads: t.start()

        for _ in range(5):
            time.sleep(0.5)
            permits = random.randint(5, 10)
            sema.increase_permits(permits)
            try:
                sema.decrease_permits(random.randint(0, permits))
            except ValueError:
                pass  # Expected in some rounds

        for t in threads:
            t.join(timeout=3)

        self.assertEqual(len(results), num_threads)

    def test_set_permits_directly(self):
        sema = Dynaphore(0)
        sema.set_permits(5)
        self.assertEqual(sema._permits, 5)

        sema.set_permits(0)
        self.assertEqual(sema._permits, 0)

        with self.assertRaises(ValueError):
            sema.set_permits(-1)

if __name__ == '__main__':
    unittest.main()
