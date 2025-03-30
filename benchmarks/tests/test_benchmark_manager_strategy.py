import unittest
from unittest.mock import patch, MagicMock
from benchmarks.benchmark_manager_strategy import (
    FullTestSuiteStrategy,
    MinimalTestSuiteStrategy,
    ScalableTestSuiteStrategy,
    ManagerStrategyFactory
)
from benchmarks.benchmark_strategy import SingleRunStrategy, MultiSampleStrategy, GridStrategy, ScalableTest


class MockBenchmarkManager:
    """A mock manager to ensure strategies call run_strategy with correct params."""
    def __init__(self):
        self.calls = []

    def run_strategy(self, strategy, benchmark_name, callback=None):
        self.calls.append((strategy, benchmark_name, callback))


class TestFullTestSuiteStrategy(unittest.TestCase):
    def test_build_strategies(self):
        strategy = FullTestSuiteStrategy()
        s_list = strategy.build_strategies()
        self.assertEqual(len(s_list), 3)
        # Each tuple: (strategy_instance, benchmark_name)
        self.assertIsInstance(s_list[0][0], SingleRunStrategy)
        self.assertIsInstance(s_list[1][0], MultiSampleStrategy)
        self.assertIsInstance(s_list[2][0], GridStrategy)

    def test_execute_runs_all(self):
        strategy = FullTestSuiteStrategy()
        mock_manager = MockBenchmarkManager()
        strategy.execute(mock_manager)
        self.assertEqual(len(mock_manager.calls), 3)


class TestMinimalTestSuiteStrategy(unittest.TestCase):
    def test_build_strategies_minimal(self):
        strategy = MinimalTestSuiteStrategy()
        s_list = strategy.build_strategies()
        self.assertEqual(len(s_list), 1)
        self.assertIsInstance(s_list[0][0], SingleRunStrategy)
        self.assertEqual(s_list[0][1], "concurrent_collection_threads")


class TestScalableTestSuiteStrategy(unittest.TestCase):
    def test_build_strategies_scalable(self):
        strat = ScalableTestSuiteStrategy(
            benchmark="concurrent_buffer",
            min_producer=4,
            max_producer=8,
            producer_step=2
        )
        s_list = strat.build_strategies()
        self.assertEqual(len(s_list), 1)
        # Should produce a tuple: (ScalableTest(...), "concurrent_buffer")
        strategy_obj, name = s_list[0]
        self.assertIsInstance(strategy_obj, ScalableTest)
        self.assertEqual(name, "concurrent_buffer")


class TestManagerStrategyFactory(unittest.TestCase):
    def test_create_known_strategies(self):
        full = ManagerStrategyFactory.create_strategy("full_test_suite")
        self.assertIsInstance(full, FullTestSuiteStrategy)

        minimal = ManagerStrategyFactory.create_strategy("minimal_test_suite")
        self.assertIsInstance(minimal, MinimalTestSuiteStrategy)

        scalable = ManagerStrategyFactory.create_strategy("scalable_test_suite", benchmark="xyz")
        self.assertIsInstance(scalable, ScalableTestSuiteStrategy)

    def test_unknown_strategy_raises(self):
        with self.assertRaises(ValueError):
            ManagerStrategyFactory.create_strategy("non_existent")


if __name__ == '__main__':
    unittest.main()
