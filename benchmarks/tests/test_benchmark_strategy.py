import unittest
from unittest.mock import MagicMock
from benchmarks.benchmark_strategy import SingleRunStrategy, MultiSampleStrategy, GridStrategy, ScalableTest

class MockBenchmarkManager:
    """A mock manager to see how strategies call run_benchmark()."""
    def __init__(self):
        self.calls = []

    def run_benchmark(self, name, producers, consumers, items_per_producer, callback=None):
        self.calls.append((name, producers, consumers, items_per_producer, callback))

class TestSingleRunStrategy(unittest.TestCase):
    def test_run_single(self):
        manager = MockBenchmarkManager()
        strategy = SingleRunStrategy(2, 1, 100)
        strategy.run(manager, "test_bench", callback=None)
        self.assertEqual(len(manager.calls), 1)
        name, p, c, ipp, cb = manager.calls[0]
        self.assertEqual(name, "test_bench")
        self.assertEqual(p, 2)
        self.assertEqual(c, 1)
        self.assertEqual(ipp, 100)

class TestMultiSampleStrategy(unittest.TestCase):
    def test_run_multi_samples(self):
        manager = MockBenchmarkManager()
        strategy = MultiSampleStrategy(1, 1, 50, samples=3)
        strategy.run(manager, "multi_bench", callback=None)
        self.assertEqual(len(manager.calls), 3)
        for call in manager.calls:
            name, p, c, ipp, cb = call
            self.assertEqual(name, "multi_bench")

class TestGridStrategy(unittest.TestCase):
    def test_grid_run(self):
        manager = MockBenchmarkManager()
        strategy = GridStrategy(producer_values=[1,2], consumer_values=[1,3], items_per_producer=10)
        strategy.run(manager, "grid_bench", callback=None)
        # Expect 4 calls: (1,1), (1,3), (2,1), (2,3)
        self.assertEqual(len(manager.calls), 4)
        combos = [(1,1), (1,3), (2,1), (2,3)]
        for i, call in enumerate(manager.calls):
            _, p, c, ipp, _ = call
            self.assertEqual((p,c), combos[i])
            self.assertEqual(ipp, 10)

class TestScalableTest(unittest.TestCase):
    def test_run_scalable(self):
        # We'll run with a small range to verify logic
        manager = MockBenchmarkManager()
        strategy = ScalableTest(
            min_producer=4, max_producer=8, producer_step=4,
            min_items_per_producer=100, max_items_per_producer=200, items_per_producer_step=100,
            ratios=[(4,1), (2,1)]
        )
        strategy.run(manager, "scalable_bench", callback=None)
        # Explanation:
        #  - p in [4,8], step=4 => p = 4, 8
        #  - ratio (4,1): if p % 4 == 0 => c = (4 // 4)*1=1 when p=4, c= (8//4)*1=2 when p=8
        #  - ratio (2,1): if p % 2 == 0 => c = (4//2)*1=2 when p=4, c=(8//2)*1=4 when p=8
        #  - items in [100,200], step=100 => 100, 200
        # For p=4 => (4,1) => c=1, (4,2) => c=2
        # For p=8 => (4,1) => c=2, (2,1)=> c=4
        # Each pair runs for items=100 and items=200 => total 8 runs
        self.assertEqual(len(manager.calls), 8)
        # Optionally, inspect them all:
        # for call in manager.calls:
        #    print(call)

if __name__ == '__main__':
    unittest.main()
