import unittest
import threading
import time
import random
from src.thread_factory import Dynaphore

class TestDynaphore(unittest.TestCase):

    def test_basic_acquire_release(self):
        sema = Dynaphore(2)
        self.assertEqual(sema._value, 2)

        sema.acquire()
        self.assertEqual(sema._value, 1)

        sema.release()
        self.assertEqual(sema._value, 2)

    def test_increase_permits(self):
        sema = Dynaphore(1)
        sema.increase_permits(3)
        self.assertEqual(sema._value, 4)

    def test_decrease_permits(self):
        sema = Dynaphore(8)  # Start higher to avoid negative cases
        sema.decrease_permits(3)
        print(sema._value)
        self.assertEqual(sema._value, 5)

        # Now test decreasing beyond the current permits (should raise)
        with self.assertRaises(ValueError):
            sema.decrease_permits(10)  # 10 > 5 -> triggers error

    def test_concurrent_acquire_release(self):
        sema = Dynaphore(0)
        acquired_threads = []

        def worker(thread_id):
            sema.acquire()
            acquired_threads.append(thread_id)
            time.sleep(random.uniform(0.1, 0.5))
            sema.release()

        threads = []
        for i in range(10):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        # Give threads a chance to block
        time.sleep(0.5)

        # Release 10 permits so they can proceed
        sema.increase_permits(10)

        for t in threads:
            t.join()

        self.assertEqual(len(acquired_threads), 10)

    def test_stress_dynaphore(self):
        sema = Dynaphore(0)
        threads = []
        results = []
        num_threads = 20

        def worker(thread_id):
            sema.acquire()
            results.append(thread_id)
            time.sleep(random.uniform(0.2, 1.0))
            sema.release()

        for i in range(num_threads):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        # Dynamic orchestration
        for _ in range(5):
            time.sleep(1)
            permits_to_add = random.randint(5, 10)
            sema.increase_permits(permits_to_add)

            permits_to_decrease = random.randint(0, permits_to_add)
            try:
                sema.decrease_permits(permits_to_decrease)
            except ValueError:
                pass  # Expected sometimes, fine for the test

        for t in threads:
            t.join()

        self.assertEqual(len(results), num_threads)

if __name__ == '__main__':
    unittest.main()
