import unittest
import threading
from thread_factory.synchronization.coordinators.conductor import Conductor
from thread_factory.utilities.coordination.package import Pack

def _spawn(n, fn):
    threads = []
    for _ in range(n):
        t = threading.Thread(target=fn, daemon=True)
        threads.append(t)
        t.start()
    return threads

class TestPackWithConductor(unittest.TestCase):

    def test_single_pack_execution(self):
        """Test a single Pack object as the Conductor's task."""
        p = Pack(lambda x, y: x + y, 2, 3)
        c = Conductor(threshold=1, tasks=p)
        threads = _spawn(1, c.start)
        for t in threads: t.join(2)
        self.assertEqual(c.results, [5])
        c.dispose()

    def test_curried_pack_in_multi_thread(self):
        """Test multiple threads executing a curried Pack with remaining args."""
        def multiply(a, b): return a * b
        p = Pack(multiply, 2).curry(10)
        c = Conductor(threshold=3, tasks=p, multiple_outcomes_per_task=True)
        threads = _spawn(3, c.start)
        for t in threads: t.join(2)
        self.assertEqual([o.result() for o in c.outcomes[0]], [20, 20, 20])
        c.dispose()

    def test_composed_pack_pipeline(self):
        """Test two composed Pack objects piped into a single task."""
        def add(x, y): return x + y
        def square(n): return n * n

        p1 = Pack(add, 3).curry(4)       # 3 + 4 = 7
        p2 = Pack(square)                # 7 * 7 = 49
        pipeline = p1 | p2

        c = Conductor(threshold=2, tasks=pipeline, multiple_outcomes_per_task=True)
        threads = _spawn(2, c.start)
        for t in threads: t.join(2)
        self.assertEqual([o.result() for o in c.outcomes[0]], [49, 49])
        c.dispose()


if __name__ == "__main__":
    unittest.main()