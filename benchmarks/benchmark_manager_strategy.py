from abc import ABC, abstractmethod
from typing import List, Tuple
from benchmarks.benchmark_strategy import BenchmarkStrategy


# =============================================================================
#   NEW ADDITIONS: ManagerStrategy + Concrete Implementations + Factory
# =============================================================================
class ManagerStrategy(ABC):
    """
    A "manager strategy" defines an entire suite/workflow of multiple
    BenchmarkStrategy runs – i.e. a set of (strategy, benchmark_name) pairs.

    Then 'execute()' will run them all in sequence.
    """

    @abstractmethod
    def build_strategies(self) -> List[Tuple[BenchmarkStrategy, str]]:
        """
        Return a list of (BenchmarkStrategy, benchmark_name) pairs to execute.
        """
        pass

    def execute(self, manager: 'BenchmarkManager'):
        """
        Execute all (strategy, benchmark_name) pairs built by build_strategies().
        """
        for strat, bench_name in self.build_strategies():
            manager.run_strategy(strat, bench_name)


# Example: A "full test suite" that runs three different strategies
class FullTestSuiteStrategy(ManagerStrategy):
    def build_strategies(self) -> List[Tuple[BenchmarkStrategy, str]]:
        from benchmark_strategy import SingleRunStrategy, MultiSampleStrategy, GridStrategy

        # In this example, we define 3 calls:
        # 1) single run (2,2,1000)
        # 2) multi-sample (2,2,1000, samples=3)
        # 3) grid ([1,2],[1,2], 500)
        suite = [
            (SingleRunStrategy(2, 2, 1000),        "concurrent_buffer_threads"),
            (MultiSampleStrategy(2, 2, 1000, 3),   "concurrent_queue_threads"),
            (GridStrategy([1, 2], [1, 2], 500),    "collections_deque_threads"),
        ]
        return suite


# If you anticipate multiple different "manager strategies," you can define more classes:
class MinimalTestSuiteStrategy(ManagerStrategy):
    def build_strategies(self) -> List[Tuple[BenchmarkStrategy, str]]:
        from benchmark_strategy import SingleRunStrategy
        # Maybe just do a single run for one concurrency test
        return [
            (SingleRunStrategy(2, 2, 1000), "concurrent_collection_threads"),
        ]


# ManagerStrategyFactory: returns the correct manager strategy by name
class ManagerStrategyFactory:
    """
    We define a simple dictionary of known manager strategies.
    If you have many, you can store them here or build them dynamically.
    """
    _registered_strategies = {
        "full_test_suite": FullTestSuiteStrategy,
        "minimal_test_suite": MinimalTestSuiteStrategy,
    }

    @classmethod
    def create_strategy(cls, name: str) -> ManagerStrategy:
        if name not in cls._registered_strategies:
            raise ValueError(f"No manager strategy registered under '{name}'")
        return cls._registered_strategies[name]()