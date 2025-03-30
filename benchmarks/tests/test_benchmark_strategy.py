import unittest
from unittest.mock import MagicMock
from benchmarks.benchmark_strategy import SingleRunStrategy, MultiSampleStrategy, GridStrategy, ScalableTest

class MockBenchmarkManager:
    """A mock manager to record params dict calls."""
    def __init__(self):
        self.calls = []

    def run_benchmark(self, name, params):
        self.calls.append((name, params))

class TestSingleRunStrategy(unittest.TestCase):
    def test_run_single(self):
        manager = MockBenchmarkManager()
        strategy = SingleRunStrategy(2, 1, 100)
        strategy.run(manager, "test_bench", callback=None)
        self.assertEqual(len(manager.calls), 1)
        name, params = manager.calls[0]
        self.assertEqual(name, "test_bench")
        self.assertEqual(params["producers"], 2)
        self.assertEqual(params["consumers"], 1)
        self.assertEqual(params["items_per_producer"], 100)

class TestMultiSampleStrategy(unittest.TestCase):
    def test_run_multi_samples(self):
        manager = MockBenchmarkManager()
        strategy = MultiSampleStrategy(1, 1, 50, samples=3)
        strategy.run(manager, "multi_bench", callback=None)
        self.assertEqual(len(manager.calls), 3)
        for call in manager.calls:
            name, params = call
            self.assertEqual(name, "multi_bench")
            self.assertEqual(params["producers"], 1)
            self.assertEqual(params["consumers"], 1)
            self.assertEqual(params["items_per_producer"], 50)

class TestGridStrategy(unittest.TestCase):
    def test_grid_run(self):
        manager = MockBenchmarkManager()
        strategy = GridStrategy(producer_values=[1,2], consumer_values=[1,3], items_per_producer=10)
        strategy.run(manager, "grid_bench", callback=None)
        self.assertEqual(len(manager.calls), 4)
        combos = [(1,1), (1,3), (2,1), (2,3)]
        for i, call in enumerate(manager.calls):
            _, params = call
            self.assertEqual((params["producers"], params["consumers"]), combos[i])
            self.assertEqual(params["items_per_producer"], 10)

class TestScalableTest(unittest.TestCase):
    def test_run_scalable(self):
        manager = MockBenchmarkManager()
        strategy = ScalableTest(
            min_producer=4, max_producer=8, producer_step=4,
            min_items_per_producer=100, max_items_per_producer=200, items_per_producer_step=100,
            ratios=[(4,1), (2,1)]
        )
        strategy.run(manager, "scalable_bench", callback=None)
        self.assertEqual(len(manager.calls), 8)
        # Optional inspection:
        # for call in manager.calls:
        #     print(call)

if __name__ == '__main__':
    unittest.main()
