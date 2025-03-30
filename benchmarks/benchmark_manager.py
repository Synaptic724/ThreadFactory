import time
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Callable, List, Optional, Tuple
from benchmarks.benchmark_manager_strategy import ManagerStrategyFactory
from benchmarks.benchmark_visualizer import BenchmarkVisualizer
from src.thread_factory import ConcurrentList
from benchmarks_builder import BenchmarkFactory
import benchmark_strategy as bs



@dataclass
class BenchmarkRecord:
    """Holds a single benchmark result."""
    name: str
    producers: int
    consumers: int
    items_per_producer: int
    total_ops: int
    duration: float
    throughput: float
    extra: Dict[str, Any] = field(default_factory=dict)


class BenchmarkManager:
    """
    A manager that:
      - Uses concurrency test objects from BenchmarkFactory.
      - Allows single-run or strategy-based runs.
      - Stores results as BenchmarkRecord in a thread-safe list.
      - Exports results and prints summary.
    """

    def __init__(self) -> None:
        # Where we store all benchmark records
        self.records: ConcurrentList[BenchmarkRecord] = ConcurrentList()

    def run_benchmark(
        self,
        name: str,
        producers: int,
        consumers: int,
        items_per_producer: int,
        callback: Optional[Callable[[dict], None]] = None
    ) -> None:
        """
        Run the concurrency benchmark identified by 'name' exactly once.
        The concurrency test is fetched from BenchmarkFactory by `name`.
        """

        # If no callback provided, use a default that logs to self.records
        if callback is None:
            def callback(data: Dict[str, Any]):
                self._store_record(name, producers, consumers, items_per_producer, data)
        else:
            # We'll wrap the user callback to also store a record
            user_callback = callback

            def callback_wrapper(data: Dict[str, Any]):
                # First store in manager
                self._store_record(name, producers, consumers, items_per_producer, data)
                # Then also let the user’s callback see the data
                user_callback(data)

            callback = callback_wrapper

        total_ops = producers * items_per_producer
        print(f"\n🚩 Starting benchmark: {name} | {producers}P / {consumers}C | Total ops: {total_ops:,}")

        start_time = time.perf_counter()

        # 1) Get the concurrency test from the factory
        test = BenchmarkFactory.get_benchmark(name)

        # 2) Run the test
        test.run_benchmark(
            callback=callback,
            producers=producers,
            consumers=consumers,
            items_per_producer=items_per_producer
        )

        end_time = time.perf_counter()
        print(f"✅ Benchmark '{name}' finished in {end_time - start_time:.2f} seconds.")

    def run_strategy(self, strategy: bs.BenchmarkStrategy, benchmark_name: str):
        """
        The provided 'strategy' calls manager.run_benchmark(...) multiple times
        (or however it is designed).
        """
        # A small local callback to pass to the strategy if we want additional logic
        # But typically the strategy can rely on manager's built-in storing logic.
        def strategy_callback(_data: Dict[str, Any]):
            pass

        # Actually run the user-supplied strategy
        strategy.run(self, benchmark_name, callback=strategy_callback)

    def _store_record(
        self,
        benchmark_name: str,
        producers: int,
        consumers: int,
        items_per_producer: int,
        data: Dict[str, Any]
    ):
        """Given a result dictionary from the concurrency test, build a BenchmarkRecord."""
        duration = data.get("duration", 0.0)
        total_ops = producers * items_per_producer
        throughput = total_ops / duration if duration > 0 else 0.0
        extra = dict(data)
        extra.pop("duration", None)  # We store duration separately

        record = BenchmarkRecord(
            name=benchmark_name,
            producers=producers,
            consumers=consumers,
            items_per_producer=items_per_producer,
            total_ops=total_ops,
            duration=duration,
            throughput=throughput,
            extra=extra
        )
        self.records.append(record)

    def export(self) -> List[Dict[str, Any]]:
        """Convert all records to dictionaries for JSON/CSV or other uses."""
        return [asdict(r) for r in self.records]

    def print_summary(self) -> None:
        """Display a simple summary of each recorded run."""
        print("\n📊 Benchmark Summary:")
        for rec in self.records:
            print(f"- {rec.name}: {rec.producers}P/{rec.consumers}C | "
                  f"{rec.total_ops:,} ops | {rec.duration:.2f}s | "
                  f"{rec.throughput:,.0f} ops/sec | extra: {rec.extra}")

    def save_as_csv(self, filepath: str) -> None:
        data = self.export()
        if not data:
            print("No records to save.")
            return
        import csv
        keys = list(data[0].keys())
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(data)
        print(f"✅ Saved benchmark records to CSV: {filepath}")

    def save_as_json(self, filepath: str) -> None:
        data = self.export()
        if not data:
            print("No records to save.")
            return
        import json
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        print(f"✅ Saved benchmark records to JSON: {filepath}")

    def save_as_yaml(self, filepath: str) -> None:
        """Save all benchmark records to a YAML file."""
        data = self.export()
        if not data:
            print("No records to save.")
            return
        import yaml
        with open(filepath, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        print(f"✅ Saved benchmark records to YAML: {filepath}")


if __name__ == "__main__":
    manager = BenchmarkManager()

    testDict = {
        'min_producer' : 4,
    'max_producer' : 20,
    'producer_step' : 2,
    'min_consumer' : 4,
    'max_consumer' : 20,
    'consumer_step' : 2,
    'min_items_per_producer' : 10000,
    'max_items_per_producer' : 50000,
    'items_per_producer_step' : 10000,
    'ratios': [(4, 1), (3, 1), (2, 1), (1, 1), (1, 2), (1, 3), (1, 4)]
    }


    suite = ManagerStrategyFactory.create_strategy(
        "scalable_test_suite",
        benchmark="concurrent_buffer",
        **testDict
    )
    suite.execute(manager)

    suite = ManagerStrategyFactory.create_strategy(
        "scalable_test_suite",
        benchmark="concurrent_collection",
        **testDict
    )
    suite.execute(manager)

    suite = ManagerStrategyFactory.create_strategy(
        "scalable_test_suite",
        benchmark="concurrent_queue",
        **testDict
    )
    suite.execute(manager)

    # 3) Export + Summary
    manager.print_summary()
    manager.save_as_csv("benchmark_results.csv")
    manager.save_as_json("benchmark_results.json")

    # 4) Visualization
    records = manager.export()
    viz = BenchmarkVisualizer(records)
    viz.show_dual_axis_chart()
