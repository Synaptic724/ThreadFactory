# benchmark_strategy.py
from abc import ABC, abstractmethod
from typing import List, Callable

class BenchmarkStrategy(ABC):
    """
    Abstract base class for defining how benchmarks should be run
    (single run, multi-sample, grid runs, etc.).
    """

    @abstractmethod
    def run(self, manager, benchmark_name: str, callback: Callable[[dict], None]):
        """
        Execute the benchmark runs against the provided manager,
        passing a callback for results.
        """
        pass


class SingleRunStrategy(BenchmarkStrategy):
    """
    Runs the specified benchmark exactly once with the given parameters.
    """

    def __init__(self, producers: int, consumers: int, items_per_producer: int):
        self.producers = producers
        self.consumers = consumers
        self.items_per_producer = items_per_producer

    def run(self, manager, benchmark_name: str, callback: Callable[[dict], None]):
        manager.run_benchmark(
            name=benchmark_name,
            producers=self.producers,
            consumers=self.consumers,
            items_per_producer=self.items_per_producer,
            callback=callback
        )


class MultiSampleStrategy(BenchmarkStrategy):
    """
    Runs the specified benchmark multiple times with the same parameters.
    """

    def __init__(self, producers: int, consumers: int, items_per_producer: int, samples: int):
        self.producers = producers
        self.consumers = consumers
        self.items_per_producer = items_per_producer
        self.samples = samples

    def run(self, manager, benchmark_name: str, callback: Callable[[dict], None]):
        for i in range(self.samples):
            print(f"\n--- [MultiSample] Running sample {i+1}/{self.samples} ---")
            manager.run_benchmark(
                name=benchmark_name,
                producers=self.producers,
                consumers=self.consumers,
                items_per_producer=self.items_per_producer,
                callback=callback
            )


class GridStrategy(BenchmarkStrategy):
    def __init__(self, producer_values, consumer_values, items_per_producer):
        self.producer_values = producer_values
        self.consumer_values = consumer_values
        self.items_per_producer = items_per_producer

    def run(self, manager, benchmark_name: str, callback: Callable[[dict], None]):
        # Just do the looping yourself
        for p in self.producer_values:
            for c in self.consumer_values:
                manager.run_benchmark(
                    name=benchmark_name,
                    producers=p,
                    consumers=c,
                    items_per_producer=self.items_per_producer,
                    callback=callback
                )
